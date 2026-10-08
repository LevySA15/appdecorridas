# Servidor do app de corrida (núcleo de regras)

Biblioteca Python pura com as regras de negócio. Dinheiro sempre em centavos inteiros.

## Rodar os testes

    python3 -m venv .venv
    .venv/bin/pip install -q "pytest>=8"
    .venv/bin/pytest -q

## Mapa do código

- `app/domain/config.py` — todos os números ajustáveis.
- `app/domain/geo.py` — distâncias.
- `app/domain/pricing.py` — preço dinâmico.
- `app/domain/fees.py` — taxa por faixa, entrada de R$ 50, dívida de dinheiro.
- `app/domain/payments.py` — divisão do pagamento, eventos repetidos, interface do provedor.
- `app/domain/ledger.py` — livro-caixa que só acrescenta.
- `app/domain/rides.py` — etapas da corrida (com fila e cancelamento).
- `app/domain/dispatch.py` — escolha da moto e reserva.
- `app/domain/safety.py` — alertas de segurança.
- `app/adapters/` — versões falsas de pagamento e mapas para teste.
