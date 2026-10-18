def test_saude_responde_ok_com_banco_e_redis(client):
    resposta = client.get("/health")
    assert resposta.status_code == 200 and resposta.json() == {"status": "ok"}


def test_saude_devolve_503_quando_algo_falha(client, runtime):
    class SessaoRuim:
        def __enter__(self):
            raise RuntimeError("sem banco")

        def __exit__(self, *args):
            return False

    runtime.session_factory = lambda: SessaoRuim()
    resposta = client.get("/health")
    assert resposta.status_code == 503 and resposta.json() == {"status": "down"}


def test_documentacao_automatica_so_existe_no_modo_dev(client):
    assert client.get("/docs").status_code == 200
