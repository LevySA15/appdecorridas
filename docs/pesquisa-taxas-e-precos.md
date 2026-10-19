# Como os outros aplicativos calculam taxa de cancelamento, "sem sinal" e preço da corrida

Pesquisa de 19/10/2026, a pedido do Levy, para trocar as regras provisórias do plano 4B (taxa de cancelamento) e do 4C (tempo sem sinal) e conferir o preço da corrida. **Quase tudo que achei é de 2019 a 2022**: Uber e 99 não publicam tabela atual na internet (as páginas oficiais da 99 responderam "muitas requisições" e a da Uber não abriu). Trate os números como ordem de grandeza, não como regra vigente.

## 1. Taxa de cancelamento

O que os dois grandes fazem:

| | Uber | 99 |
|---|---|---|
| Janela sem cobrança | 2 minutos depois de confirmada a corrida (regra de 2020) | de 2 a 4 minutos, conforme a fonte; remetem aos Termos de Uso de cada cidade |
| O que dispara a taxa | o motorista **fez progresso** em direção ao passageiro | o motorista andou **0,3 km ou 1 minuto** (matéria de jan/2022) |
| Como é calculada | **tempo e distância** que o motorista já percorreu; não é valor fixo | R$ 5 (matéria de jan/2022) |
| Mínimo e máximo | R$ 5 e R$ 20 (carro, 2020) | R$ 5 |
| Quando **não** cobra | se o motorista não está indo até o passageiro | se o motorista está parado ou indo no sentido contrário; se o motorista cancela |
| Passageiro não aparece | taxa depois de 5 minutos de espera no ponto | taxa se demora demais no embarque |
| Aviso | o app mostra o valor **antes** de confirmar o cancelamento | o app mostra depois se houve cobrança |

inDrive: não achei regra publicada. Moto (Uber Moto e 99Moto): não achei taxa de cancelamento própria.

**O que o nosso app faz hoje** (plano 4B): janela de 5 minutos do aceite da moto (mais generosa que as deles); depois dela, R$ 3 a R$ 5 conforme a fração do caminho até o ponto que a moto já andou; moto no ponto = R$ 5; avisa o valor antes de confirmar (igual à Uber).

**A diferença que importa:** Uber e 99 **não cobram se o motorista não se mexeu**. Hoje o nosso app cobra R$ 3 mesmo com a moto parada, e cobra R$ 5 de uma moto que só andou 400 m (porque conta a fração do caminho, não os metros).

### Proposta para a conta (A)

1. Janela grátis de 5 minutos do aceite (decisão do Levy, vira parâmetro).
2. Depois dela, a taxa depende dos **metros que a moto andou** em direção ao passageiro:
   - menos de **300 m** andados (o mesmo corte da 99): **R$ 0,00**;
   - a partir de 300 m: **R$ 3,00**, subindo em linha reta até **R$ 5,00** com **1,5 km** andados, em passos de R$ 0,10;
   - moto no ponto de embarque, ou passageiro que não aparece em 5 minutos: **R$ 5,00**.
3. Sem posição recente da moto: R$ 3,00 (a favor do motoqueiro, que já estava vindo há mais de 5 minutos; hoje já é assim).
4. Os números 300 m, 1,5 km e R$ 3 a R$ 5 viram parâmetros no painel.

Efeito: passageiro não paga por moto parada; moto que andou pouco paga o mínimo; quem andou o caminho todo recebe o máximo.

## 2. "Muito tempo sem sinal"

Não existe número público. O que achei:

- A Uber tem o **U-Ajuda / RideCheck** (no Brasil desde 2020): detecta **parada longa e inesperada** e desvio de rota usando o GPS e os sensores do celular. Ao detectar, **pergunta ao motorista e ao passageiro "está tudo bem?"**; quem responde que sim encerra o alerta; quem precisa pode ligar para a emergência ou compartilhar a viagem. A Uber **não publica o tempo** que dispara o alerta.
- Aplicativos de trabalhador isolado (lone worker) usam **temporizador de check-in** que o cliente configura; o exemplo que achei usa 120 minutos, escala que não serve para corrida de moto.

Conclusão: **os 2 / 4 / 6 minutos (corrida até 3 km / de 3 a 10 km / acima) continuam sendo palpite**, sem fonte para confirmar nem derrubar. Proposta:

1. Manter a tabela no lançamento.
2. Nas primeiras semanas de uso de verdade, olhar quanto tempo normalmente se passa entre duas posições da mesma corrida (o servidor já guarda) e regular o tempo um pouco acima do normal; os tempos já são parâmetros no painel.
3. Ideia tirada do modelo da Uber, se o Levy quiser: **avisar primeiro o passageiro** ("está tudo bem?") e só chamar o contato de emergência se ele não responder em 1 a 2 minutos. Hoje o aviso vai ao passageiro e ao contato ao mesmo tempo.

## 3. Preço da corrida

Estrutura da Uber: **tarifa base + valor por minuto + valor por km**, vezes um multiplicador de demanda, com **corrida mínima**. Exemplo da Uber X em São Paulo (matéria antiga, vários anos): base R$ 2,00 + R$ 1,40 por km + R$ 0,26 por minuto, mínimo R$ 7,00.

O nosso (spec, seção 6): base **R$ 3,00 + R$ 1,50 por km**, **mínimo R$ 5,00**, multiplicador de **0,8 a 1,6** conforme pedidos por moto livre (muda em passos de 0,1), arredondado a R$ 0,50. Sem valor por minuto.

| Distância | Preço normal (fator 1,0) |
|---|---|
| 1 km | R$ 5,00 (mínimo) |
| 2 km | R$ 6,00 |
| 3 km | R$ 7,50 |
| 5 km | R$ 10,50 |
| 8 km | R$ 15,00 |

Diferenças e o que achei:

- **Valor por minuto:** os apps grandes cobram porque o trânsito pesa para o carro. Moto em cidade pequena quase não tem esse problema, e o tempo de espera já é tratado pela taxa de 5 minutos no ponto. Não recomendo mexer agora.
- **Referência de preço:** a página da Uber para Santo Antônio de Jesus mostra "viagem de 8 minutos ≈ R$ 6" (Uber Moto) e "10 minutos ≈ R$ 7" (carro). Uma viagem de 8 minutos de moto dá uns 3 km, que no nosso app custa R$ 7,50, cerca de 25% mais. **Pouca confiança nesse número**: a mesma página diz que a Uber não oferece mototáxi na cidade.
- **Preço dos mototaxistas locais: não achei.** É a referência que decide; só se descobre perguntando. Tabela para o Levy preencher com 3 a 5 mototaxistas de Santo Antônio de Jesus:

| Trajeto | Mototáxi A | Mototáxi B | Mototáxi C | Nosso app |
|---|---|---|---|---|
| uns 1 km (ex.: do centro à rodoviária) | | | | R$ 5,00 |
| uns 2 km | | | | R$ 6,00 |
| uns 4 km | | | | R$ 9,00 |
| uns 7 km | | | | R$ 13,50 |

- **Regra municipal:** um resumo da busca indica que a **Lei 929/2008 de Santo Antônio de Jesus** regula o mototáxi e diz que a **tarifa é fixada por decreto do prefeito**, com base nos custos da atividade. Não consegui abrir o texto da lei nem achei o decreto. Isso **contradiz** a pergunta 1 do advogado (a prefeitura teria dito que não há lei) e pode importar para o preço dinâmico do app. Entrou nas perguntas do advogado.

## Fontes

- Uber, taxa de cancelamento (2 min, mínimo R$ 5, máximo R$ 20, tempo e distância): <https://olhardigital.com.br/noticia/uber-muda-regras-sobre-taxa-de-cancelando-e-valor-maximo-sobe-para-r/107553>
- Uber, espera e cancelamento: <https://tecnoblog.net/noticias/uber-avisa-regras-taxa-espera-cancelamento/> e <https://tecnoblog.net/noticias/uber-muda-regras-de-taxa-de-cancelamento-no-brasil/>
- 99, R$ 5 com 0,3 km ou 1 minuto: <https://garagem360.com.br/o-carro-nao-vem-o-passo-a-passo-para-cancelar-uma-corrida-da-99>
- 99, regras gerais (resumo da busca; página oficial não abriu): <https://99app.com/blog/passageiro/passageiro-saiba-como-funciona-a-taxa-de-cancelamento-99/>
- Uber U-Ajuda / RideCheck: <https://www.uber.com/pt-BR/newsroom/uber-lanca-ferramenta-para-identificar-paradas-inesperadas-ou-longas> e <https://tecnoblog.net/noticias/uber-usa-celular-detectar-paradas-inesperadas-acidentes/>
- Estrutura do preço da Uber e exemplo de São Paulo: <https://tecnoblog.net/188610/taxi-ou-uber-preco-qual-mais-barato/> e <https://olhardigital.com.br/2023/04/26/dicas-e-tutoriais/uber-entenda-como-o-preco-da-corrida-e-calculado/>
- Uber em Santo Antônio de Jesus (preço médio): <https://www.uber.com/br/pt-br/r/cities/taxi/moto-taxi/santo-antonio-de-jesus-ba-br/>
- Lei municipal 929/2008 (mototáxi, só o resumo da busca): <https://leismunicipais.com.br/a/ba/s/santo-antonio-de-jesus/lei-ordinaria/2008/93/929/lei-ordinaria-n-929-2008-dispoe-sobre-a-prestacao-de-servico-publico-de-transporte-individual-de-passageiros-ou-de-cargas-por-meio-de-motocicletas-denominado-moto-taxi-no-ambito-do-municipio-de-santo-antonio-de-jesus-e-da-outras-providencias>
- Check-in de trabalhador isolado (CheckedSafe): <https://www.checkedsafe.com/resources/lone-worker-app-user-guide/>
