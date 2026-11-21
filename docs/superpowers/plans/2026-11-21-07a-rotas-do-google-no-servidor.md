# Rotas reais do Google no servidor — plano de implementação

> **Para quem executa:** use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans, tarefa por tarefa.
> Os passos usam caixas `- [ ]`.

**Objetivo:** com `GOOGLE_MAPS_API_KEY` no `.env`, o servidor calcula distância, tempo e traçado das corridas pela Routes API do Google; sem
chave, ou quando o Google falha, tudo continua como hoje.

**Arquitetura:** um adaptador novo `GoogleMaps` (`MapsProvider`: `route` e `eta_seconds`) em `server/app/adapters/google_maps.py`, com cache,
teto diário de chamadas, pausa depois de falhas seguidas e reserva na estimativa de `FakeMaps`. `build_runtime` escolhe o adaptador pelas
configurações. Nenhum serviço, rota, tabela ou app muda.

**Tecnologias:** Python 3.12, biblioteca padrão (`urllib`, `logging`), pytest. **Nenhuma dependência nova.**

**Desenho:** `docs/superpowers/specs/2026-11-21-mapa-real-no-servidor-design.md`

## Restrições globais

- Textos de registro (log) e erros de configuração em português, no estilo do resto do servidor.
- A chave da API só vai no cabeçalho `X-Goog-Api-Key`; **nunca** em URL, mensagem de erro ou registro.
- `GoogleMaps` nunca levanta exceção para quem chama (`QuoteService`, `DispatchService`): qualquer falha devolve a estimativa de reserva.
- Sem chave, o comportamento é idêntico ao de hoje (`FakeMaps`); os testes existentes e o simulador não mudam.
- O teste `tests/deploy/test_arquivos_de_instalacao.py` exige que as **chaves** de `server/deploy/app.env.example` sejam exatamente o conjunto
  `CHAVES`: as linhas novas do modelo ficam **comentadas** (`# GOOGLE_MAPS_API_KEY=...`).
- Cada tarefa termina com os testes dela verdes e um commit em português terminando com
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Rodadas de pytest uma de cada vez (mesmo Redis db 15); `free -m` antes das longas.

## Foco da revisão

1. O Google responde 200 mas sem rota (`{}`, `routes: []`, ponto fora de estrada): vira estimativa, sem exceção (Tarefa 1).
2. A chave nunca aparece no registro, nem quando a chamada falha com erro que cita o endereço (Tarefa 1).
3. Google fora do ar: depois de 3 falhas seguidas, as cotações seguintes **não** esperam 3 s cada uma (Tarefa 2).
4. O contador diário vira à meia-noite da Bahia (UTC−3), não à meia-noite UTC (Tarefa 2).
5. Configuração torta: teto `0` ou `abc`, modo `BICYCLE`, chave só com espaços — erro claro ou "sem chave", nunca um servidor que sobe quebrado (Tarefa 3).

---

### Task 1: `GoogleMaps` — chamada, leitura da resposta e reserva

**Arquivos:**
- Criar: `server/app/adapters/google_maps.py`
- Criar: `server/tests/adapters/test_google_maps.py`

**Interfaces:**
- Consome: `app.domain.maps.Route(distance_m: int, duration_s: int, points: tuple[GeoPoint, ...])`, `MapsProvider`, `app.adapters.fake_maps.FakeMaps`
  (`route`, `eta_seconds`), `app.domain.geo.GeoPoint(lat, lng)`.
- Produz: `ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"`;
  `Post = Callable[[str, dict[str, str], dict, float], dict]` (url, cabeçalhos, corpo JSON, tempo máximo em segundos → resposta JSON já lida);
  `decode_polyline(encoded: str) -> tuple[GeoPoint, ...]`; `urllib_post(url, headers, body, timeout_s) -> dict`;
  `class GoogleMaps(api_key: str, *, travel_mode: str = "DRIVE", fallback: MapsProvider | None = None, post: Post | None = None,
  clock: Callable[[], float] = time.time, timeout_s: float = 3.0)` com `route(origin, destination) -> Route` e `eta_seconds(origin, destination) -> int`.
  (A Tarefa 2 acrescenta parâmetros ao construtor; todos com padrão.)

- [ ] **Passo 1: testes que falham** em `test_google_maps.py`. Apoio: `class Post` que guarda `calls` (url, headers, body, timeout_s de cada chamada)
  e devolve (ou levanta, se for `Exception`) as respostas dadas, repetindo a última; `BOA = {"routes": [{"distanceMeters": 2310, "duration": "412s",
  "polyline": {"encodedPolyline": CODIFICADA}}]}` com `CODIFICADA` = a polilinha do exemplo do Google (abaixo); `ORIGEM = GeoPoint(-12.9644, -39.2597)`,
  `DESTINO = GeoPoint(-12.9500, -39.2500)`; `def maps(post, **kw): return GoogleMaps("chave-secreta", post=post, **kw)`. Testes:
  - `test_decode_polyline_do_exemplo_do_google`: `decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")` arredondado a 5 casas é
    `[(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]`; `decode_polyline("") == ()`.
  - `test_rota_boa_vira_route_com_distancia_tempo_e_tracado`: `route == Route(2310, 412, decode_polyline(CODIFICADA))`.
  - `test_pedido_vai_com_chave_no_cabecalho_mascara_de_campos_e_corpo_certo`: uma chamada; `url == ROUTES_URL`; `headers["X-Goog-Api-Key"] == "chave-secreta"`;
    `headers["X-Goog-FieldMask"] == "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"`; `body["origin"]["location"]["latLng"] ==
    {"latitude": ORIGEM.lat, "longitude": ORIGEM.lng}` (e o destino igual); `body["travelMode"] == "DRIVE"`; `body["routingPreference"] == "TRAFFIC_UNAWARE"`;
    `timeout_s == 3.0`. Com `travel_mode="TWO_WHEELER"` o corpo leva `"TWO_WHEELER"`.
  - `test_duracao_com_fracao_arredonda`: `"90.6s"` → `duration_s == 91`.
  - `test_sem_polilinha_o_tracado_e_origem_e_destino`: resposta sem `polyline` → `points == (ORIGEM, DESTINO)`.
  - `test_eta_usa_so_a_duracao`: `eta_seconds(...) == 412`; o `X-Goog-FieldMask` dessa chamada é `"routes.duration"`.
  - `test_resposta_sem_rota_cai_na_estimativa` (parametrizado: `{}`, `{"routes": []}`, `{"routes": [{}]}`, `{"routes": [{"distanceMeters": "abc", "duration": "1s"}]}`,
    `{"routes": [{"distanceMeters": 100, "duration": "rapido"}]}`, `["lixo"]`): `route(...) == FakeMaps().route(ORIGEM, DESTINO)` e
    `eta_seconds(...) == FakeMaps().eta_seconds(ORIGEM, DESTINO)`; nenhuma exceção.
  - `test_erro_na_chamada_cai_na_estimativa_e_a_chave_nao_vai_para_o_registro` (com `caplog`, nível WARNING): `post` levanta `OSError("sem rede")`; o resultado é a
    estimativa; `"chave-secreta" not in caplog.text`; o registro tem "Google Maps" e "estimativa".
  - `test_post_padrao_fala_http_de_verdade_com_um_servidor_local`: sobe `http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)` numa thread; o `Handler`
    responde JSON `{"chave": <cabeçalho X-Goog-Api-Key>, "corpo": <JSON recebido>}` em `POST /ok` e status 403 em `POST /nega`; `urllib_post` com a URL de `/ok`
    devolve esse dicionário (com o corpo que enviou) e com `/nega` levanta `urllib.error.HTTPError`.
- [ ] **Passo 2:** `cd server && .venv/bin/pytest tests/adapters/test_google_maps.py -q` → falham (módulo inexistente).
- [ ] **Passo 3:** implementar `google_maps.py` como as Interfaces dizem. `decode_polyline`: algoritmo padrão do Google (blocos de 5 bits, deslocamentos
  acumulados, precisão 1e5). Leitura da resposta: `routes[0]`; `distanceMeters` precisa ser número finito positivo (senão a resposta é recusada), `duration`
  é texto `"<número>s"` (`int(round(float(texto[:-1])))`; outro formato recusa); polilinha ausente ou vazia → `(origem, destino)`. Qualquer recusa ou exceção
  (`Exception`, inclusive do `post`) → `logging.getLogger("app.google_maps").warning("Google Maps falhou (%s); usei a estimativa.", <tipo da exceção ou motivo>)`
  e devolve `fallback.route`/`fallback.eta_seconds` (`fallback` padrão = `FakeMaps()`). O registro leva o **tipo** da exceção e o motivo, nunca cabeçalhos.
  `urllib_post`: `urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"}, method="POST")`,
  `urlopen(..., timeout=timeout_s)`, `json.loads` da resposta.
- [ ] **Passo 4:** repetir o passo 2 → passam. `.venv/bin/pytest tests/adapters -q` → verde.
- [ ] **Passo 5:** commit `feat(servidor): adaptador de rotas do Google com reserva na estimativa`.

---

### Task 2: cache, teto diário e pausa depois de falhas

**Arquivos:**
- Modificar: `server/app/adapters/google_maps.py`, `server/tests/adapters/test_google_maps.py`

**Interfaces:**
- Consome (Tarefa 1): `GoogleMaps`, `Post`, o apoio de teste `Post`/`maps`/`BOA`/`ORIGEM`/`DESTINO`; `app.domain.clock.local_date(epoch_s) -> date` (dia da Bahia).
- Produz: o construtor ganha `daily_limit: int = 800`, `route_ttl_s: float = 21_600.0`, `eta_ttl_s: float = 120.0`, `cache_size: int = 2000`,
  `failures_before_pause: int = 3`, `pause_s: float = 60.0`. Comportamento: (a) cache de resposta **boa** do Google, uma tabela por tipo (rota, tempo), chave =
  `(round(lat, 4), round(lng, 4))` da origem e do destino, vence depois de `route_ttl_s`/`eta_ttl_s` e guarda no máximo `cache_size` entradas (sai a mais antiga);
  (b) contador de chamadas enviadas no dia da Bahia (`local_date(clock())`): ao chegar em `daily_limit` as chamadas seguintes do mesmo dia nem saem e devolvem a estimativa
  (um aviso no registro por dia); (c) `failures_before_pause` falhas seguidas pausam as chamadas por `pause_s` (devolvem a estimativa sem chamar); uma resposta boa zera a contagem.

- [ ] **Passo 1: testes que falham** (mesmo arquivo; relógio manual `class Relogio` com `now` e `advance(s)`; `post` com `BOA`):
  - `test_mesma_rota_duas_vezes_chama_o_google_uma_vez`; e uma origem que difere só na 5ª casa decimal (`ORIGEM.lat + 0.00001`) também acerta o cache; uma que difere na 4ª não.
  - `test_cache_da_rota_vence_depois_de_6_horas_e_o_do_tempo_depois_de_2_minutos`: `advance(21_599)` ainda acerta, `advance(2)` depois chama de novo; `eta_seconds` idem com 119 s / 2 s.
  - `test_cache_guarda_no_maximo_cache_size_entradas`: `cache_size=2`, três rotas distintas, voltar à primeira chama o Google de novo.
  - `test_estimativa_de_reserva_nao_entra_no_cache`: 1ª chamada falha (`OSError`), 2ª resposta boa → a 2ª devolve a rota do Google (não a estimativa) e fez 2 chamadas.
  - `test_teto_diario_para_de_chamar_e_volta_no_dia_seguinte_da_bahia`: `daily_limit=2`, três rotas distintas no mesmo dia → `len(post.calls) == 2` e a 3ª é a estimativa; um registro WARNING sobre o teto
    (e só um mesmo com mais chamadas barradas); acertos de cache não contam. Relógio em 23:59 da Bahia (`datetime(2026, 11, 20, 23, 59, tzinfo=LOCAL_TZ).timestamp()`), avançar 2 min (00:01 do dia 21) →
    volta a chamar; o mesmo avanço **sem** cruzar a meia-noite da Bahia (começando às 20:00) não zera. (Foco 4.)
  - `test_chamada_que_falha_conta_para_o_teto`.
  - `test_tres_falhas_seguidas_pausam_o_google_por_60_segundos`: `post` sempre `OSError`; 3 chamadas distintas → 3 chamadas ao `post`; a 4ª e a 5ª **não** chamam (`len(post.calls) == 3`) e devolvem a estimativa;
    `advance(61)` → tenta de novo (4ª chamada ao `post`). (Foco 3.)
  - `test_resposta_boa_no_meio_zera_a_contagem_de_falhas`: falha, falha, boa, falha, falha → continua chamando (nenhuma pausa).
- [ ] **Passo 2:** `cd server && .venv/bin/pytest tests/adapters/test_google_maps.py -q` → os novos falham.
- [ ] **Passo 3:** implementar (estruturas simples: `dict` ordenado por inserção para o cache com remoção da primeira chave; contador `(dia, n)`; `falhas_seguidas` e `pausado_ate`). Tudo atrás de um
  `threading.Lock` (o servidor atende pedidos em várias threads). Ordem em cada chamada: cache → pausa → teto → chamada; chamada enviada conta no teto mesmo se falhar.
- [ ] **Passo 4:** repetir o passo 2 → tudo passa.
- [ ] **Passo 5:** commit `feat(servidor): cache, teto diário e pausa do Google Maps`.

---

### Task 3: configuração, escolha do adaptador e guia

**Arquivos:**
- Modificar: `server/app/settings.py`, `server/app/runtime.py`, `server/deploy/app.env.example`, `docs/instalacao.md`
- Testes: `server/tests/test_settings.py`, `server/tests/test_runtime_maps.py` (novo), `server/tests/deploy/test_arquivos_de_instalacao.py`, `server/tests/deploy/test_guia.py`

**Interfaces:**
- Consome (Tarefa 2): `GoogleMaps(api_key, daily_limit=, travel_mode=)`, `FakeMaps`.
- Produz: `Settings.google_maps_api_key: str | None = None`, `Settings.maps_daily_call_limit: int = 800`, `Settings.maps_travel_mode: str = "DRIVE"`;
  `load_settings` lê `GOOGLE_MAPS_API_KEY` (texto só com espaços = sem chave; guarda sem as pontas), `MAPS_DAILY_CALL_LIMIT` (inteiro ≥ 1; senão
  `RuntimeError("MAPS_DAILY_CALL_LIMIT deve ser um número inteiro maior que zero (veio 'abc')")`) e `MAPS_TRAVEL_MODE` (`DRIVE` ou `TWO_WHEELER`, sem diferenciar
  maiúscula; senão `RuntimeError` citando `MAPS_TRAVEL_MODE`); `build_maps(settings: Settings) -> MapsProvider` em `runtime.py` (`GoogleMaps` com chave; senão `FakeMaps()`),
  usado por `build_runtime` no lugar do `FakeMaps()` fixo. Registro INFO ao escolher ("Mapa: rotas do Google (…)" / "Mapa: estimativa em linha reta (sem GOOGLE_MAPS_API_KEY)"),
  sem a chave.

- [ ] **Passo 1: testes que falham.**
  - `test_settings.py`: sem as variáveis, `google_maps_api_key is None`, `maps_daily_call_limit == 800`, `maps_travel_mode == "DRIVE"`; com `GOOGLE_MAPS_API_KEY=abc`,
    `MAPS_DAILY_CALL_LIMIT=300`, `MAPS_TRAVEL_MODE=two_wheeler` lê `("abc", 300, "TWO_WHEELER")`; parametrizado, `MAPS_DAILY_CALL_LIMIT` em `["0", "-5", "abc", "1.5"]` e
    `MAPS_TRAVEL_MODE=BICYCLE` levantam `RuntimeError` citando o nome da variável; `GOOGLE_MAPS_API_KEY="   "` vira `None`. (Foco 5.)
  - `test_runtime_maps.py`: `build_maps(Settings(database_url="x", redis_url="y"))` é `FakeMaps`; com `google_maps_api_key="k", maps_daily_call_limit=5, maps_travel_mode="TWO_WHEELER"`
    é `GoogleMaps` e o corpo do primeiro pedido (injetando um `post` por atributo público `post` do adaptador, ou checando os atributos `daily_limit` e `travel_mode`)
    leva `TWO_WHEELER` e o teto vale 5; o registro INFO não contém `"k"` como chave (use uma chave longa como `"CHAVE-SECRETA-123"` e confira que não aparece em `caplog.text`).
  - `test_arquivos_de_instalacao.py`: `set(parse_env_file(app.env.example)) == CHAVES` continua valendo e o **texto** do modelo cita `# GOOGLE_MAPS_API_KEY=`, `# MAPS_DAILY_CALL_LIMIT=`
    e `# MAPS_TRAVEL_MODE=`; `load_settings` do modelo continua aceito.
  - `test_guia.py`: o guia cita `GOOGLE_MAPS_API_KEY`, `Routes API`, `MAPS_DAILY_CALL_LIMIT` e `TWO_WHEELER`.
- [ ] **Passo 2:** `cd server && .venv/bin/pytest tests/test_settings.py tests/test_runtime_maps.py tests/deploy -q` → os novos falham.
- [ ] **Passo 3:** implementar em `settings.py` e `runtime.py` (`build_maps` ao lado de `build_runtime`; deixar o atributo `daily_limit`/`travel_mode`/`post` públicos no `GoogleMaps`).
- [ ] **Passo 4:** `server/deploy/app.env.example`: bloco comentado depois do `UPLOAD_DIR` explicando em 3-4 linhas e com `# GOOGLE_MAPS_API_KEY=`, `# MAPS_DAILY_CALL_LIMIT=800`,
  `# MAPS_TRAVEL_MODE=DRIVE`. `docs/instalacao.md`: **Passo 12. (Opcional) Mapa de verdade** (depois do Passo 11, antes de "Onde fica cada coisa"), em português simples, numerado:
  criar um projeto no Google Cloud; ligar só a **Routes API**; criar uma chave de API e restringi-la à Routes API e ao IP do servidor; colocar um alerta de orçamento (por exemplo R$ 300); colar a chave em
  `/etc/app-corrida/app.env` como `GOOGLE_MAPS_API_KEY=...` e `systemctl restart app-corrida`; conferir no registro (`journalctl -u app-corrida`) a linha "Mapa: rotas do Google"; explicar o teto diário
  (`MAPS_DAILY_CALL_LIMIT`, padrão 800 ≈ US$ 70 por mês) e que, se o Google falhar, o preço sai pela estimativa; e que `MAPS_TRAVEL_MODE=TWO_WHEELER` é o modo moto, ainda a testar no Brasil
  (se o Google recusar, o servidor avisa no registro e usa a estimativa).
- [ ] **Passo 5:** repetir o passo 2 → passam; depois `.venv/bin/pytest tests -q -x --ignore=tests/sim` → verde.
- [ ] **Passo 6:** commit `feat(servidor): liga as rotas do Google pela chave no .env; guia do mapa de verdade`.

---

### Task 4: verificação final e roteiro

**Arquivos:**
- Modificar: `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md` (linha nova **7A** na tabela, logo antes da linha do plano 7, e a seção "Itens que sobraram do plano 7A" antes de "Itens que sobraram do plano 3")

- [ ] **Passo 1:** `free -m`; `cd server && .venv/bin/pytest tests -q --ignore=tests/sim` (uma rodada, em primeiro plano). Esperado: tudo verde. (O simulador não roda esta mudança: usa `FakeMaps` por construção; se
  `git diff` mostrar mudança fora de `adapters/google_maps.py`, `settings.py`, `runtime.py`, `deploy/`, `docs/`, rodar `tests/sim` também, sozinho.)
- [ ] **Passo 2:** conferir à mão, sem chave, que o servidor sobe como antes: `cd server && .venv/bin/python -c "from app.settings import load_settings; from app.runtime import build_maps; print(type(build_maps(load_settings())).__name__)"` → `FakeMaps`.
- [ ] **Passo 3:** escrever no roteiro: o que foi feito; suítes e contagens; **não conferido contra o Google de verdade** (sem chave; formato do pedido e da resposta é o da documentação da Routes API v2);
  decisões (modo `DRIVE`, teto 800/dia, 3 s, 3 falhas = pausa de 60 s, cache 6 h/2 min); o que não foi feito (mapa nos apps, busca de endereço, tempo de chegada da cotação pelo Google,
  GPS do passageiro, trânsito); e a observação de custo: o servidor chama o mapa **uma vez por cotação**, bem menos que os ~7 cálculos por corrida da spec (seção 10.3), porque o tempo de chegada mostrado
  na cotação é estimativa própria.
- [ ] **Passo 4:** commit `docs: roteiro do plano 7A (rotas do Google no servidor)`.
