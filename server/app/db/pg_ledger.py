"""Livro-caixa gravado no PostgreSQL (spec, seção 7.6).

As regras (cada cobrança soma zero, sem pagamento nem estorno repetidos, correções balanceadas)
são as do `Ledger` do domínio: cada operação carrega os lançamentos da referência, deixa o domínio
validar e grava só os lançamentos novos. O banco repete a proteção: chave única contra repetição e
gatilhos que recusam alterar, apagar ou esvaziar a tabela.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LedgerRow
from app.domain.ledger import EntryKind, Ledger, LedgerEntry
from app.domain.payments import Split


class PgLedger:
    PROVIDER = Ledger.PROVIDER
    COMPANY = Ledger.COMPANY

    def __init__(self, session: Session) -> None:
        self.session = session

    def _load(self, ref: str) -> Ledger:
        rows = self.session.execute(
            select(LedgerRow).where(LedgerRow.ref == ref).order_by(LedgerRow.id)
        ).scalars()
        return Ledger.from_entries(
            LedgerEntry(r.id, r.ref, r.account, r.amount_cents, EntryKind(r.kind), r.note) for r in rows
        )

    def _store_new(self, ledger: Ledger, already: int) -> None:
        for e in ledger.entries[already:]:
            self.session.add(
                LedgerRow(ref=e.ref, account=e.account, amount_cents=e.amount_cents, kind=e.kind.value, note=e.note)
            )
        self.session.flush()

    def post_charge_payment(self, charge_id: str, rider_id: str, price_cents: int, split: Split) -> None:
        ledger = self._load(f"charge:{charge_id}")
        before = len(ledger.entries)
        ledger.post_charge_payment(charge_id, rider_id, price_cents, split)
        self._store_new(ledger, before)

    def post_refund(self, charge_id: str) -> None:
        ledger = self._load(f"charge:{charge_id}")
        before = len(ledger.entries)
        ledger.post_refund(charge_id)
        self._store_new(ledger, before)

    def post_entry_fee(self, rider_id: str, amount_cents: int) -> None:
        ledger = self._load(f"entry:{rider_id}")
        before = len(ledger.entries)
        ledger.post_entry_fee(rider_id, amount_cents)
        self._store_new(ledger, before)

    def post_correction(self, ref: str, lines: list[tuple[str, int]], reason: str) -> None:
        ledger = self._load(ref)
        before = len(ledger.entries)
        ledger.post_correction(ref, lines, reason)
        self._store_new(ledger, before)

    def balance(self, account: str) -> int:
        total = self.session.execute(
            select(func.coalesce(func.sum(LedgerRow.amount_cents), 0)).where(LedgerRow.account == account)
        ).scalar_one()
        return int(total)

    def is_balanced(self) -> bool:
        unbalanced = self.session.execute(
            select(LedgerRow.ref).group_by(LedgerRow.ref).having(func.sum(LedgerRow.amount_cents) != 0)
        ).first()
        return unbalanced is None

    def reconcile(self, provider_received_by_ref: dict[str, int]) -> dict[str, int]:
        rows = self.session.execute(
            select(LedgerRow).where(LedgerRow.account == self.PROVIDER).order_by(LedgerRow.id)
        ).scalars()
        provider_only = Ledger.from_entries(
            LedgerEntry(r.id, r.ref, r.account, r.amount_cents, EntryKind(r.kind), r.note) for r in rows
        )
        return provider_only.reconcile(provider_received_by_ref)
