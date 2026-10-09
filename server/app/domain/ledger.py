"""Livro-caixa que só acrescenta (spec, seção 7.6).

Cada `ref` (uma cobrança Pix, uma entrada de R$ 50) soma zero: o provedor é a origem do dinheiro
(valor negativo); o motoqueiro e a empresa são o destino (valores positivos).
A dívida de corridas em dinheiro vive na conta do motoqueiro (`RiderAccount`), não aqui.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from app.domain.payments import Split


class EntryKind(str, Enum):
    RIDE_PAYMENT = "ride_payment"
    REFUND = "refund"
    ENTRY_FEE = "entry_fee"
    CORRECTION = "correction"


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: int
    ref: str
    account: str
    amount_cents: int
    kind: EntryKind
    note: str = ""


class Ledger:
    PROVIDER = "provider"
    COMPANY = "company"

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    @classmethod
    def from_entries(cls, entries: Iterable[LedgerEntry]) -> Ledger:
        """Livro em memória montado a partir de lançamentos que já existem (por exemplo, do banco)."""
        ledger = cls()
        ledger._entries = list(entries)
        return ledger

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def _append(self, ref: str, account: str, amount_cents: int, kind: EntryKind, note: str = "") -> None:
        self._entries.append(LedgerEntry(len(self._entries) + 1, ref, account, amount_cents, kind, note))

    def _has(self, ref: str, kind: EntryKind) -> bool:
        return any(e.ref == ref and e.kind is kind for e in self._entries)

    def post_charge_payment(
        self, charge_id: str, rider_id: str, price_cents: int, split: Split
    ) -> None:
        """Lança um Pix pago. A chave é a cobrança, não a corrida: uma corrida que troca de moto
        pode ter uma cobrança estornada e outra paga."""
        if split.rider_cents + split.company_cents != price_cents:
            raise ValueError("a divisão não fecha com o preço da corrida")
        ref = f"charge:{charge_id}"
        if self._has(ref, EntryKind.RIDE_PAYMENT):
            raise ValueError(f"pagamento da cobrança {charge_id} já lançado")
        self._append(ref, self.PROVIDER, -price_cents, EntryKind.RIDE_PAYMENT)
        self._append(ref, f"rider:{rider_id}", split.rider_cents, EntryKind.RIDE_PAYMENT)
        self._append(ref, self.COMPANY, split.company_cents, EntryKind.RIDE_PAYMENT)

    def post_refund(self, charge_id: str) -> None:
        ref = f"charge:{charge_id}"
        originals = [e for e in self._entries if e.ref == ref and e.kind is EntryKind.RIDE_PAYMENT]
        if not originals:
            raise ValueError(f"pagamento da cobrança {charge_id} não encontrado")
        if self._has(ref, EntryKind.REFUND):
            raise ValueError(f"cobrança {charge_id} já devolvida")
        for e in originals:
            self._append(ref, e.account, -e.amount_cents, EntryKind.REFUND)

    def post_entry_fee(self, rider_id: str, amount_cents: int) -> None:
        ref = f"entry:{rider_id}"
        if self._has(ref, EntryKind.ENTRY_FEE):
            raise ValueError(f"entrada do motoqueiro {rider_id} já lançada")
        self._append(ref, self.PROVIDER, -amount_cents, EntryKind.ENTRY_FEE)
        self._append(ref, self.COMPANY, amount_cents, EntryKind.ENTRY_FEE)

    def post_correction(self, ref: str, lines: list[tuple[str, int]], reason: str) -> None:
        if not reason.strip():
            raise ValueError("a correção precisa de um motivo")
        if not any(e.ref == ref for e in self._entries):
            raise ValueError(f"referência desconhecida: {ref}")
        if sum(amount for _, amount in lines) != 0:
            raise ValueError("as linhas da correção precisam somar zero")
        for account, amount in lines:
            self._append(ref, account, amount, EntryKind.CORRECTION, reason)

    def balance(self, account: str) -> int:
        return sum(e.amount_cents for e in self._entries if e.account == account)

    def is_balanced(self) -> bool:
        totals: dict[str, int] = {}
        for e in self._entries:
            totals[e.ref] = totals.get(e.ref, 0) + e.amount_cents
        return all(total == 0 for total in totals.values())

    def reconcile(self, provider_received_by_ref: dict[str, int]) -> dict[str, int]:
        """Compara o livro com o extrato do provedor. Devolve só as referências com diferença
        (valor do extrato menos valor do livro)."""
        mine: dict[str, int] = {}
        for e in self._entries:
            if e.account == self.PROVIDER:
                mine[e.ref] = mine.get(e.ref, 0) - e.amount_cents
        diffs: dict[str, int] = {}
        for ref in set(mine) | set(provider_received_by_ref):
            diff = provider_received_by_ref.get(ref, 0) - mine.get(ref, 0)
            if diff != 0:
                diffs[ref] = diff
        return diffs
