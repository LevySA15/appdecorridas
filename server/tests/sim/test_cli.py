import simulator.__main__ as cli
from simulator.behavior import Profile
from simulator.model import Outcome, SimConfig
from simulator.stats import RideRecord, Stats

AUDIT_OK = {
    "ledger_balanced": True, "reconcile_diff": {}, "rides_by_state": {"completed": 1}, "open_rides": [],
    "double_booked_riders": [],
}


def rodada(audit=None) -> Outcome:
    stats = Stats()
    stats.rides["ride-1"] = RideRecord("ride-1", 1, "pix", 700, "Preço normal.", 0.0, 5.0, 60.0, 70.0, 190.0, "completed")
    cfg = SimConfig(url="http://x", admin_phone="75 99999-0000", profile=Profile())
    return Outcome(cfg, stats, AUDIT_OK if audit is None else audit, 200.0, 1)


def argumentos(*extra):
    return cli.build_parser().parse_args(["run", "--admin-phone", "75 99999-0000", *extra])


def test_valores_padrao_da_linha_de_comando():
    args = argumentos()
    cfg = cli.make_config(args, args.url, args.admin_phone, fast=False)
    assert (cfg.riders, cfg.passengers, cfg.minutes, cfg.seed) == (8, 16, 10.0, 1)
    assert cfg.profile.speedup == 1.0 and cfg.profile.pace == 1.0 and cfg.profile.pix_window_s == 120.0


def test_opcoes_de_velocidade_ritmo_perfil_e_cidade_chegam_ao_perfil():
    args = argumentos("--speed", "3", "--pace", "0.5", "--profile", "bagunca", "--city-scale", "0.3", "--max-rides", "4")
    cfg = cli.make_config(args, args.url, args.admin_phone, fast=False)
    assert (cfg.profile.speedup, cfg.profile.pace, cfg.profile.city_scale, cfg.max_rides) == (3.0, 0.5, 0.3, 4)
    assert cfg.profile.stop_mid_trip > 0.1                                # o perfil "bagunca" veio junto


def test_modo_rapido_alinha_o_perfil_aos_prazos_curtos_do_servidor():
    args = cli.build_parser().parse_args(["demo", "--fast"])
    cfg = cli.make_config(args, "http://x", "75 99999-0000", fast=True)
    assert cfg.profile.pix_window_s == 40.0 and cfg.profile.offer_window_s == 8.0 and cfg.profile.speedup == 4.0


def test_velocidade_acima_do_limite_do_servidor_nao_comeca(capsys):
    assert cli.main(["run", "--admin-phone", "75 99999-0000", "--speed", "9"]) == 2
    assert "velocidade" in capsys.readouterr().err


def test_perfil_desconhecido_nao_comeca(capsys):
    assert cli.main(["run", "--admin-phone", "75 99999-0000", "--profile", "doidao"]) == 2
    assert "perfil" in capsys.readouterr().err


def test_rodada_limpa_grava_o_relatorio_e_sai_com_zero(monkeypatch, tmp_path, capsys):
    async def falsa(cfg):
        return rodada()

    monkeypatch.setattr(cli, "simulate", falsa)
    assert cli.main(["run", "--admin-phone", "75 99999-0000", "--out", str(tmp_path)]) == 0
    [arquivo] = tmp_path.glob("relatorio-*.md")
    assert "**Tudo certo.**" in arquivo.read_text(encoding="utf-8")
    assert "Relatório gravado em" in capsys.readouterr().out


def test_rodada_com_problema_sai_com_um(monkeypatch, tmp_path):
    async def falsa(cfg):
        return rodada({**AUDIT_OK, "ledger_balanced": False})

    monkeypatch.setattr(cli, "simulate", falsa)
    assert cli.main(["run", "--admin-phone", "75 99999-0000", "--out", str(tmp_path)]) == 1


def test_ctrl_c_interrompe_com_aviso_e_codigo_130(monkeypatch, tmp_path, capsys):
    async def interrompida(cfg):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "simulate", interrompida)
    assert cli.main(["run", "--admin-phone", "75 99999-0000", "--out", str(tmp_path)]) == 130
    assert "Interrompido" in capsys.readouterr().err
    assert list(tmp_path.glob("relatorio-*.md")) == []


def test_servidor_fora_do_ar_nao_comeca_e_diz_por_que(tmp_path, capsys):
    assert cli.main(["run", "--url", "http://127.0.0.1:1", "--admin-phone", "75 99999-0000", "--out", str(tmp_path)]) == 2
    assert "Erro: não consegui pedir o código" in capsys.readouterr().err
