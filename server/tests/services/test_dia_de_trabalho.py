from app.adapters.fake_payments import FakePaymentProvider
from app.db import repositories as repo
from app.db.pg_ledger import PgLedger
from app.domain.fees import register_completed_ride
from app.domain.rides import CancelResult
from app.domain.types import PaymentMethod
from app.services.payments import PaymentService
from tests.helpers_db import add_accepted_ride, add_passenger, add_rider

FEE = 100


def test_dia_de_trabalho_com_dinheiro_pix_e_estorno_fecha_as_contas(session):
    provider = FakePaymentProvider()
    service = PaymentService(provider)
    add_passenger(session)
    add_rider(session)

    # 1) uma corrida em dinheiro já concluída: a taxa vira dívida do motoqueiro
    acc = repo.get_rider_account(session, "r1", for_update=True)
    register_completed_ride(acc, PaymentMethod.CASH, FEE)
    repo.save_rider_account(session, acc)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100

    # 2) uma corrida Pix de R$ 7,00: a dívida é abatida quando o Pix é pago
    add_accepted_ride(session, ride_id="ride-2", price=700)
    charge2 = service.start_pix_charge(session, "ride-2", FEE)
    assert repo.get_rider_account(session, "r1").cash_debt_cents == 100  # ainda não abateu
    assert service.on_provider_event(session, provider.mark_paid(charge2.charge_id)) == "applied"
    acc = repo.get_rider_account(session, "r1", for_update=True)
    register_completed_ride(acc, PaymentMethod.PIX, FEE)
    repo.save_rider_account(session, acc)
    assert (acc.cash_debt_cents, acc.debt_reserved_cents, acc.completed_rides) == (0, 0, 2)

    # 3) uma corrida Pix de R$ 6,00, paga e depois cancelada: o dinheiro volta
    add_accepted_ride(session, ride_id="ride-3", price=600)
    charge3 = service.start_pix_charge(session, "ride-3", FEE)
    service.on_provider_event(session, provider.mark_paid(charge3.charge_id))
    assert service.cancel_ride(session, "ride-3", now=20) == CancelResult(0, True)

    # fechamento: o livro bate com o extrato do provedor e tudo soma zero
    ledger = PgLedger(session)
    assert ledger.balance("rider:r1") == 500
    assert ledger.balance(PgLedger.COMPANY) == 200
    assert ledger.balance(PgLedger.PROVIDER) == -700
    assert ledger.is_balanced() is True
    extrato = {
        f"charge:{c.charge_id}": c.amount_cents
        for c in provider.charges.values()
        if c.paid and not c.refunded
    }
    assert extrato == {f"charge:{charge2.charge_id}": 700}
    assert ledger.reconcile(extrato) == {}
