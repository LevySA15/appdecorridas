# App de corrida do Recôncavo Baiano

Aplicativo de moto (e depois carro) barato para o Recôncavo: o passageiro pede, o motoqueiro aceita, o Pix e o dinheiro
são tratados pelo servidor e o dono acompanha tudo por um painel. Este repositório tem o servidor, o painel e os dois
aplicativos de celular.

**Situação (06/11/2026):** tudo o que não depende de CNPJ, advogado ou conta de terceiros está feito e testado em
computador. Pix, mapa do Google e código de login por WhatsApp ainda são **de mentira** (plano 7). Os apps **nunca foram
vistos num celular de verdade pelo desenvolvimento**: falta o teste do Levy. O servidor está pronto para um **teste fechado**
numa máquina na internet, não para o público.

## Pastas

| Pasta | O que tem |
|---|---|
| `server/` | Servidor (Python, FastAPI, PostgreSQL, Redis): regras, dinheiro, corrida, segurança, API e tempo real. Leia `server/README.md`. |
| `server/painel/` | Painel do dono (um site só, sem compilação), servido em `/painel`. |
| `server/deploy/` | Arquivos para instalar o servidor: serviço, HTTPS (Caddy), backup, restauração e modelo de configuração. |
| `server/simulator/` | Motoqueiros e passageiros de mentira que fazem corridas inteiras pela API. |
| `mobile/` | Apps Flutter: `apps/passenger`, `apps/rider` e os pacotes `corrida_core` (API, sessão, tempo real) e `corrida_ui` (telas e peças comuns). Leia `mobile/README.md`. |
| `docs/` | Contrato da API (`api-v1.md`), guia de instalação (`instalacao.md`), simulador, pesquisa de taxas e o roteiro dos planos. |

## Por onde começar

- **Instalar o servidor num computador na internet (teste fechado):** `docs/instalacao.md`.
- **Rodar tudo no seu computador:** `server/README.md` (servidor e painel) e `mobile/README.md` (apps no celular por USB).
- **O que já foi feito e o que falta:** `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md` (cada plano tem o seu arquivo
  na mesma pasta, e cada um termina com a lista do que ficou de fora).
- **Contrato entre servidor e apps:** `docs/api-v1.md`.

## Testes

    cd server && .venv/bin/pytest -q                       # ~11 min, com as rodadas longas do simulador; -m "not slow" pula as longas
    cd mobile && dart pub get && tool/contrato.sh         # os apps falando com um servidor de verdade e descartável
    (cd mobile/packages/corrida_core && dart test)        # e `flutter test` em cada app e em packages/corrida_ui

## O que depende de gente de fora (plano 7 em diante)

CNPJ e advogado liberam o Pix de verdade (Woovi), o mapa (Google Maps) e o código de login por WhatsApp. Antes de abrir para o
público também faltam: prazos de guarda de dados pessoais (LGPD), termos de uso, contato de suporte e a publicação na Google Play.
