# Roteiro dos planos de implementação

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md`

A especificação cobre várias partes independentes. Cada parte vira um plano próprio, que entrega algo que funciona e se testa sozinho. A ordem abaixo respeita as dependências.

| # | Plano | O que entrega | Depende de | Precisa de CNPJ/dinheiro real? |
|---|---|---|---|---|
| 1 | **Núcleo de regras do servidor** (`2026-10-08-01-nucleo-de-regras.md`) | Biblioteca Python pura e testada: preço dinâmico, taxas por faixa, dívida de dinheiro, divisão do pagamento, livro-caixa, máquina de estados da corrida (com fila), escolha de moto, alertas de segurança. | nada | não |
| 2A | **Banco, Redis e fluxo de dinheiro** (`2026-10-08-02a-banco-e-dinheiro.md`) | PostgreSQL com migrações, repositórios, livro-caixa persistente (só acrescenta, protegido no banco), configuração no banco, posições e reservas no Redis, e o serviço transacional de pagamentos (cobrança, aviso de pago, vencimento, cancelamento, estorno). Sem HTTP. | 1 | não |
| 2B | **Corrida de ponta a ponta, em serviços** (`2026-10-09-02b-corrida-de-ponta-a-ponta.md`) | Login por código, cadastro e aprovação do motoqueiro, preço e pedido, procura e ofertas (uma por vez, com fila), andamento da corrida, dinheiro do fim da corrida em dinheiro vivo (QR, bloqueio automático e repasse ao motoqueiro quando o passageiro paga), taxa de entrada, avaliações e varreduras de tempo. Sem HTTP. | 2A | não |
| 2C | **API e tempo real** (`2026-10-18-02c-api-e-tempo-real.md`) | FastAPI sobre os serviços do 2B: rotas, autenticação por token, webhook do provedor (conferindo valor e corrida), WebSocket, publicação dos avisos depois do commit, repetição das varreduras e da checagem diária de documentos, aviso de segurança (parada longa e saída da rota) com o SOS, envio de documentos. | 2B | não |
| 3 | **Simulador** | Motoqueiros e passageiros falsos andando por Santo Antônio de Jesus usando a API do plano 2. | 2 | não |
| 4 | **Painel do dono** | Site para aprovar cadastros, ver corridas, dinheiro, taxas, bloqueios. | 2 | não |
| 5 | **App do motoqueiro (Flutter, Android)** | Cadastro, ficar disponível, oferta, fila, capacete, QR, extrato. | 2 | não |
| 6 | **App do passageiro (Flutter, Android)** | Pedir, pagar, acompanhar, código, SOS, avaliar. | 2 | não |
| 7 | **Integrações reais** | Woovi (Pix e divisão), Google Maps, código por WhatsApp. | 2, CNPJ, advogado | **sim** |
| 8 | **Etapa 2 e publicação** | Cartão pela Asaas; publicação na Google Play; iPhone. | 7 | **sim** |

Ferramentas que ainda precisam ser instaladas no computador do Levy (não existem hoje): PostgreSQL com PostGIS e Redis (plano 2, por pacote do sistema ou Docker), Flutter e Android SDK (planos 5 e 6). O computador tem 7 GB de RAM e pouca memória livre, então os planos 5 e 6 vão pedir atenção ao consumo.

## Itens para o plano 2C

Vindos da revisão final do 2A (ainda abertos):
- Aviso do provedor para cobrança desconhecida levanta `LookupError`: a camada HTTP decide se confirma ou falha.
- Conferir `amount_cents` e `ride_id` do aviso com a cobrança gravada e autenticar o webhook.
- `save_rider_account` regrava as quatro colunas: só chamar depois de ler com `for_update=True`.
- Criar o cliente Redis sempre com `decode_responses=True` (as posições recusam cliente sem isso).
- Limpar do Redis (`pos:geo`, `pos:seen`) as motos que somem sem avisar.
- CHECKs em `pix_charges` e chave estrangeira em `rides.current_charge_id` numa migração nova; transformar o `compare_metadata` do Alembic em teste.

Vindos do plano 2B:
- Publicar os avisos do `EventCollector` somente depois do `commit` e rodar `SweepService.run` a cada poucos segundos (um commit por rodada, erros do relatório vão para o registro).
- Rodar `RiderService.block_expired_documents` uma vez por dia.
- Compensação do cancelamento tardio: hoje só fica registrada no histórico da corrida (`cancelled`), sem movimento de dinheiro. Decidir a política (valor em aberto na spec) e como cobrar.
- Pagamento atrasado de corrida em dinheiro: a cobrança do QR do fim continua valendo; com a Woovi real ela expira, então será preciso recriá-la quando o passageiro abrir a tela "Pagamento pendente".
- Dívida reservada de um QR que nunca é pago continua reservada até alguém pagar ou o Levy resolver no painel (ver plano 4).
- O Pix que cria a cobrança e a chamada ao provedor continuam dentro da transação (idempotência no plano 7).
- Aviso de segurança durante a corrida (usar `app.domain.safety.evaluate`), SOS e "tudo bem?" do passageiro.
- Decidir se a corrida com bloqueio por falta de pagamento conta para as 10 corridas de teste (hoje conta).
- Cada unidade de trabalho (requisição ou rodada de varredura) usa **um** `EventCollector`, compartilhado por todos os serviços dela; nunca um coletor global entre requisições.
- Os adaptadores reais do provedor de pagamento traduzem erros de rede para `PaymentProviderError`.
- Cadência da varredura (hoje cada rodada tenta de novo as procuras sem oferta) e um `commit` por corrida, para segurar as travas por menos tempo.
- Repetir a transação quando o banco derrubar uma por impasse (resíduo da ordem de travas ao entrar na fila).
- Quando o provedor de Pix estiver fora, oferecer só dinheiro na hora do pedido (spec, seção 12).
- Menores adiados do 2B: motoqueiro na 10ª corrida sem entrada continua `online`; downgrade da migração 0002 falha com cobrança de entrada; códigos de login antigos continuam valendo; `accept_offer` não reconfere bloqueio; `register_rider` concorrente vaza `IntegrityError`; faltam índices em `rides(state, rider_id, passenger_id)` e `ride_offers(ride_id)`; taxa da corrida da fila fixada no aceite; índice único parcial de uma corrida aberta por passageiro.

## Decisões já tomadas

- Corrida em dinheiro sem pagamento: bloqueio automático após 5 minutos, sem taxa para o motoqueiro, repasse quando o passageiro pagar (feito no 2B). Em aberto, com o Levy: se o passageiro nunca pagar, quem arca com o prejuízo (por enquanto, o motoqueiro).

## Perguntas para o advogado (conversa na semana de 12/10/2026)

1. Em Santo Antônio de Jesus não há lei de mototáxi nem permissão sendo emitida (informação da prefeitura). O que isso significa para quem presta o serviço e para um aplicativo que o intermedeia: é permitido, tolerado ou infração? Quem responde por multa e apreensão?
2. A Lei federal 12.009/2009 exige autorização municipal. Um app pode começar antes de o município regulamentar? Que risco a empresa corre (multa, Procon, responsabilidade solidária)?
3. Que tipo de empresa abrir (MEI não serve; ME/LTDA), e o CNAE correto para intermediação de transporte por aplicativo.
4. Vínculo de emprego com o motoqueiro (STF Tema 1291 ainda indefinido): como estruturar termos de uso e o cadastro para reduzir o risco.
5. Recebimento de dinheiro de terceiros e saldo recarregável (regras do Banco Central), e o que precisa para a divisão automática de Pix com a Woovi.
6. LGPD: base legal e aviso para coletar CPF, CNH, foto e localização.
7. Seguro: vale contratar seguro de acidentes para passageiro e motoqueiro?
8. Bloquear o passageiro que não pagou e repassar o valor ao motoqueiro quando ele pagar: há algum risco de cobrança indevida, de LGPD ou do Código de Defesa do Consumidor? O que precisa constar nos termos de uso?
