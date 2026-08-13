# Torre de Vigia (watchtower) — levantamento

Levantamento feito em 2026-08-13. Números da wiki/suporte **cruzados contra o
servidor br143**, seguindo a regra do projeto de não aceitar número de mundo
vindo só da comunidade (ver `CLAUDE.md`, quinto padrão de bug).

**Fontes consultadas:**
- [Watchtower — Tribalwars Wiki EN](https://help.tribalwars.net/wiki/Watchtower) — tabela completa custo/pop/raio
- [O que é uma Torre de Vigia? — Suporte InnoGames pt_BR](https://support.innogames.com/kb/TribalWars/pt_BR/1819) — faixas de tamanho de ataque, mesma tabela em pt
- [Torre de Vigia — Tribalwars Wiki BR](https://help.tribalwars.com.br/wiki/Torre_de_Vigia) — múltiplas torres, destruição por catapulta, ícone de olho
- [Watchtower — Suporte InnoGames en_DK](https://support.innogames.com/kb/TribalWars/en_DK/5306)
- [Points (Totals)](https://help.tribalwars.net/wiki/Points_(Totals)), [Farm](https://help.tribalwars.net/wiki/Farm), [Warehouse](https://help.tribalwars.net/wiki/Warehouse) — wiki EN
- Servidor br143: `interface.php?func=get_building_info`, `interface.php?func=get_config`, `/page/settings`

---

## 1. Estado no br143

A feature está **ativa** no mundo, confirmada pelos dois lados do servidor
(a lição do quinto padrão: `get_config` e `/page/settings` não expõem o mesmo
conjunto de campos, então cita-se onde se procurou):

| Fonte | Evidência |
|---|---|
| `get_config` → `<game>` | `<watchtower>1</watchtower>` (e `<church>0</church>`) |
| `/page/settings` | "Igreja: Inativo — **Torre de vigia: Ativo**" |
| `get_config` → `<buildings>` | `<custom_watchtower>-1</custom_watchtower>` — sem teto customizado, vale o máximo padrão 20 |
| `get_config` → `<build>` | `<destroy>1</destroy>` — demolição permitida, a torre não é irreversível |
| `get_building_info` → `<watchtower>` | `max_level=20 min_level=0`, base `12000/14000/10000`, `pop=500`, fatores `1.17/1.17/1.18`, `pop_factor=1.18`, `build_time=13200`, `build_time_factor=1.2` |

**Nenhuma aldeia gerenciada tem torre.** O bot já lê o nível (chave
`buidling_levels.watchtower` — sim, com o typo — em `cache/managed/*.json`) e o
valor é `0` nas sete aldeias, snapshot de 2026-08-13:

```
BBM 001  pts=6021  main=20  farm=26  watchtower=0
BBM 002  pts=1997  main=11  farm=15  watchtower=0
BBM 003  pts=693   main=11  farm=11  watchtower=0
BBM 004  pts=497   main=10  farm=9   watchtower=0
BBM 005  pts=634   main=10  farm=10  watchtower=0
BBM 006  pts=391   main=10  farm=9   watchtower=0
BBM 007  pts=453   main=11  farm=10  watchtower=0
```

Nenhum template em `templates/builder/` menciona `watchtower`, e não há chave
`watchtower` em `config.json` nem em `config.example.json`.

## 2. Mecânica

- Marca **todo ataque que entra no raio** com (a) tamanho do exército e (b) se
  leva nobre — independentemente de qual aldeia é o alvo final. Vale inclusive
  para ataques que apenas **atravessam** o raio a caminho de outro lugar.
- As marcas **persistem** mesmo depois de o ataque sair do raio.
- Faixas de tamanho: **pequeno 1–1000**, **médio 1001–5000**, **grande >5000** tropas.
- Ícone de **olho** ao lado do comando = "este ataque será marcado quando entrar
  no raio". Sem o olho, não será marcado.
- Marcas aparecem na visão geral da aldeia; com Premium, também na tela de Chegadas.
- Quantas torres quiser por conta. **Catapultas destroem.**
- Raio desenhado no mapa (navegador); no mobile, tela `watchtower`.

Limitações que importam para automação:

- Só ataques enviados **depois** de a torre existir são garantidamente marcados.
- Aldeia recém-conquistada: só ataques enviados enquanto ela já era sua.
- **Compartilhar comandos com a tribo anula o efeito observável** — comandos
  compartilhados já vêm todos visíveis e auto-marcados, então não sobra nada
  para a torre marcar. É a causa nº 1 de "testei e não funciona".

## 3. Tabela por nível

Requisitos: **Edifício principal 5 + Fazenda 5** (todas as aldeias atuais já passam).

A tabela pública bate exatamente com os fatores do `get_building_info` do br143 —
recalculada a partir da base e dos fatores, fecha nos 20 níveis.

| Nv | Madeira | Argila | Ferro | Custo total | Pop acum. | Raio (campos) | Pontos acum. | Armazém mín. |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12.000 | 14.000 | 10.000 | 36.000 | 500 | 1,1 | 42 | 14 |
| 2 | 14.040 | 16.380 | 11.800 | 42.220 | 590 | 1,3 | 50 | 15 |
| 3 | 16.427 | 19.165 | 13.924 | 49.516 | 696 | 1,5 | 60 | 16 |
| 4 | 19.219 | 22.423 | 16.430 | 58.072 | 822 | 1,7 | 73 | 17 |
| 5 | 22.487 | 26.234 | 19.388 | 68.109 | 969 | 2,0 | 87 | 17 |
| 6 | 26.309 | 30.694 | 22.878 | 79.881 | 1.144 | 2,3 | 105 | 18 |
| 7 | 30.782 | 35.912 | 26.996 | 93.690 | 1.350 | 2,6 | 125 | 19 |
| 8 | 36.015 | 42.017 | 31.855 | 109.887 | 1.593 | 3,0 | 150 | 20 |
| 9 | 42.137 | 49.160 | 37.589 | 128.886 | 1.879 | 3,4 | 181 | 20 |
| 10 | 49.301 | 57.518 | 44.355 | 151.174 | 2.218 | 3,9 | 217 | 21 |
| 11 | 57.682 | 67.296 | 52.338 | 177.316 | 2.617 | 4,4 | 260 | 22 |
| 12 | 67.488 | 78.736 | 61.759 | 207.983 | 3.088 | 5,1 | 312 | 23 |
| 13 | 78.961 | 92.121 | 72.876 | 243.958 | 3.644 | 5,8 | 374 | 23 |
| 14 | 92.384 | 107.782 | 85.994 | 286.160 | 4.300 | 6,7 | 449 | 24 |
| 15 | 108.089 | 126.104 | 101.472 | 335.665 | 5.074 | 7,6 | 539 | 25 |
| 16 | 126.465 | 147.542 | 119.737 | 393.744 | 5.987 | 8,7 | 647 | 26 |
| 17 | 147.964 | 172.624 | 141.290 | 461.878 | 7.065 | 10,0 | 777 | 26 |
| 18 | 173.117 | 201.970 | 166.722 | 541.809 | 8.336 | 11,5 | 932 | 27 |
| 19 | 202.547 | 236.000 | 196.733 | 635.280 | 9.837 | 13,1 | 1.118 | 28 |
| 20 | 236.981 | 276.477 | 232.144 | 745.602 | **11.607** | **15,0** | 1.342 | 29 |

**Acumulado até o nível 20:** 1.560.384 madeira + 1.820.452 argila +
1.466.271 ferro ≈ **4,85 milhões** de recursos.

Raio ≈ `1,1 × 1,1475^(nível−1)` — cresce ~14,75% por nível, enquanto o custo
cresce ~17%. Em **área** coberta o ganho é quadrático: ~3,8 campos² no nível 1
contra ~707 campos² no nível 20.

A coluna "armazém mín." é o nível de armazém que comporta o recurso mais caro
daquele upgrade (capacidade do armazém 30 = 400.000).

## 4. O custo real é população

- Fazenda nível 30 = **24.000** de população.
- Torre nível 20 = **11.607** de população → **48% da fazenda cheia**, e ela some
  de uma vez, não gradualmente.
- Traduzindo: 11.607 pop ≈ 11.607 lanças/espadas, ou ~1.934 cavalarias pesadas,
  ou ~2.320 aríetes. É um exército inteiro.
- O **nível 1 sozinho custa 500 pop** para 1,1 campo de raio — é de longe o pior
  degrau da tabela (o salto 1→2 custa só 90 pop e ainda soma 0,2 campo).
- Nível 10 (3,9 campos): 2.218 pop = 9,2% de uma fazenda 30, mais ~817k de
  recurso acumulado.

Conclusão de posicionamento: torre é decisão de **aldeia de retaguarda com
fazenda alta e tropa baixa**, escolhida para cobrir o cluster — não de aldeia de
front, que precisa da população para tropa. Pela foto atual da conta, a única
candidata plausível é **BBM 001** (6.021 pts, fazenda 26); as outras seis não têm
base econômica nem para o nível 5.

## 5. Implicação para o bot

`docs/game_comparison.md` §3 tratava watchtower como "sem ação — já coberto pela
Feature 16". Duas correções:

1. Aquele texto não trazia raio nem custo. Com os números acima, fica claro que
   o fator dominante da decisão é **população**, não a mecânica de detecção.
2. A Feature 16 (`docs/backlog.md`, "DefenceManager avançado") propõe consumir
   dados de watchtower (`data-command-id`, tamanho, flag de nobre). **Hoje ela
   teria zero dado de entrada**: o mundo tem a feature ativa, mas nenhuma aldeia
   da conta tem torre. Escrever o parser antes de existir uma torre em campo é
   escrever código que nunca será exercitado — exatamente o terceiro padrão de
   bug do `CLAUDE.md` (função definida e nunca chamada / caminho morto que, ao
   ser ressuscitado, revela bugs que ninguém tinha exercitado).

Ordem sã: construir a torre em campo primeiro (ou pelo menos decidir construir),
depois capturar o HTML real da tela de chegadas com marcas, depois escrever o
parser contra esse HTML.

## 6. A aldeia de torre da conta — BBM 002 (`38409`, 578\|305)

Escolhida em 2026-08-13. Não por geometria: **no nível 20 as sete aldeias
cobrem todas as outras** (maior distância do império = 9,06 contra raio 15), então
a geometria não discrimina. Foi escolhida por ser a defensiva mais desenvolvida
(2.032 pts). A BBM 001 seria mais rápida (30 dias contra 48) mas é o núcleo
ofensivo; a mais central (BBM 006, 5,83) é a mais lenta (54 dias).

### Configuração-alvo

| Edifício | Nível | Pop | Motivo |
|---|---:|---:|---|
| Torre de vigia | 20 | 11.607 | razão de ser |
| Ferreiro | 20 | 395 | requisito da academia + pesquisa |
| Estábulo | 20 | 158 | recrutamento de cav. pesada no tempo mínimo |
| Mina de ferro | 30 | 949 | produção máxima |
| Poço de argila | 30 | 447 | produção máxima |
| Bosque | 30 | 326 | produção máxima |
| Edifício principal | 20 | 99 | mínimo da academia |
| Muralha | 20 | 99 | inegociável |
| Mercado | 10 | 82 | mínimo da academia |
| Academia | 1 | 80 | cunhar moeda |
| Quartel | 5 | 13 | mínimo do estábulo |
| Estátua | 1 | 10 | custo fixo |
| Fazenda / Armazém / Praça | 30/30/1 | 0 | — |
| Oficina / Esconderijo | 0 | 0 | sem aríete/catapulta; inútil no late game |

**14.265 pop de edifícios** = 59,4% da fazenda 30. Sobram 9.735 → **1.622
cavalarias pesadas** (6 pop, 11 min/campo, def 200/80/180).

Números reais, porém, dependem de duas coisas fora do bot:

| Cenário | Pop livre | Cav. pesadas |
|---|---:|---:|
| Tropa velha mantida, sem demolir | 8.361 | 1.394 |
| Dispensando as 989 pop de tropa velha | 9.350 | 1.558 |
| Dispensando + demolindo mercado 21→10, quartel 6→5, esconderijo 3→0 | 9.735 | 1.622 |

### `templates/builder/watchtower_support.txt`

139 entradas, 0 mortas. Decisões de ordenação, todas derivadas de simulação:

1. **Ferro 2 níveis à frente de madeira e argila** — cav. pesada custa
   200/150/**600**.
2. **Cav. pesada liberada no dia 3** (`stable:10` + `smith:15` — confirmado na
   fonte oficial; **não** é estábulo 20).
3. **Economia antes da torre.** O pior upgrade de mina (ferro 29→30) se paga em
   239 h; a torre sozinha consome 337 h de produção máxima só para acumular.
   Toda mina se paga dentro do projeto, então minas primeiro domina.
4. **Torre 1–10 após `farm:22`, torre 11–20 no fim.** Pôr tudo no fim termina
   2,3 dias antes mas entrega a torre 9,5 dias depois; escolhido o segundo.
   Efeito colateral bom: o bloco 1–10 fica antes de `farm:30`, então o
   auto-insert de fazenda ainda funciona como rede de segurança.

Cronograma para a BBM 002: cav. pesada dia 3 · torre nv 10 dia 23 · minas 30
dia 27 · fazenda 30 dia 34 · **torre nv 20 dia 48**.

### `templates/troops/watchtower_support.txt`

Quatro tiers, só cavalaria pesada. Gates em `smith`/`watchtower`, **não em
`barracks`** — o quartel fica travado em 5, e o `defensive_1`, indexado por
quartel, nunca chegaria ao tier que tem `heavy`.

| Gate | Alvo | Ativa em |
|---|---:|---|
| `stable: 1` | — (`build: {}`) | hoje; existe só para `current_unit_entry` nunca ser `None` |
| `smith: 15` | 150 | dia 3 |
| `watchtower: 10` | 500 | dia 23 |
| `watchtower: 20` | 1350 | dia 48 |

150 e 500 são **o limite exato** onde deixam de ser gratuitos (175 e 750 já
elevam a pressão de população). 1350 fica abaixo do teto de propósito: um alvo
inatingível faria `reserve_resources` registrar pedido todo ciclo e a aldeia
viraria ímã permanente de `resource_sharing`.

⚠️ **As 989 pop de tropa velha são o gargalo dominante, não os alvos.** Com
elas dispensadas, recrutar 150 cav. pesadas custa exatamente o mesmo que
recrutar zero (12 pontos de pressão, todos estruturais); mantendo-as, os mesmos
150 quadruplicam a pressão para 44 — e cada ponto é o auto-insert puxando
fazenda para a frente, desfazendo a otimização "minas antes de tudo".

Simulação confirma: **a torre nunca fica bloqueada por falta de população em
fazenda 30** em nenhuma configuração testada. Folga final: 261 pop.

### Armadilhas do motor encontradas no caminho

- **Template de construção não aceita comentário.** `get_template()` faz
  `.strip().split()` e depois `entry.split(":")` desempacota em dois — token
  sem `:` derruba o builder com `ValueError`.
- **Todo tier de tropa precisa da chave `farm`.** `village.py:648` faz
  `current_unit_entry["farm"]` sem guarda. `"farm": []` é seguro: `attack()`
  itera a lista vazia e não envia nada.
- **O primeiro tier precisa de um gate já satisfeito**, senão
  `current_unit_entry` fica `None` e `attack.template` nunca é atribuído.
- **O bot não sabe demolir.** A única ocorrência de `destroy` no projeto é
  `destroy=0` na URL de construção instantânea. As demolições do alvo são
  manuais — o mundo permite (`<destroy>1</destroy>`), o bot é que não faz.

### Pendências

1. **Cunhagem de moeda depende de `snobs > 0`** (ver Feature 30 em
   `docs/features_log.md`). A BBM 002 está com `snobs: 4` = 400 pop de nobres,
   que **não cabem** no orçamento acima. Só morde quando a academia ficar
   pronta, por volta do dia 25.
2. **`units_in_total` conta tropa fora dando suporte?** O extractor remove
   linhas com `village_anchor` (`extractors.py:237`) e o comentário é ambíguo.
   Numa aldeia que vive com cavalaria emprestada, isso decide se o alvo de 1350
   é "no total" ou "em casa" — e no segundo caso o teto de população estoura.
   Só verificável com o HTML real de `place&mode=units` com suporte em trânsito.
3. **Fase 2 não iniciada** — planejamento *proativo* de sítios de torre
   (procurar no mapa onde a próxima torre deveria ficar e alimentar isso na
   seleção de alvos de conquista), registrada como **Feature 31** em
   `docs/backlog.md`. A Feature 30 é só reativa: opina sobre aldeia já
   conquistada, não sobre o que conquistar.
4. `watchtower.enabled` segue `false`: a Feature 30 não vai designar torres
   novas até ser ligada.

## 7. Espaçamento entre torres — de onde vem o `min_spacing: 16`

Levantado em 2026-08-13 para a Feature 30 (alocação territorial de aldeias de
torre). A pergunta: qual a distância mínima entre duas torres para que a
segunda não seja redundante?

**Geometria pura.** Duas torres de raio R a distância `d`:

| `d` | Sobreposição | Área nova | pop/campo² | Situação |
|---:|---:|---:|---:|---|
| 10 | 58% | 294 | 39,4 | redundância pesada |
| 15 | 39% | 430 | 27,0 | sem buraco |
| 20 | 22% | 552 | 21,0 | sem buraco |
| **25,98** | **6%** | **666** | **17,4** | **ótimo hexagonal** |
| 30 | 0% | 707 | 16,4 | buraco de 2,3 campos |

O ótimo hexagonal fica em `d = R√3 = 25,98` — o maior espaçamento sem buraco.

**E é uma armadilha.** Numa malha com espaçamento `s`, o ponto pior fica a
`s/√3` da torre mais próxima, então o aviso vale `R − s/√3` campos. Em
`s = R√3` isso dá **exatamente zero**: o ataque é marcado no instante em que
aterrissa. O ótimo hexagonal maximiza **área** e zera **tempo** — e tempo é o
produto da torre.

| `s` | Pior distância | Aviso (aro, 18 min/campo) | Aviso (nobre, 35) |
|---:|---:|---:|---:|
| 15 | 8,66 | 114 min | 221 min |
| 18 | 10,39 | 82 min | 161 min |
| 20 | 11,55 | 62 min | 120 min |
| 24 | 13,86 | 20 min | 40 min |
| 25,98 | 15,00 | **0 min** | **0 min** |
| 28+ | 16,17 | descoberto | descoberto |

**Simulação empírica** contra o mapa real do br143 (`/map/village.txt.gz`,
público), conquistando as bárbaras mais próximas do cluster da conta em ordem
de distância e aplicando a regra "aldeia a ≥ `s` de toda torre vira torre".
Aviso em modelo de **pior caso** (ataque vindo do lado oposto à torre; a média
é melhor, entre `R−d` e `R+d`).

Império de 67 aldeias:

| `s` | Torres | Descobertas | Aviso mediano | Aviso p10 |
|---:|---:|---|---:|---:|
| 15 | 4 | 0 | 149 min | 92 min |
| **16** | **4** | **0** | **149 min** | **92 min** |
| 17 | 2 | 5 | 107 min | 4 min |
| 20 | 2 | 8 | 107 min | 0 min |
| 26 | 1 | **22 de 67** | 29 min | 0 min |

**16 é o maior espaçamento que ainda cobre tudo**, em todos os tamanhos de
império testados (27, 47 e 67 aldeias). 17 é um precipício: perde uma torre e
o décimo percentil do aviso cai de 92 para 4 minutos. Com 26, um terço do
império fica cego.

Leitura intuitiva: espaçamento ≈ raio significa *"conquistou uma aldeia que
nenhuma torre enxerga? ela vira torre"*.

⚠️ **O precipício entre 16 e 17 é propriedade da distribuição de aldeias desta
vizinhança, não uma lei geral.** Numa região de densidade diferente ele se
move — por isso o valor é configurável e o padrão fica no lado seguro.

Custo: ~4 torres num império de 67 aldeias = 46.428 pop e 19,4M de recursos,
6% das aldeias convertidas em olhos.

## 8. O que não foi verificado

- **Tempo de construção real.** O servidor dá `build_time=13200s`,
  `build_time_factor=1.2` e `buildtime_formula=2`. Isso rende 3,7h no nível 1 e
  684h acumuladas **assumindo Edifício Principal nível 1**. A fórmula de redução
  por nível de EP na variante `formula=2` não foi confirmada: não aparece em
  `get_config` nem em `/page/settings`, e a wiki não separa as duas fórmulas.
  Os tempos reais serão bem menores que os da tabela acima.
- **O markup HTML das marcas** na tela de chegadas — o que a Feature 16
  precisaria casar por regex. Exige sessão autenticada *e* uma torre construída;
  nenhuma das duas condições existe hoje.
