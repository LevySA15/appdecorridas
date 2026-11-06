# Apps do passageiro e do motoqueiro (Flutter)

Planos 5 e 6: a base compartilhada (`corrida_core`, `corrida_ui`) e os dois apps Android, `apps/passenger` e `apps/rider`.

## O que já existe

`packages/corrida_core` (Dart puro, não depende de Flutter):

- `ApiClient`: HTTP com token, erros (`ApiException` com o `code` estável da API; `NetworkException` sem rede) e `brl()` para mostrar centavos.
- `AuthApi` e `SessionManager`: entrar por código, guardar a sessão (`SessionStore`) e reagir à sessão vencida (401).
- `PassengerApi` e `RiderApi` com os modelos de cada papel (`PassengerState`, `PassengerRide`, `Quote`, `RiderState`, `Offer`, ...). Leitura tolerante: campo novo é ignorado, campo que falta vira `null`, estado desconhecido vira `unknown`.
- `RealtimeClient`: WebSocket (`/v1/ws`) com reconexão, `ready` e pedido de reler o estado (`resync`); fecha com 4401 e não reconecta (sessão recusada). A conexão padrão usa o ping do protocolo para perceber conexão meio aberta.
- Fotos de documento: o envio tem tempo próprio de 120 s; os apps devem **comprimir a foto** antes de enviar. Depois de um `NetworkException` numa chamada que muda algo (pedir, cancelar, aceitar), releia o `state` antes de tentar de novo.

O contrato com o servidor é `docs/api-v1.md`. Os avisos do tempo real são dicas: a fonte da verdade é `GET /v1/passenger/state` e `GET /v1/rider/state`.

## Instalar o Flutter

O Flutter (3.47.7, estável de 8/10/2026) fica em `~/development/flutter`, fora do repositório:

    export PATH="$HOME/development/flutter/bin:$PATH"
    flutter --disable-analytics && dart --disable-analytics
    flutter config --android-sdk ~/Android/Sdk

O Android SDK já está em `~/Android/Sdk`. Para **gerar o aplicativo no celular** (planos 5B e 6) falta aceitar as licenças do
Android, e isso é uma decisão sua: rode `flutter doctor --android-licenses` e leia e aceite. Para o pacote `corrida_core` não precisa.

## Testar

    cd mobile && dart pub get
    (cd packages/corrida_core && dart test && dart analyze)      # servidor de mentira (rápido)
    tool/contrato.sh                                             # contra um servidor de verdade e descartável

`tool/contrato.sh` sobe o servidor do simulador (`server/scripts/sandbox_server.py`, num esquema e num banco do Redis só dele),
roda uma sequência inteira (cadastro e aprovação do motoqueiro, corrida com Pix, com saldo, cancelada e em dinheiro, dívida,
saque) pelo cliente Dart e derruba o servidor. Precisa do PostgreSQL, do Redis e da `.venv` do servidor (ver `server/README.md`).
Se o contrato quebrar, o pacote e o servidor se afastaram: corrija o lado errado e a `docs/api-v1.md`.

## GPS do motoqueiro (plano 5D)

O app do motoqueiro tem dois modos de posição:

| Como gerar | Posição | Quando usar |
|---|---|---|
| `flutter run` (depuração) | **de mentira**: toca no mapa para "andar" | teste em casa com os passageiros do simulador |
| `flutter run --dart-define=GPS=real` ou `flutter build apk --release` | **GPS do celular**, com serviço em primeiro plano (notificação "Recôncavo Motoqueiro") e tela sempre acesa enquanto disponível ou numa corrida | rua de verdade |
| `--dart-define=GPS=fake` num build de release | de mentira | demonstração |

Com o GPS de verdade o aparelho pede a **permissão de localização** na hora de tocar em "Estou rodando"; sem ela (ou com o GPS
desligado) o motoqueiro não fica disponível e a tela diz o que fazer. O SOS (nos dois apps) abre o discador com o **190**
preenchido e a pessoa aperta "ligar".

## Apontar os apps para um servidor (plano 4G)

Sem opção nenhuma os apps falam com `http://localhost:8000` (celular ligado por USB, com `adb reverse`). Para um servidor de verdade,
diga o endereço **completo** na hora de gerar o app:

    flutter build apk --release --dart-define=API_URL=https://corrida.exemplo.com.br      # em cada app (passenger e rider)
    flutter run --dart-define=API_URL=http://10.0.2.2:8000                                # depuração: HTTP é aceito

O app de **release só aceita `https://`** (o Android bloqueia HTTP sem criptografia): com `http://` ele para na partida com a
mensagem "API_URL inválida". A instalação do servidor está em `docs/instalacao.md`.

## Pastas

| Pasta | O que é |
|---|---|
| `pubspec.yaml` | espaço de trabalho Dart (`workspace:`) |
| `packages/corrida_core/lib/src` | cliente da API, sessão, modelos e tempo real |
| `packages/corrida_core/test` | testes com servidor de mentira |
| `packages/corrida_core/test_contract` | teste de contrato (só roda com `CORRIDA_URL`) |
| `tool/contrato.sh` | roda o contrato contra o servidor descartável |

Computador com 7 GB de memória: a análise do Flutter e o Gradle pesam; feche o navegador antes de gerar um APK.
