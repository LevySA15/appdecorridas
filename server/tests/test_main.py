from fastapi import FastAPI

import app.main as main


def test_fabrica_do_servidor_liga_o_agendador(monkeypatch, settings):
    import dataclasses

    chamadas = {}
    pronta = dataclasses.replace(settings, mode="dev", webhook_secret="segredo")
    monkeypatch.setattr(main, "load_settings", lambda: pronta)
    monkeypatch.setattr(main, "build_runtime", lambda s: ("runtime-de-mentira", s))

    def create_app_falso(runtime, **kwargs):
        chamadas.update(runtime=runtime, **kwargs)
        return FastAPI()

    monkeypatch.setattr(main, "create_app", create_app_falso)
    assert isinstance(main.create_default_app(), FastAPI)
    assert chamadas == {"runtime": ("runtime-de-mentira", pronta), "run_background": True}
