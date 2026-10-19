"""Um dia de ponta a ponta usando só a API, o aviso do provedor assinado, o WebSocket e as varreduras."""
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

from app.api.webhook import SIGNATURE_HEADER, sign
from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.db.pg_ledger import PgLedger
from app.domain.clock import local_date
from app.scheduler import sweep_once
from tests.api.conftest import WEBHOOK_SECRET
from tests.api.helpers import login
from tests.helpers import ORIGIN, pt
from tests.helpers_db import make_cpf

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
_pool = ThreadPoolExecutor(max_workers=2)


def lugar(ponto, texto):
    return {"lat": ponto.lat, "lng": ponto.lng, "text": texto}


QUOTE = {"pickup": lugar(ORIGIN, "Rua A"), "destination": lugar(pt(1500, 0), "Feira livre")}


def test_um_dia_inteiro_pela_api(client, runtime, session, clock, listen):
    def webhook(evento):
        corpo = json.dumps(evento).encode()
        return client.post("/v1/webhooks/pix", content=corpo, headers={SIGNATURE_HEADER: sign(WEBHOOK_SECRET, corpo)})

    def posicao(ponto=pt(300, 0)):
        client.post("/v1/rider/position", json={"lat": ponto.lat, "lng": ponto.lng}, headers=rider.headers)

    def pedir(metodo):
        posicao()                                                      # a posição precisa estar fresca
        quote = client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers)
        assert quote.status_code == 200, quote.text
        corrida = client.post(
            "/v1/passenger/rides", json={"quote_id": quote.json()["quote_id"], "method": metodo}, headers=pax.headers
        ).json()
        assert client.post(f"/v1/rider/offers/{corrida['ride_id']}/accept", headers=rider.headers).status_code == 200
        return corrida

    def percurso(corrida, parar_s=0):
        rid = corrida["ride_id"]
        client.post(f"/v1/rider/rides/{rid}/arrive", headers=rider.headers)
        client.post(f"/v1/rider/rides/{rid}/helmet", headers=rider.headers)
        assert client.post(f"/v1/rider/rides/{rid}/start", json={"pin": corrida["pin"]}, headers=rider.headers).status_code == 200
        for _ in range(parar_s // 4):
            clock.advance(4)
            posicao(pt(500, 3))
        clock.advance(60)
        return client.post(f"/v1/rider/rides/{rid}/complete", headers=rider.headers).json()

    # 1) pessoas: o administrador existe; o motoqueiro se cadastra com fotos; o dono aprova
    repo.add_user(session, user_id="adm-1", phone="+5575999990000", name="Levy", role="admin")
    admin = login(client, runtime, "75 99999-0000", "admin")
    rider = login(client, runtime, "75 99777-0002", "rider")
    pax = login(client, runtime, "75 99999-0001", "passenger", name="Ana Lima")
    hoje = local_date(clock.now)
    chaves = {
        campo: client.put(f"/v1/rider/documents/{kind}", content=JPEG, headers=rider.headers).json()["key"]
        for campo, kind in (("selfie_key", "selfie"), ("cnh_photo_key", "cnh"), ("crlv_key", "crlv"))
    }
    registro = client.post(
        "/v1/rider/register",
        json={
            "name": "Carlos Moto", "cpf": make_cpf("123456789"), "cnh_number": "12345678901", "plate": "ABC1D23",
            "moto_model": "Honda CG 160", "cnh_expires_on": str(hoje + dt.timedelta(days=700)),
            "crlv_expires_on": str(hoje + dt.timedelta(days=300)), **chaves,
        },
        headers=rider.headers,
    )
    assert registro.status_code == 201
    estado = client.get("/v1/rider/state", headers=rider.headers).json()
    assert estado["registration"]["status"] == "pending"
    assert client.post("/v1/rider/online", headers=rider.headers).json()["error"]["code"] == "not_approved"
    fila = client.get("/v1/admin/riders", headers=admin.headers).json()
    assert [r["name"] for r in fila] == ["Carlos Moto"]
    assert client.get(f"/v1/riders/{rider.user_id}/documents/cnh", headers=admin.headers).content == JPEG
    assert client.post(f"/v1/admin/riders/{rider.user_id}/approve", headers=admin.headers).status_code == 204
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    client.put("/v1/passenger/emergency-contact", json={"name": "Maria", "phone": "75 98888-7777"}, headers=pax.headers)
    avisos_pax, avisos_rider, avisos_admin = listen(pax.user_id), listen(rider.user_id), listen(admin.user_id)

    # 2) corrida 1, Pix: pedido, aceite, pagamento assinado, parada longa, "tudo bem", fim e notas
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"token": pax.token})
        assert _pool.submit(ws.receive_json).result(timeout=3)["type"] == "ready"
        corrida1 = pedir("pix")
        cobranca1 = repo.get_current_charge_id(session, corrida1["ride_id"])
        assert webhook(runtime.provider.mark_paid(cobranca1)).json() == {"status": "applied"}
        fim1 = percurso(corrida1, parar_s=200)
        assert fim1["state"] == "completed" and fim1["end_payment"] is None
        alerta = next(m for m in avisos_pax.messages if m["type"] == "safety_check")["data"]
        assert client.post(
            f"/v1/rides/{corrida1['ride_id']}/safety/{alerta['alert_id']}/ok", headers=pax.headers
        ).status_code == 204
        vistos = []
        while "trip_completed" not in vistos:           # tudo isso também chegou pelo WebSocket, na ordem
            vistos.append(_pool.submit(ws.receive_json).result(timeout=3)["type"])
        assert [t for t in vistos if t != "rider_position"] == [
            "rider_accepted", "pix_confirmed", "rider_arrived", "trip_started", "safety_check", "trip_completed",
        ]
    assert client.post(f"/v1/rides/{corrida1['ride_id']}/rating", json={"stars": 5}, headers=pax.headers).status_code == 204
    assert client.post(f"/v1/rides/{corrida1['ride_id']}/rating", json={"stars": 4}, headers=rider.headers).status_code == 204
    assert client.get("/v1/passenger/state", headers=pax.headers).json()["ride"] is None

    # 3) corrida 2, dinheiro: ninguém paga; passam 5 minutos; o passageiro é bloqueado; paga atrasado pelo QR
    corrida2 = pedir("cash")
    fim2 = percurso(corrida2)
    qr2 = fim2["end_payment"]["charge_id"]
    assert qr2 and client.get(f"/v1/charges/{qr2}", headers=pax.headers).json()["amount_cents"] == corrida2["price_cents"]
    clock.advance(301)
    assert sweep_once(runtime).cash_blocked == 1
    assert "payment_pending" in avisos_pax.types and "passenger_blocked" in avisos_rider.types
    estado_pax = client.get("/v1/passenger/state", headers=pax.headers).json()
    assert estado_pax["pending_payment"]["blocked"] is True and "Falta pagar" in estado_pax["blocked_reason"]
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).status_code == 403
    assert webhook(runtime.provider.mark_paid(qr2)).json() == {"status": "applied"}
    assert "unblocked" in avisos_pax.types and avisos_rider.messages[-1]["data"]["late"] is True
    assert client.post("/v1/passenger/quotes", json=QUOTE, headers=pax.headers).status_code == 200

    # 4) corrida 3 (a 10ª): paga na mão; o motoqueiro precisa pagar a entrada de R$ 50 para continuar
    acc = repo.get_rider_account(session, rider.user_id, for_update=True)
    acc.completed_rides = 9
    repo.save_rider_account(session, acc)
    corrida3 = pedir("cash")
    percurso(corrida3)
    assert client.post(f"/v1/rider/rides/{corrida3['ride_id']}/cash-received", headers=rider.headers).status_code == 204
    assert "entry_required" in avisos_rider.types and session.get(RiderProfileRow, rider.user_id).online is False
    assert client.post("/v1/rider/online", headers=rider.headers).json()["error"]["code"] == "entry_pending"
    entrada = client.post("/v1/rider/entry-charge", headers=rider.headers).json()
    assert client.post(f"/v1/dev/pix/{entrada['charge_id']}/pay").json() == {"status": "applied"}
    assert client.post("/v1/rider/online", headers=rider.headers).json()["error"]["code"] == "debt_pending"
    divida = client.post("/v1/rider/debt-charge", headers=rider.headers).json()      # a dívida de R$ 1,00 também bloqueia
    assert client.post(f"/v1/dev/pix/{divida['charge_id']}/pay").json() == {"status": "applied"}
    assert client.post("/v1/rider/online", headers=rider.headers).status_code == 204
    conta = client.get("/v1/rider/state", headers=rider.headers).json()["account"]
    assert (conta["completed_rides"], conta["entry_paid"], conta["cash_debt_cents"], conta["needs_entry"]) == (
        10, True, 0, False,
    )

    # 5) o livro-caixa fecha e bate com o extrato do provedor; o dono viu o alerta e a nota do motoqueiro subiu
    livro = PgLedger(session)
    assert livro.is_balanced() is True
    p1, p2 = corrida1["price_cents"], corrida2["price_cents"]
    assert livro.balance(f"rider:{rider.user_id}") == (p1 - 100) + (p2 - 100)
    assert livro.balance(PgLedger.COMPANY) == 100 + 100 + 5000 + 100
    assert livro.balance(PgLedger.PROVIDER) == -(p1 + p2 + 5000 + 100)
    extrato = {
        (f"entry:{c.rider_id}" if c.purpose == "entry" else f"charge:{c.charge_id}"): c.amount_cents
        for c in runtime.provider.charges.values()
        if c.paid and not c.refunded
    }
    assert livro.reconcile(extrato) == {}
    assert avisos_admin.types.count("safety_alert") == 1
    assert client.get("/v1/rider/state", headers=rider.headers).json()["registration"]["rating"] == 5.0
