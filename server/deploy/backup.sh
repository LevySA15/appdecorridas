#!/usr/bin/env bash
# Backup diário do banco e das fotos de documento.
#
# Variáveis (do arquivo de configuração; ver server/deploy/app.env.example):
#   DATABASE_URL             endereço do banco (aceita o prefixo postgresql+psycopg://)
#   UPLOAD_DIR               pasta das fotos de documento
#   BACKUP_DIR               onde guardar (padrão /var/backups/app-corrida)
#   BACKUP_KEEP_DAYS         dias de guarda dos backups do banco (padrão 14)
#   BACKUP_KEEP_UPLOAD_DAYS  dias de guarda dos backups das fotos (padrão 7)
#   BACKUP_NOW               AAAAMMDD-HHMMSS, só para teste (padrão: agora)
#
# O arquivo só ganha o nome final depois de conferido; qualquer falha termina com código diferente de zero.
set -euo pipefail

erro() { echo "backup: $*" >&2; exit 1; }

[ -n "${DATABASE_URL:-}" ] || erro "falta DATABASE_URL (veja server/deploy/app.env.example)"
dir=${BACKUP_DIR:-/var/backups/app-corrida}
keep_db=${BACKUP_KEEP_DAYS:-14}
keep_up=${BACKUP_KEEP_UPLOAD_DAYS:-7}
agora=${BACKUP_NOW:-$(date +%Y%m%d-%H%M%S)}
url=${DATABASE_URL/postgresql+psycopg:\/\//postgresql:\/\/}

umask 077
mkdir -p "$dir"
chmod 700 "$dir"

# sobras de uma queda no meio de um backup anterior
rm -f "$dir"/db-[0-9]*-[0-9]*.dump.part "$dir"/uploads-[0-9]*-[0-9]*.tar.gz.part

db_final="$dir/db-$agora.dump"
db_parte="$db_final.part"
trap 'rm -f "$db_parte" "${up_parte:-}"' EXIT

pg_dump --format=custom --no-owner --dbname "$url" --file "$db_parte" || erro "o pg_dump falhou"
pg_restore --list "$db_parte" > /dev/null || erro "o backup do banco saiu ilegível"
chmod 600 "$db_parte"
mv "$db_parte" "$db_final"
echo "backup: banco gravado em $db_final"

if [ -n "${UPLOAD_DIR:-}" ] && [ -d "$UPLOAD_DIR" ] && [ -n "$(ls -A "$UPLOAD_DIR")" ]; then
  up_final="$dir/uploads-$agora.tar.gz"
  up_parte="$up_final.part"
  rc=0; tar -czf "$up_parte" -C "$UPLOAD_DIR" . || rc=$?
  [ "$rc" -le 1 ] || erro "o tar das fotos falhou"       # 1 = um arquivo mudou durante a leitura (envio na hora do backup): vale
  tar -tzf "$up_parte" > /dev/null || erro "o backup das fotos saiu ilegível"
  chmod 600 "$up_parte"
  mv "$up_parte" "$up_final"
  echo "backup: fotos gravadas em $up_final"
else
  echo "backup: aviso: sem fotos para guardar (UPLOAD_DIR vazio ou inexistente)" >&2
fi

# limpeza: pela data que está no nome, só dos nossos arquivos, e nunca o mais novo de cada tipo
hoje=$(date -ud "${agora:0:8}" +%s)
limpar() {  # prefixo sufixo dias
  local prefixo=$1 sufixo=$2 dias=$3 arquivos=() f nome data idade
  for f in "$dir"/$prefixo-[0-9]*-[0-9]*$sufixo; do
    [ -e "$f" ] || continue
    nome=$(basename "$f")
    [[ $nome =~ ^$prefixo-([0-9]{8})-([0-9]{6})${sufixo//./\\.}$ ]] || continue
    arquivos+=("$f")
  done
  [ ${#arquivos[@]} -gt 1 ] || return 0
  local mais_novo
  mais_novo=$(printf '%s\n' "${arquivos[@]}" | sort | tail -n 1)
  for f in "${arquivos[@]}"; do
    [ "$f" = "$mais_novo" ] && continue
    data=$(basename "$f"); data=${data#"$prefixo"-}; data=${data:0:8}
    idade=$(( (hoje - $(date -ud "$data" +%s)) / 86400 ))
    if [ "$idade" -gt "$dias" ]; then rm -f "$f"; echo "backup: apagado $(basename "$f") (${idade} dias)"; fi
  done
}
limpar db .dump "$keep_db"
limpar uploads .tar.gz "$keep_up"
