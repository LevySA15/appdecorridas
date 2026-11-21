# Nome, perfil e histórico de corridas do passageiro — desenho curto

Data: 21/11/2026. Aprovado pelo Levy em conversa ("pode ir", 21/11/2026) depois da proposta de fechar as telas que a spec
aprovada (seção 4, "Passageiro: … histórico · perfil") promete e que ainda não existem. Tamanho: mudança pequena, duas partes.

## Por quê

- A spec lista **histórico** e **perfil** entre as telas do passageiro; nenhum dos dois existe (nem a rota do histórico no servidor).
- **Achado novo:** o app do passageiro **nunca pergunta o nome**. `PUT /v1/me` e `AuthApi.updateName` existem, mas nenhuma tela os chama,
  então todo passageiro novo fica com `users.name = ""`. O motoqueiro recebe a corrida com `passenger: {name: ""}`, e o painel
  (alertas, recursos, passageiros) mostra nome vazio. Isso é um buraco de funcionamento, não de enfeite.
- O que eu tinha apontado como terceira lacuna (aviso de documento vencendo para o motoqueiro) **já existe**: a home do motoqueiro
  avisa 30 dias antes, com botão de renovar, e tem testes. Fica fora deste trabalho (erro meu na primeira proposta, corrigido).

## Objetivos

1. **Nome obrigatório antes de usar o app.** Quando o servidor diz que o passageiro não tem nome, o app mostra uma tela "Como podemos te
   chamar?" antes da Home e só segue depois de salvar. Vale também para contas que já existem com nome vazio (não depende de "é novo").
2. **Perfil:** tela com nome (editável), telefone (só leitura), contato de emergência (editável) e "Sair". O contato de emergência sai da
   tela da carteira e passa para o perfil; a carteira fica só com dinheiro.
3. **Histórico:** `GET /v1/passenger/rides?limit&offset` devolve as corridas **encerradas** do passageiro (concluída, cancelada, sem moto),
   da mais nova para a mais antiga. Tela "Minhas corridas" a partir da Home, com a lista e, ao tocar, o recibo da corrida.

## Fora do escopo

Filtros e busca no histórico, recibo em PDF ou compartilhável, histórico do motoqueiro (ele já tem o extrato do dia), trocar telefone,
foto de perfil, apagar conta/histórico (LGPD é conversa com o advogado), notificação, qualquer mudança em dinheiro ou estados da corrida.

## Não-objetivos que seriam falha

Mudar regra de pagamento, taxa, cancelamento ou estado de corrida; exigir o nome no **servidor** a ponto de quebrar quem já usa a API
(a trava é no app); migração de banco (nenhuma coluna nova: tudo que o histórico mostra já está gravado).

## Desenho

**Servidor** (sem migração)
- `GET /v1/passenger/state` ganha `name` (texto, vazio se ainda não definido) e `phone` (para o perfil mostrar o número). O app decide a
  tela do nome por `name`, sem chamada extra. (`phone` foi acrescentado ao escrever o plano: evita o perfil depender de outra chamada.)
- Salvar o nome e o contato: rotas que já existem (`PUT /v1/me`, `PUT /v1/passenger/emergency-contact`).
- `GET /v1/passenger/rides?limit=20&offset=0` (`limit` de 1 a 50): cada item traz `ride_id`, `state`, `created_at` (segundos), `price_cents`,
  `method` (`pix`, `cash` ou `balance`), `pickup_text`, `destination_text`, `distance_m`, `rider` (`name`, `plate`, `moto_model`, ou `null`
  se ninguém aceitou), `my_stars` (nota que o passageiro deu, ou `null`), `fee_cents` (taxa de cancelamento, 0 se não houve),
  `fee_refunded` (a taxa foi devolvida porque o recurso foi aceito), `payment_pending` (corrida em dinheiro concluída ainda não paga).
  A resposta é `{"rides": [...], "has_more": bool}`. Só corridas do próprio passageiro; só encerradas (a corrida aberta continua vindo do
  `state`). Consulta com índice em `rides(passenger_id, state)`.
- Contrato novo registrado em `docs/api-v1.md`.

**Apps** (`corrida_core` + app do passageiro)
- `PassengerState.name`; modelo `RideHistoryItem`; `PassengerApi.history(limit, offset)`; o contrato de `mobile/tool/contrato.sh` cobre a rota
  nova (a auditoria "toda chave que o servidor manda é lida pelo modelo" pega divergência).
- Telas "burras" (dados + callbacks), navegação toda em `app.dart`, como as outras: tela do nome (porta de entrada), `ProfileScreen`,
  `HistoryScreen` (lista paginada com "ver mais") e o recibo (uma tela simples). A Home ganha dois atalhos: "Minhas corridas" e "Perfil".
- O texto "Saldo / Carteira" e o "Sair" da Home continuam; "Sair" também aparece no perfil.

## Abordagens consideradas

1. **Nome:** (a) campo na tela de login; (b) tela própria antes da Home, ligada ao `state.name` vazio — **escolhida**: cobre quem já tem conta
   sem nome e não mexe no login, que é compartilhado com o app do motoqueiro. (c) exigir no servidor — descartada, quebraria clientes e testes
   que criam passageiro sem nome.
2. **Paginação do histórico:** (a) por cursor de data; (b) `limit`+`offset`, igual às listas do painel — **escolhida**: o histórico de uma
   pessoa é pequeno, e o padrão já existe.
3. **Onde fica o histórico:** (a) aba inferior; (b) atalhos na Home — **escolhida**: a Home é uma lista simples e não tem barra de abas;
   criar navegação por abas é mudança maior que o pedido.

## Decisões minhas (para o Levy conferir)

- O contato de emergência **muda de lugar** (carteira → perfil); o motivo é que ele é dado da pessoa, não dinheiro.
- O recibo mostra nome, placa e modelo da moto (o mesmo que o passageiro já vê na corrida), nunca CPF nem telefone do motoqueiro.
- Corrida cancelada ou sem moto aparece no histórico sem preço de corrida; se houve taxa de cancelamento, mostra a taxa.
- Nome de 2 a 120 letras (a regra que o servidor já tem).

## Fica para quem constrói

Textos exatos das telas, ordem dos campos do recibo, estados vazios ("você ainda não fez corridas"), testes de cada tela e do servidor
(TDD, como nos outros planos), e a conferência final com `flutter analyze`, as suítes do servidor e do Dart e o contrato.
