# Servidor do app de corrida

Núcleo de regras (plano 1), banco, Redis e fluxo de dinheiro (plano 2A), serviços da corrida (plano 2B), API com
tempo real (plano 2C) e simulador (plano 3). Dinheiro sempre em centavos inteiros. O contrato da API está em `docs/api-v1.md`.

## Pré-requisitos

- Python 3.12, PostgreSQL 16 com PostGIS e Redis rodando (`systemctl is-active postgresql redis-server`).
- `server/.env` com `DATABASE_URL`, `REDIS_URL`, `APP_MODE=dev` e `WEBHOOK_SECRET` (o arquivo é ignorado pelo git; nunca o envie).
  Opcional: `UPLOAD_DIR` (onde ficam as fotos dos documentos; por padrão `server/var/uploads`, também fora do git).

## Instalar e rodar os testes

    python3 -m venv .venv
    .venv/bin/pip install -q "pytest>=8" "httpx2>=2.0" "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" \
        "redis>=5.0" tzdata "fastapi>=0.115" "uvicorn[standard]>=0.30"
    .venv/bin/pytest -q

Os testes do simulador (`tests/sim`) sobem o servidor de verdade e levam cerca de 1 minuto e meio; para o dia a dia, pule as
rodadas longas com `.venv/bin/pytest -q -m "not slow"`.

Os testes de banco criam um esquema temporário (`t_...`) no banco de desenvolvimento, aplicam as
migrações nele e o apagam no fim. Se um teste for interrompido à força, sobra um esquema `t_...`;
apague com `DROP SCHEMA "t_..." CASCADE`. O Redis dos testes é o banco número 15.

## Migrações

    .venv/bin/alembic upgrade head      # aplica no banco de desenvolvimento
    .venv/bin/alembic current           # mostra a versão atual

## Rodar o servidor (desenvolvimento)

    .venv/bin/python -m app.cli create-admin --phone "75 99999-0000" --name "Levy"    # uma vez
    .venv/bin/uvicorn --factory app.main:create_default_app --port 8000                # um processo só

- Sem WhatsApp e sem Pix de verdade ainda (plano 7): o código de login aparece no registro do servidor e em
  `GET /v1/dev/otp?phone=...`; um Pix é "pago" com `POST /v1/dev/pix/{charge_id}/pay`.
- `http://127.0.0.1:8000/docs` mostra todas as rotas; `http://127.0.0.1:8000/health` confere banco e Redis.
- O agendador roda dentro do servidor: varredura de tempo a cada 3 s, checagem diária de documentos vencidos e limpeza
  das posições que sumiram (a cada minuto).

## Simulador

Motoqueiros e passageiros de mentira que fazem corridas inteiras pela API (guia completo em `docs/simulador.md`):

    .venv/bin/python -m simulator demo --fast        # servidor descartável + 10 minutos de gente de mentira + relatório

## Mapa do código

- `app/domain/` — regras de negócio puras (preço, taxa, dívida, divisão, livro-caixa em memória, corrida, escolha da moto, segurança).
- `app/db/` — modelos, repositórios, consultas (`queries.py`), livro-caixa persistente (`pg_ledger.py`) e configuração no banco (`config_store.py`).
- `app/infra/` — Redis (posições, reservas, fator de preço, limite de tentativas, saúde do Pix, marcas de tarefas), rastro de segurança e fotos dos documentos.
- `app/services/` — `auth`, `riders`, `quotes`, `ride_requests`, `dispatch`, `trips`, `payments`, `sweeps`, `safety`; `events.py` anota os avisos.
- `app/runtime.py` — `Runtime.run`: a unidade de trabalho de cada pedido (sessão, serviços com um `EventCollector` só, commit, depois publicação dos avisos; repete por impasse no banco).
- `app/realtime/hub.py` — conexões WebSocket e entrega dos avisos de qualquer thread.
- `app/api/` — `app.py` (montagem), `errors.py` (erros → respostas), `deps.py` (quem chama), `views.py` (como a corrida aparece), `webhook.py` (aviso assinado do provedor), `routes/` (uma pasta de rotas por assunto).
- `scripts/smoke_server.py` — sobe o servidor de verdade num esquema temporário e confere login, WebSocket e agendador (`PYTHONPATH=. .venv/bin/python scripts/smoke_server.py`; usa o Redis banco 14 e o apaga no fim).
- `simulator/` — o simulador (plano 3): `sandbox.py` (servidor descartável), `rider.py`, `passenger.py` e `admin.py` (os atores), `runner.py` (a rodada), `report.py` (o relatório); só fala com o servidor pela API, exceto o `sandbox.py`.
- `app/scheduler.py` — varredura, tarefa diária e limpeza; `app/main.py` — ponto de entrada do uvicorn; `app/cli.py` — criar o administrador.
- `app/adapters/` — provedores falsos (pagamento, mapas, código de login, aviso ao contato), os únicos que existem até o plano 7.
- `migrations/` — esquema do banco (Alembic).

## Regras de convivência

- Serviços e repositórios não fazem `commit`: quem chama controla a transação (`Runtime.run` nas rotas; `sweep_once` nas varreduras).
- Os serviços recebem `now` como parâmetro e anotam avisos num `EventCollector`; ele só é publicado depois do commit. Cada unidade de trabalho tem o seu coletor: nunca compartilhe um entre pedidos.
- Login: `AuthService.verify_code` não levanta erro para código errado; devolve `ok=False` para a tentativa ser gravada (a rota responde 401 depois do commit).
- Ordem de travas: corrida, corrida da fila, motoqueiro, cobrança, passageiro.
- `save_rider_account` regrava as quatro colunas: só chame depois de ler com `for_update=True`.
- O cliente Redis é sempre criado com `decode_responses=True` (as posições recusam cliente sem isso).
