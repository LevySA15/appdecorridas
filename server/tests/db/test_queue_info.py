"""`queue_info`: a corrida da fila que volta para a busca e é aceita por outra moto fica com duas ofertas "aceitas"."""
from app.db import queries
from app.db.models import RideOfferRow, RideRow
from tests.helpers_db import add_passenger, add_rider


def _corrida_com_ofertas(session, *ofertas):
    add_passenger(session)
    add_rider(session, "r1", "+5575900000011")
    add_rider(session, "r2", "+5575900000012", cpf="222.222.222-22", cnh="CNH0002", plate="BBB2B22")
    session.add(RideRow(id="ride-1", passenger_id="p1", rider_id="r2", price_cents=700, payment_method="cash", pin="1234", state="queued"))
    session.flush()
    for rider, eta, criada in ofertas:
        session.add(RideOfferRow(ride_id="ride-1", rider_id=rider, status="accepted", eta_seconds=eta, created_at=criada, expires_at=criada + 15))
        session.flush()


def test_corrida_da_fila_liberada_e_aceita_de_novo_usa_a_oferta_mais_nova(session):
    # r1 aceitou e a fila estourou (a oferta dele continua "aceita" no histórico); depois r2 aceitou
    _corrida_com_ofertas(session, ("r1", 95, 1.0), ("r2", 240, 600.0))
    info = queries.queue_info(session, "ride-1", "r2")
    assert info["eta_seconds"] == 240


def test_corrida_da_fila_com_uma_oferta_aceita_continua_igual(session):
    _corrida_com_ofertas(session, ("r2", 120, 1.0))
    assert queries.queue_info(session, "ride-1", "r2") == {"finishing_at": "", "eta_seconds": 120}


def test_sem_oferta_aceita_o_tempo_e_nulo(session):
    _corrida_com_ofertas(session)
    assert queries.queue_info(session, "ride-1", "r2")["eta_seconds"] is None
