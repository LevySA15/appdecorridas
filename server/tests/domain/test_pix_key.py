import pytest

from app.domain.pix_key import normalize_pix_key


def test_cpf_valido_com_pontuacao():
    chave = normalize_pix_key(" 529.982.247-25 ")
    assert (chave.kind, chave.value, chave.masked) == ("cpf", "52998224725", "final 4725")


@pytest.mark.parametrize("cpf", ["529.982.247-26", "111.111.111-11", "000.000.000-00", "5299822472"])
def test_cpf_com_digito_errado_ou_repetido_e_recusado(cpf):
    with pytest.raises(ValueError, match="Chave Pix inválida"):
        normalize_pix_key(cpf)


def test_cnpj_valido():
    chave = normalize_pix_key("11.222.333/0001-81")
    assert (chave.kind, chave.value) == ("cnpj", "11222333000181")


def test_cnpj_com_digito_errado_e_recusado():
    with pytest.raises(ValueError, match="Chave Pix inválida"):
        normalize_pix_key("11.222.333/0001-82")


@pytest.mark.parametrize("texto", ["+55 (75) 98851-0824", "+55 75 98851-0824", "+5575988510824"])
def test_telefone_com_mais_55_vira_so_digitos(texto):
    chave = normalize_pix_key(texto)
    assert (chave.kind, chave.value, chave.masked) == ("phone", "+5575988510824", "final 0824")


def test_telefone_fixo_com_mais_55_tambem_vale():
    assert normalize_pix_key("+55 (75) 3631-1234").value == "+557536311234"


@pytest.mark.parametrize("texto", ["(75) 98851-0824", "75988510824", "75 3631-1234"])
def test_telefone_sem_mais_55_e_recusado_para_um_cpf_errado_nao_virar_telefone(texto):
    with pytest.raises(ValueError, match="Chave Pix inválida"):
        normalize_pix_key(texto)


def test_email_valido_fica_em_minusculas():
    chave = normalize_pix_key("  Levy.Anjos@Exemplo.COM ")
    assert (chave.kind, chave.value, chave.masked) == ("email", "levy.anjos@exemplo.com", "final .com")


@pytest.mark.parametrize("texto", ["sem-arroba", "a@b", "@exemplo.com", "a b@exemplo.com", "a@@exemplo.com", "x" * 80 + "@exemplo.com"])
def test_email_ruim_e_recusado(texto):
    with pytest.raises(ValueError, match="Chave Pix inválida"):
        normalize_pix_key(texto)


def test_chave_aleatoria_e_um_uuid():
    chave = normalize_pix_key("123E4567-E89B-12D3-A456-426614174000")
    assert (chave.kind, chave.value) == ("random", "123e4567-e89b-12d3-a456-426614174000")


@pytest.mark.parametrize("texto", ["", "   ", "abc", "123", "12345678-1234-1234-1234-12345678901", "++5575988510824", "+44 20 7946 0958"])
def test_lixo_e_recusado(texto):
    with pytest.raises(ValueError, match="Chave Pix inválida"):
        normalize_pix_key(texto)
