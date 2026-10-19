"""Chave Pix de quem saca o saldo: confere o formato e guarda só o final (LGPD)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_INVALID = "Chave Pix inválida."
_EMAIL = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PHONE_TEXT = re.compile(r"\+?[\d\s().\-/]+")


@dataclass(frozen=True)
class PixKey:
    kind: str       # cpf | cnpj | phone | email | random
    value: str      # a chave como vai ao provedor
    masked: str     # o que fica no banco: só o final


def _cpf_ok(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
        if (total * 10) % 11 % 10 != int(digits[size]):
            return False
    return True


def _cnpj_ok(digits: str) -> bool:
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    def check_digit(base: str) -> int:
        weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if len(base) == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        rest = sum(int(c) * w for c, w in zip(base, weights)) % 11
        return 0 if rest < 2 else 11 - rest

    return check_digit(digits[:12]) == int(digits[12]) and check_digit(digits[:13]) == int(digits[13])


def _make(kind: str, value: str) -> PixKey:
    return PixKey(kind, value, "final " + value[-4:])


def normalize_pix_key(raw: str) -> PixKey:
    """Reconhece o tipo da chave e a deixa como o provedor espera. Levanta `ValueError` se não for uma chave."""
    text = (raw or "").strip()
    if not text:
        raise ValueError(_INVALID)
    if "@" in text:
        email = text.lower()
        if len(email) > 77 or not _EMAIL.fullmatch(email):
            raise ValueError(_INVALID)
        return _make("email", email)
    if _UUID.fullmatch(text.lower()):
        return _make("random", text.lower())
    if not _PHONE_TEXT.fullmatch(text):
        raise ValueError(_INVALID)
    digits = re.sub(r"\D", "", text)
    if text.startswith("+"):                                   # a chave de telefone do Pix sempre leva +55
        if text.count("+") == 1 and digits.startswith("55") and len(digits) in (12, 13):
            return _make("phone", "+" + digits)
        raise ValueError(_INVALID)
    if _cpf_ok(digits):
        return _make("cpf", digits)
    if _cnpj_ok(digits):
        return _make("cnpj", digits)
    raise ValueError(_INVALID)       # telefone só com +55: um CPF digitado errado não pode virar o telefone de outra pessoa
