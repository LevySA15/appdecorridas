"""Provedor de pagamento falso, para testes e para o simulador. Não fala com ninguém."""
from __future__ import annotations

from app.domain.payments import PixCharge, RefundUndeliverable, Split


class FakePaymentProvider:
    def __init__(self) -> None:
        self.charges: dict[str, PixCharge] = {}
        self._counter = 0
        self.undeliverable: set[str] = set()            # cobranças cuja devolução "não chega" à chave do passageiro
        self.refund_all_undeliverable = False           # idem, para todas (testes e simulador)

    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split, purpose: str = "ride",
        passenger_id: str = "",
    ) -> PixCharge:
        if split.rider_cents + split.company_cents != amount_cents:
            raise ValueError("a divisão não fecha com o valor da cobrança")
        self._counter += 1
        charge = PixCharge(
            charge_id=f"ch-{self._counter}",
            ride_id=ride_id,
            rider_id=rider_id,
            amount_cents=amount_cents,
            split=split,
            purpose=purpose,
            passenger_id=passenger_id,
            br_code=f"fake-pix|ch-{self._counter}|{amount_cents}",
        )
        self.charges[charge.charge_id] = charge
        return charge

    def mark_paid(self, charge_id: str) -> dict:
        charge = self.charges[charge_id]
        charge.paid = True
        return {
            "event_id": f"evt-{charge_id}-paid",
            "type": "paid",
            "charge_id": charge_id,
            "ride_id": charge.ride_id,
            "amount_cents": charge.amount_cents,
        }

    def refund(self, charge_id: str, amount_cents: int | None = None) -> None:
        charge = self.charges[charge_id]
        if not charge.paid:
            raise ValueError("cobrança não paga, não há o que devolver")
        remaining = charge.amount_cents - charge.refunded_cents
        if remaining <= 0:
            raise ValueError("cobrança já devolvida")
        amount = remaining if amount_cents is None else amount_cents
        if amount <= 0 or amount > remaining:
            raise ValueError(f"valor de devolução inválido: {amount} (restam {remaining})")
        if self.refund_all_undeliverable or charge_id in self.undeliverable:
            raise RefundUndeliverable(f"a devolução da cobrança {charge_id} não chega à chave do passageiro")
        charge.refunded_cents += amount
        charge.refunded = charge.refunded_cents == charge.amount_cents
