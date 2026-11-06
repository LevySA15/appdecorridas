"""Backup e restauração de verdade, contra um PostgreSQL descartável (pasta temporária, só socket, usuário comum)."""
import glob
import os
import random
import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
BACKUP = DEPLOY / "backup.sh"
RESTORE = DEPLOY / "restore.sh"


def _pg_bin() -> Path | None:
    achados = sorted(glob.glob("/usr/lib/postgresql/*/bin/initdb"))
    return Path(achados[-1]).parent if achados else None


PG_BIN = _pg_bin()
pytestmark = pytest.mark.skipif(PG_BIN is None, reason="PostgreSQL (initdb) não está instalado")


def _env(**extra: str) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "BACKUP_", "DATABASE_URL", "UPLOAD_DIR"))}
    base["PATH"] = f"{PG_BIN}:{base['PATH']}"
    base.update(extra)
    return base


def _rodar(*cmd: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), env=_env(**extra), capture_output=True, text=True, timeout=120)


class Cluster:
    def __init__(self, raiz: Path, porta: int) -> None:
        self.sock, self.porta = raiz / "sock", porta

    def url(self, banco: str, driver: str = "postgresql") -> str:
        return f"{driver}://teste@/{banco}?host={self.sock}&port={self.porta}"

    def sql(self, banco: str, comando: str) -> str:
        r = _rodar("psql", self.url(banco), "-Atc", comando)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("pg")
    (raiz / "sock").mkdir()
    porta = random.randint(55000, 59000)
    c = Cluster(raiz, porta)
    assert _rodar(str(PG_BIN / "initdb"), "-D", str(raiz / "data"), "-U", "teste", "-A", "trust", "-E", "UTF8",
                  "--locale=C.UTF-8", "--no-sync").returncode == 0
    opcoes = f"-c listen_addresses='' -c unix_socket_directories={raiz / 'sock'} -c port={porta} -c fsync=off"
    start = _rodar(str(PG_BIN / "pg_ctl"), "-D", str(raiz / "data"), "-o", opcoes, "-w", "-l", str(raiz / "log"), "start")
    assert start.returncode == 0, start.stderr + (raiz / "log").read_text()
    try:
        for banco in ("origem", "destino"):
            assert _rodar("createdb", "-h", str(raiz / "sock"), "-p", str(porta), "-U", "teste", banco).returncode == 0
        c.sql("origem", "create table pessoas(id int primary key, nome text); "
                        "insert into pessoas values (1, 'João da Conceição'), (2, 'Maria');")
        yield c
    finally:
        _rodar(str(PG_BIN / "pg_ctl"), "-D", str(raiz / "data"), "-m", "immediate", "stop")


@pytest.fixture()
def ambiente(tmp_path, cluster):
    uploads = tmp_path / "uploads"
    (uploads / "rider1").mkdir(parents=True)
    (uploads / "rider1" / "selfie.jpg").write_bytes(b"\xff\xd8 foto de mentira \x00\x01")
    return {"DATABASE_URL": cluster.url("origem"), "UPLOAD_DIR": str(uploads), "BACKUP_DIR": str(tmp_path / "backups")}


def _modo(caminho: Path) -> int:
    return stat.S_IMODE(caminho.stat().st_mode)


def _backup(ambiente, **extra):
    return _rodar(str(BACKUP), **{**ambiente, **extra})


def test_backup_grava_banco_e_fotos_com_permissao_restrita(ambiente):
    r = _backup(ambiente)
    assert r.returncode == 0, r.stderr
    pasta = Path(ambiente["BACKUP_DIR"])
    arquivos = sorted(p.name for p in pasta.iterdir())
    assert len(arquivos) == 2 and arquivos[0].startswith("db-") and arquivos[0].endswith(".dump")
    assert arquivos[1].startswith("uploads-") and arquivos[1].endswith(".tar.gz")
    assert _modo(pasta) == 0o700 and all(_modo(pasta / a) == 0o600 for a in arquivos)


def test_o_dump_restaura_os_mesmos_dados(ambiente, cluster):
    assert _backup(ambiente).returncode == 0
    dump = next(Path(ambiente["BACKUP_DIR"]).glob("db-*.dump"))
    cluster.sql("destino", "drop table if exists pessoas")
    r = _rodar(str(RESTORE), "db", str(dump), **{**ambiente, "DATABASE_URL": cluster.url("destino")})
    assert r.returncode == 0, r.stderr
    assert cluster.sql("destino", "select id || ':' || nome from pessoas order by id") == "1:João da Conceição\n2:Maria"


def test_endereco_no_formato_do_sqlalchemy_tambem_funciona(ambiente, cluster):
    r = _backup(ambiente, DATABASE_URL=cluster.url("origem", driver="postgresql+psycopg"))
    assert r.returncode == 0, r.stderr
    assert list(Path(ambiente["BACKUP_DIR"]).glob("db-*.dump"))


def test_sem_database_url_falha_dizendo_o_que_falta(ambiente):
    ambiente.pop("DATABASE_URL")
    r = _backup(ambiente)
    assert r.returncode != 0 and "DATABASE_URL" in r.stderr


def test_banco_que_nao_existe_falha_e_nao_deixa_arquivo(ambiente, cluster):
    r = _backup(ambiente, DATABASE_URL=cluster.url("nao_existe"))
    assert r.returncode != 0 and r.stderr.strip()
    pasta = Path(ambiente["BACKUP_DIR"])
    assert not pasta.exists() or list(pasta.iterdir()) == []


def test_pasta_de_fotos_que_nao_existe_so_avisa(ambiente):
    r = _backup(ambiente, UPLOAD_DIR=ambiente["UPLOAD_DIR"] + "-nao-existe")
    assert r.returncode == 0, r.stderr
    pasta = Path(ambiente["BACKUP_DIR"])
    assert list(pasta.glob("db-*.dump")) and not list(pasta.glob("uploads-*"))
    assert "fotos" in r.stderr.lower()


def test_limpeza_pela_data_do_nome_e_so_do_que_e_dela(ambiente):
    pasta = Path(ambiente["BACKUP_DIR"])
    pasta.mkdir(mode=0o700)
    for nome in ("db-20260215-030000.dump",            # 14 dias: fica
                 "db-20260214-030000.dump",            # 15 dias: sai
                 "uploads-20260222-030000.tar.gz",     # 7 dias: fica
                 "uploads-20260221-030000.tar.gz",     # 8 dias: sai
                 "notas.txt", "db-velho.txt", "db-abc.dump", "db-20260101-030000.dump.part-de-outro"):
        (pasta / nome).write_bytes(b"x")
    (pasta / "db-20260101-030000.dump.part").write_bytes(b"restos de uma queda")
    r = _backup(ambiente, BACKUP_NOW="20260301-030000", BACKUP_KEEP_DAYS="14", BACKUP_KEEP_UPLOAD_DAYS="7")
    assert r.returncode == 0, r.stderr
    restam = {p.name for p in pasta.iterdir()}
    assert {"db-20260215-030000.dump", "uploads-20260222-030000.tar.gz", "notas.txt", "db-velho.txt", "db-abc.dump",
            "db-20260101-030000.dump.part-de-outro", "db-20260301-030000.dump", "uploads-20260301-030000.tar.gz"} == restam


def test_nunca_apaga_o_unico_backup_de_um_tipo(ambiente):
    pasta = Path(ambiente["BACKUP_DIR"])
    pasta.mkdir(mode=0o700)
    (pasta / "uploads-20200101-030000.tar.gz").write_bytes(b"x")
    r = _backup(ambiente, UPLOAD_DIR=ambiente["UPLOAD_DIR"] + "-nao-existe", BACKUP_NOW="20260301-030000")
    assert r.returncode == 0, r.stderr
    assert (pasta / "uploads-20200101-030000.tar.gz").exists()


def test_restauracao_recusa_banco_com_dados_e_aceita_com_substituir(ambiente, cluster):
    assert _backup(ambiente).returncode == 0
    dump = str(next(Path(ambiente["BACKUP_DIR"]).glob("db-*.dump")))
    destino = {**ambiente, "DATABASE_URL": cluster.url("destino")}
    cluster.sql("destino", "drop table if exists pessoas")
    assert _rodar(str(RESTORE), "db", dump, **destino).returncode == 0
    cluster.sql("destino", "delete from pessoas where id = 2")
    recusou = _rodar(str(RESTORE), "db", dump, **destino)
    assert recusou.returncode != 0 and "--substituir" in recusou.stderr
    assert cluster.sql("destino", "select count(*) from pessoas") == "1"          # nada foi mexido
    assert _rodar(str(RESTORE), "db", dump, "--substituir", **destino).returncode == 0
    assert cluster.sql("destino", "select count(*) from pessoas") == "2"


def test_restaura_as_fotos_e_recusa_pasta_com_arquivos(ambiente, tmp_path):
    assert _backup(ambiente).returncode == 0
    tar = str(next(Path(ambiente["BACKUP_DIR"]).glob("uploads-*.tar.gz")))
    novo = tmp_path / "restaurado"
    r = _rodar(str(RESTORE), "uploads", tar, **{**ambiente, "UPLOAD_DIR": str(novo)})
    assert r.returncode == 0, r.stderr
    assert (novo / "rider1" / "selfie.jpg").read_bytes() == b"\xff\xd8 foto de mentira \x00\x01"
    de_novo = _rodar(str(RESTORE), "uploads", tar, **{**ambiente, "UPLOAD_DIR": str(novo)})
    assert de_novo.returncode != 0 and "--substituir" in de_novo.stderr
    assert _rodar(str(RESTORE), "uploads", tar, "--substituir", **{**ambiente, "UPLOAD_DIR": str(novo)}).returncode == 0


@pytest.mark.parametrize("tipo", ["db", "uploads"])
def test_arquivo_ilegivel_ou_inexistente_e_recusado(ambiente, tmp_path, tipo):
    lixo = tmp_path / "lixo.bin"
    lixo.write_bytes(b"isto nao e um backup")
    for arquivo in (lixo, tmp_path / "nao-existe"):
        r = _rodar(str(RESTORE), tipo, str(arquivo), **{**ambiente, "UPLOAD_DIR": str(tmp_path / "vazio")})
        assert r.returncode != 0 and r.stderr.strip()


def test_restauracao_sem_argumentos_mostra_o_uso(ambiente):
    r = _rodar(str(RESTORE), **ambiente)
    assert r.returncode != 0 and "uso" in r.stderr.lower()
