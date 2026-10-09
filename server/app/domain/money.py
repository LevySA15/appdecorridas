"""Formatação de dinheiro para textos que o usuário lê."""
from __future__ import annotations


def brl(cents: int) -> str:
    if cents < 0:
        raise ValueError("o valor não pode ser negativo")
    return f"R$ {cents // 100},{cents % 100:02d}"
