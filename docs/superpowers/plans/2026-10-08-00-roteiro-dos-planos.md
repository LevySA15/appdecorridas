# Roteiro dos planos de implementação

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md`

A especificação cobre várias partes independentes. Cada parte vira um plano próprio, que entrega algo que funciona e se testa sozinho. A ordem abaixo respeita as dependências.

| # | Plano | O que entrega | Depende de | Precisa de CNPJ/dinheiro real? |
|---|---|---|---|---|
| 1 | **Núcleo de regras do servidor** (`2026-10-08-01-nucleo-de-regras.md`) | Biblioteca Python pura e testada: preço dinâmico, taxas por faixa, dívida de dinheiro, divisão do pagamento, livro-caixa, máquina de estados da corrida (com fila), escolha de moto, alertas de segurança. | nada | não |
| 2A | **Banco, Redis e fluxo de dinheiro** (`2026-10-08-02a-banco-e-dinheiro.md`) | PostgreSQL com migrações, repositórios, livro-caixa persistente (só acrescenta, protegido no banco), configuração no banco, posições e reservas no Redis, e o serviço transacional de pagamentos (cobrança, aviso de pago, vencimento, cancelamento, estorno). Sem HTTP. | 1 | não |
| 2B | **Corrida de ponta a ponta, em serviços** (`2026-10-09-02b-corrida-de-ponta-a-ponta.md`) | Login por código, cadastro e aprovação do motoqueiro, preço e pedido, procura e ofertas (uma por vez, com fila), andamento da corrida, dinheiro do fim da corrida em dinheiro vivo (QR, bloqueio automático e repasse ao motoqueiro quando o passageiro paga), taxa de entrada, avaliações e varreduras de tempo. Sem HTTP. | 2A | não |
| 2C | **API e tempo real** (`2026-10-18-02c-api-e-tempo-real.md`) | FastAPI sobre os serviços do 2B: login, cadastro com fotos, preço, pedido, ofertas, corrida, cobrança e QR do Pix, aviso assinado do provedor, WebSocket, varredura de tempo e checagem diária rodando sozinhas, alertas de segurança com SOS, mínimo do painel (aprovar cadastros e ver alertas) e o contrato em `docs/api-v1.md`. | 2B | não |
| 3 | **Simulador** | Motoqueiros e passageiros falsos andando por Santo Antônio de Jesus usando a API do plano 2. | 2 | não |
| 4 | **Painel do dono** | Site para aprovar cadastros, ver corridas, dinheiro, taxas, bloqueios. | 2 | não |
| 5 | **App do motoqueiro (Flutter, Android)** | Cadastro, ficar disponível, oferta, fila, capacete, QR, extrato. | 2 | não |
| 6 | **App do passageiro (Flutter, Android)** | Pedir, pagar, acompanhar, código, SOS, avaliar. | 2 | não |
| 7 | **Integrações reais** | Woovi (Pix e divisão), Google Maps, código por WhatsApp. | 2, CNPJ, advogado | **sim** |
| 8 | **Etapa 2 e publicação** | Cartão pela Asaas; publicação na Google Play; iPhone. | 7 | **sim** |

Ferramentas que ainda precisam ser instaladas no computador do Levy (não existem hoje): PostgreSQL com PostGIS e Redis (plano 2, por pacote do sistema ou Docker), Flutter e Android SDK (planos 5 e 6). O computador tem 7 GB de RAM e pouca memória livre, então os planos 5 e 6 vão pedir atenção ao consumo.

## Itens que sobraram do plano 2C

Do Levy decidir (o servidor segue o padrão atual):
- Compensação do cancelamento tardio: hoje só fica registrada no histórico da corrida, sem movimento de dinheiro, e a API não a promete ao app. Decidir a política (valor em aberto na spec) e como cobrar.
- Se a corrida com bloqueio por falta de pagamento conta para as 10 corridas de teste (hoje conta).

Plano 3 (simulador): usa `/v1/dev/otp` e `/v1/dev/pix/{id}/pay`; motoqueiros falsos mandam posição a cada 4 s.

Plano 4 (painel): listas de corridas, dinheiro e taxas, devedores, bloqueio de passageiro, parâmetros (`app_config`); a dívida reservada de um QR que nunca é pago continua reservada até alguém resolver; registro das ações do administrador; CORS para o site.

Planos 5 e 6 (apps): histórico de corridas e extrato do dia (rotas novas), notificação push (FCM) para oferta e avisos com o app fechado, reenvio de avisos perdidos.

Plano 7 (integrações reais): adaptadores da Woovi, do Google Maps e do WhatsApp (também para o aviso ao contato de emergência); traduzir erros de rede para `PaymentProviderError`; idempotência da chamada ao provedor (hoje dentro da transação); recriar o QR do pagamento atrasado quando ele expira (a Woovi real expira); inverter o padrão de `APP_MODE` para exigir os adaptadores reais.

Mais de um processo: exige um canal entre eles (Redis pub/sub) para o hub do WebSocket e uma trava para o agendador.

Menores do 2B que seguem abertos: o `downgrade` da migração 0002 falha se existe cobrança de entrada; a taxa da corrida da fila é fixada no aceite.

## Decisões já tomadas

- Corrida em dinheiro sem pagamento: bloqueio automático após 5 minutos, sem taxa para o motoqueiro, repasse quando o passageiro pagar (feito no 2B). Em aberto, com o Levy: se o passageiro nunca pagar, quem arca com o prejuízo (por enquanto, o motoqueiro).

- SOS: o servidor aceita durante toda a corrida (a caminho, na chegada e andando); mostrar o botão sempre ou só dentro do aviso automático é decisão do Levy nas telas do app (spec, seção 9, itens 4 e 5).

## Perguntas para o advogado (conversa na semana de 12/10/2026)

1. Em Santo Antônio de Jesus não há lei de mototáxi nem permissão sendo emitida (informação da prefeitura). O que isso significa para quem presta o serviço e para um aplicativo que o intermedeia: é permitido, tolerado ou infração? Quem responde por multa e apreensão?
2. A Lei federal 12.009/2009 exige autorização municipal. Um app pode começar antes de o município regulamentar? Que risco a empresa corre (multa, Procon, responsabilidade solidária)?
3. Que tipo de empresa abrir (MEI não serve; ME/LTDA), e o CNAE correto para intermediação de transporte por aplicativo.
4. Vínculo de emprego com o motoqueiro (STF Tema 1291 ainda indefinido): como estruturar termos de uso e o cadastro para reduzir o risco.
5. Recebimento de dinheiro de terceiros e saldo recarregável (regras do Banco Central), e o que precisa para a divisão automática de Pix com a Woovi.
6. LGPD: base legal e aviso para coletar CPF, CNH, foto e localização.
7. Seguro: vale contratar seguro de acidentes para passageiro e motoqueiro?
8. Bloquear o passageiro que não pagou e repassar o valor ao motoqueiro quando ele pagar: há algum risco de cobrança indevida, de LGPD ou do Código de Defesa do Consumidor? O que precisa constar nos termos de uso?
