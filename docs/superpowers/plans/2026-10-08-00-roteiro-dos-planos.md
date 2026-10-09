# Roteiro dos planos de implementação

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md`

A especificação cobre várias partes independentes. Cada parte vira um plano próprio, que entrega algo que funciona e se testa sozinho. A ordem abaixo respeita as dependências.

| # | Plano | O que entrega | Depende de | Precisa de CNPJ/dinheiro real? |
|---|---|---|---|---|
| 1 | **Núcleo de regras do servidor** (`2026-10-08-01-nucleo-de-regras.md`) | Biblioteca Python pura e testada: preço dinâmico, taxas por faixa, dívida de dinheiro, divisão do pagamento, livro-caixa, máquina de estados da corrida (com fila), escolha de moto, alertas de segurança. | nada | não |
| 2A | **Banco, Redis e fluxo de dinheiro** (`2026-10-08-02a-banco-e-dinheiro.md`) | PostgreSQL com migrações, repositórios, livro-caixa persistente (só acrescenta, protegido no banco), configuração no banco, posições e reservas no Redis, e o serviço transacional de pagamentos (cobrança, aviso de pago, vencimento, cancelamento, estorno). Sem HTTP. | 1 | não |
| 2B | **Corrida, API e tempo real** (plano escrito depois que o 2A estiver pronto) | FastAPI: login (WhatsApp falso), cadastro e aprovação do motoqueiro, pedido de corrida, procura e ofertas, corrida de ponta a ponta, WebSocket. Escrito depois do 2A porque usa o código real do banco. | 2A | não |
| 3 | **Simulador** | Motoqueiros e passageiros falsos andando por Santo Antônio de Jesus usando a API do plano 2. | 2 | não |
| 4 | **Painel do dono** | Site para aprovar cadastros, ver corridas, dinheiro, taxas, bloqueios. | 2 | não |
| 5 | **App do motoqueiro (Flutter, Android)** | Cadastro, ficar disponível, oferta, fila, capacete, QR, extrato. | 2 | não |
| 6 | **App do passageiro (Flutter, Android)** | Pedir, pagar, acompanhar, código, SOS, avaliar. | 2 | não |
| 7 | **Integrações reais** | Woovi (Pix e divisão), Google Maps, código por WhatsApp. | 2, CNPJ, advogado | **sim** |
| 8 | **Etapa 2 e publicação** | Cartão pela Asaas; publicação na Google Play; iPhone. | 7 | **sim** |

Ferramentas que ainda precisam ser instaladas no computador do Levy (não existem hoje): PostgreSQL com PostGIS e Redis (plano 2, por pacote do sistema ou Docker), Flutter e Android SDK (planos 5 e 6). O computador tem 7 GB de RAM e pouca memória livre, então os planos 5 e 6 vão pedir atenção ao consumo.

## Itens obrigatórios para o plano 2B (vindos da revisão final do 2A)

- Aviso do provedor para cobrança desconhecida: hoje levanta `LookupError`; a camada HTTP decide se confirma ou falha (o provedor tenta de novo).
- Conferir `amount_cents` e `ride_id` do aviso com a cobrança gravada e autenticar o webhook.
- `save_rider_account` regrava as quatro colunas: só chamar depois de ler com `for_update=True` (inclusive ao registrar corrida concluída).
- Pagar ou perdoar dívida respeitando a dívida reservada (`debt_reserved_cents`); travar corridas em ordem fixa quando uma operação envolver duas (promoção da fila).
- Criar o cliente Redis sempre com `decode_responses=True` (as posições recusam cliente sem isso).
- Limpar do Redis (`pos:geo`, `pos:seen`) as motos que somem sem avisar.
- Acrescentar CHECKs em `pix_charges` e chave estrangeira em `rides.current_charge_id` numa migração nova; transformar o `compare_metadata` do Alembic em teste.
- **Corrida em dinheiro sem pagamento (decisão do Levy, 09/10/2026):** não existe botão de "passageiro não pagou". Passados `cash_pay_wait_s` (5 min, ajustável) do fim da corrida, o servidor bloqueia o passageiro sozinho (`unpaid_cents`) e libera o motoqueiro; o motoqueiro **não deve taxa** daquela corrida. Quando o passageiro paga, gera-se uma cobrança Pix com a divisão normal (taxa para a empresa, resto para o motoqueiro daquela corrida) e o bloqueio cai. No código: trocar `report_non_payment` (hoje acionado pelo motoqueiro) por um bloqueio automático por tempo, criar `RideConfig.cash_pay_wait_s = 300` e um caso de uso no `PaymentService` para a cobrança da dívida (ligada à corrida antiga, que já está concluída, então `on_pix_paid` não serve). Hoje `register_completed_ride` soma a taxa à dívida do motoqueiro sempre que `fee_collected_by_split` não é verdadeiro: no calote não somar. Decidir se essa corrida conta para as 10 do período de teste.
- **Pendente do Levy:** se o passageiro nunca pagar, o motoqueiro perde o valor ou a empresa cobre?

## Perguntas para o advogado (conversa na semana de 12/10/2026)

1. Em Santo Antônio de Jesus não há lei de mototáxi nem permissão sendo emitida (informação da prefeitura). O que isso significa para quem presta o serviço e para um aplicativo que o intermedeia: é permitido, tolerado ou infração? Quem responde por multa e apreensão?
2. A Lei federal 12.009/2009 exige autorização municipal. Um app pode começar antes de o município regulamentar? Que risco a empresa corre (multa, Procon, responsabilidade solidária)?
3. Que tipo de empresa abrir (MEI não serve; ME/LTDA), e o CNAE correto para intermediação de transporte por aplicativo.
4. Vínculo de emprego com o motoqueiro (STF Tema 1291 ainda indefinido): como estruturar termos de uso e o cadastro para reduzir o risco.
5. Recebimento de dinheiro de terceiros e saldo recarregável (regras do Banco Central), e o que precisa para a divisão automática de Pix com a Woovi.
6. LGPD: base legal e aviso para coletar CPF, CNH, foto e localização.
7. Seguro: vale contratar seguro de acidentes para passageiro e motoqueiro?
8. Bloquear o passageiro que não pagou e repassar o valor ao motoqueiro quando ele pagar: há algum risco de cobrança indevida, de LGPD ou do Código de Defesa do Consumidor? O que precisa constar nos termos de uso?
