# O mapa dos apps

Os dois apps desenham o mapa por trás de um único ponto (`corrida_ui`: `CorridaMapView` e `CorridaMapPicker`), que escolhe entre três motores:

| Motor | O que é | Quando |
|---|---|---|
| `fake` | Desenho de mentira da cidade (ruas, avenidas, parque, rio). Sem internet, sempre igual. | Testes, `flutter run` e o navegador (`tool/web.sh`). Padrão fora do release. |
| `osm` | Ruas de verdade do OpenStreetMap, com os mesmos pinos e o trajeto. Mexe e dá zoom com os dedos; a câmera enquadra embarque e destino. | Padrão do app de **release** sem chave do Google. Em qualquer build: `--dart-define=MAP=osm`. |
| `google` | Mapa do Google (Maps SDK para Android), com os mesmos pinos, o trajeto, o estilo escuro e a câmera enquadrando embarque e destino. | Sempre que o app é compilado com `--dart-define=GOOGLE_MAPS_API_KEY=...` (ou `MAP=google`). **Só no celular:** na web (navegador de teste) `google` vira `osm`. |

Escolha à mão: `flutter run --dart-define=MAP=osm` (ou `=fake`, `=google`). O app do motoqueiro continua escolhendo o GPS por `--dart-define=GPS=real|fake`.
Regra completa (`resolveMapEngine`): `MAP` escolhido ganha de tudo; sem `MAP`, com chave do Google = `google`, sem chave o release usa `osm` e o resto `fake`.

## Mapa do Google nos apps (o que fazer para ligar)

O código está pronto e testado com um Google de mentira (`packages/corrida_ui/test/google_map_test.dart`), mas **ainda não foi visto com a chave de verdade nem num celular**: falta só a chave.

1. No Google Cloud (o mesmo projeto das rotas serve), ative **Maps SDK for Android**.
2. Crie uma **segunda chave** (a do servidor, só com Routes API e restrita por IP, não pode ir para o celular). Restrinja esta: "Restrições de aplicativo" = **apps Android**, com duas entradas: `com.reconcavo.passenger` e `com.reconcavo.rider`, cada uma com o **SHA-1** da chave que assina o APK (hoje o release é assinado com a chave de depuração; no computador onde você compila: `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android | grep SHA1`); "APIs" = só Maps SDK for Android.
3. Guarde a chave num arquivo que **não vai para o GitHub**: `mobile/chaves.json` com `{"GOOGLE_MAPS_API_KEY": "cole-a-chave"}` (já está no `.gitignore`).
4. Rode ou compile com o arquivo (o Gradle põe a chave no manifesto do Android sozinho):

       cd mobile/apps/passenger && flutter run -d <id do celular> --dart-define-from-file=../../chaves.json
       cd mobile/apps/rider     && flutter run -d <id do celular> --dart-define-from-file=../../chaves.json --dart-define=GPS=real
       flutter build apk --release --dart-define=API_URL=https://corrida.seudominio.com.br --dart-define-from-file=../../chaves.json

5. No servidor, ligue `GOOGLE_MAPS_API_KEY` (a chave **do servidor**, a da Routes API) e `MAPS_DAILY_CALL_LIMIT=500`; ver `docs/instalacao.md` e a conta em "Quanto custa o Google" abaixo.
6. Sinais de que deu certo: o mapa mostra as ruas do Google com o logotipo "Google" no canto de baixo, acima da folha de controles; **mapa cinza, sem ruas ou com aviso de desenvolvimento = chave errada ou restrição errada** (pacote ou SHA-1 diferente do APK instalado; veja `adb logcat | grep -i "Google Maps"`).

### Endereço escrito pelo Google

Com o mapa do Google, o endereço escrito dos pontos ("Rua Severo Vieira, 120 - São Cristóvão") vem da **Geocoding API do Google, pelo servidor**: o app chama `GET /v1/passenger/address?lat=&lng=` e o servidor pergunta ao Google.
Assim a chave fica só no servidor, o gasto tem teto e o resultado fica guardado.

| Mapa do app | Quem escreve o endereço |
|---|---|
| `google` | o servidor (Google). Precisa da **Geocoding API** ligada na chave do servidor |
| `osm` | Nominatim (OpenStreetMap), direto do celular |
| `fake` | ninguém (os pontos do desenho de mentira não são de lugar nenhum) |

- **Teto e pausa próprios:** `GEOCODE_DAILY_CALL_LIMIT` (padrão 600 por dia, no máximo cerca de US$ 40 por mês), pausa de 60 s depois de 3 falhas seguidas, tudo separado das rotas (um problema no endereço não para o preço, e vice-versa).
- **Cache de 24 horas** por ponto (arredondado a 1 m: pontos vizinhos não herdam o número da casa); o mesmo ponto pedido de novo não é cobrado.
- **Limite por passageiro:** 40 consultas por minuto (duas por cotação, e cotações são no máximo 20 por minuto).
- **Falha nunca trava o pedido:** sem a chave do Google, sem internet, teto do dia, API desligada ou "nenhum resultado" = o pedido segue sem endereço escrito (a cotação não espera por isso). O servidor registra o motivo (`journalctl -u app-corrida | grep "Google Maps"`) sem nunca escrever a chave.
- **Frase:** rua + número + bairro, em português; só entram resultados de rua, bairro ou lugar (sem "plus codes").
- Sem a chave do Google o servidor responde sempre `{"text": null}` (nunca inventa endereço): num app com mapa do Google e servidor sem chave, ninguém vê endereço escrito.

Como o mapa foi feito: o padding do próprio mapa leva a altura da folha de baixo (`bottomSpace`), assim a câmera enquadra os marcadores na parte livre e o logotipo do Google fica à vista, como os termos pedem;
os pinos são desenhados em código (PNG) iguais aos do OpenStreetMap; a miniatura de trajeto na oferta do motoqueiro não recebe toque (a lista continua rolando).

## Ver o mapa de verdade no seu celular agora (USB, servidor no computador)

O build de depuração usa o desenho de mentira por padrão; peça o mapa de verdade (o celular precisa de internet para os ladrilhos, além do cabo):

    adb reverse tcp:8000 tcp:8000
    cd mobile/apps/passenger && flutter run -d <id do celular> --dart-define=MAP=osm
    cd mobile/apps/rider     && flutter run -d <id do celular> --dart-define=MAP=osm --dart-define=GPS=real   # GPS de verdade (sem isto o motoqueiro "anda" tocando no mapa)

No passageiro, toque em "Estou aqui" para o embarque virar a sua posição (o Android pede a permissão de localização). Servidor sem `GOOGLE_MAPS_API_KEY` (ver limite 2 abaixo).

## Limites do `osm` (leia antes de abrir ao público)

1. **O servidor de ladrilhos do OpenStreetMap (`tile.openstreetmap.org`) é para uso leve.** Serve ao teste fechado (algumas pessoas). Para
   abrir ao público é preciso um provedor com contrato (MapTiler, Stadia, Mapbox…) ou o mapa do Google; a URL e o nome do app que se identifica
   ficam em `packages/corrida_ui/lib/src/osm_map.dart` (`osmTileUrl`, `osmUserAgentPackage`). A atribuição "© OpenStreetMap" já aparece no canto.
2. **Mapa do Google no servidor × mapa de outro fornecedor no app.** Com `GOOGLE_MAPS_API_KEY` ligada, o servidor calcula as rotas pela Routes API
   (plano 7A). Os termos do Google proíbem usar os serviços deles num aplicativo que mostra mapa de outro fornecedor. Então: **app com `osm` = servidor
   sem a chave (estimativa em linha reta, que é o padrão)**; **app com `google` (seção acima) = servidor com a chave**. Nunca o contrário.
3. O trajeto desenhado é uma linha reta entre embarque e destino (não é a rota das ruas).
4. Sem busca de endereço (digitar para procurar): o passageiro toca no mapa ou usa "Estou aqui" (o servidor responde "fora da área de atendimento" se o ponto estiver longe de Santo Antônio de Jesus).
   Cada ponto marcado ganha o **endereço escrito** ("Rua Severo Vieira - São Cristóvão") pelo Nominatim, o serviço de endereços do OpenStreetMap: uma consulta por ponto, no máximo uma por segundo, e se falhar o pedido
   segue sem endereço. **Privacidade (LGPD):** as coordenadas do embarque e do destino vão para o servidor do OpenStreetMap; entra na política de privacidade e na conversa com o advogado, e antes de abrir ao público
   o serviço de endereços também precisa de um provedor com contrato (`packages`: `apps/passenger/lib/address_lookup.dart`). **Com o mapa do Google o endereço escrito vem do Google, pelo servidor** (seção abaixo), e o Nominatim
   não é usado.
5. Os ladrilhos vêm da internet: sem sinal o mapa fica cinza (os pinos e o resto da tela funcionam).

Armadilhas já pagas (não repita): **(1)** enquadrar a câmera com `fitCamera` dentro do `onMapReady` deixa o mapa sem os ladrilhos do zoom novo (cinza, ou borrado) — a primeira imagem
já nasce enquadrada por `initialCameraFit` e só as mudanças seguintes usam `fitCamera`, depois do quadro atual; **(2)** `Place` precisa de igualdade por valor (o mapa compara os marcadores a cada reconstrução);
**(3)** objetos do mapa (`MapOptions`, `TileLayer`) nascem uma vez no `State`, nunca dentro do `build`.

Conferido no navegador sem janela (`mobile/tool/ui`): ruas aparecem, toque marca embarque e destino, câmera enquadra os dois, escuro inverte os ladrilhos.
**Não foi visto num celular de verdade.**

## Quanto custa o Google (levantado em 24/11/2026)

Preços lidos nas páginas oficiais do Google Maps Platform (`developers.google.com/maps/billing-and-pricing/pricing`), **sem** o crédito de US$ 200 por mês, que acabou em março de 2025:
cada tipo de uso tem a sua própria cota grátis por mês. Os números abaixo valem para o servidor como ele está hoje (rota de carro, sem trânsito em tempo real, que o Google cobra como **Essentials**).

| Uso | Cota grátis por mês | Depois da cota (por mil) |
|---|---|---|
| Rotas (`computeRoutes`, Essentials) | 10.000 | US$ 5,00 (US$ 4,00 acima de 100 mil) |
| Endereço escrito de um ponto (Geocoding) | 10.000 | US$ 5,00 (US$ 4,00 acima de 100 mil) |
| Mapa dentro do app (Maps SDK, Android/iOS) | sem limite | grátis (a confirmar na página de SKUs de mapas) |
| Busca de endereço digitado (Autocomplete, por sessão) | sem limite | grátis; a ficha do lugar escolhido é outro item, ainda não conferido |

**Atenção:** rota com trânsito em tempo real (`TRAFFIC_AWARE`) é **Pro** (US$ 10 por mil, 5 mil grátis); rota de moto (`TWO_WHEELER`) é **Enterprise** (US$ 15 por mil, 1 mil grátis).
Hoje o servidor usa `TRAFFIC_UNAWARE` + `DRIVE` (Essentials), então não pague a mais sem querer.

**Quantas chamadas por corrida** (o código, não a spec): a cotação chama o Google **uma vez** (`GoogleMaps.route`, com cache de 6 horas para pontos quase iguais) e o tempo de chegada só é pedido para a moto que está
terminando outra corrida. A spec de outubro supunha 7 cálculos por corrida; o código faz bem menos. Premissas deste cálculo (minhas, a calibrar com o teste fechado): **3 rotas por corrida** (cerca de 2,5 cotações
porque o passageiro muda de destino, mais uma parte para o tempo de chegada) e **4 endereços escritos por corrida** (embarque e destino, com um ou dois toques a mais no mapa), câmbio de R$ 5,40 por dólar.

| Corridas por mês | Rotas | Endereços | Total em US$ | Total em R$ | R$ por corrida |
|---|---|---|---|---|---|
| 300 (teste fechado) | 900 | 1.200 | 0 | 0 | 0 |
| 1.500 (cerca de 50 por dia) | 4.500 | 6.000 | 0 | 0 | 0 |
| 3.000 | 9.000 | 12.000 | 10 | 54 | 0,02 |
| 5.000 | 15.000 | 20.000 | 75 | 405 | 0,08 |
| 10.000 | 30.000 | 40.000 | 250 | 1.350 | 0,14 |
| 20.000 | 60.000 | 80.000 | 600 | 3.240 | 0,16 |

- O teto atual do servidor (`MAPS_DAILY_CALL_LIMIT`, 800 por dia ≈ 24 mil rotas por mês) custa no máximo **US$ 70 por mês** em rotas.
- Sem o Google nos endereços (se continuar o Nominatim/OpenStreetMap), tire a coluna "Endereços": rotas sozinhas ficam grátis até 3.300 corridas por mês e custam cerca de US$ 25 em 5.000.
- Em 20 mil corridas por mês o Google fica perto de **R$ 0,16 por corrida**, perto dos R$ 0,19 da spec (que supunha 7 rotas e sem endereços). A taxa da empresa de R$ 0,70 por corrida cobre isso, mas o Pix (R$ 0,50) e o Google juntos já a consomem.
- Faltam nesta conta: a ficha do lugar escolhido na busca de endereço (ainda não existe no app), o WhatsApp do código de login e a hospedagem.
- Os 4 endereços por corrida desta conta agora são de verdade: `GET /v1/passenger/address` (Geocoding Essentials, US$ 5 por mil depois dos 10 mil grátis), com cache de 24 h e teto `GEOCODE_DAILY_CALL_LIMIT`.
  O teto padrão (600 por dia = 18 mil por mês) custa no máximo **US$ 40 por mês**; para 1.500 corridas por mês (6.000 por mês, cerca de 200 por dia) pode ficar no padrão.

### Para o começo: cerca de 1.500 corridas por mês (volume informado pelo Levy em 24/11/2026)

- **Custo esperado: R$ 0.** Dá cerca de 4.500 rotas e 6.000 endereços por mês, abaixo dos 10 mil grátis de cada um. Passa a pagar só acima de **2.500 corridas por mês** (os endereços estouram primeiro; as rotas, em 3.300).
- **Se minhas premissas estiverem erradas:** com o dobro de chamadas (7 rotas e 8 endereços por corrida) fica em US$ 12,50 (cerca de R$ 68); com o triplo, US$ 65 (cerca de R$ 350).
- **Teto do servidor:** a média é de 150 rotas por dia. Sugestão: `MAPS_DAILY_CALL_LIMIT=500` no `.env` (pico de mais de 3 vezes a média), que limita o gasto com rotas a **US$ 25 por mês** mesmo se um passageiro (ou um erro) ficar pedindo cotação sem parar. O padrão do código (800) continua valendo se nada for definido.
- **Alerta de gasto no Google:** crie um de R$ 50 por mês (e não R$ 300, como está em `docs/instalacao.md`), para avisar logo se algo sair do previsto. O Google exige cartão no faturamento mesmo dentro da cota grátis.
