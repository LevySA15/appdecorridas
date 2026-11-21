# Rotas reais do Google no servidor — desenho curto

Data: 21/11/2026. Aprovado pelo Levy em conversa ("pode", 21/11/2026) depois da proposta: só a parte do **servidor** agora; o mapa real
dentro dos apps fica para quando ele tiver a chave e o celular (não dá para ver um mapa renderizando nesta máquina). Tamanho: mudança pequena.

## Por quê

Hoje distância e tempo da corrida vêm de `FakeMaps` (linha reta × 1,3, a 8 m/s). Para um teste de campo em Santo Antônio de Jesus o preço
precisa sair da rua de verdade. Quem usa o mapa no servidor: `QuoteService` (`maps.route`, **uma chamada por cotação**: distância → preço,
tempo, e o traçado que o alerta de "fora da rota" usa) e `DispatchService` (`maps.eta_seconds`, só para a moto que está terminando outra
corrida, para a fila). O tempo de chegada mostrado na cotação já é uma estimativa própria e **não** passa pelo mapa.

## Objetivos

1. `GoogleMaps` (novo adaptador, `MapsProvider`: `route` e `eta_seconds`) usa a Routes API do Google (`directions/v2:computeRoutes`).
2. Liga sozinho quando `GOOGLE_MAPS_API_KEY` existe no `.env`/ambiente; sem chave tudo fica como hoje (`FakeMaps`).
3. **Nunca trava a corrida por causa do Google:** qualquer falha (rede, chave ruim, cota, resposta estranha, sem rota) cai na estimativa
   de hoje e vai para o registro. Depois de 3 falhas seguidas o servidor para de chamar o Google por 60 s (um Google fora do ar não pode
   somar 3 s a cada cotação).
4. **Teto diário de chamadas** (`MAPS_DAILY_CALL_LIMIT`, padrão 800 por dia ≈ 24 mil por mês ≈ US$ 70, dentro do orçamento de R$ 150–500):
   passou do teto, usa a estimativa até o dia seguinte (dia da Bahia). Cache evita pagar duas vezes pela mesma conta.

## Fora do escopo

Mapa dentro dos apps, busca de endereço (Places), GPS do passageiro, tempo de chegada da cotação pelo Google (dobraria o gasto: fica
como possível melhora), trânsito em tempo real, Pix e WhatsApp reais (planos à parte).

## Desenho

- Arquivo `server/app/adapters/google_maps.py`: `decode_polyline(encoded) -> tuple[GeoPoint, ...]` (algoritmo padrão, precisão 1e5) e `GoogleMaps`.
- `GoogleMaps(api_key, *, daily_limit=800, travel_mode="DRIVE", fallback=None, post=None, clock=time.time, timeout_s=3.0)`. `post` é um
  chamador injetável `post(url, headers, body, timeout_s) -> dict` (o padrão usa `urllib` da biblioteca padrão: **nenhuma dependência nova**);
  os testes injetam respostas gravadas. A chave vai só no cabeçalho `X-Goog-Api-Key` e nunca aparece no registro.
- Pedido: `POST https://routes.googleapis.com/directions/v2:computeRoutes`, cabeçalho `X-Goog-FieldMask:
  routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline`, corpo com `origin`/`destination` (`location.latLng`), `travelMode`,
  `routingPreference: TRAFFIC_UNAWARE`, `units: METRIC`. Resposta lida: `routes[0].distanceMeters`, `routes[0].duration` (texto `"123s"`),
  `routes[0].polyline.encodedPolyline`.
- Cache só de resposta boa do Google, na memória do processo: rota por 6 h, tempo de chegada por 2 min; chave = coordenadas arredondadas a
  4 casas (~11 m); no máximo 2000 entradas (sai a mais antiga). Estimativa de reserva **não** entra no cache (quando o Google volta, volta já).
- Contador do dia na memória do processo, só de chamadas reais (não conta cache nem reserva). É proteção de gasto, não contabilidade: um
  reinício do servidor zera o contador.
- `Settings`: `google_maps_api_key: str | None = None`, `maps_daily_call_limit: int = 800` (inteiro ≥ 1, senão erro claro ao ligar),
  `maps_travel_mode: str = "DRIVE"` (`DRIVE` ou `TWO_WHEELER`, senão erro claro). `build_runtime` escolhe `GoogleMaps` ou `FakeMaps`.
- Documentação: passo opcional "Mapa de verdade" em `docs/instalacao.md` (criar a chave, só a Routes API, restringir, alerta de orçamento) e as
  linhas no `app.env.example`.

## Abordagens consideradas

1. **Cliente HTTP:** (a) `httpx`/`requests` como dependência nova; (b) `urllib` da biblioteca padrão com um chamador injetável — **escolhida**
   (zero dependência nova, e o teste troca só o chamador).
2. **Quando o Google falha:** (a) a cotação falha com erro; (b) cai na estimativa de hoje — **escolhida**: o passageiro nunca fica sem
   conseguir pedir moto por causa de um serviço de fora; o custo é o preço sair menos preciso nesses momentos (o registro diz quando).
3. **Teto de chamadas:** (a) contador no Redis; (b) na memória do processo — **escolhida**: o serviço roda em um processo só e o teto é para
   conter surpresa de fatura, não para contar centavo.

## Decisões minhas (para o Levy conferir)

- Modo de viagem padrão `DRIVE`: não confirmei que o Google calcula `TWO_WHEELER` (moto) no Brasil. Dá para testar trocando
  `MAPS_TRAVEL_MODE=TWO_WHEELER` quando houver a chave; se o Google recusar, o servidor cai na estimativa e avisa no registro.
- Teto padrão 800 chamadas por dia, tempo máximo de espera de 3 s por chamada, 3 falhas seguidas = pausa de 60 s. São constantes
  fáceis de mudar.
- A rota do Google vale como "rota esperada" do alerta de fora da rota (hoje é um traço reto): é o efeito esperado e desejado.

## Fica para quem constrói

Nomes internos, mensagens do registro, e os testes (resposta boa, polilinha conhecida do Google, sem rota, erro HTTP, chave ruim, resposta
torta, cache, teto, pausa depois de falhas, chave nunca no registro).
