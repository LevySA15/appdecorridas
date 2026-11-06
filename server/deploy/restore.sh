#!/usr/bin/env bash
# Restaura um backup feito pelo backup.sh.
#
#   restore.sh db      ARQUIVO.dump    [--substituir]   (usa DATABASE_URL: o banco de destino)
#   restore.sh uploads ARQUIVO.tar.gz  [--substituir]   (usa UPLOAD_DIR: a pasta de destino)
#
# Por segurança, recusa um destino que já tem dados; --substituir autoriza (no banco, apaga o que estiver lá).
set -euo pipefail

erro() { echo "restore: $*" >&2; exit 1; }
uso() { echo "uso: restore.sh db ARQUIVO.dump [--substituir] | restore.sh uploads ARQUIVO.tar.gz [--substituir]" >&2; exit 2; }

[ $# -ge 2 ] || uso
tipo=$1; arquivo=$2; substituir=nao
if [ $# -ge 3 ]; then [ "$3" = "--substituir" ] && [ $# -eq 3 ] || uso; substituir=sim; fi
[ -f "$arquivo" ] || erro "não achei o arquivo $arquivo"

case "$tipo" in
  db)
    [ -n "${DATABASE_URL:-}" ] || erro "falta DATABASE_URL (o banco que vai receber o backup)"
    url=${DATABASE_URL/postgresql+psycopg:\/\//postgresql:\/\/}
    pg_restore --list "$arquivo" > /dev/null 2>&1 || erro "$arquivo não é um backup de banco legível"
    # tabelas, visões e sequências que não pertencem a uma extensão
    quantas=$(psql "$url" -Atc "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where c.relkind in ('r','p','v','m','S') and n.nspname not in ('pg_catalog','information_schema','pg_toast')
      and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e')") || erro "não consegui falar com o banco"
    if [ "$quantas" -gt 0 ] && [ "$substituir" = nao ]; then
      erro "o banco de destino já tem dados. Se é isso mesmo que você quer, repita com --substituir (apaga o que está lá)."
    fi
    limpar=(); [ "$substituir" = sim ] && limpar=(--clean --if-exists)
    pg_restore --no-owner --exit-on-error "${limpar[@]}" --dbname "$url" "$arquivo" || erro "a restauração do banco falhou"
    echo "restore: banco restaurado de $arquivo"
    ;;
  uploads)
    [ -n "${UPLOAD_DIR:-}" ] || erro "falta UPLOAD_DIR (a pasta que vai receber as fotos)"
    tar -tzf "$arquivo" > /dev/null 2>&1 || erro "$arquivo não é um backup de fotos legível"
    if [ -d "$UPLOAD_DIR" ] && [ -n "$(ls -A "$UPLOAD_DIR")" ] && [ "$substituir" = nao ]; then
      erro "a pasta $UPLOAD_DIR já tem arquivos. Se é isso mesmo que você quer, repita com --substituir (os de mesmo nome são trocados)."
    fi
    umask 077
    mkdir -p "$UPLOAD_DIR"
    chmod 700 "$UPLOAD_DIR"
    tar -xzf "$arquivo" -C "$UPLOAD_DIR" || erro "a restauração das fotos falhou"
    echo "restore: fotos restauradas em $UPLOAD_DIR"
    ;;
  *) uso ;;
esac
