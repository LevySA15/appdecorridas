import os
import stat

import pytest

from app.infra.documents import LocalDocumentStore, UploadError, sniff_image

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"0" * 64


@pytest.mark.parametrize(
    "dados, ext, tipo",
    [(JPEG, "jpg", "image/jpeg"), (PNG, "png", "image/png"), (WEBP, "webp", "image/webp")],
)
def test_reconhece_a_imagem_pelo_conteudo_e_nao_pelo_nome(dados, ext, tipo):
    assert sniff_image(dados) == (ext, tipo)


@pytest.mark.parametrize("dados", [b"", b"<html><script>alert(1)</script></html>", b"%PDF-1.7 ...", b"GIF89a....", b"\xff\xd8"])
def test_o_que_nao_e_imagem_aceita_e_recusado(dados):
    with pytest.raises(UploadError) as erro:
        sniff_image(dados)
    assert erro.value.status in (415, 422)


def test_guarda_e_devolve_com_chave_aleatoria(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    chave = loja.save("rider-1", "selfie", JPEG)
    assert chave.startswith("rider-1/selfie-") and chave.endswith(".jpg")
    assert loja.exists(chave) is True
    assert loja.read(chave) == (JPEG, "image/jpeg")
    assert loja.save("rider-1", "selfie", JPEG) != chave        # nunca sobrescreve


def test_arquivo_fica_so_para_o_dono_do_servidor(tmp_path):
    loja = LocalDocumentStore(tmp_path / "docs")
    chave = loja.save("rider-1", "cnh", PNG)
    arquivo = tmp_path / "docs" / chave
    assert stat.S_IMODE(os.stat(arquivo).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(arquivo.parent).st_mode) == 0o700


@pytest.mark.parametrize(
    "chave",
    ["../segredo", "rider-1/../../etc/passwd", "/etc/passwd", "rider-1/selfie-0123456789abcdef.exe", "rider-1/x", "", "a/b/c.jpg"],
)
def test_chave_estranha_nunca_chega_ao_disco(tmp_path, chave):
    loja = LocalDocumentStore(tmp_path)
    assert loja.exists(chave) is False
    with pytest.raises(LookupError):
        loja.read(chave)


def test_dono_e_tipo_invalidos_sao_recusados(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    with pytest.raises(ValueError):
        loja.save("../fora", "selfie", JPEG)
    with pytest.raises(ValueError):
        loja.save("rider-1", "senha", JPEG)


# --- plano 4F: listar e apagar -----------------------------------------------------------------


def test_lista_os_arquivos_com_a_hora_da_ultima_mudanca(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    a = loja.save("rider-1", "selfie", JPEG)
    b = loja.save("rider-2", "cnh", PNG)
    os.utime(tmp_path / a, (1_000.0, 1_000.0))
    achados = {item.key: item.modified_at for item in loja.list_all()}
    assert achados.keys() == {a, b} and achados[a] == 1_000.0 and achados[b] > 1_000.0


def test_lista_ignora_o_que_nao_e_foto_nossa(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    chave = loja.save("rider-1", "selfie", JPEG)
    (tmp_path / "rider-1" / "selfie-0123456789abcdef.jpg.part").write_bytes(b"x")     # envio pela metade
    (tmp_path / "rider-1" / "anotacao.txt").write_text("oi")
    (tmp_path / "solto.jpg").write_bytes(JPEG)                                         # fora de uma pasta de dono
    assert [item.key for item in loja.list_all()] == [chave]


def test_lista_de_pasta_que_nao_existe_e_vazia(tmp_path):
    assert LocalDocumentStore(tmp_path / "nada").list_all() == []


def test_apaga_o_arquivo_e_apagar_de_novo_nao_da_erro(tmp_path):
    loja = LocalDocumentStore(tmp_path)
    chave = loja.save("rider-1", "selfie", JPEG)
    loja.delete(chave)
    assert loja.exists(chave) is False
    loja.delete(chave)


@pytest.mark.parametrize("chave", ["../segredo", "rider-1/../../etc/passwd", "/etc/passwd", "", "a/b/c.jpg"])
def test_apagar_chave_estranha_nao_toca_em_nada(tmp_path, chave):
    (tmp_path / "importante.txt").write_text("fica")
    loja = LocalDocumentStore(tmp_path / "docs")
    loja.save("rider-1", "selfie", JPEG)
    loja.delete(chave)
    assert (tmp_path / "importante.txt").read_text() == "fica" and len(loja.list_all()) == 1
