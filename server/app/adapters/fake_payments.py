"""Provedor de pagamento falso, para testes e para o simulador. Não fala com ninguém."""
from __future__ import annotations

from app.domain.payments import PixCharge, Split


class FakePaymentProvider:
    def __init__(self) -> None:
        self.charges: dict[str, PixCharge] = {}
        self._counter = 0

    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split
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

    def refund(self, charge_id: str) -> None:
        charge = self.charges[charge_id]
        if not charge.paid:
            raise ValueError("cobrança não paga, não há o que devolver")
        if charge.refunded:
            raise ValueError("cobrança já devolvida")
        charge.refunded = True
