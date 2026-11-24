# Os apps no navegador (conferir telas e fluxos sem celular)

Os dois apps Flutter também compilam para a web. **Isto é só uma ferramenta de desenvolvimento**: serve para ver as telas, testar o
fluxo inteiro de uma corrida e achar defeito de layout sem precisar de um celular. Quem usa o dia a dia continua sendo o app Android.

## Subir tudo

```bash
cd mobile
tool/web.sh build          # compila os dois (cerca de 4 minutos; use `build passenger` ou `build rider` para um só)
tool/web.sh up             # servidor descartável (porta 8100) + passageiro (8081) + motoqueiro (8082)
```

Depois abra:

| O que | Endereço |
|---|---|
| App do passageiro (numa moldura de celular) | http://localhost:8081/celular.html |
| App do motoqueiro (numa moldura de celular) | http://localhost:8082/celular.html |
| Painel do dono | http://127.0.0.1:8100/painel/ |

- O código de login não é enviado: `curl "http://127.0.0.1:8100/v1/dev/otp?phone=75999990001"` (o telefone é o que você digitou no app).
- O administrador do servidor descartável é o `75 99999-0000` (o painel tem o botão "Pegar o código").
- O banco é **descartável**: `tool/web.sh down` apaga tudo (esquema, Redis, fotos). Nada disto toca o banco de desenvolvimento.
- O servidor só aceita chamadas do navegador vindas de `localhost`/`127.0.0.1` e só com `DEV_ROUTES` ligado (modo de desenvolvimento);
  num servidor público (`DEV_ROUTES=off`) o CORS nem existe.

## Cenários automáticos (navegador sem janela)

`mobile/tool/ui/` tem um pequeno "robô" (Playwright, com o Chromium que já vem instalado em `~/.cache/ms-playwright`) que abre os
apps, aperta os botões pelo texto e **tira foto de cada tela** (390x844, claro ou escuro). Primeira vez: `cd mobile/tool/ui && npm install`.

```bash
cd mobile/tool/ui
SHOTS=/tmp/fotos node corrida_completa.js claro dinheiro   # uma corrida de ponta a ponta com os dois apps (cash)
SHOTS=/tmp/fotos node corrida_completa.js escuro pix       # idem, em Pix e no tema escuro
SHOTS=/tmp/fotos node cancelamentos.js claro               # cancelar procurando, cancelar com moto, SOS
SHOTS=/tmp/fotos node passageiro_telas.js claro            # carteira, histórico, recibo, perfil
SHOTS=/tmp/fotos node motoqueiro1.js claro                 # cadastro do motoqueiro com as 3 fotos
SHOTS=/tmp/fotos node painel.js 1280                       # entra no painel e fotografa cada aba (use 390 para celular)
```

Variáveis: `PAX=<telefone>` (use um telefone novo a cada rodada: passageiro com taxa pendente fica bloqueado de propósito),
`API_URL` (padrão `http://127.0.0.1:8100`), `SHOTS` (pasta das fotos). Os cenários escrevem na tela o texto de cada passo e
os erros do navegador, e param no primeiro botão que não achar.

Por que sem janela: o Chrome do dia a dia, quando está atrás de outra janela, **não deixa tirar foto** (a captura espera por um
quadro que nunca vem). O Chromium sem janela não tem esse problema e não atrapalha quem está usando o computador.

## O que isto não substitui

- Mapa de verdade, GPS, câmera, discador (190), notificação e bateria: só num celular.
- O navegador usa o WebSocket do próprio navegador (sem o ping do protocolo do celular).
- O build web é de **perfil** (não release), porque o release recusa `http://`. Não publique isto em lugar nenhum.

## Testes de tela pequena e letra grande

`mobile/apps/*/test/telas_pequenas_test.dart` põe as telas principais num celular de 320x568 com letra 1,5x (claro e escuro) e falha
se qualquer coisa estourar. Já pegou: botão dentro de `ListTile` que não cabia (início do motoqueiro), folha de cotação mais alta que a tela
e a dica do mapa engolindo o toque.
