import pytest

from app.domain.money import brl


@pytest.mark.parametrize(
    "cents, texto",
    [(700, "R$ 7,00"), (5000, "R$ 50,00"), (5, "R$ 0,05"), (123456, "R$ 1234,56"), (0, "R$ 0,00")],
)
def test_formata_reais(cents, texto):
    assert brl(cents) == texto


def test_valor_negativo_e_recusado():
    with pytest.raises(ValueError):
        brl(-1)
