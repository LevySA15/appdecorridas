# Servidor do app de corrida

Núcleo de regras (plano 1) mais banco, Redis e fluxo de dinheiro (plano 2A). Dinheiro sempre em centavos inteiros.

## Pré-requisitos

- Python 3.12, PostgreSQL 16 com PostGIS e Redis rodando (`systemctl is-active postgresql redis-server`).
- `server/.env` com `DATABASE_URL` e `REDIS_URL` (o arquivo é ignorado pelo git; nunca o envie).

## Instalar e rodar os testes

    python3 -m venv .venv
    .venv/bin/pip install -q "pytest>=8" "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" "redis>=5.0"
    .venv/bin/pytest -q

Os testes de banco criam um esquema temporário (`t_...`) no banco de desenvolvimento, aplicam as
migrações nele e o apagam no fim. Se um teste for interrompido à força, sobra um esquema `t_...`;
apague com `DROP SCHEMA "t_..." CASCADE`. O Redis dos testes é o banco número 15.

## Migrações

    .venv/bin/alembic upgrade head      # aplica no banco de desenvolvimento
    .venv/bin/alembic current           # mostra a versão atual

## Mapa do código

- `app/domain/` — regras de negócio puras (preço, taxa, dívida, divisão, livro-caixa em memória, corrida, escolha da moto, segurança).
- `app/db/` — modelos, repositórios, livro-caixa persistente (`pg_ledger.py`) e configuração no banco (`config_store.py`).
- `app/infra/redis_store.py` — posições das motos e reservas com validade.
- `app/services/payments.py` — serviço transacional de pagamentos Pix (cobrança, aviso de pago, vencimento, cancelamento, estorno).
- `app/adapters/` — provedores falsos de pagamento e mapas, para testes e simulador.
- `migrations/` — esquema do banco (Alembic).

## Regras de convivência

- Serviços e repositórios não fazem `commit`: quem chama controla a transação.
- Ordem de travas no banco: corrida, motoqueiro, cobrança.
