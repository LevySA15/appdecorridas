"""Gente de mentira: nome, telefone e documentos válidos para o servidor e sempre os mesmos para o mesmo número.

Os telefones ficam numa faixa só do simulador (75 98100-xxxx para passageiros, 75 98200-xxxx para motoqueiros) e todo
nome termina com "(sim)", para ninguém confundir com gente de verdade nas listas do painel.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

JPEG = b"\xff\xd8\xff\xe0" + b"SIMULADOR" * 8        # o servidor só olha o começo do arquivo
FIRST = ("Ana", "Bruno", "Carla", "Diego", "Elaine", "Felipe", "Gabriela", "Hugo", "Isabela", "João", "Karina", "Lucas")
LAST = ("Silva", "Souza", "Lima", "Santos", "Oliveira", "Pereira", "Costa", "Ribeiro", "Almeida", "Nunes", "Rocha")
MODELS = ("Honda CG 160", "Honda Biz 125", "Yamaha Factor 150", "Honda Pop 110i", "Yamaha Fazer 250")


@dataclass(frozen=True)
class Identity:
    index: int
    phone: str
    name: str


@dataclass(frozen=True)
class RiderIdentity(Identity):
    cpf: str = ""
    cnh_number: str = ""
    plate: str = ""
    moto_model: str = ""
    cnh_expires_on: dt.date = dt.date.min
    crlv_expires_on: dt.date = dt.date.min


def _name(index: int, kind: int) -> str:
    return f"{FIRST[(index * 5 + kind) % len(FIRST)]} {LAST[(index * 7 + kind * 3) % len(LAST)]} (sim)"


def _cpf(index: int) -> str:
    digits = [5] + [int(c) for c in f"{index:08d}"]
    for n in (9, 10):
        total = sum(digits[i] * (n + 1 - i) for i in range(n))
        digits.append((total * 10 % 11) % 10)
    return "".join(map(str, digits))


def _plate(index: int) -> str:
    return f"SIM{(index // 2600) % 10}{chr(65 + (index // 100) % 26)}{index % 100:02d}"


def passenger_identity(index: int) -> Identity:
    return Identity(index, f"75 98100-{index:04d}", _name(index, 1))


def rider_identity(index: int, today: dt.date) -> RiderIdentity:
    return RiderIdentity(
        index, f"75 98200-{index:04d}", _name(index, 2), _cpf(index), f"{20_000_000_000 + index}", _plate(index),
        MODELS[index % len(MODELS)], today + dt.timedelta(days=700), today + dt.timedelta(days=300),
    )
