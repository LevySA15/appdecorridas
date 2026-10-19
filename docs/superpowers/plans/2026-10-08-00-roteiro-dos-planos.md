# Roteiro dos planos de implementação

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md`

A especificação cobre várias partes independentes. Cada parte vira um plano próprio, que entrega algo que funciona e se testa sozinho. A ordem abaixo respeita as dependências.

| # | Plano | O que entrega | Depende de | Precisa de CNPJ/dinheiro real? |
|---|---|---|---|---|
| 1 | **Núcleo de regras do servidor** (`2026-10-08-01-nucleo-de-regras.md`) | Biblioteca Python pura e testada: preço dinâmico, taxas por faixa, dívida de dinheiro, divisão do pagamento, livro-caixa, máquina de estados da corrida (com fila), escolha de moto, alertas de segurança. | nada | não |
| 2A | **Banco, Redis e fluxo de dinheiro** (`2026-10-08-02a-banco-e-dinheiro.md`) | PostgreSQL com migrações, repositórios, livro-caixa persistente (só acrescenta, protegido no banco), configuração no banco, posições e reservas no Redis, e o serviço transacional de pagamentos (cobrança, aviso de pago, vencimento, cancelamento, estorno). Sem HTTP. | 1 | não |
| 2B | **Corrida de ponta a ponta, em serviços** (`2026-10-09-02b-corrida-de-ponta-a-ponta.md`) | Login por código, cadastro e aprovação do motoqueiro, preço e pedido, procura e ofertas (uma por vez, com fila), andamento da corrida, dinheiro do fim da corrida em dinheiro vivo (QR, bloqueio automático e repasse ao motoqueiro quando o passageiro paga), taxa de entrada, avaliações e varreduras de tempo. Sem HTTP. | 2A | não |
| 2C | **API e tempo real** (`2026-10-18-02c-api-e-tempo-real.md`) | FastAPI sobre os serviços do 2B: login, cadastro com fotos, preço, pedido, ofertas, corrida, cobrança e QR do Pix, aviso assinado do provedor, WebSocket, varredura de tempo e checagem diária rodando sozinhas, alertas de segurança com SOS, mínimo do painel (aprovar cadastros e ver alertas) e o contrato em `docs/api-v1.md`. | 2B | não |
| 3 | **Simulador** (`2026-10-18-03-simulador.md`) | Pacote `simulator/`: motoqueiros e passageiros de mentira andando por Santo Antônio de Jesus e fazendo corridas inteiras só pela API (HTTP + WebSocket), com servidor descartável (`demo`), perfis de comportamento (`calmo`, `normal`, `bagunca`), relatório em português com veredito e a rota de conferência `GET /v1/dev/audit`. Guia em `docs/simulador.md`. | 2C | não |
| 4 | **Painel do dono** | Site para aprovar cadastros, ver corridas, dinheiro, taxas, bloqueios. | 2 | não |
| 5 | **App do motoqueiro (Flutter, Android)** | Cadastro, ficar disponível, oferta, fila, capacete, QR, extrato. | 2 | não |
| 6 | **App do passageiro (Flutter, Android)** | Pedir, pagar, acompanhar, código, SOS, avaliar. | 2 | não |
| 7 | **Integrações reais** | Woovi (Pix e divisão), Google Maps, código por WhatsApp. | 2, CNPJ, advogado | **sim** |
| 8 | **Etapa 2 e publicação** | Cartão pela Asaas; publicação na Google Play; iPhone. | 7 | **sim** |

Ferramentas que ainda precisam ser instaladas no computador do Levy (não existem hoje): PostgreSQL com PostGIS e Redis (plano 2, por pacote do sistema ou Docker), Flutter e Android SDK (planos 5 e 6). O computador tem 7 GB de RAM e pouca memória livre, então os planos 5 e 6 vão pedir atenção ao consumo.

## Itens que sobraram do plano 2C

Do Levy decidir: respondido em 18/10/2026, ver "Decisões já tomadas" (cancelamento tardio, corrida bloqueada por falta de pagamento, calote). Falta transformar a decisão em código (hoje a compensação do cancelamento tardio só fica registrada no histórico da corrida, sem movimento de dinheiro, e a API não a promete ao app).

Plano 3 (simulador): feito; ver "Itens que sobraram do plano 3" abaixo.

Plano 4 (painel): o simulador (`python -m simulator run`) deixa o servidor de desenvolvimento com movimento para o painel mostrar; listas de corridas, dinheiro e taxas, devedores, bloqueio de passageiro, parâmetros (`app_config`); a dívida reservada de um QR que nunca é pago continua reservada até alguém resolver; registro das ações do administrador; CORS para o site.

Planos 5 e 6 (apps): histórico de corridas e extrato do dia (rotas novas), notificação push (FCM) para oferta e avisos com o app fechado, reenvio de avisos perdidos.

Plano 7 (integrações reais): adaptadores da Woovi, do Google Maps e do WhatsApp (também para o aviso ao contato de emergência); traduzir erros de rede para `PaymentProviderError`; idempotência da chamada ao provedor (hoje dentro da transação); recriar o QR do pagamento atrasado quando ele expira (a Woovi real expira); inverter o padrão de `APP_MODE` para exigir os adaptadores reais.

Mais de um processo: exige um canal entre eles (Redis pub/sub) para o hub do WebSocket e uma trava para o agendador.

Da revisão final do 2C (ainda abertos): alerta de "muito tempo sem sinal" (spec, seção 12) quando a moto para de mandar posição no meio da corrida, que precisa de um tipo de alerta novo, uma varredura no agendador e do Levy definir o tempo e quem é avisado; efeitos externos (devolução no provedor, mensagem do SOS, marca do Redis) rodam antes do commit e se repetem se o banco derrubar a transação por impasse (plano 7: idempotência); menores: fotos órfãs sem limpeza nem cota; WebSocket aberto continua recebendo avisos depois de logout ou bloqueio; SOS em dois toques simultâneos pode criar dois alertas; `ValueError` genérico devolve texto interno ao app; `/rider/state` pode mostrar oferta já vencida por até 3 s; cobrança de entrada pendente não reaparece no estado do motoqueiro; `answer_ok` trava antes de conferir o dono. (O pool do banco, 10+10, foi medido no plano 3 com 60 motoqueiros e 200 passageiros e não formou fila: fica como está.)

Menores do 2B que seguem abertos: o `downgrade` da migração 0002 falha se existe cobrança de entrada; a taxa da corrida da fila é fixada no aceite.

## Itens que sobraram do plano 3

Do Levy decidir: nada novo.

Para os planos seguintes:
- Plano 4 (painel): o mapa ao vivo com as motos é do painel; o simulador só grava o relatório da rodada.
- Aviso de "muito tempo sem sinal" (item aberto do 2C): quando existir, ensinar o motoqueiro de mentira a parar de mandar posição no meio da corrida.
- O primeiro minuto de uma rodada grande (todo mundo entra de uma vez) tem chamadas acima de 3 s. Se os apps abrirem em rajada na vida real, olhar a fila de conexões e a consulta de estado.
- Plano 7: o simulador usa as rotas `/v1/dev/*`, que não existem com os adaptadores reais. Contra o ambiente de testes da Woovi ele precisaria de outro jeito de "pagar" o Pix; até lá fica no modo `demo`, com adaptadores falsos.
- Fora do alcance do simulador: mais de um processo do servidor e queda do banco ou do Redis no meio da rodada.

Da revisão final do plano 3 (adiados, todos pequenos): Ctrl+C no `run` diz "servidor descartável apagado" sem haver um; falta teste de Ctrl+C dentro do `Sandbox`; os passos de limpeza do `Sandbox` não são isolados e o Redis só é esvaziado no fim (uma rodada morta à força deixa sobras no banco 14); corrida que some do estado durante uma reconexão de propósito pode reprovar uma rodada `bagunca` (cerca de 0,2% das corridas); o relatório só confere as corridas abertas que o próprio simulador pediu; corrida sobrada de um `run` interrompido é ignorada; a espera de 3 s pelo aviso final é curta para picos de 3 a 4 s de atraso; o script de fumaça lê o registro do servidor antes de ele desligar; falta teste do login com token vencido; `--riders`/`--passengers` de 10000 para cima geram telefone inválido.

## Decisões já tomadas

- Corrida em dinheiro sem pagamento: bloqueio automático após 5 minutos, sem taxa para o motoqueiro, repasse quando o passageiro pagar (feito no 2B). Se o passageiro nunca pagar, quem arca com o prejuízo (por enquanto, o motoqueiro): o Levy considera o caso raro e não pede decisão agora (ver o item "Calote" abaixo).

- Cancelamento pelo passageiro (Levy, 18/10/2026): janela grátis de **5 minutos**, contada a partir do aviso da taxa; depois dela, taxa de **R$ 3 a R$ 5 conforme a distância que a moto já andou** (Levy, 19/10/2026); o passageiro pode **contestar depois** (recurso). Cobrança (Levy, 19/10/2026): a taxa **sai sozinha do saldo do passageiro no app**; se ele não tem saldo, Pix já pago → a taxa é retida da devolução; dinheiro ou cartão → a taxa vira pendência no app e o passageiro fica **sem pedir corrida até pagar**. Hoje o servidor usa 60 s depois do aceite e R$ 2 (`free_cancel_after_accept_s`, `cancel_compensation_cents`), só registrados, e **não existe saldo do passageiro no código**: é um conceito novo, e um saldo que guarda dinheiro do passageiro cai na mesma pergunta do Banco Central/advogado do saldo do motoqueiro. Ainda a confirmar com o Levy: (a) a janela conta do aceite da moto, que é quando a tela mostra o aviso (suposição, ele não contestou); (b) a conta exata entre R$ 3 e R$ 5 (sugestão: cresce junto com a distância andada, de R$ 3 com a moto saindo a R$ 5 com a moto no ponto, em degraus de R$ 0,50); (c) como o saldo do passageiro é abastecido (recarga por Pix? crédito de devoluções?); (d) o recurso vira uma fila no painel (plano 4), a taxa fica cobrada até o Levy decidir e, se aceito, é devolvida.
- Calote (Levy, 18/10/2026): ele considera o risco muito pequeno pelas travas. Pix: pago antes. Cartão (plano 8): tenta na hora; se negar, mostra o motivo e cancela a corrida; se por erro a corrida for validada com o cartão recusado, ou o dinheiro não chegar, o passageiro fica sem poder pedir até pagar. Dinheiro: o motoqueiro confirma que recebeu e a taxa sai do saldo dele no app; sem saldo, ele não pode aceitar corrida até pagar, mas ainda faz uma corrida antes do bloqueio. Quem arca com o prejuízo no caso que sobrar fica como está (o motoqueiro) e não pede decisão agora. A corrida bloqueada por falta de pagamento continua contando para as corridas de teste (o Levy não pediu mudança). A confirmar: o "saldo no app" do motoqueiro hoje é uma dívida descontada da próxima corrida Pix (limite R$ 10, bloqueia só corridas em dinheiro); o jeito do Levy parece ser dívida com limite de uma taxa, e bloquear também as corridas em Pix impediria o motoqueiro de quitar pelo próprio repasse. Resposta do Levy em 19/10/2026 à proposta (baixar o limite para uma taxa e bloquear só as corridas em dinheiro): "sim, mas não precisa bloquear as corridas em dinheiro não". **Ambígua, falta esclarecer** (não bloquear nada? bloquear tudo, e não só o dinheiro?); até lá o código fica como está.
- Teste e entrada do motoqueiro (Levy, 18/10/2026, ainda **não decidido**, "vou ver"): as corridas de teste **têm** taxa (confirmado, não são de graça); ele pensa em tirar a entrada de R$ 50 ou manter só uma vez, e subir o teste de 10 para 20 corridas. São parâmetros (`trial_rides`, `entry_fee_cents`); tirar a entrada pede um pequeno ajuste em `fees.py`, que hoje bloqueia depois do teste enquanto a entrada não for paga. Sem a entrada, a spec (seção 7.4) mostra que a taxa por corrida passa a ser a única receita, e com R$ 1,00 sobram só cerca de R$ 0,31 por corrida.
- "Muito tempo sem sinal" (Levy, 19/10/2026): quem é avisado = **o passageiro e o contato de emergência**. O painel também mostraria o alerta (suposição minha, porque os alertas de segurança já aparecem lá). **Falta o tempo**: os "5 minutos" de antes eram do cancelamento, não deste alerta.

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
