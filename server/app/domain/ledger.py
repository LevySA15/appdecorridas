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
    BALANCE_CREDIT = "balance_credit"   # dinheiro que fica como saldo do passageiro (devolução que não chegou, recurso)
    BALANCE_SPEND = "balance_spend"     # saldo do passageiro paga a taxa ao motoqueiro
    TOPUP = "topup"                     # recarga do saldo por Pix
    DEBT_PAYMENT = "debt_payment"       # o motoqueiro pagou por Pix a dívida da taxa das corridas em dinheiro
    WITHDRAWAL = "withdrawal"           # o passageiro sacou o saldo por Pix


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

    @staticmethod
    def balance_account(passenger_id: str) -> str:
        """Conta do saldo do passageiro (positiva = dinheiro dele guardado no app)."""
        return f"balance:{passenger_id}"

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

    def post_charge_payment_from_balance(
        self, charge_id: str, passenger_id: str, rider_id: str, price_cents: int, split: Split
    ) -> None:
        """Lança uma corrida paga com o saldo do passageiro: o dinheiro sai de `balance:<id>`, não do provedor."""
        if split.rider_cents + split.company_cents != price_cents:
            raise ValueError("a divisão não fecha com o preço da corrida")
        ref = f"charge:{charge_id}"
        if self._has(ref, EntryKind.RIDE_PAYMENT):
            raise ValueError(f"pagamento da cobrança {charge_id} já lançado")
        self._append(ref, self.balance_account(passenger_id), -price_cents, EntryKind.RIDE_PAYMENT)
        self._append(ref, f"rider:{rider_id}", split.rider_cents, EntryKind.RIDE_PAYMENT)
        self._append(ref, self.COMPANY, split.company_cents, EntryKind.RIDE_PAYMENT)

    def _reverse(self, charge_id: str, destination: str, kind: EntryKind, keep_cents: int) -> None:
        """Desfaz um pagamento. O motoqueiro fica com `keep_cents` (taxa retida), a empresa devolve a sua parte
        e o resto do valor vai para `destination` (o provedor, que devolve o Pix, ou o saldo do passageiro).
        Pagamento feito com o saldo só volta para o mesmo saldo: o provedor nunca recebeu esse dinheiro."""
        ref = f"charge:{charge_id}"
        originals = [e for e in self._entries if e.ref == ref and e.kind is EntryKind.RIDE_PAYMENT]
        if not originals:
            raise ValueError(f"pagamento da cobrança {charge_id} não encontrado")
        if self._has(ref, EntryKind.REFUND) or self._has(ref, EntryKind.BALANCE_CREDIT):
            raise ValueError(f"cobrança {charge_id} já devolvida")
        source = next(e for e in originals if e.amount_cents < 0)      # de onde o dinheiro saiu: provedor ou saldo
        if source.account.startswith("balance:") and destination != source.account:
            raise ValueError("pagamento feito com saldo só volta para o saldo")
        price = -source.amount_cents
        if not 0 <= keep_cents <= price:
            raise ValueError("a parte retida precisa estar entre zero e o valor da cobrança")
        for e in originals:
            if e is source:
                continue
            adjust = keep_cents - e.amount_cents if e.account.startswith("rider:") else -e.amount_cents
            self._append(ref, e.account, adjust, kind)
        self._append(ref, destination, price - keep_cents, kind)

    def post_refund(self, charge_id: str, *, keep_cents: int = 0) -> None:
        """Devolve o Pix pago; com `keep_cents`, a taxa retida fica com o motoqueiro e só o resto volta."""
        self._reverse(charge_id, self.PROVIDER, EntryKind.REFUND, keep_cents)

    def post_refund_to_balance(self, charge_id: str, passenger_id: str, *, keep_cents: int = 0) -> None:
        """A devolução não chegou à chave Pix do passageiro: o valor vira saldo dele no app."""
        self._reverse(charge_id, self.balance_account(passenger_id), EntryKind.BALANCE_CREDIT, keep_cents)

    def post_spend_balance(self, ref: str, passenger_id: str, rider_id: str, amount_cents: int) -> None:
        if amount_cents <= 0:
            raise ValueError("o valor gasto do saldo precisa ser positivo")
        if self._has(ref, EntryKind.BALANCE_SPEND):
            raise ValueError(f"gasto do saldo {ref} já lançado")
        self._append(ref, self.balance_account(passenger_id), -amount_cents, EntryKind.BALANCE_SPEND)
        self._append(ref, f"rider:{rider_id}", amount_cents, EntryKind.BALANCE_SPEND)

    def post_withdrawal(self, withdrawal_id: str, passenger_id: str, amount_cents: int) -> None:
        """O passageiro sacou o saldo: sai do saldo dele e vira Pix pelo provedor."""
        if amount_cents <= 0:
            raise ValueError("o valor do saque precisa ser positivo")
        ref = f"withdraw:{withdrawal_id}"
        if self._has(ref, EntryKind.WITHDRAWAL):
            raise ValueError(f"saque {withdrawal_id} já lançado")
        self._append(ref, self.balance_account(passenger_id), -amount_cents, EntryKind.WITHDRAWAL)
        self._append(ref, self.PROVIDER, amount_cents, EntryKind.WITHDRAWAL)

    def post_topup(self, charge_id: str, passenger_id: str, amount_cents: int) -> None:
        if amount_cents <= 0:
            raise ValueError("o valor da recarga precisa ser positivo")
        ref = f"charge:{charge_id}"
        if self._has(ref, EntryKind.TOPUP):
            raise ValueError(f"recarga da cobrança {charge_id} já lançada")
        self._append(ref, self.PROVIDER, -amount_cents, EntryKind.TOPUP)
        self._append(ref, self.balance_account(passenger_id), amount_cents, EntryKind.TOPUP)

    def post_debt_payment(self, charge_id: str, amount_cents: int) -> None:
        """O motoqueiro pagou a dívida da taxa por Pix: dinheiro do provedor para a empresa."""
        if amount_cents <= 0:
            raise ValueError("o valor da dívida paga precisa ser positivo")
        ref = f"charge:{charge_id}"
        if self._has(ref, EntryKind.DEBT_PAYMENT):
            raise ValueError(f"pagamento de dívida da cobrança {charge_id} já lançado")
        self._append(ref, self.PROVIDER, -amount_cents, EntryKind.DEBT_PAYMENT)
        self._append(ref, self.COMPANY, amount_cents, EntryKind.DEBT_PAYMENT)

    def post_debt_refund(self, charge_id: str, amount_cents: int) -> None:
        """Devolve ao motoqueiro o que ele pagou a mais do que devia (a dívida diminuiu antes de o Pix chegar)."""
        if amount_cents <= 0:
            raise ValueError("o valor devolvido precisa ser positivo")
        ref = f"charge:{charge_id}"
        paid = sum(e.amount_cents for e in self._entries if e.ref == ref and e.kind is EntryKind.DEBT_PAYMENT and e.account == self.COMPANY)
        if not paid:
            raise ValueError(f"pagamento de dívida da cobrança {charge_id} não encontrado")
        if self._has(ref, EntryKind.REFUND):
            raise ValueError(f"excesso da cobrança {charge_id} já devolvido")
        if amount_cents > paid:
            raise ValueError("o excesso devolvido é maior que o pago")
        self._append(ref, self.PROVIDER, amount_cents, EntryKind.REFUND)
        self._append(ref, self.COMPANY, -amount_cents, EntryKind.REFUND)

    def post_credit_from_company(self, ref: str, passenger_id: str, amount_cents: int) -> None:
        """A empresa devolve ao passageiro, como saldo, uma taxa que o administrador aceitou rever."""
        if amount_cents <= 0:
            raise ValueError("o crédito precisa ser positivo")
        if self._has(ref, EntryKind.BALANCE_CREDIT):
            raise ValueError(f"crédito {ref} já lançado")
        self._append(ref, self.COMPANY, -amount_cents, EntryKind.BALANCE_CREDIT)
        self._append(ref, self.balance_account(passenger_id), amount_cents, EntryKind.BALANCE_CREDIT)

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
