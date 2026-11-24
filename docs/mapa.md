# O mapa dos apps

Os dois apps desenham o mapa por trás de um único ponto (`corrida_ui`: `CorridaMapView` e `CorridaMapPicker`), que escolhe entre dois motores:

| Motor | O que é | Quando |
|---|---|---|
| `fake` | Desenho de mentira da cidade (ruas, avenidas, parque, rio). Sem internet, sempre igual. | Testes, `flutter run` e o navegador (`tool/web.sh`). Padrão fora do release. |
| `osm` | Ruas de verdade do OpenStreetMap, com os mesmos pinos e o trajeto. Mexe e dá zoom com os dedos; a câmera enquadra embarque e destino. | Padrão do app de **release**. Em qualquer build: `--dart-define=MAP=osm`. |

Escolha à mão: `flutter run --dart-define=MAP=osm` (ou `=fake`). O app do motoqueiro continua escolhendo o GPS por `--dart-define=GPS=real|fake`.

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
   (plano 7A). Os termos do Google proíbem usar os serviços deles num aplicativo que mostra mapa de outro fornecedor. Então: **teste fechado com
   `osm` = servidor sem a chave (estimativa em linha reta, que é o padrão)**; ao ligar a chave do Google, o app inteiro deve passar a mostrar o
   mapa do Google (`google_maps_flutter`, ainda não feito: precisa da chave e de um celular) — ou o servidor passar a usar rotas de um motor livre.
   Decisão do Levy quando for abrir ao público.
3. O trajeto desenhado é uma linha reta entre embarque e destino (não é a rota das ruas).
4. Sem busca de endereço (digitar para procurar): o passageiro toca no mapa ou usa "Estou aqui" (o servidor responde "fora da área de atendimento" se o ponto estiver longe de Santo Antônio de Jesus).
   Cada ponto marcado ganha o **endereço escrito** ("Rua Severo Vieira - São Cristóvão") pelo Nominatim, o serviço de endereços do OpenStreetMap: uma consulta por ponto, no máximo uma por segundo, e se falhar o pedido
   segue sem endereço. **Privacidade (LGPD):** as coordenadas do embarque e do destino vão para o servidor do OpenStreetMap; entra na política de privacidade e na conversa com o advogado, e antes de abrir ao público
   o serviço de endereços também precisa de um provedor com contrato (`packages`: `apps/passenger/lib/address_lookup.dart`).
5. Os ladrilhos vêm da internet: sem sinal o mapa fica cinza (os pinos e o resto da tela funcionam).

Armadilhas já pagas (não repita): **(1)** enquadrar a câmera com `fitCamera` dentro do `onMapReady` deixa o mapa sem os ladrilhos do zoom novo (cinza, ou borrado) — a primeira imagem
já nasce enquadrada por `initialCameraFit` e só as mudanças seguintes usam `fitCamera`, depois do quadro atual; **(2)** `Place` precisa de igualdade por valor (o mapa compara os marcadores a cada reconstrução);
**(3)** objetos do mapa (`MapOptions`, `TileLayer`) nascem uma vez no `State`, nunca dentro do `build`.

Conferido no navegador sem janela (`mobile/tool/ui`): ruas aparecem, toque marca embarque e destino, câmera enquadra os dois, escuro inverte os ladrilhos.
**Não foi visto num celular de verdade.**
