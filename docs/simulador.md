# Simulador

Motoqueiros e passageiros **de mentira** que andam por Santo Antônio de Jesus e usam o servidor pela API, exatamente como os apps de verdade vão usar. Serve para três coisas:

1. ver o servidor funcionando com muita gente ao mesmo tempo;
2. achar defeito antes de ter gente de verdade: toda rodada termina com um veredito, "Tudo certo" ou a lista do que deu errado;
3. deixar o servidor com movimento para o painel e os apps mostrarem.

Nada aqui é de verdade: não há dinheiro, WhatsApp nem mapa. As pessoas de mentira têm nome terminado em "(sim)", e os telefones ficam numa faixa só delas (`75 98100-xxxx` para passageiros, `75 98200-xxxx` para motoqueiros).

## Rodar sozinho (recomendado): `demo`

A partir da pasta `server/`:

    .venv/bin/python -m simulator demo --fast
    .venv/bin/python -m simulator demo --fast --riders 30 --passengers 90 --minutes 5

O `demo` sobe um servidor **descartável** (um esquema só dele no banco, o Redis número 14 e uma pasta temporária de fotos), cria as pessoas, solta todo mundo, mostra uma linha de situação a cada 10 segundos e, no fim, imprime o relatório, grava uma cópia em `server/var/sim/relatorio-AAAAMMDD-HHMMSS.md` e **apaga tudo**: não encosta nos seus dados de desenvolvimento. Rode um `demo` por vez (ele usa sempre o Redis número 14).

`--fast` encurta os prazos do servidor descartável (o Pix vence em 40 s, a procura desiste em 45 s, a oferta vale 8 s, o aviso de parada vem em 40 s, o passageiro que não paga o dinheiro é bloqueado em 45 s) e deixa as pessoas mais rápidas e as motos até 4 vezes mais rápidas (no máximo 108 km/h: acima de 140 km/h o servidor desconfia de localização falsa). Em poucos minutos aparecem Pix vencido, passageiro bloqueado, aviso de segurança e SOS. Sem `--fast`, os prazos são os de verdade e a rodada anda no ritmo real.

## Rodar contra o servidor que está no ar: `run`

    .venv/bin/python -m app.cli create-admin --phone "75 99999-0000" --name "Levy"       # uma vez
    .venv/bin/uvicorn --factory app.main:create_default_app --port 8000                  # em outro terminal
    .venv/bin/python -m simulator run --admin-phone "75 99999-0000" --riders 10 --passengers 30 --minutes 10

**Depois de reiniciar o servidor de desenvolvimento, o `run` reprova:** o Pix falso recomeça a numeração (`ch-1`, `ch-2`...) e a conferência final compara com o histórico antigo do banco. Use o `demo`, ou recomece o banco de desenvolvimento antes.

As pessoas de mentira ficam gravadas no banco desse servidor (procure os nomes com "(sim)"). Os códigos de login delas são pedidos uma vez e os tokens ficam em `server/var/sim/pessoas.json`, que só você lê e o git ignora; da segunda rodada em diante ninguém pede código de novo (o servidor limita a 100 pedidos por hora por aparelho; com mais de 90 pessoas, a primeira rodada precisa esperar a hora virar).

## Opções

| Opção | Para que serve | Padrão |
|---|---|---|
| `--riders N` / `--passengers N` | quantos motoqueiros e passageiros | 8 e 16 |
| `--minutes N` | quanto tempo a rodada pede corridas novas (depois ela espera as abertas terminarem) | 10 |
| `--profile` | `calmo` (tudo certo), `normal` ou `bagunca` (toque duplo, código errado, parada longa, desvio de rota, SOS, Pix atrasado, QR sem pagar, conexão que cai) | `normal` |
| `--seed N` | repete a mesma "personalidade" das pessoas (a hora exata das coisas muda, porque o servidor é de verdade) | 1 |
| `--speed N` | multiplica a velocidade das motos, de 1 a 4 (o teto é 108 km/h) | 1 |
| `--pace N` | multiplica as esperas das pessoas (`0.2` = cinco vezes mais depressa) | 1 |
| `--max-rides N` | para depois de N pedidos | sem limite |
| `--city-scale N` | encolhe a cidade (`0.2` = viagens bem curtas) | 1 |
| `--fast` (só `demo`) | prazos curtos no servidor e gente mais rápida | desligado |
| `--out PASTA` | onde gravar o relatório | `server/var/sim` |

Sai com código 0 se deu tudo certo, 1 se achou problema e 2 se nem conseguiu começar (por exemplo, servidor fora do ar). Ctrl+C interrompe e, no `demo`, apaga o servidor descartável.

## Como ler o relatório

- **Corridas:** quantas foram pedidas e como cada uma terminou (concluída, cancelada pelo passageiro, sem moto, Pix vencido...).
- **Tempos:** da procura até alguém aceitar, do aceite até a moto chegar, e da saída até o fim.
- **Dinheiro:** corridas e valores por forma de pagamento, e os preços mostrados (o preço sobe quando falta moto livre).
- **O que as pessoas fizeram:** a contagem dos comportamentos (oferta recusada, código errado, SOS, QR pago...).
- **Suspeitas de localização falsa:** aparece só se o servidor avisou o administrador. O simulador não falsifica nada, então isso quase sempre quer dizer moto rápida demais para o intervalo entre as posições; não reprova a rodada.
- **Chamadas à API:** por rota, quantas vezes, quantos erros e o tempo (mediana, 90% e máximo). "Erros" aqui inclui erros normais, como uma oferta que venceu antes do toque.
- **Respostas inesperadas do servidor:** o que **não** devia ter acontecido (erro 500, falta de resposta, erro que o simulador não esperava). Se tiver qualquer linha aqui, a rodada reprova.
- **Conferência final do servidor:** o livro-caixa fecha e bate com o extrato do provedor falso, ninguém ficou com duas corridas ao mesmo tempo e nenhuma corrida ficou aberta.
- **Veredito:** "Tudo certo" ou a lista numerada de problemas.

## O que o simulador não faz

- Não testa app nenhum (tela, GPS de verdade, notificação com o app fechado).
- O mapa é falso: a moto anda em linha reta, e a rua é 30% mais longa que a reta só para o preço.
- Pix, WhatsApp e o contato de emergência são falsos até o plano 7.
- Não derruba o banco nem o Redis no meio da rodada, e não testa mais de um processo do servidor.
- O aviso de "muito tempo sem sinal" ainda não existe no servidor (item aberto do plano 2C), então não há o que simular.

## Medidas de referência (18/10/2026)

Computador do Levy (8 núcleos, 7 GB), servidor e simulador na mesma máquina, sem mais nada rodando. Rodada de
`demo --riders 60 --passengers 200 --minutes 3 --speed 4 --pace 0.7 --seed 8` (cerca de 35 corridas por minuto), repetida quatro vezes:
135 a 141 corridas pedidas, 123 a 131 concluídas, de 16.860 a 22.559 chamadas à API por rodada, nenhuma resposta inesperada e o
livro-caixa fechado em todas.

| Rota | Mediana | 90% | Máximo |
|---|---|---|---|
| estado do passageiro (`GET /v1/passenger/state`) | 18 a 20 ms | 146 a 389 ms | 3,4 a 4,0 s |
| estado do motoqueiro | 15 a 17 ms | 54 a 82 ms | cerca de 3,2 s |
| posição do motoqueiro | 9 a 10 ms | 23 a 40 ms | 1,8 a 2,2 s |
| preço da corrida | 20 a 23 ms | 38 a 63 ms | 0,25 a 0,46 s |
| pedir corrida | 44 a 47 ms | 74 a 126 ms | 0,24 a 0,78 s |
| aceitar oferta | 33 a 37 ms | 71 a 130 ms | 0,32 a 0,80 s |
| terminar corrida | 29 a 30 ms | 60 a 82 ms | 0,20 a 0,45 s |

O máximo vem do começo da rodada, quando todo mundo entra de uma vez. O pool de conexões do banco (10+10) não virou fila nessa carga:
duas das quatro rodadas usaram 30+20 e o resultado não se distingue do de 10+10. **Meça sempre com o computador parado:** com os
testes rodando ao mesmo tempo, a mesma rodada chegou a 785 ms no 90% do estado do passageiro.
