# Plano 6D — identidade visual, apps no navegador e testes de tela (rodada autônoma de 24/11/2026)

O Levy mandou: "continue o app de moto de forma autônoma, decida os melhores caminhos, abra o navegador para executar testes à vontade, e me dê o
máximo de desenvolvimento dentro de 5 horas". Não havia plano escrito antes: as decisões abaixo são minhas, para o Levy conferir.

## Ponto de partida

Os apps nunca tinham sido vistos numa tela de verdade (só testes de widget e um aparelho que o Levy conectou por USB para o login e o pedido).
Compilar os dois para a web e abrir num navegador foi a primeira vez que alguém olhou a aparência, e mostrou o que testes não mostram:

- **Os apps não tinham tema nenhum.** O vermelho `#D92D27` que o Levy escolheu em 09/10/2026 (spec, seção 11) nunca tinha sido aplicado: era o roxo
  padrão do Flutter. As telas eram listas de texto, sem mapa à vista, sem foto/ficha do motoqueiro, sem o código de 4 dígitos em destaque.
- Depois de pedir a corrida o app voltava para o início (a pessoa tinha de tocar em "Acompanhar corrida").
- A tela do Pix só tinha o texto do "copia e cola" (sem QR, sem botão de copiar) — e a spec manda o motoqueiro mostrar um QR no fim da corrida em dinheiro.
- Textos do sistema em inglês ("Back", "6 characters remaining"), distância com ponto ("3.3 km").
- Em celular pequeno, o início do motoqueiro estourava (botão dentro de `ListTile`) e a folha da cotação ficava mais alta que a tela.
- A dica "Toque para marcar…" cobria o alto do mapa e engolia o toque.

## O que entrou

**Identidade e telas** (`packages/corrida_ui`, nos dois apps)
- Tema claro/escuro (`corridaTheme`), cor de destaque só como fundo de botão/pino (regra de contraste da spec), campos preenchidos com o rótulo dentro.
- Peças novas: `SheetCard` (folha de baixo que rola e nunca passa de 80% da tela), `InfoPill`, `NoticeCard` (aviso com tarja vermelha, botão ao lado ou
  embaixo conforme a largura), `InitialsAvatar`, `PinDigits`.
- Mapa de mentira redesenhado (ruas, avenidas, parques, rio, pinos e trajeto; claro e escuro; recorta no próprio quadro).
- Passageiro: início com mapa e folha ("Pra onde vamos?" + atalhos Carteira/Corridas/Perfil), pedir corrida com cotação em folha e forma de pagamento em fichas,
  acompanhar com mapa + ficha do motoqueiro + código em destaque + preço/distância/forma, avaliar com estrelas legíveis, perfil, recibo sem linhas vazias.
- Motoqueiro: cartão grande "Estou rodando", oferta com fichas, extrato do dia em cartões, tela de espera/bloqueio com ícone, máscaras de CPF/data/placa/CNH.
- Tela do Pix com **QR code**, botão **Copiar código** e **Fechar** sempre à vista.
- Apps em **português do Brasil** (`flutter_localizations`), ícones de moto (passageiro: fundo vermelho; motoqueiro: fundo preto com moto vermelha), títulos da web.

**Navegador** (`docs/navegador.md`)
- `mobile/tool/web.sh build|up|down`: os dois apps em `localhost:8081/8082` contra um servidor descartável (`:8100`), com moldura de celular.
- Cenários em `mobile/tool/ui/` (navegador sem janela): corrida completa em dinheiro e em Pix com os **dois apps**, cancelamentos/SOS, carteira, histórico/recibo,
  perfil, cadastro do motoqueiro com as 3 fotos, internet caindo (pedir sem internet, abrir sem servidor, perder a conexão no meio da corrida), painel em todas as abas.
- Servidor: CORS só com `DEV_ROUTES` ligado (`localhost`/`127.0.0.1`), `scripts/sandbox_server.py --port`.

**Testes novos**
- Servidor: **matriz de autorização** (toda rota da API, lida do OpenAPI, exige login e cada prefixo recusa os outros papéis com 403; rota nova sem regra reprova),
  **IDOR** (corrida, cobrança e documentos de outro usuário), CORS de desenvolvimento, limite de cotações/pedidos, painel (rótulos, páginas), busca de passageiro.
- Apps: `telas_pequenas_test.dart` nos dois (celular 320x568, letra 1,5x, claro e escuro), Pix (QR, copiar), máscaras.

**Mapa de verdade e localização** (`docs/mapa.md`)
- Os apps desenham o mapa por `CorridaMapView`/`CorridaMapPicker`, que escolhem entre o desenho de mentira (testes, `flutter run`, navegador) e **as ruas de verdade do
  OpenStreetMap** (app de **release**, ou `--dart-define=MAP=osm`): toque marca embarque e destino, a câmera enquadra os dois, claro/escuro, atribuição "© OpenStreetMap".
- Passageiro: botão **"Estou aqui"** (posição do celular vira o embarque; permissão de localização pedida na hora; frases claras para GPS desligado/negado/sem sinal).
- Passageiro: o embarque e o destino ganham o **endereço escrito** (Nominatim, uma consulta por ponto): aparece na cotação ("De / Para"), na oferta do motoqueiro, no recibo e no painel; falha não trava o pedido.
- Motoqueiro: **miniatura do trajeto** na oferta (embarque e destino) para decidir antes de aceitar; a tela da corrida virou mapa por trás + folha de controles embaixo (como a do passageiro).
- Achado e corrigido no caminho (levou uma hora): o mapa de verdade ficava **cinza ou borrado** quando a câmera era enquadrada com `fitCamera` dentro do `onMapReady` (os ladrilhos do zoom novo
  não eram pedidos/pintados na web). Agora a primeira imagem já nasce enquadrada (`initialCameraFit`) e as mudanças seguintes enquadram no quadro seguinte. Também: `Place` ganhou igualdade por valor
  (o mapa comparava marcadores a cada reconstrução) e os objetos do mapa nascem uma vez no `State`. Detalhes em `docs/mapa.md`.
- **Limites:** ladrilhos do OSM e o serviço de endereços (as coordenadas vão para o OpenStreetMap: LGPD) só para teste fechado; **mapa do Google no servidor × mapa de outro fornecedor no app** (termos do Google) — ver `docs/mapa.md`.

**Servidor / painel**
- Avaliar uma corrida que não é sua responde 403 **antes** de olhar o estado (de fora não se descobre em que estado a corrida dos outros está).
- Busca de passageiros por telefone aceita o jeito que o dono copia ("(75) 99999-0001", "+55 75 …") e `%`/`_` deixam de ser coringa.
- **Limite por passageiro**: 20 cotações e 8 pedidos de corrida por minuto (429 `too_many_requests`). Cotar custa dinheiro (Google); isto não atrapalha quem usa de verdade.
- Painel: cores da marca, estados e formas de pagamento em português, resumo por estado em tabela (era JSON cru), páginas de 50 (Anterior/Próxima) em cadastros,
  corridas e passageiros, e no celular o menu vira uma faixa que rola e a tabela rola de lado (o botão "Detalhe" não some mais).

## Achados que não eram de tela

- O Chrome do dia a dia (o da extensão) **não deixa tirar foto quando está atrás de outra janela** (a captura espera um quadro que nunca vem); por isso os
  cenários usam o Chromium sem janela do Playwright.
- A corrida em dinheiro deixa o passageiro "bloqueado" assim que ela termina, antes de o motoqueiro tocar em "Recebi o dinheiro" (regra do servidor,
  `passenger_block_reason`). O app agora não repete o bloqueio quando já mostra o cartão do pagamento/taxa pendente. A regra em si ficou como está.

## Decisões minhas, para o Levy conferir

1. O vermelho da spec vale como identidade; o escuro acompanha a configuração do celular.
2. O início do passageiro perdeu o botão "Sair" (fica no Perfil). Durante a viagem some o "Cancelar" do passageiro (fica o SOS); antes da viagem continua.
3. Limites de 20 cotações e 8 pedidos por minuto (constantes em `app/api/routes/passenger.py`).
4. Dependências novas: `qr_flutter` (QR do Pix), `flutter_map` + `latlong2` (mapa), `geolocator` também no passageiro; `flutter_launcher_icons` só como ferramenta.
5. Mapa de verdade (OpenStreetMap) como padrão do release e desenho de mentira nos testes/depuração: é a única forma de o teste fechado mostrar a cidade sem a chave do Google; trocar é um parâmetro.
6. Ícone do motoqueiro preto com a moto vermelha, para não confundir os dois apps na tela do celular.

## Não feito (precisa do Levy ou do plano 7)

- ~~Mapa do **Google** dentro dos apps~~ — **feito depois, na mesma tarde** (terceiro motor `google` em `corrida_ui`, chave no manifesto do Android pelo Gradle, 21 testes com um Google de mentira;
  `docs/mapa.md`, seção "Mapa do Google nos apps"). **Falta ver com a chave de verdade num celular.** O endereço escrito pelo Google também foi feito (servidor, `GET /v1/passenger/address`). Continuam faltando: busca de endereço digitado (Places) e o trajeto pelas ruas (hoje é linha reta).
- Os apps **ainda não foram vistos num celular de verdade** depois destas mudanças (os dois APKs de depuração compilam); notificação com o app fechado (Firebase).
- Revisão independente (só autorrevisão) — a regra desta máquina não deixa chamar subagente sem o Levy pedir.
