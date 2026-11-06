# Servidor pronto para ir ao ar (plano 4G) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, escolha do Levy) para implementar este plano tarefa a tarefa. Os passos usam caixas `- [ ]`.

**Goal:** deixar pronto tudo o que dá para preparar, sem o Levy e sem CNPJ, para colocar o servidor num computador na internet **para um teste fechado**: HTTPS, serviço que reinicia sozinho, backup que se prova restaurável, apps apontando para um endereço de verdade e um guia passo a passo em português simples.

**Architecture:** arquivos de implantação em `server/deploy/` (Caddy para HTTPS, unidades do systemd, scripts de backup e restauração, modelo do arquivo de configuração); duas mudanças pequenas no servidor (cabeçalhos de segurança; interruptor `DEV_ROUTES` para não montar as rotas de desenvolvimento num servidor público); uma no app (endereço do servidor por `--dart-define=API_URL=`); o guia em `docs/instalacao.md`.

**Tech Stack:** Python 3.12 / FastAPI / uvicorn, PostgreSQL 16 (`pg_dump`/`pg_restore`), Redis, Caddy 2, systemd, bash, Dart/Flutter.

**Spec:** não há documento de desenho. O pedido do Levy (06/11/2026): "pode fazer a outra parte" = a parte preparatória do bloco 3 que não depende dele (modelos de configuração e script de backup, sem instalar nada). Motivos das decisões abaixo, para quem for conferir.

## Fatos que moldam o plano (conferidos no código)

- `build_runtime` **só aceita `APP_MODE=dev`** (`app/runtime.py:185`): enquanto o plano 7 não existe, o servidor usa adaptadores falsos. Em modo dev, `GET /v1/dev/otp?phone=…` devolve o código de login de qualquer pessoa e `/docs` mostra tudo. Logo, **este plano prepara um teste fechado, não o lançamento público**: nenhuma integração real é ligada e o guia diz isso no topo.
- O limite de pedidos de código por IP (`app/api/routes/auth.py:38`) usa `request.client.host`, então atrás de um proxy ele só serve se o uvicorn ler o `X-Forwarded-For`. **Conferido na Task 5: o uvicorn já faz isso por padrão para `127.0.0.1`** (a premissa inicial de que daria problema estava errada); as flags `--proxy-headers --forwarded-allow-ips 127.0.0.1` ficam explícitas no serviço para não depender do padrão nem da variável `FORWARDED_ALLOW_IPS`.
- Os dois apps têm `http://localhost:8000` fixo no código. O Android de release bloqueia HTTP sem criptografia.
- O usuário do banco de desenvolvimento (`appcorrida`) não pode criar bancos; o teste de backup sobe um PostgreSQL descartável numa pasta temporária (`initdb` do usuário comum).
- O painel (`server/painel`) não tem script, estilo nem `onclick` dentro do HTML/JS e só fala com o próprio endereço (`fetch` relativo, `window.open(blob)`): cabe numa política `default-src 'self'`.

## Global Constraints

- Português claro nos textos para o Levy; código e comentários seguem o padrão do projeto (português).
- Nada de segredo no git: o modelo de configuração só tem valores de exemplo que começam com `TROQUE`.
- Dinheiro, banco e regras de negócio não mudam. `Settings`/`Runtime` só ganham `dev_routes` (padrão `True`, então desenvolvimento, simulador e contrato dos apps continuam iguais).
- Um processo só do uvicorn (`--workers 1`): o hub de WebSocket e o agendador vivem dentro dele.
- Backups contêm CPF, telefone e fotos de documento (LGPD): pasta `0700`, arquivos `0600`, validade curta e configurável; o prazo certo é pergunta para o advogado.
- Ninguém instala nada na máquina do Levy nem num servidor: só arquivos, testes e documentação.

## Review Focus

- Backup que sai incompleto (disco cheio, `pg_dump` falha no meio) não pode ficar com cara de bom: arquivo só aparece com o nome final depois de conferido, e a falha devolve código de saída ≠ 0.
- A limpeza de backups antigos nunca apaga arquivo que não seja dela (outra coisa na mesma pasta) e nunca apaga o único backup que existe.
- Restaurar por cima de um banco que já tem dados exige confirmação explícita (`--substituir`).
- Servidor público: `/docs`, `/openapi.json` e `/v1/dev/*` respondem 404 com `DEV_ROUTES=off`, mesmo em `APP_MODE=dev`.
- O app de release com `API_URL=http://...` (sem HTTPS) deve falhar alto na partida em vez de parecer funcionar e travar no primeiro pedido.

---

### Task 1: Cabeçalhos de segurança

**Files:**
- Create: `server/app/api/security_headers.py`
- Modify: `server/app/api/app.py` (instalar depois de `install_error_handlers`)
- Test: `server/tests/api/test_security_headers.py`

**Interfaces:**
- Produces: `install_security_headers(app: FastAPI) -> None`; constante `PAINEL_CSP: str`.

- [ ] **Step 1: testes (RED).** `test_toda_resposta_traz_os_cabecalhos_basicos` (`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, em `/health`, numa rota da API com 401 e numa 404); `test_painel_traz_politica_de_conteudo_restrita` (`Content-Security-Policy` em `/painel/` e `/painel/painel.js` contendo `default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`, sem `unsafe-inline` nem `unsafe-eval`); `test_a_api_nao_leva_a_politica_do_painel` (`/health` sem CSP); `test_painel_cabe_na_politica` (lê `index.html`/`painel.js`/`painel.css`: nenhum `<script>` sem `src`, nenhum `<style>`, nenhum atributo `style=`/`on…=`, nenhum `setAttribute("style"`, nenhuma URL `http(s)://` externa; a mensagem do erro diz "ajuste `PAINEL_CSP`").
- [ ] **Step 2:** rodar `pytest tests/api/test_security_headers.py -q`. Expected: FAIL (módulo inexistente).
- [ ] **Step 3: implementar** `install_security_headers` como middleware HTTP que acrescenta os quatro cabeçalhos básicos a toda resposta (sem sobrescrever os que a rota já definiu) e, quando o caminho começa por `/painel`, o `Content-Security-Policy` = `default-src 'self'; img-src 'self' blob: data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`. HSTS não entra aqui (é do proxy, só vale com HTTPS).
- [ ] **Step 4:** rodar o arquivo de teste e depois `pytest -q -m "not slow"`. Expected: PASS.
- [ ] **Step 5: commit** `feat(servidor): cabeçalhos de segurança e política de conteúdo do painel`.

### Task 2: Interruptor `DEV_ROUTES`

**Files:**
- Modify: `server/app/settings.py`, `server/app/runtime.py` (campo `dev_routes` e `build_runtime`), `server/app/api/app.py`
- Test: `server/tests/test_settings.py`, `server/tests/api/test_dev_routes_switch.py`

**Interfaces:**
- Produces: `Settings.dev_routes: bool = True`; variável `DEV_ROUTES` aceita `on/off`, `1/0`, `true/false`, `sim/nao` (qualquer caixa); outro valor → `RuntimeError` citando `DEV_ROUTES`. `Runtime.dev_routes: bool = True`. Em `create_app`: `dev = runtime.mode == "dev" and runtime.dev_routes`.

- [ ] **Step 1: testes (RED).** Em `test_settings.py`: padrão `True`; `DEV_ROUTES=off` e `nao` → `False`; `on` → `True`; `talvez` → `RuntimeError` com `DEV_ROUTES`. Em `test_dev_routes_switch.py` (monta o app com o `runtime` das fixtures e `runtime.dev_routes = False`): `/v1/dev/otp`, `/docs`, `/openapi.json` dão 404 e `/health` continua 200; com `True`, `/docs` dá 200 (comportamento atual preservado).
- [ ] **Step 2:** rodar. Expected: FAIL (`dev_routes` não existe).
- [ ] **Step 3: implementar** conforme as Interfaces; `build_runtime` repassa `settings.dev_routes`.
- [ ] **Step 4:** testes do arquivo + `pytest -q -m "not slow"`. Expected: PASS.
- [ ] **Step 5: commit** `feat(servidor): interruptor DEV_ROUTES para não montar as rotas de desenvolvimento num servidor público`.

### Task 3: Endereço do servidor nos apps

**Files:**
- Create: `mobile/packages/corrida_core/lib/src/server_url.dart`; export em `corrida_core.dart`
- Modify: `mobile/apps/passenger/lib/main.dart`, `mobile/apps/rider/lib/main.dart`, `mobile/README.md`
- Test: `mobile/packages/corrida_core/test/server_url_test.dart`

**Interfaces:**
- Produces: `Uri serverUrlFrom(String define, {bool isRelease = false})`. Vazio → `http://localhost:8000` (modo atual com `adb reverse`); senão precisa ser `http://` ou `https://` com host, tolera uma `/` no fim (removida); qualquer outra coisa → `FormatException` começando por `API_URL inválida`. Com `isRelease: true`, `http://` que não seja o `localhost` padrão → `FormatException` dizendo que o Android de release exige HTTPS.

- [ ] **Step 1: testes (RED)** em `server_url_test.dart`: vazio → `http://localhost:8000`; `https://corrida.exemplo.com.br/` → sem a barra final; `http://10.0.2.2:8000` aceito em depuração; `ftp://x`, `corrida.exemplo.com.br` (sem esquema), `https://` (sem host) → `FormatException`; release + `http://servidor.exemplo` → `FormatException` com "HTTPS"; release + vazio → padrão (continua valendo o `adb reverse`).
- [ ] **Step 2:** `cd mobile/packages/corrida_core && dart test test/server_url_test.dart`. Expected: FAIL.
- [ ] **Step 3: implementar** `serverUrlFrom`; nos dois `main.dart`: `const _apiUrl = String.fromEnvironment('API_URL');` e `final _serverUrl = serverUrlFrom(_apiUrl, isRelease: kReleaseMode);` (o passageiro importa `kReleaseMode` de `flutter/foundation.dart`). Confirmar em `realtime.dart` que `https` vira `wss`; se não virar, corrigir com teste. README: seção "Apontar os apps para um servidor" com `flutter build apk --release --dart-define=API_URL=https://…`.
- [ ] **Step 4:** `dart test` em `corrida_core`, `flutter analyze` na raiz, `flutter test` em `passenger` e `rider`. Expected: PASS, análise limpa.
- [ ] **Step 5: commit** `feat(mobile): endereço do servidor por --dart-define=API_URL (HTTPS obrigatório no release)`.

### Task 4: Backup e restauração

**Files:**
- Create: `server/deploy/backup.sh`, `server/deploy/restore.sh` (executáveis)
- Test: `server/tests/deploy/test_backup_e_restauracao.py` (+ `__init__.py`)

**Interfaces:**
- `backup.sh` lê do ambiente `DATABASE_URL` (aceita o prefixo `postgresql+psycopg://`, que ele troca por `postgresql://`), `UPLOAD_DIR`, `BACKUP_DIR` (padrão `/var/backups/app-corrida`), `BACKUP_KEEP_DAYS` (padrão 14, banco) e `BACKUP_KEEP_UPLOAD_DAYS` (padrão 7, fotos). Cria `BACKUP_DIR` com `0700`; grava `db-AAAAMMDD-HHMMSS.dump` (`pg_dump --format=custom`) e `uploads-AAAAMMDD-HHMMSS.tar.gz`, ambos `0600`, escrevendo primeiro em `.part`, conferindo (`pg_restore --list` / `tar -tzf`) e só então renomeando. Depois apaga, **pela data no nome**, os arquivos `db-*.dump` mais velhos que `BACKUP_KEEP_DAYS` e `uploads-*.tar.gz` mais velhos que `BACKUP_KEEP_UPLOAD_DAYS`, mas nunca o mais novo de cada tipo; ignora qualquer outro arquivo. Falta de variável, `pg_dump` falhando ou arquivo ilegível → mensagem em português no stderr e saída ≠ 0, sem deixar `.part`. `UPLOAD_DIR` inexistente ou vazio → não gera tar (aviso) e não falha.
- `restore.sh db ARQUIVO.dump` (usa `DATABASE_URL`) e `restore.sh uploads ARQUIVO.tar.gz` (usa `UPLOAD_DIR`). Recusa, com saída ≠ 0 e explicação, se o destino já tem tabelas (banco) ou arquivos (pasta) — a menos que receba `--substituir`; sem o argumento certo ou com arquivo ilegível também recusa. Restauração do banco: `pg_restore --no-owner --exit-on-error` (com `--clean --if-exists` só em `--substituir`).

- [ ] **Step 1: testes (RED).** Fixture de módulo `cluster` que roda `initdb` numa pasta temporária, sobe com `pg_ctl` (socket unix na pasta, `listen_addresses=''`), cria os bancos `origem` e `destino`, e derruba tudo no fim; pula o módulo se `initdb`/`pg_ctl` não existirem em `/usr/lib/postgresql/*/bin`. Testes: backup grava os dois arquivos com os nomes e permissões (`0600`, pasta `0700`) e o dump restaura os mesmos dados no `destino` (tabela com linhas, incluindo acento); nenhum `.part` sobra; `DATABASE_URL` com `+psycopg` funciona; sem `DATABASE_URL` → ≠ 0; `pg_dump` com banco inexistente → ≠ 0 e nenhum arquivo `db-*` novo; limpeza: arquivos com data velha no nome somem, os de hoje ficam, um arquivo `notas.txt` e um `db-velho.txt` ficam, e o único backup velho que existe não é apagado; restauração recusa banco com tabelas sem `--substituir` e aceita com ele; `restore.sh uploads` devolve os arquivos (conteúdo igual) numa pasta vazia e recusa numa pasta com arquivos.
- [ ] **Step 2:** `pytest tests/deploy -q`. Expected: FAIL (scripts inexistentes).
- [ ] **Step 3: implementar** os dois scripts em bash com `set -euo pipefail`; a data vem de `date` (aceita `BACKUP_NOW=AAAAMMDD-HHMMSS` para teste determinístico da limpeza).
- [ ] **Step 4:** `pytest tests/deploy -q` e `pytest -q -m "not slow"`. Expected: PASS.
- [ ] **Step 5: commit** `feat(deploy): backup do banco e das fotos com conferência, limpeza e restauração`.

### Task 5: Arquivos de instalação

**Files:**
- Create: `server/deploy/app-corrida.service`, `server/deploy/app-corrida-backup.service`, `server/deploy/app-corrida-backup.timer`, `server/deploy/Caddyfile`, `server/deploy/app.env.example`
- Test: `server/tests/deploy/test_arquivos_de_instalacao.py`

**Interfaces:**
- `app-corrida.service`: usuário `corrida`; `WorkingDirectory=/opt/app-corrida/server`; `EnvironmentFile=/etc/app-corrida/app.env`; `ExecStartPre` roda `alembic upgrade head`; `ExecStart` = `.venv/bin/uvicorn --factory app.main:create_default_app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1`; `Restart=on-failure` com `RestartSec=3` e limite de tentativas; `After`/`Wants` do postgresql e redis; endurecimento (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, `ReadWritePaths=/var/lib/app-corrida`, `PYTHONDONTWRITEBYTECODE=1`).
- `app-corrida-backup.service` (`Type=oneshot`, mesmo `EnvironmentFile`, `ExecStart=/opt/app-corrida/server/deploy/backup.sh`, escreve em `/var/backups/app-corrida`) e `.timer` (todo dia às 03:30, `Persistent=true`).
- `Caddyfile`: `{$APP_DOMAIN}` com HTTPS automático; `404` para `/v1/dev/*`, `/docs*`, `/openapi.json`; `Strict-Transport-Security`; `request_body` com limite igual ao dos envios de foto do servidor (conferir a constante em `app/api/routes/rider.py`); `encode zstd gzip`; `reverse_proxy 127.0.0.1:8000`.
- `app.env.example`: `DATABASE_URL`, `REDIS_URL`, `APP_MODE=dev`, `DEV_ROUTES=off`, `WEBHOOK_SECRET=TROQUE-…`, `UPLOAD_DIR=/var/lib/app-corrida/uploads`, `BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `BACKUP_KEEP_UPLOAD_DAYS`, cada uma com comentário em português.

- [ ] **Step 1: testes (RED).** Unidades lidas com `configparser` (`strict=False`): o `ExecStart` do serviço tem `--workers 1`, `--proxy-headers`, `--forwarded-allow-ips 127.0.0.1` e escuta só em `127.0.0.1`; roda como `corrida` e não como root; tem `ExecStartPre` com `alembic upgrade head`; o backup usa o mesmo `EnvironmentFile`; o timer tem `OnCalendar` e `Persistent=true`. `Caddyfile`: contém `reverse_proxy 127.0.0.1:8000`, os três caminhos bloqueados e `{$APP_DOMAIN}`; não tem nome de domínio real. `app.env.example`: `parse_env_file` lê; as chaves são exatamente as listadas; todo valor de segredo começa por `TROQUE`; `APP_MODE=dev`, `DEV_ROUTES=off`; `load_settings(env_path=…, environ={})` passa e dá `dev_routes=False`. O mesmo arquivo não está no `.gitignore` (`git check-ignore` devolve ≠ 0).
- [ ] **Step 2:** `pytest tests/deploy/test_arquivos_de_instalacao.py -q`. Expected: FAIL.
- [ ] **Step 3: escrever os arquivos** conforme as Interfaces. Conferência manual: `systemd-analyze verify` (com caminhos de teste) nas três unidades; sem erro além de "arquivo executável não existe" na máquina de desenvolvimento.
- [ ] **Step 4:** `pytest tests/deploy -q`. Expected: PASS.
- [ ] **Step 5: commit** `feat(deploy): serviço, backup diário, Caddy e modelo de configuração`.
- [x] **Conferência real (feita):** servidor descartável com limite por IP em 5; cinco pedidos com `X-Forwarded-For: A` passam, o sexto dá 429 e o primeiro de `B` passa — igual **com e sem** as flags (o padrão do uvicorn já confia em `127.0.0.1`). O teste do arquivo do serviço garante que as flags continuem explícitas.

### Task 6: Guia de instalação

**Files:**
- Create: `docs/instalacao.md`
- Modify: `server/README.md` (apontar para o guia e para `server/deploy/`)
- Test: `server/tests/deploy/test_guia.py`

O guia é para o Levy, sem jargão; cada passo traz o comando, o que deve aparecer e o que fazer se não aparecer. Estrutura: (0) **o que isto é e o que não é**: teste fechado com adaptadores falsos, nada de dinheiro real, não divulgar o endereço; códigos de login lidos no registro do servidor (`journalctl -u app-corrida -f`); corrida paga em dinheiro (o Pix de mentira só "paga" pela rota de desenvolvimento, que fica fechada — para o teste pode abrir um túnel `ssh -L 8000:127.0.0.1:8000` e ligar `DEV_ROUTES=on` só nesse momento); (1) o que contratar (servidor pequeno Ubuntu 24.04 e domínio; sem preço inventado); (2) apontar o domínio; (3) preparar a máquina (firewall só 22/80/443, usuário `corrida`, PostgreSQL 16 + PostGIS, Redis só local com gravação em disco ligada); (4) baixar o código e instalar; (5) configurar `app.env`; (6) Caddy e o serviço; (7) conferir (`/health`, o painel, criar o administrador); (8) gerar os apps com `API_URL`; (9) backup diário e **ensaio de restauração** (passo a passo, com a pasta de teste); (10) atualizar (backup antes); (11) se algo der errado (como ler o registro, reiniciar, voltar); (12) **antes de abrir para o público**: plano 7, CNPJ e advogado, prazos de guarda dos backups e das fotos (LGPD), trocar `APP_MODE`.

- [ ] **Step 1: teste (RED).** `test_guia.py`: o guia existe; todo caminho `server/deploy/…` citado nele existe; menciona `API_URL`, `DEV_ROUTES`, `journalctl`, `restore.sh` e "ensaio"; contém o aviso de que é teste fechado antes de qualquer comando (a palavra "fechado" aparece nas primeiras 25 linhas); o `server/README.md` aponta para `docs/instalacao.md`.
- [ ] **Step 2:** `pytest tests/deploy/test_guia.py -q`. Expected: FAIL.
- [ ] **Step 3: escrever** o guia e a linha no README.
- [ ] **Step 4:** `pytest tests/deploy -q`. Expected: PASS.
- [ ] **Step 5: commit** `docs: guia de instalação do servidor para o teste fechado`.
- [ ] **Ensaio real (vai para o registro):** seguir o passo (9) à risca na máquina de desenvolvimento: `backup.sh` contra o banco de desenvolvimento, `restore.sh db` num PostgreSQL descartável, `alembic current` no destino = versão atual e contagens de linhas iguais nas tabelas principais.

### Task 7: Fechamento

- [ ] Roteiro (`docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`): linha do 4G e seção "Itens que sobraram do plano 4G" (itens abertos abaixo); riscar o "menor adiado" do 4A sobre cabeçalhos de segurança do painel.
- [ ] Memória do projeto (`project-ride-app-reconcavo.md` e a linha do índice).
- [ ] Autorrevisão da branch inteira contra este plano, suíte completa do servidor, suítes Dart, `flutter analyze`; corrigir Importante/Crítico com teste vermelho antes.
- [ ] Mesclar na `main` sem criar commit extra de mesclagem (fast-forward), empurrar sem `--force`, apagar a branch e o registro de execução.

## Itens que este plano deixa abertos (vão para o roteiro)

- Servidor público de verdade exige o plano 7 (código por WhatsApp, Pix, mapa) e `APP_MODE` ≠ `dev`.
- Cópia dos backups para **fora** da máquina (outro servidor ou armazenamento na nuvem): precisa de uma conta e de escolha do Levy; o guia só explica por que é necessário.
- Prazo de guarda dos backups (14 dias o banco, 7 as fotos) e relação com a limpeza de fotos da LGPD (pergunta para o advogado).
- Aviso de falha do backup (hoje só aparece em `systemctl status`/registro); monitoramento externo do `/health`.
- Redis sem senha (só escuta em `127.0.0.1`).
