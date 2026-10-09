# App de corrida de moto do Recôncavo — Especificação de design

**Data:** 2026-10-08
**Dono do projeto:** Levy
**Nome do app:** provisório ("App de corrida do Recôncavo"). O nome final ainda não foi escolhido e a pasta do projeto também usa um nome provisório.
**Estado:** aprovada pelo Levy em 2026-10-08. Próximo passo: plano de implementação.

Legenda usada ao longo do texto:
- **Decidido** = o Levy escolheu.
- **Proposta** = sugestão minha, com valor inicial para ajustar depois com dados reais.
- **Em aberto** = ainda sem resposta, com quem resolve e quando.

---

## 1. Objetivo

Criar um aplicativo de corridas de moto **barato e justo** para **Santo Antônio de Jesus (BA)**, no Recôncavo Baiano, com três peças: app do passageiro, app do motoqueiro e um painel de controle para o dono. Os grandes apps (Uber, 99, inDrive) já operam no país com comissões de 0 a 40% conforme a plataforma; o diferencial aqui é preço baixo e simples, presença local e confiança. O Levy vai operar sozinho no começo e contratar pessoas depois.

Ordem de produtos: **moto → carro → entregas**. Esta especificação cobre apenas a **moto** em Santo Antônio de Jesus. Carro e entregas ficam para depois.

## 2. Contexto e decisões de negócio

| Tema | Decisão |
|---|---|
| Cidade piloto | **Decidido:** Santo Antônio de Jesus (~103 mil habitantes, polo regional de comércio e serviços, feira livre grande). |
| Quem é o motoqueiro | **Decidido:** autônomos. **Atualização de 09/10/2026 (informação do Levy, vinda da prefeitura):** a prefeitura diz que **não existe** lei municipal de mototáxi em Santo Antônio de Jesus e que **não emite mais** permissão desse tipo desde a posse do atual prefeito. A premissa antiga ("a prefeitura está regularizando a documentação deles") **não vale mais**; ver seção 14, itens 1 e 2. |
| Prazo | **Decidido:** sem data. Prefere bem feito a rápido. |
| Orçamento | **Decidido:** R$ 150 a R$ 500 por mês de custo fixo, mais ~R$ 2.500 de investimento inicial (detalhes do investimento não confirmados). |
| Plataformas | **Decidido:** começar só no **Android** (único celular de teste do Levy). iPhone entra depois. |
| Operação | **Decidido:** Levy sozinho no início; painel preparado para mais pessoas com níveis de acesso. |
| Tecnologia pedida | **Decidido:** servidor em Python, banco SQL próprio, celular Android e iOS. |

### Cobrança do motoqueiro (decidido)
1. Cadastro e aprovação pelo Levy.
2. **10 corridas de teste.** Elas **têm** a taxa por corrida (o Levy mudou isso no meio da conversa). O motoqueiro ainda não paga a entrada.
3. Depois da 10ª corrida o app bloqueia novas corridas até ele pagar **R$ 50 por Pix, uma vez só**.
4. Depois disso, paga só a **taxa por corrida**.

### Taxa por corrida
- **Decidido:** a taxa é menor quando o motoqueiro roda mais no dia.
- **Proposta de estrutura:** taxa cheia como base, com **descontos por faixas** de corridas no dia (por exemplo 1ª a 5ª taxa cheia, 6ª a 10ª menor, da 11ª em diante a menor). No dia seguinte volta à base. É a mesma conta que "descer e subir", mas aparece para o motoqueiro como prêmio e não como castigo por parar.
- **Decidido:** a taxa deve ser **a menor possível, desde que haja lucro** por corrida.
- **Proposta:** como ponto de partida, uma taxa base de **R$ 1,00** por corrida (cerca de 14% de uma corrida de R$ 7), que deixa cerca de R$ 0,31 por corrida depois da cota grátis de mapas (seção 7.4). Os descontos por faixa precisam respeitar o piso de lucro. O valor final é confirmado com a proposta comercial da Woovi.
- **Em aberto:** os valores das faixas e o piso. O Levy decide depois de ver o custo do provedor de pagamento e o lucro (seção 7.4).

### Preço para o passageiro (decidido)
- Um **preço final único**, mostrado antes do pedido. Não há taxa de serviço separada para o passageiro; os custos de pagamento e a taxa da empresa estão dentro desse valor.
- O preço é calculado pela **distância**, pela **quantidade de motos livres** e pelo **movimento de pedidos naquele horário**.
- Faixa vista pelo Levy: normalmente R$ 6 a R$ 8; cerca de R$ 5 quando há muita moto livre e muito pedido; até R$ 12 de manhã cedo ou muito tarde, com pouca moto.

## 3. Escopo da versão 1

### Entra
- App do passageiro (Android): login, pedir moto, ver preço antes, pagar (Pix ou dinheiro), acompanhar no mapa, código de 4 dígitos, avaliar.
- App do motoqueiro (Android): cadastro, ficar disponível, receber e aceitar corrida, fila de uma corrida, confirmar capacete, QR de pagamento, extrato do dia.
- Painel do dono (site): aprovar motoqueiros, ver corridas, dinheiro, taxas, reclamações, bloqueios.
- Servidor com cadastro, procura, preço dinâmico, pagamentos, segurança e livro-caixa.
- Pagamentos: **Pix pela Woovi + dinheiro**. Sem saldo recarregável.

### Fica para depois
- Cartão de crédito pela **Asaas** (etapa 2 de pagamentos).
- Saldo recarregável (só depois de confirmação com advogado, ver seção 7.5).
- App para iPhone.
- Carro e entregas.
- Compartilhar corrida em tempo real com contato (o Levy não escolheu para a v1).

## 4. Telas

**Passageiro:** entrada com código pelo WhatsApp · mapa com "Para onde?" · confirmação com preço, tempo de chegada e forma de pagar · procurando moto · moto a caminho (ficha do motoqueiro, código de 4 dígitos, tempo) · pagamento do Pix (2 minutos) · corrida em andamento · fim e avaliação · histórico · perfil.

**Motoqueiro:** entrada e cadastro com documentos · "Ficar disponível / Parar" · oferta de corrida (cerca de 15 segundos) · a caminho do passageiro · confirmar capacete e pedir o código · corrida em andamento · fim com QR de pagamento e botão de confirmar · extrato do dia (corridas, ganhos, taxa, faixa de desconto) · documentos e avisos de vencimento.

**Painel do dono:** fila de cadastros para aprovar · lista e detalhe de corridas · motoqueiros e passageiros (bloquear/liberar) · dinheiro e taxas · devedores · alertas de segurança · parâmetros (faixas de preço, taxas, limites).

## 5. Ciclo da corrida

### 5.1 Etapas
1. **Pedido.** O passageiro escolhe destino, vê o preço final e escolhe a forma de pagamento (Pix ou dinheiro). O preço fica travado.
2. **Procura.** O servidor acha as motos livres mais próximas **pelo tempo de rota**, oferece a **uma moto por vez** com cerca de **15 segundos** para aceitar, e desiste depois de cerca de **2 minutos**, avisando o passageiro.
3. **A caminho.** O passageiro vê a ficha do motoqueiro, o tempo de chegada e o código de 4 dígitos.
4. **Chegada.** O motoqueiro confirma que tem capacete extra, o passageiro diz o código e a corrida começa.
5. **Em andamento.** Acompanha o trajeto. Se a moto para muito tempo ou sai da rota, aparece o aviso de segurança.
6. **Fim.** Fecha a corrida, calcula a taxa, libera o dinheiro. Os dois se avaliam.

### 5.2 Regra de uma corrida por vez e corrida na fila (decidido)
- O motoqueiro **nunca** tem duas corridas ativas ao mesmo tempo.
- Quando está terminando uma corrida, o app pode oferecer um novo pedido que **espera na fila**. O passageiro vê "a moto está terminando uma corrida em [ponto] e chega em X minutos". A nova corrida só começa depois que a primeira termina.
- **Proposta de parâmetros:** "terminando" = a cerca de 2 minutos ou 500 metros do destino; no máximo **1 corrida na fila** por motoqueiro; o motoqueiro aceita ou recusa **sem penalidade** e nada começa sozinho; o passageiro cancela de graça enquanto espera na fila; se o tempo de espera passar de cerca de **8 minutos**, o passageiro é passado para outra moto; o Pix é criado quando o motoqueiro aceita a corrida da fila.

### 5.3 Cancelamento (proposta)
Grátis até a moto aceitar e por 1 minuto depois. Depois disso, uma compensação pequena ao motoqueiro (valor em aberto). Há um tempo máximo de espera na chegada, depois do qual a corrida cancela com a mesma compensação.

## 6. Preço dinâmico

- **Decidido:** o preço sobe e desce conforme a oferta de motos e a procura, nos dois sentidos.
- **Proposta:** `preço = tarifa pela distância × fator`, com o **fator entre 0,8 e 1,6**. Numa corrida típica de R$ 7, isso dá de R$ 5,60 a R$ 11,20. Arredondar para R$ 0,50.
- O fator vem da relação entre pedidos e motos livres na região nos últimos minutos e muda **aos poucos** (sem saltos bruscos).
- O app mostra o **motivo** do preço ("muita moto livre agora, preço menor" / "poucas motos agora, preço maior").
- O preço é travado quando o passageiro confirma o pedido.
- **Em aberto:** a tarifa por distância (valor por km e mínimo). Serão calibrados com corridas reais do teste fechado. Os limites 0,8 e 1,6 são estimativas minhas.

## 7. Pagamentos

### 7.1 Formas de pagar (decidido)
O passageiro escolhe **antes de pedir**: **Pix** ou **dinheiro**. Cartão e saldo recarregável ficam para depois.

### 7.2 Como funciona cada uma
- **Pix pré-pago.** A cobrança é criada **quando a moto aceita**, pois a divisão automática do pagamento precisa saber qual motoqueiro vai receber. O passageiro tem **2 minutos** para pagar, senão a corrida cancela e a moto é liberada. Se foi pago e a corrida cancelou, a devolução é automática.
- **Dinheiro.** No fim da corrida a tela do motoqueiro mostra um **QR do Pix** com o valor e um **botão de confirmar pagamento**. O passageiro paga em Pix (pelo QR) ou em dinheiro, e o motoqueiro confirma. O QR também faz a divisão automática.
- **Divisão automática.** O provedor divide o pagamento na hora entre a conta do motoqueiro e a da empresa. O dinheiro do motoqueiro **não passa pela conta da empresa**. Cada motoqueiro tem uma subconta no provedor, aberta no cadastro com a verificação feita pelo próprio provedor.
- **Taxa das corridas em dinheiro vivo.** Fica como dívida do motoqueiro e é descontada da **próxima corrida paga por Pix**. Há um limite de dívida (**proposta:** R$ 10,00); acima disso o app para de oferecer corridas em dinheiro até ele pagar por Pix.
- **Decidido (Levy, 09/10/2026): o motoqueiro só deve a taxa quando o passageiro de fato pagou em dinheiro.** A dívida aparece na tela do motoqueiro. Se o passageiro vai embora sem pagar (calote), **o motoqueiro não deve taxa** daquela corrida; o calote fica como dívida do passageiro (`unpaid_cents`). Interpretação minha da resposta do Levy, a confirmar.
- **Passageiro que sai sem pagar** fica bloqueado para novos pedidos até pagar o valor devido.

### 7.3 Provedores
- **Woovi:** Pix e divisão. Pelo site oficial, o Pix custa 0,80% do valor, **mínimo de R$ 0,50 e máximo de R$ 5,00** (ou R$ 0,85 fixo no plano fixo). A divisão e as subcontas são grátis. Saque para chave Pix é grátis a partir de R$ 500 e custa R$ 1,00 abaixo disso; Pix enviado custa R$ 1,00.
- **Asaas (etapa 2, só cartão):** R$ 0,49 + 2,99% por cobrança à vista. O Levy decidiu que a Asaas **não** é reserva do Pix.
- **Consequência da etapa 2:** o motoqueiro terá subconta nos dois provedores (dois cadastros e dois saldos).
- Fora da lista por falta de preço público confiável ou por limitação: Mercado Pago (divisão só entre contas Mercado Pago), Efí (divisão documentada para boleto e cartão, Pix não confirmado), Pagar.me (preço só sob consulta).

Custo de pagamento por corrida de R$ 7, para referência: Pix na Woovi **R$ 0,50 (7%)**; cartão na Asaas **R$ 0,70 (10%)**; Pix na Asaas R$ 1,99 (28%). A Woovi é a mais barata em todas as comparações que fiz.

### 7.4 Lucro por corrida (exemplo, não previsão)
A taxa da empresa precisa cobrir o custo de pagamento e o de mapas. Na v1 (sem saldo recarregável) o Pix é pago a cada corrida: **R$ 0,50 na Woovi**. O custo de mapas é de cerca de **R$ 0,19** por corrida **depois** da cota grátis do Google (suposição minha, seção 10.3); dentro da cota grátis é zero. Corridas pagas em dinheiro não pagam Pix na hora, mas a taxa só entra depois como dívida descontada.

Sobra por corrida, **antes dos impostos**:

| Taxa por corrida | Depois da cota grátis de mapas | Dentro da cota grátis |
|---|---|---|
| R$ 0,70 (10% de R$ 7) | R$ 0,01 | R$ 0,20 |
| R$ 1,00 | R$ 0,31 | R$ 0,50 |
| R$ 1,50 | R$ 0,81 | R$ 1,00 |

**Conclusão:** com taxa de R$ 0,70 quase não sobra nada por corrida. Os R$ 50 de entrada (R$ 1.000 para 20 motoqueiros, uma vez só) e uma taxa maior, ou menos custo por corrida, é que sustentam o negócio. O exemplo de lucro mensal que mostrei na conversa usava um custo de pagamento menor (R$ 0,12, que dependia do saldo recarregável) e estava otimista demais para a v1. **O valor da taxa precisa ser decidido com estes números na mão** (decisão do Levy, antes do lançamento). Formas de melhorar a margem: taxa maior, trocar o mapa por um mais barato quando o volume crescer, ou, depois do parecer do advogado, o saldo recarregável.

### 7.5 Saldo recarregável (adiado)
Guardar saldo pré-pago de passageiros pode ser tratado pelo Banco Central como emissão de moeda eletrônica, que exige autorização, salvo exceções como o arranjo de propósito limitado (Resolução BCB 80/2021). Também não combina com a divisão automática, pois o dinheiro ficaria parado esperando as corridas. Só será considerado depois de parecer de advogado e, se for feito, usando a carteira do próprio provedor.

### 7.6 Livro-caixa
Todo movimento de dinheiro é registrado em uma tabela que **não permite apagar nem alterar** (só acrescentar lançamentos de correção). Todo dia o sistema compara o livro com o extrato do provedor e aponta diferenças.

## 8. Cadastro e conferência do motoqueiro

- **Dados:** celular (código pelo WhatsApp), nome, CPF, selfie, foto da CNH, documento da moto (CRLV), placa. A conta de pagamento é aberta junto, com a verificação feita pelo provedor.
- **Decidido:** o app **não pede nem mostra** a permissão da prefeitura. Veja o risco na seção 14.
- **Aprovação:** manual pelo Levy no painel. Um mesmo CPF, CNH, placa só pode ter um cadastro (evita repetir o teste).
- **Bloqueios automáticos:** CNH ou documento da moto vencidos. Nota baixa e denúncias vão para análise do Levy.
- **Ficha mostrada ao passageiro:** foto, nome, placa, modelo da moto e nota. **Sem** selo de permissão da prefeitura.
- **Extrato do motoqueiro:** corridas, ganhos, taxa e faixa de desconto do dia, em tempo real.

## 9. Segurança (decidido)

1. **Ficha do motoqueiro** na tela do passageiro (seção 8).
2. **Código de 4 dígitos** que o passageiro diz ao motoqueiro antes de a corrida começar.
3. **Confirmação do capacete extra** pelo motoqueiro antes de começar.
4. **Aviso automático** se a moto parar por muito tempo ou sair muito da rota, perguntando se está tudo bem. O **SOS** (liga para o 190 e avisa um contato do passageiro) aparece **dentro desse aviso**.
5. **Proposta minha, o Levy decide:** um acesso discreto ao SOS na tela da corrida, sempre disponível, para quando o perigo não disparar o aviso automático (por exemplo, rota certa e motoqueiro agressivo).
6. Não escolhido: compartilhar a corrida em tempo real com um contato.

Contexto: em Salvador, os feridos em acidentes de moto subiram 45% depois da chegada das corridas por aplicativo (Bahia Notícias).

## 10. Arquitetura

### 10.1 Peças
1. **O que as pessoas usam:** app do passageiro, app do motoqueiro (mesma base de código, dois apps) e painel web.
2. **Servidor (Python, FastAPI), um programa só:** cadastro e conferência, pedido de corrida, preço dinâmico, pagamentos, segurança.
3. **Dados:** PostgreSQL com extensão geográfica (PostGIS) para o histórico oficial; Redis para a posição atual das motos.
4. **Serviços de fora:** Woovi (Pix), Asaas (cartão, etapa 2), Google Maps (mapa, rotas, endereços), avisos no celular (Firebase Cloud Messaging) e código de login pelo WhatsApp.

### 10.2 Tecnologias
- **Celular:** Flutter (um código para Android e iPhone; Android primeiro). Escolha minha, aprovada junto com o caminho.
- **Servidor:** Python com FastAPI. Começa com **um servidor pequeno no Brasil**; custo estimado de R$ 50 a R$ 150 por mês (não conferido).
- **Tempo real:** os apps conversam com o servidor por requisições comuns e por conexão contínua (WebSocket) para ofertas, posição e estado da corrida. O motoqueiro envia a posição a cada cerca de **4 segundos** enquanto está disponível; no Android isso exige um serviço em primeiro plano com notificação visível.
- **Painel:** site em Python/web, com níveis de acesso desde o início.

### 10.3 Mapas (decidido)
- **Google Maps no começo.** Mostrar o mapa no Android é grátis; rotas e endereços são cobrados depois de 10 mil usos grátis por mês, a cerca de US$ 5 por mil.
- Estimativa: ~7 cálculos de rota por corrida (suposição minha), cerca de US$ 0,035 (~R$ 0,19) depois da cota grátis. Reduz calculando a rota só para as 3 motos mais próximas.
- O código de mapas fica **isolado em um módulo único**, para trocar por mapa aberto depois se o custo pesar. Se usar Google, usa tudo do Google (os termos não permitem misturar com outro mapa).
- No mapa aberto de Santo Antônio de Jesus: 1.120 trechos de rua com nome e 25 bairros, mas só 26 números de casa e 22 lugares com nome (consulta de 2026-10-08), o que torna a busca de destino fraca.

### 10.4 Login (decidido)
Código pelo **WhatsApp** (cerca de US$ 0,0068 por mensagem no Brasil pela tabela da Meta de julho de 2026, segundo uma fonte; outra fonte fala em US$ 0,0315). **SMS só de reserva**, por ser bem mais caro (cerca de US$ 0,05 por SMS). Sessão longa (o código só é pedido em celular novo) e limite de pedidos de código por número, contra abuso.

### 10.5 Dados principais
Usuário (passageiro e motoqueiro) · Perfil do motoqueiro e documentos · Moto · Corrida e seus eventos · Cobrança/pagamento · Lançamentos do livro-caixa · Taxa e dívida do motoqueiro · Avaliação · Alerta de segurança · Zona de preço · Parâmetros configuráveis.

## 11. Visual e voz do app

- **Decidido:** estilo **A "claro e direto"** no modo claro (branco, preto e uma cor de destaque; letras grandes; poucas escolhas) e estilo **C "escuro e ousado"** no modo escuro. O app acompanha a configuração do celular.
- **Decidido (Levy, 09/10/2026):** cor de destaque **vermelho #D92D27**, no lugar do verde #54CF57 escolhido antes. Valor visto no protótipo `docs/prototipo/index.html`.
- **Regra de contraste:** a cor de destaque é usada como **fundo** de botões, pinos, barra de progresso e detalhes, com **texto branco por cima** (contraste de 4,8 para 1). Em texto sobre fundo branco também passa (mesmo contraste). No modo escuro, o vermelho serve como fundo de botão e pino, não como texto pequeno sobre o preto. O vermelho também sinaliza alerta; por isso o aviso de segurança usa tela inteira vermelha e nenhum erro comum usa essa cor sozinha (sempre com texto explicando).
- **Mapa em primeiro plano**, com a faixa de controles embaixo, como nos apps grandes.
- **Voz:** frases curtas e simples, jeito de falar da região ("Pra onde vamos?"). O texto exato é definido na implementação.
- Os mockups das escolhas antigas estão em `.superpowers/brainstorm/` (pasta local, fora do controle de versão). O protótipo atual, com o vermelho, está em `docs/prototipo/index.html`.

## 12. Erros e resiliência

- **Sem internet:** corrida em andamento continua; o app reconecta. Muito tempo sem sinal gera aviso.
- **Pix:** não pago em 2 minutos cancela; pago e cancelado devolve; aviso repetido do provedor não cobra duas vezes (cada evento é tratado uma vez só); provedor fora do ar: o app oferece só dinheiro.
- **Dois pedidos para a mesma moto:** o servidor reserva a moto para um pedido só.
- **GPS ruim ou localização falsa:** ignora saltos estranhos, confirma antes do aviso de segurança e detecta localização falsa.
- **Servidor fora do ar:** os apps mostram "instável"; backup diário do banco.
- **Dinheiro:** livro-caixa e comparação diária com o provedor (seção 7.6).

## 13. Testes e lançamento

### 13.1 Testes
1. Testes automáticos das regras de dinheiro, preço, escolha de moto e etapas da corrida, escritos **antes** do código.
2. **Simulador** com motoqueiros e passageiros falsos andando por Santo Antônio de Jesus.
3. Ambiente de testes da Woovi antes de usar dinheiro real.
4. **Teste fechado** no Android: Levy, cerca de 5 motoqueiros e amigos, com valores pequenos reais.
5. Conferências antes de abrir: contador (impostos e tipo de empresa), advogado (pagamentos, termos de uso, permissões), LGPD, política de privacidade.

### 13.2 Lançamento em fases (segue o plano do Instagram)
0. Construção e simulador, sem gente real.
1. Teste fechado.
2. Pré-cadastro dos motoqueiros pelo Instagram; o Levy aprova os documentos.
3. Com cerca de **20 aprovados**, abre o app do passageiro. As 10 corridas de teste dos motoqueiros só começam aqui, porque sem passageiro não há corrida.
4. Depois: cartão pela Asaas e, no futuro, carros e entregas.

### 13.3 Publicação na Google Play
Uma conta pessoal nova precisa de um teste fechado com pelo menos **12 pessoas por 14 dias seguidos** antes de publicar (recrutar de 15 a 20). Conta de empresa parece isenta, mas pede número D-U-N-S (confirmado só em guias; conferir na Google). A fase de teste fechado cobre essa regra.

## 14. Riscos e pontos em aberto

### Legais e regulatórios
1. **Não há lei municipal de mototáxi nem permissão sendo emitida (atualizado em 09/10/2026).** Eu tinha anotado a "Lei 929/2008" como existente, mas **nunca li o texto** e agora não achei nenhum registro dela para Santo Antônio de Jesus (busca de 09/10/2026), e a prefeitura disse ao Levy que essa lei não existe aqui e que não emite mais esse tipo de documento. **Tratar a anotação antiga como errada ou não confirmada.** A Lei federal 12.009/2009 deixa a regulamentação do mototáxi para cada município; sem regra local, **não sei dizer** se o serviço é permitido, tolerado ou infração. **Quem resolve:** o advogado (conversa marcada para a semana de 12/10/2026). **Pedir à prefeitura a resposta por escrito (ofício ou protocolo)**, porque o advogado vai precisar dela. Perguntas para o advogado estão no roteiro dos planos.
2. **O app não confere permissão nenhuma (decisão do Levy), e agora não existe permissão para conferir.** Se a atividade for irregular no município, o motoqueiro pode receber multa e ter a moto removida, e a empresa pode ser responsabilizada (em São Paulo, o Procon multou Uber e 99 por mototáxi irregular). Recomendação mantida e reforçada: **não abrir ao público antes da conversa com o advogado**. O app não tem como impedir um motoqueiro irregular.
3. **Saldo recarregável e recebimento de dinheiro de terceiros** (seção 7.5). Advogado/contador.
4. **Vínculo de emprego de motoristas de aplicativo (STF, Tema 1291)** ainda sem decisão (adiado de novo em 27/08/2026). Quanto mais o app controla o motoqueiro, maior o risco. Por isso: aceitar/recusar sem penalidade, sem "próxima corrida" automática, descontos por faixa em vez de aumento por parar.
5. **LGPD:** documentos pessoais exigem proteção e regra de guarda. Tempo de guarda **em aberto**, a definir com advogado.
6. **Impostos** sobre a taxa da empresa e tipo de empresa: contador decide.
7. Regras de moto por aplicativo variam por município e há projetos de lei federais em tramitação (PL 2949/2024 e outros). Acompanhar.

### Negócio e custos
8. **Margem da taxa** é pequena com o custo real de pagamento (seção 7.4). O Levy decide o valor da taxa com os números reais.
9. **Quem paga o saque do motoqueiro** na Woovi (R$ 1,00 abaixo de R$ 500). Em aberto; confirmar na proposta comercial.
10. **Preço do código de WhatsApp:** fontes divergem (US$ 0,0068 × US$ 0,0315). Confirmar na tabela oficial da Meta.
11. **Proposta comercial e teste da Woovi** (divisão em ambiente de teste) ainda não feitos.
12. **Empresa (CNPJ):** o Levy **ainda não tem**, só CPF. Ele vai conversar com um advogado **antes** de abrir o CNPJ. WhatsApp comercial, Woovi e Google Play provavelmente pedem CNPJ, então **dinheiro real e publicação nas lojas dependem disso**. Construir o servidor, o simulador e os apps de teste não depende.
13. **Tipo de conta na Google Play** (pessoal × empresa).
14. **Nome do app** e logo: o Levy ainda não tem ideia de nome. Decidir antes de publicar nas lojas; até lá o nome é provisório.
15. **Custo de servidor** (R$ 50 a R$ 150) e de mapas são estimativas minhas.

### Técnicos
16. A cobertura do mapa aberto em prédios não foi obtida na consulta.
17. iPhone: exige Mac ou serviço de build na nuvem e um iPhone para testar.

## 15. Fontes principais

- Asaas, preços: https://www.asaas.com/precos-e-taxas
- Woovi, preços: https://woovi.com/pricing/
- Google Maps Platform (cobrança Android): https://developers.google.com/maps/documentation/android-sdk/usage-and-billing
- Google Play, requisito de teste: https://support.google.com/googleplay/android-developer/answer/14151465
- Resolução BCB 80/2021: https://www.legisweb.com.br/legislacao/?id=411674
- Mototáxi por aplicativo e regulação municipal: https://www.portaldotransito.com.br/noticias/mobilidade-e-tecnologia/seguranca/mototaxi-por-aplicativo-seguranca-e-regulamentacao-em-debate/
- Multas a Uber e 99 por mototáxi irregular: https://canaltech.com.br/mercado/procon-sp-multa-uber-e-99-por-mototaxi-irregular-em-sao-paulo/
- Decisão do STF sobre limites municipais ao mototáxi: https://conjur.com.br/2020-out-24/lei-municipal-nao-restringir-servico-mototaxi-stf/
- Acidentes de moto em Salvador: https://www.bahianoticias.com.br/noticia/300655-uber-e-99-feridos-em-acidentes-de-moto-tem-aumento-de-45-com-a-chegada-de-viagens-por-app-em-salvador
- Psicologia dos apps de corrida: https://work21.gatech.edu/2019/01/21/the-science-behind-ubers-nudges e https://uxmag.com/articles/how-uber-uses-psychology-to-perfect-their-customer-experience

## 16. Próximo passo

Depois da aprovação do Levy, escrever o **plano de implementação** (skill `writing-plans`), em etapas pequenas e testáveis, começando pelo servidor e pelo simulador, antes dos apps e de qualquer dinheiro real.
