# Troca Premium — mecânica, economia e a estratégia de fazer PP

Levantado em 2026-08-17. Origem: o usuário observou que jogadores alternam entre
um mundo dedicado a vender recursos por Pontos Premium e o mundo seguinte jogado
a sério, e que isso só compensa no início do mundo.

Duas fontes independentes: medições diretas no servidor br143 (sessão do bot e
`interface.php`) e transcrições de 9 vídeos de YouTube extraídas pelo usuário
(legenda automática — os números vêm corrompidos, ver a seção de ressalvas).

**Nada disto está implementado.** O gap de código está no fim, e virou Feature 34
no `backlog.md`.

---

## 1. A mecânica, medida no servidor

`interface.php?func=get_config` → bloco `<premium>` da br143 traz
`PremiumExchange = 1` e `MerchantExchange = 1`: a troca existe neste mundo.
(Endpoint público, sem autenticação.)

A tela `game.php?village=<id>&screen=market&mode=exchange` embute
`PremiumExchange.receiveData({...})`, que `Extractor.premium_data()` já lê. Resposta
real de 2026-08-17, aldeia 41123 (K35):

```
stock    = wood 270112 / stone 280799 / iron 261012
capacity  = idênticos ao stock  -> bolsa 100% cheia
rates     = ~0,00122 PP por unidade de recurso
tax       = {buy: 0.03, sell: 0}
duration  = 7200 (2h)     merchants = 164
```

**A taxa é** `preço_marginal = resource_base_price - resource_price_elasticity *
estoque / (capacidade + stock_size_modifier)`, em PP por unidade. Na br143:
`0,015 - 0,0148 * estoque/(capacidade + 20000)`. É a mesma fórmula que
`PremiumExchange.calculate_marginal_price()` já implementa — foi portada do JS do
jogo pelo upstream e **confere com o servidor**.

Fatos de mecânica confirmados (suporte oficial pt-BR + tutorial oficial em vídeo):

- **Uma bolsa por continente.** As 8 aldeias da conta atual estão todas em K35,
  ou seja, uma bolsa só, sem diversificação.
- **Estoque cheio = venda bloqueada.** *"Quando o estoque de uma troca está cheio,
  nenhum recurso desse tipo pode mais ser vendido para ela."* É o estado atual do
  K35.
- **Entrega em 2h**, usando os mercadores da própria aldeia. Comprar usa os
  mercadores da bolsa.
- **Continentes adjacentes rebalanceiam capacidade e estoque diariamente.**
- **PP servem em qualquer mundo do mesmo mercado, mas não em outro mercado** (br
  continua br). É isto que faz a estratégia de alternar mundos funcionar — não é
  contorno, é desenho: o tutorial oficial diz literalmente *"podem começar um
  Mundo com o único propósito de fazer pilhagens premium para ajudar no Mundo
  atual ou em próximos Mundos"*.
- **PP obtidos na troca não são transferíveis para outra conta.** A wiki EN fala
  em 60 dias, o suporte pt-BR fala em nunca; um dos vídeos mostra a tela
  distinguindo PP transferível de intransferível por idade de aquisição, o que
  favorece a leitura dos 60 dias. **Não resolvido, e irrelevante para uso
  próprio.**

## 2. A economia: por que a janela é o início do mundo

O piso da taxa (estoque 100%) depende da **capacidade da bolsa**, que cresce com a
região. Não existe um "pior caso" universal:

| capacidade | recursos por 1 PP, estoque cheio |
|---|---|
| 100 mil | 375 |
| 270 mil (K35 hoje) | 819 |
| 1 milhão | 2.040 |
| 2 milhões | 2.886 |

Com a bolsa **vazia** a taxa é `1/0,015 = 66,7` recursos por PP, independente da
capacidade. Ou seja: entre a abertura do mundo e a saturação, o custo de 1 PP
multiplica por 12 no K35 e por 30+ num continente grande.

**Aferição cruzada:** um vídeo mostra o mundo 107 (velho, venda bloqueada) onde
1 PP comprava 2129 de madeira. Invertendo a fórmula, isso implica capacidade de
~1,08 milhão — plausível e consistente. A fórmula prevê corretamente um mundo que
nunca observamos.

**Correção de um erro anterior:** numa primeira análise eu tratei "12×" como
número geral. É específico da capacidade do K35.

## 3. A estratégia, segundo os vídeos

Três canais distintos convergem no mesmo método. Resumo consolidado:

**Construção**
- Dias 1–4: **só lanceiros**. Fazenda e armazém *apenas o suficiente* — o armazém
  dimensionado pelas horas offline (ex.: 12h dormindo × produção/hora), nunca mais.
- **Nada de minas** nos primeiros ~15 dias. Recurso vem da coleta, não da produção.
  (Contraintuitivo, e afirmado por dois canais independentes.)
- Dia 5, últimas 24h de proteção: **esconderijo 10, muralha 10**.
- Fase de venda: **armazém 20–23, mercado 17–21**.
- Alvo de tropa: **2.000 lanceiros + 500–600 espadachins**, atingido por volta do
  dia 9 (mundo velocidade 2) ou 13–15 (velocidade 1). Mais que 2.000 lanceiros é
  desperdício.
- Uma aldeia. Não nobla. A mesma tropa coleta e defende — 2.000 lanceiros tornam
  a aldeia cara demais para valer a pena noblar.

**Recurso vem de coleta, não de farm.** Argumento repetido: no início do mundo as
bárbaras estão esgotadas e cheias de *spikes* (defesa escondida em bárbara), então
cada cavalaria leve perdida custa ~450 recursos com retorno quase nulo. Coleta é
lucro sem risco. 2.000 lanceiros nas 4 opções de coleta 24h ≈ **120 mil
recursos/dia** (40k de cada) — número batido por dois canais.

**Cronograma de taxas** (média por fase do mundo, do canal TW BOT):

| fase | taxa média (recursos por PP) |
|---|---|
| dias 1–8 | 64–79 |
| fase seguinte de venda | ~90 |
| blocos de ~15 dias seguintes | ~280, depois ~590, depois ~890 |
| a partir de ~2 meses | venda deixa de compensar |

O estoque da bolsa leva **40–45 dias** para lotar (fonte de 2016), e o dev do
TW BOT diz que a dificuldade de vender *"geralmente acontece no segundo mês"*.
Duas fontes, 5 anos de distância, mesma janela.

**Rendimento declarado**, por conta única:
- ~10 mil PP nos 8 primeiros dias de venda (960k de recursos à taxa média 90).
- 20–22 mil PP em 2 meses só com coleta.
- +~10 mil PP com arbitragem (abaixo) → ~30 mil PP em 40–50 dias.
- Aferição independente: 4.325 PP em uma semana com uma aldeia de 488 pontos.

**Como vendem — as duas regras que importam:**

1. **Lotes pequenos.** A taxa piora dentro da própria venda: *"vendam de 1K em 1K…
   6.000 não vale 6× o que vale 1.000, porque a taxa já é atualizada antes de você
   vender"*. Isto é exatamente a integral que `PremiumExchange.calculate_cost()`
   já modela — a matemática que temos descreve o fenômeno que eles descobriram na
   mão.
2. **Limiar de taxa.** Configura-se "vender quando a taxa for X ou menor" e
   espera-se a queda, em vez de despejar. A automação deles checa o mercado 5–10×
   por segundo para pegar os vales. Regra automática usada: vender à média −15%,
   comprar à média +60%. Ajuste manual: se recurso começar a acumular sem vender,
   sobe um pouco o limiar.

**O gargalo é o mercador, não a produção.** Explícito em duas fontes e no tutorial
oficial: com poucos mercadores, uma boa taxa aparece e não há como despachar. É a
razão de mercado 17–21.

**A parte mais lucrativa é arbitrar, não vender.** Comprar com a taxa alta e
revender com a taxa baixa, no mesmo dia. Exemplo: 300k de recursos comprados à
taxa média 800 custam 375 PP; revendidos à taxa média 425 rendem 705 PP →
**330 PP/dia de lucro**, que *soma* ao rendimento da coleta. Variante geográfica
(vídeo de 2025): comprar num continente e vender no vizinho, já que as bolsas são
independentes. Variante de 2020: fundar a aldeia na **beirada do mapa**, em
continente pouco povoado, onde a bolsa satura mais devagar.

**Conta premium não é pré-requisito.** Há teste grátis de conta premium ao atingir
500 pontos. Dois vídeos recomendam gastar os primeiros PP em Reforço de Recursos
(+20%, 150 PP/30 dias) e Assistente de Saque, argumentando que se pagam sozinhos.

## 4. A tese contrária, e por que ela não é ruído

Um dos canais (2016) argumenta para **não** vender no início: aldeia parada em ~98
pontos só vendendo vira alvo assim que a proteção acaba, e quem farma 200–400k/dia
ganha mais construindo do que vendendo. Não é incompatível com o resto — é a
diferença entre "mundo descartável só para PP" e "jogar sério com PP de apoio",
que são exatamente as duas modalidades que o usuário descreveu ao levantar o tema.

## 5. Confirmação em campo: a aldeia BBM 002

A `BBM 002` (38409) foi conquistada de um jogador que estava exatamente nesta
estratégia. Reconstruído a partir dos logs (`TWB_BUILD`) e confirmado pelo usuário:

- Ao entrar sob gestão do bot em 2026-08-07: **armazém 29, mercado 21**, com
  principal 3, muralha 4, ferreiro 0, estábulo 0, quartel 3, poços 9/8/10.
- O mercado foi demolido manualmente pelo usuário de 21 → 14 para caber no teto
  do template `watchtower_support` (mercado 10). O armazém 29 nunca foi tocado.

Mercado 21 e armazém 29 estão no topo exato da faixa que os vídeos recomendam
(17–21 e 20–23) e batem com o tutorial oficial: *"se decidirem fazer experiências
com o mercado, podem subir mais o nível de algumas coisas do que seria normal: o
Mercado e o Armazém."* Principal 3 / ferreiro 0 / estábulo 0 é o outro lado da
mesma moeda: nada de militar.

## 6. Ressalvas sobre as fontes

- **As transcrições são de legenda automática.** Números saem corrompidos
  ("6479" para "64 a 79", "2011" para "20 mil"). Onde possível, cada número foi
  cruzado com a fórmula medida no servidor em vez de aceito do texto.
- **Multi-conta permeia o material.** Dois vídeos falam abertamente em criar
  contas descartáveis para alimentar a bolsa. Isso é banível e contamina os
  números — parte do "20k PP" pode pressupor várias contas. O método do TW BOT é
  o único explicitamente **por conta única** ("com base no lucro de uma única
  conta"), e é o que dá para replicar limpo.
- **Divergência não resolvida: 64 vs 66.** Duas fontes independentes afirmam que
  a taxa mínima do jogo é **64** recursos por PP, inclusive com estoque zerado.
  A fórmula com as constantes da br143 dá **66** (`1/0,015 = 66,7`, e 66 pela
  `calculate_rate_for_one_point`). Note que `1/64 = 0,015625` — é possível que
  outros mundos usem esse `resource_base_price`, ou que exista um piso separado.
  Diferença de 3%, não muda decisão nenhuma. **Custa um acesso à tela da bolsa na
  abertura do próximo mundo para resolver.**
- **Não lidas:** P2-04 (aparenta ser a versão 2019 do mesmo vídeo do canal do
  P2-03), P2-06, e as três de início de mundo (P5-*), que não tratam de PP.
  Lista completa e transcrições em `Desktop/ytdownloader/` (fora do repositório).

## 6b. O mundo novo é o br144, e o ruleset já está publicado

Levantado em 2026-08-20. **Correção de premissa:** eu tinha assumido que br144 já
rodava e que o mundo novo seria o br145. Errado — `br145` ainda redireciona para
o portal, e `br144` **está provisionado mas ainda não abriu**:

> `/page/settings` do br144: **Início 27/ago./2026 (09:30)**

Conferido contra os vizinhos na mesma leitura: br142 começou 22/abr, br143
(o mundo em jogo hoje) 16/jun. Ou seja, `interface.php?func=get_config` e
`/page/settings` respondem para um mundo **antes** da abertura — todo o ruleset
está disponível com uma semana de antecedência, de graça e sem autenticação.

⚠️ O usuário falou em "dia 26"; a página do jogo diz **27/ago 09:30**. Um dia
importa quando a tese inteira é que os dias 1–8 são a janela mais valiosa.

Regras do br144 que mudam decisão (todas de `/page/settings` + `get_config`):

| parâmetro | br144 | por que importa |
|---|---|---|
| Velocidade do jogo | **2** | é o caso "2.000 lanceiros por volta do dia 9" dos vídeos |
| Velocidade das unidades | 0.5 | |
| Fator de produção | 1 | com `base_production` 30, mina nível 0 ainda rende |
| **Arqueiros** | **Ativo** | br143 é Inativo — `resolve_troop_template` vai pedir a variante `_archer` |
| **Coletando (scavenging)** | **Ativo** | é o motor de renda da estratégia inteira |
| Proteção a novatos | **5 dias** | bate com "dia 5, últimas 24h: esconderijo 10, muralha 10" |
| Moral | Baseado em pontos | |
| Limite de ataque falso | 1% dos pontos | |
| Aumento de lealdade/hora | **2** | br143 é 1 — confirma que isso é por mundo |
| PremiumExchange | **1** | a bolsa existe |
| Conta premium grátis | em **500** e 15.000 pontos | o teste grátis que os vídeos citam |

Duas medições que resolvem perguntas antigas:

- **`base_production = 30`** (bloco `<game>`). Mina em nível 0 **não** produz
  zero, então "nada de minas nos primeiros 15 dias" é sobrevivível — não é o
  suicídio econômico que parecia. Ressalva honesta: não confirmei se a
  velocidade do mundo multiplica esse número.
- **Capacidade da fazenda = `round(240 * 1,1721^(nível-1))`**, ajustada contra
  **duas aldeias reais do br143 no mesmo dia**: fazenda 15 → pop_max 2216
  (fórmula: 2217) e fazenda 26 → 12715 (exato). Não veio de wiki.

## 7. O gap do nosso código

`ResourceManager.do_premium_stuff()` (`game/resources.py`) é código do upstream
(commits de 2021 e 2023), **nunca exercitado nesta conta** — `world.trade_for_premium`
e o mesmo campo nas 8 aldeias estão `false`, e nenhum log em `cache/logs` menciona
premium. Distância entre o que existe e o que a estratégia exige:

1. **Bug de cálculo.** `resources.py:202` faz `prices[p] = stock[p] * rates[p]`.
   Isso não é preço: é o valor em PP do estoque inteiro da bolsa (~330 PP no K35).
   O preço é `1/rates[p]` (~819). Rodando o código real contra os dados reais de
   2026-08-17, o `optimize_n` devolve `n_to_sell: 0` e o guard `ratio > 0.4`
   aborta com "Not worth trading" — não venderia nada, e não por prudência.
   O filtro anterior (`prices[gpl] * 1.1 < self.actual[gpl]`) vira, com esse
   valor, "tenho mais de ~363 de madeira?", que é sempre verdade.
2. **Não existe limiar de taxa.** É a regra central da estratégia (vender quando
   a taxa cair abaixo de X) e não há config nem código para ela.
3. **Não existe lote de venda configurável.** A "oferta" pequena é o que evita
   afundar a própria taxa. Nossa matemática (`calculate_cost`) já modela o efeito,
   mas nada o controla.
4. **O bot nunca compra** — `# twb never buys on premium exchange`, com
   `tax["buy"]` desativado no cálculo. A metade mais lucrativa (arbitragem) está
   arquitetonicamente fora.
5. **`n_to_sell: 0` não é checado** antes do envio; só o `ratio` impede o envio
   vazio, por acaso.
6. **Nunca validado em pt-BR.** `exchange_begin`/`exchange_confirm` e o formato
   `result["response"][0]["rate_hash"]` são suposição do upstream. Mesmo perfil da
   Feature 9, onde o caminho de envio inteiro estava errado e nunca tinha sido
   exercitado.

## 8. O que foi feito em 2026-08-20 (Feature 34, primeira metade)

Os itens 1, 2, 3 e 5 acima estão **fechados**; o 4 (compra/arbitragem) segue
fora de propósito, e o 6 (validação em pt-BR) **não dá para fechar antes do
dia 27** — ver o porquê no fim.

**`ResourceManager.do_premium_stuff()` reescrito** (`game/resources.py`):

- **O preço agora é `calculate_rate_for_one_point()`** (recursos por PP), não
  `stock * rates`. Era isso que zerava o `n_to_sell` e abortava com "Not worth
  trading" — uma recusa que parecia prudência e era erro de conta.
- **Limiar de taxa** (`premium_exchange.max_rate_per_point`, padrão 90): só
  vende enquanto a bolsa pedir no máximo X recursos por PP. É a regra central
  da estratégia, e não existia nem como config.
- **Lote configurável** (`sell_batch`, padrão 1000) e **piso de lote**
  (`min_sell_batch`): cada lote relê a bolsa em vez de assumir a taxa do
  anterior, porque a taxa piora dentro da própria venda. O piso existe porque
  um mercador carrega 1000 e leva 2h de ida e volta — despachar 200 nele
  desperdiça 80% do recurso que esta mesma pesquisa identificou como gargalo.
- **Os três recursos**, não só o mais abundante. O gate anterior era
  `get_plenty_off()`, que responde *"que recurso está transbordando o
  armazém?"* — pergunta certa para o mercado normal e errada aqui. Terceiro
  padrão do CLAUDE.md: função certa, uso errado.
- **Bolsa cheia é checada por recurso** (`capacity - stock <= 0`), que é
  exatamente o estado do K35 hoje e a razão de o bot não poder nem tentar.
- **Reserva respeitada**: nunca vende o que `requested` já prometeu a
  construção/recrutamento, nem abaixo do piso `keep_wood/stone/iron`.

**Guardas no caminho de envio.** `get_api_action()` devolve **três** coisas
diferentes — o JSON, o objeto `Response` cru quando o corpo não é JSON, ou
`None` em falha de rede — e a versão anterior fazia
`result["response"][0]["rate_hash"]` direto, o que era `TypeError` em dois dos
três casos. Agora `_premium_extract_rate_hash()` aceita as formas plausíveis
(lista, dict, hash na raiz) e, quando não acha, **despeja a resposta crua em
`cache/premium/`** — para o diagnóstico do dia 1 custar um arquivo e não um
ciclo perdido.

**Testes:** `tests/test_premium_exchange.py`, com os números da bolsa lidos do
br143 em 2026-08-20 (bolsa 100% cheia, o estado real). Cobre bolsa cheia,
bolsa vazia na taxa de piso, limiar bloqueando, reserva, piso de lote,
`premium_keep` por instância (primeiro padrão) e as oito formas de retorno do
`exchange_begin`.

**Smoke de leitura contra o servidor**, depois dos testes passarem
(`cache/_smoke_premium.py`, sétimo padrão): lê a bolsa de verdade com os
cabeçalhos do próprio wrapper e imprime a decisão, sem nunca chamar o envio.
Rodado em 41123: taxa 773/796/754, espaço 0 nos três, decisão "não vender".

### O que continua aberto, e por quê

⚠️ **`exchange_begin`/`exchange_confirm` seguem NÃO validados em pt-BR.** A
bolsa do K35 está 100% cheia nos três recursos (remedido em 2026-08-20: 0 de
espaço), então **não existe forma de exercitar uma venda real antes do dia
27**. Todo o resto do caminho está testado; o formato do `rate_hash` é a única
peça que continua sendo suposição herdada do upstream. É o mesmo perfil da
Feature 9, cujo caminho de envio inteiro estava errado por nunca ter rodado —
e lá foram três erros distintos numa tacada só. **Planejar supervisão humana
no primeiro envio real.**

Detalhe medido de passagem: a capacidade da bolsa **encolheu duas vezes no
mesmo dia** (madeira 257.683 às 10h → 256.087 às 12h; era 270.112 em 17/08).
O rebalanceamento diário entre continentes adjacentes é real e mensurável —
número de bolsa vale pelo dia em que foi lido.
