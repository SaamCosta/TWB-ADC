# TWB-ADC — Backend

> Documento único do bot: arquitetura, estado das features, mecânicas do mundo
> medidas no servidor, dívida técnica, o que está aberto e o roteiro de evolução
> derivado do estudo dos concorrentes.
>
> **Consolidado em 2026-09-14.** Substitui `auditoria_codigo_2026-08-08.md`,
> `backlog.md`, `features_log.md`, `bugs_flags.md`, `game_comparison.md`,
> `troca_premium.md`, `watchtower.md`, `feature26_batch_capture.md`,
> `roteiro_benchmark_bots.md` e os quatro relatórios de `benchmarks/`.
>
> ⚠️ **Nem tudo é recuperável.** Os sete primeiros estavam versionados e
> continuam em `git show 85fbbcb:docs/<arquivo>`. Os **quatro relatórios de
> `benchmarks/` e o `roteiro_benchmark_bots.md` nunca foram commitados** e foram
> perdidos na consolidação (ver o vigésimo terceiro padrão no `CLAUDE.md`). O que
> sobreviveu deles é a §7 deste documento — conclusões, backlog e critérios; o
> detalhe por concorrente (identidade, infraestrutura, catálogo funcional,
> matrizes de privacidade, inventário de fontes) e o protocolo de benchmark
> (módulos M01–M15, cenários, pontuação) **não existem mais**.
>
> O par deste documento é [`frontend.md`](frontend.md) (webmanager e interface).
> As **lições de método** (os vinte e dois padrões de bug recorrentes) continuam
> em `CLAUDE.md`, que é o arquivo que entra em contexto — não são duplicadas aqui.

---

## 1. Como ler este documento

Três coisas diferentes convivem aqui e é importante não confundi-las:

| Tipo de afirmação | Como reconhecer | Peso |
|---|---|---|
| **Medido** | traz a fonte (`get_config`, `/page/settings`, cache real, log, teste) e a data | forte |
| **Implementado e validado em campo** | cita a data e o efeito observado no jogo | forte |
| **Implementado, não validado** | diz explicitamente "pendente de validação em campo" | médio — o caminho pode nunca ter rodado |
| **Proposto** | seções 7 e 9 | nenhum — é backlog, não estado |

A regra que organiza o documento: **código que nunca rodou em campo não conta
como funcionalidade.** O histórico deste projeto tem três casos de caminho
inteiro errado que passava nos testes porque nunca tinha sido exercitado
(Feature 9, a conquista PvP, a venda premium).

---

## 2. Arquitetura

### 2.1 Fluxo por ciclo

```
twb.py (loop principal)
  ├─ carrega config.json, faz merge por build.version, resolve sessão
  ├─ para cada aldeia gerenciada: Village.run()
  │     BuildingManager → TroopManager → SnobManager
  │       → AttackManager / ConquestManager → DefenceManager
  │       → ResourceManager / ResourceSharingManager
  └─ sistemas globais: Hunter, ZoneManager, PvpConquestManager,
     VillageManager.farm_manager
```

`Village.run()` escreve o snapshot da aldeia em `cache/managed/<id>.json` ao fim
do ciclo. Esse arquivo é o contrato de leitura do webmanager.

### 2.2 Módulos

| Diretório | Papel |
|---|---|
| `twb.py` | loop, config, merge, sessão, tee do log de sessão |
| `game/attack.py` | `AttackManager` (farm) e `ConquestManager` (trem de nobres contra bárbaras) |
| `game/defence_manager.py` | bandeiras, evacuação, apoio entre aldeias, leitura de ataques recebidos |
| `game/troopmanager.py` | recrutamento, pesquisa, coleta, **reservas de tropa** |
| `game/buildingmanager.py` | fila de construção a partir de templates |
| `game/resources.py` | mercado, troca premium |
| `game/resource_sharing.py` | transferência direta entre aldeias próprias |
| `game/hunter.py` | agendamento de ataques coordenados (Feature 10) |
| `game/zone_manager.py` | clustering geográfico (Feature 11) |
| `game/pvp_conquest.py` | conquista PvP semi-manual (Feature 13) |
| `game/simulator.py` | simulador de batalha |
| `game/map.py` | varredura de setores do mapa, cache de aldeias |
| `game/snobber.py` | nobres e cunhagem |
| `game/statue_manager.py`, `game/inventory_manager.py` | Paladino e inventário (leitura) |
| `core/` | `request.py` (HTTP/sessão), `extractors.py` (regex sobre HTML), `filemanager.py`, `templates.py`, `reporter.py`, `notification.py`, `world_config.py` |
| `pages/` | `overview.py`, `statue.py`, `inventory.py` — telas parseadas |
| `webmanager/` | dashboard Flask; ver [`frontend.md`](frontend.md) |

Total: ~20.200 linhas de Python fora de `tests/`.

### 2.3 Estado persistente

Todo estado runtime é JSON por diretório em `cache/`:

| Caminho | Conteúdo | Reescrito? |
|---|---|---|
| `cache/managed/<id>.json` | snapshot da aldeia por ciclo | sim, todo ciclo |
| `cache/villages/<id>.json` | dono, pontos, coordenada (do mapa) | sim, quando muda |
| `cache/reports/<id>.json` | relatório de batalha | **não** — só nasce e morre |
| `cache/attacks/`, `cache/conquest/`, `cache/pvp_conquest/`, `cache/hunter/` | estado por operação | sim |
| `cache/resource_sharing/pending.json` | livro-razão de remessas em voo | sim |
| `cache/zones.json`, `cache/world/config_<mundo>.json` | zonas e config do mundo | sim |
| `cache/logs/session_latest.log` | **tee do stdout do bot** — única fonte dos loggers | reescrito a cada run |
| `cache/logs/twb_*.log` | eventos do *reporter* (`TWB_*`) | acumulam |

⚠️ Os dois logs não são intercambiáveis: `twb_*.log` **não contém nenhuma linha
de `DefenceManager`, `Attacks` ou `Village`**. Ao planejar uma análise por log,
conferir qual das duas fontes tem o dado.

`.gitignore` cobre `cache/**`, `config.json`, `config.bak`.

### 2.4 Regras de configuração

Três regras, todas verificadas automaticamente por `tests/test_config_integrity.py`
(varredura por AST de toda chamada a `get_config`/`get_village_config`):

1. toda chave lida precisa existir em `config.example.json`;
2. toda chave lida por aldeia precisa existir em `village_template`;
3. toda chave precisa estar documentada em `webmanager/helpfile.py`.

Estado em 2026-08-31: **51 chaves globais e 23 por aldeia**, todas conformes.

**Bump de `build.version`:** só em `config.example.json`. O merge em `twb.py:231`
roda quando as versões **divergem** — igualar as duas **desliga** a propagação.
Antes de disparar o merge num `config.json` vivo, lembrar que `merge_configs()`
usa o template como base e descarta chave que só exista no config do usuário
(aldeias são exceção: lá acrescenta sem remover).

### 2.5 Testes

32 arquivos em `tests/`, cada um roda sozinho sem `pytest`:

```powershell
foreach ($t in (Get-ChildItem tests/test_*.py)) { python $t.FullName }
```

São testes de lógica pura, sem rede e sem estado de jogo. Cobrem: conquista
bárbara (nobre em voo, lealdade, alvo perdido, semântica de status, faixa de
queda), encoding do `FileManager`, alocação de torre, slots de Paladino, escolha
de pacote de farm, mecânicas do mundo (`WorldConfig`), motivo de recusa do jogo,
limite de ataque falso, venda na bolsa premium, templates de builder, comandos
recebidos, gate de urgência do apoio, bônus do "Sinal da Aflição", alcance do
mapa, perfis de farm, guarda do log de sessão, integridade da config, política de
bandeira, `ReportReader`, `BotManager`, lote de ataques, suspensão do farm por
PvP, defaults da API.

`tests/smoke_bot_manager.py` fica fora do glob de propósito (abre console de
verdade). **A maior parte do bot segue sem cobertura** — em especial tudo que faz
requisição.

**Fixture de markup do jogo se copia do servidor, não se inventa.** Cookies em
`cache/session.json`, user-agent em `config.json` → `bot`; um `requests.session()`
acessa qualquer tela sem atrapalhar o bot rodando. E **sonde com os cabeçalhos do
próprio wrapper** (`core/request.py`): `get_url`, `get_api_data` e
`get_api_action` montam conjuntos diferentes, e a mesma URL responde envelopes
diferentes conforme o cabeçalho.

---

## 3. Estado das features

Ordem histórica de implementação:
`4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 18 → 19 → 20 → 21 → 22 → 23 →
24f1 → 14 → 15 → 16 → 17 → 27 → 25f1 → 32p1 → 26`.

| # | Feature | Estado | Validação em campo |
|---:|---|---|---|
| 4 | Horários ativos por aldeia | ✅ | sim |
| 5 | Farm score por loot/distância | ✅ | sim (o cálculo era inerte até o Lote 5 — P1-8) |
| 6 | Herança de config por proximidade | ✅ | sim |
| 7 | Proporção ofensiva/defensiva | ✅ | sim |
| 8 | Alvo automático de conquista bárbara | ✅ | sim, com incidente (§6.1) |
| 9 | Transferência de recursos entre aldeias | ✅ reformulada 2026-08-11 | **sim** — 4 transferências reais |
| 10 | Hunter (ataques coordenados) | ✅ | sim |
| 11 | Zonas geográficas | ✅ | sim |
| 12 | Evacuação preventiva regional | ✅ | ⚠️ **não** |
| 13 | Conquista PvP semi-manual | ✅ | **sim, 2026-08-07** — conquista confirmada ponta a ponta |
| 14 | Templates de tropa no webmanager | ✅ | sim |
| 15 | Alvo manual de conquista bárbara | ✅ | sim |
| 16 | `DefenceManager` avançado | ✅ | parcial — ver §6.2 |
| 17 | Relatório de império | ✅ polimento fechado 2026-08-31 | sim |
| 18 | Moral/night bonus dinâmicos no simulador | ✅ | ⚠️ não isoladamente |
| 19 | Página de bandeiras | ✅ | sim |
| 20 | Página de resource sharing | ✅ | sim |
| 21 | Página de relatórios | ✅ polimento fechado 2026-08-31 | sim |
| 22 | Detecção de conta premium | ✅ | sim — conta **não** é premium |
| 23 | Variância comportamental | ✅ | sim |
| 24 | Paladino — fase 1 (leitura, slots) | ✅ | sim |
| 24b | Paladino — fase 2 (treino por XP, re-especialização) | ⬜ pendente | — |
| 25 | Inventário — fase 1 (catálogo read-only) | ✅ 2026-08-16 | sim |
| 25b | Inventário — fase 2 (ativar boosts) | ⬜ pendente | falta o POST de `consume` capturado |
| 26 | Envio de ataques em lote (`train[N][unit]`) | ✅ | **sim, 2026-09-04** — dois ataques em 115 ms |
| 27 | Conquista bárbara respeita reserva cruzada | ✅ 2026-08-08 | ⚠️ não |
| 28 | Farm automático de aldeias de jogador | ⬜ **descartado** — ver §7.5 | — |
| 29 | Janela de bônus noturno do defensor | ⛔ bloqueado | exige conta premium |
| 30 | Alocação territorial de torre — fase 1 | ✅ 2026-08-13 | sim |
| 31 | Sítios proativos de torre — fase 2 | ⬜ pendente | — |
| 32 | Bandeira por **perfil** (parte 1) | ✅ 2026-08-31 | ⚠️ **1 de 18** — ver §6.3 |
| 32b | Bandeira por **fase** da aldeia (parte 2) | ⬜ pendente | falta definir o sinal de fase |
| 33 | Cunhagem automática nativa | ⬜ pendente | — |
| 34 | Troca Premium | ✅ itens 1,2,3,5 (2026-08-20) | ⚠️ envio nunca rodou em pt-BR — §4.5 |

### 3.1 Notas que não cabem na tabela

**Feature 9 — resource sharing.** Duas regras em vez de uma: *transbordo* (por
percentual da própria capacidade) e *necessidade* (por sobra absoluta acima de
`need_donor_floor`, 20.000). Necessidade primeiro; o transbordo restante vai para
a aldeia com mais **espaço livre**. A versão de regra única não movia nada contra
os dados reais da conta. A validação achou que o caminho de envio inteiro estava
errado: `mode=send_res` não existe, o destino é por coordenada (`x`/`y`) e não por
`target_village`, e há uma **segunda etapa de confirmação** sem a qual nada sai.
⚠️ Não existe gate por aldeia — `resource_sharing.enabled` é global.
⚠️ Quem poupa para nobre precisa declarar `village.keep_resources`; a reserva
automática (`required_resources`) registra o que *falta* e some exatamente quando
proteger passa a importar.

**Feature 13 — conquista PvP.** A validação de 2026-08-07 revelou e corrigiu
**dez** bugs que nunca tinham sido exercitados: ordem de execução antes do farm,
encadeamento de passos por ciclo, múltiplos nobres por aldeia, exclusão do
Paladino da escolta, um `target_id` errado que impedia qualquer disparo real do
Hunter, sobrecomprometimento clear+escolta, `self.villages` nunca sincronizando
aldeias novas, `inherit_on_first_run` divergente do exemplo, detecção de posse
falhando em silêncio (atributos inexistentes em `WebWrapper`), e dois bugs de
interface. Trem falhado agora vira `status: "failed"` depois de
`FAILED_GRACE_SECONDS = 7200`, com `fail_reason` distinguindo
`train_arrived_no_conquest` de `train_outcome_unknown`. **Sem retry automático de
propósito.**

**Feature 16 — `DefenceManager` avançado.** O leitor de comandos recebidos
(`Extractor.incoming_commands`) **nunca casou uma linha** desde que foi escrito —
o regex tinha sido feito contra markup suposto. Corrigido em 2026-08-22 com
fixture verbatim de um trem de nobres real; o teste inclui um caso que roda o
regex **antigo** contra o markup real e exige zero casamentos.

**Feature 26 — lote nativo.** `train[N][unit]` num POST só. Medido: **115 ms**
entre dois ataques, contra ~2m19s pelo caminho anterior. A captura foi feita com
ensaio controlado antes de escrever o código.

---

## 4. Mecânicas do mundo, medidas no servidor

### 4.1 Fontes e método

Quatro fontes, **públicas e sem autenticação** exceto onde indicado:

| Fonte | O que entrega |
|---|---|
| `interface.php?func=get_config` | XML com as regras do mundo (`<moral>`, `<night>`, `<snob>`, `<premium>`, velocidades) |
| `interface.php?func=get_unit_info` | tropas: velocidade, carga, ataque/defesa |
| `interface.php?func=get_building_info` | custos, fatores, população por edifício |
| `/page/settings` | a **mesma regra em português**, para o jogador |
| `backend/get_servers.php` | lista de mundos por mercado |

⚠️ **`get_config` e `/page/settings` não expõem o mesmo conjunto de campos.**
Ausência num deles não é ausência no servidor. Foi assim que a regeneração de
lealdade ficou meses errada no config: o número está publicado em português
(*"Aumento de lealdade por hora: 1"*) e não existe no XML.

⚠️ **Valor de API pode já vir transformado.** As velocidades de `get_unit_info`
**já são** os min/campo efetivos, com `speed` e `unit_speed` embutidos. No br143
(ambos = 1) as duas hipóteses dão o mesmo número e o erro seria invisível para
sempre; o br139 (`speed=1.4`, `unit_speed=0.75`) publica `17,142857` para o
lanceiro, que é exatamente `18/(1,4×0,75)`. Quando um valor deveria escalar com um
parâmetro do mundo, buscar uma instância onde esse parâmetro **não** seja neutro.

### 4.2 br143 — valores verificados

| Parâmetro | Valor | Fonte |
|---|---|---|
| Aumento de lealdade por hora | **1** (o config assumia 1,5) | só `/page/settings` |
| Redução de lealdade por nobre | 20–35 (faixa) | ambas (`<mood>`) |
| Lealdade de aldeia recém-conquistada | 25 | medido em relatório |
| Distância máxima do nobre | 70 campos | ambas (`<snob><max_dist>`) |
| Arqueiro | **desligado** (`<archer>0</archer>`) | `get_config` + ausência em `get_unit_info` |
| Pesquisa | simplificada (`<tech>2</tech>`) — só nível 1 existe | ambas |
| Espadachim `def_cav` | 25 (br142, com arqueiro: 15) | `get_unit_info` |
| População de edifício | `round(pop × pop_factor^(n-1))`, não cumulativa | `get_building_info` |
| Capacidade da fazenda | ×1,1722 por nível; nível 30 = **24.006** | `get_building_info` |
| Bolsa premium | `PremiumExchange=1`, `MerchantExchange=1` | `get_config` |

Mundos br **com** arqueiro em 2026-08-18: br137, br141, br142, brc2, brp10.
**Sem**: br132, br138, br139, br140, br143.
⚠️ A detecção de mundo **desabilita a unidade, não troca o template**: quem abrir
mundo com arqueiro precisa apontar `off_archer`/`def_archer` na mão. As variantes
**sem** arqueiro são o default porque degradam melhor — `def_archer` num mundo sem
arqueiro pararia em ~11.600 de pop dos ~20.000 planejados, porque os 7.500
arqueiros entram em `disabled_units` e nada os substitui.

### 4.3 Moral e bônus noturno

O sistema de moral vem da tag de topo **`<moral>`**, não de `<mood>` — este foi o
P2-29, um número real, lido do servidor, **do campo errado**. Valores mapeados
contra o servidor (não contra a wiki, que erra):

| `<moral>` | Significado |
|---|---|
| 0 | desligado |
| 1 | só por pontos |
| 2 | pontos **e** tempo |
| 3 | pontos e tempo, ilimitado |

Não existe modo "só por tempo". Piso de moral: `MORAL_POINTS_FLOOR = 30`.

`night.active`: **0** = off, **1** = janela fixa do mundo, **2** = cada jogador
escolhe sua própria janela de 8h. O br143 usa **2**, e a consequência é cara:
`WorldConfig.is_night_bonus_active()` devolve `None` ("desconhecível") e o
`PvpConquestManager` assume o pior caso (defesa dobrada), o que com
`pvp_conquest.dynamic_moral_night_bonus` ligado reprova praticamente toda
simulação. A janela do defensor **é** scrapeável (hover de aldeia no mapa) mas
**só com conta premium** — e a conta não tem (Feature 22, detecção real). Isso é
a Feature 29, bloqueada por pré-requisito de campo.

Correção pendente e independente de premium: comparar contra a hora de
**chegada** do ataque, não a hora atual. Para trem de nobre as duas diferem por
horas, e isso também vale em mundo de janela fixa.

### 4.4 Torre de vigia

**Mecânica.** Marca todo ataque que **entra no raio** com tamanho do exército
(pequeno 1–1000, médio 1001–5000, grande >5000) e se leva nobre — inclusive
ataques que só **atravessam** o raio a caminho de outro lugar. As marcas
persistem. Requisitos: Edifício principal 5 + Fazenda 5. Catapultas destroem.

⚠️ **Compartilhar comandos com a tribo anula o efeito observável** — comandos
compartilhados já vêm marcados, então não sobra nada para a torre marcar. É a
causa nº 1 de "testei e não funciona".

**Custo.** Raio ≈ `1,1 × 1,1475^(nível−1)`; custo cresce ~17% por nível. O custo
que decide é **população**:

| Nível | Raio (campos) | Pop acumulada | Recurso acumulado |
|---:|---:|---:|---:|
| 1 | 1,1 | 500 | 36 mil |
| 5 | 2,0 | 969 | 254 mil |
| 10 | 3,9 | 2.218 | 817 mil |
| 15 | 7,6 | 5.074 | 2,17 M |
| 20 | **15,0** | **11.607** | **4,85 M** |

Torre nível 20 = **48% de uma fazenda 30**, e some de uma vez. Equivale a ~11.600
lanças, ~1.934 cavalarias pesadas ou ~2.320 aríetes. O nível 1 sozinho custa 500
pop para 1,1 campo — de longe o pior degrau (o salto 1→2 custa 90 pop e soma 0,2
campo). Conclusão de posicionamento: torre é decisão de **aldeia de retaguarda
com fazenda alta e tropa baixa**, não de aldeia de front.

**Espaçamento (`min_spacing: 16`).** O ótimo geométrico hexagonal é `d = R√3 =
25,98` — e é uma armadilha: numa malha de espaçamento `s` o pior ponto fica a
`s/√3` da torre, então o aviso vale `R − s/√3`, que em `s = R√3` dá **exatamente
zero**. O ótimo hexagonal maximiza área e zera tempo; tempo é o produto da torre.

Simulação contra o mapa real do br143 (`/map/village.txt.gz`, público),
império de 67 aldeias, aviso em modelo de pior caso:

| `s` | Torres | Descobertas | Aviso mediano | Aviso p10 |
|---:|---:|---|---:|---:|
| 15 | 4 | 0 | 149 min | 92 min |
| **16** | **4** | **0** | **149 min** | **92 min** |
| 17 | 2 | 5 | 107 min | **4 min** |
| 20 | 2 | 8 | 107 min | 0 min |
| 26 | 1 | 22 de 67 | 29 min | 0 min |

16 é o maior espaçamento que cobre tudo em impérios de 27, 47 e 67 aldeias. 17 é
um precipício. ⚠️ **O precipício é propriedade desta vizinhança, não lei geral** —
por isso é configurável e o default fica no lado seguro. Regra intuitiva:
*"conquistou aldeia que nenhuma torre enxerga? ela vira torre"*.

**Não verificado:** o tempo real de construção (a fórmula de redução por nível de
EP na variante `buildtime_formula=2` não aparece em nenhuma das duas fontes) e o
**markup HTML das marcas** na tela de chegadas — que é o que a Feature 16
precisaria casar. A segunda condição passou a existir: a BBM 002 tem torre
nível 8.

### 4.5 Troca premium

**Fórmula da taxa** (confere com o servidor; já implementada em
`PremiumExchange.calculate_marginal_price()`):

```
preço_marginal = base_price - elasticity × estoque / (capacidade + stock_size_modifier)
br143:           0,015      - 0,0148    × estoque / (capacidade + 20000)
```

**Economia.** Com a bolsa vazia, 1 PP custa `1/0,015 = 66,7` recursos,
independente da capacidade. Com ela cheia, depende da capacidade do continente:

| Capacidade | Recursos por 1 PP (estoque cheio) |
|---|---|
| 100 mil | 375 |
| 270 mil (K35 em 2026-08) | 819 |
| 1 milhão | 2.040 |
| 2 milhões | 2.886 |

Ou seja: a janela de valor é o **início do mundo**. Entre a abertura e a
saturação o custo de 1 PP multiplica por 12 no K35 e por 30+ num continente
grande. (Aferição cruzada: um mundo antigo onde 1 PP comprava 2.129 de madeira
implica capacidade de ~1,08 M pela fórmula invertida — ela prevê corretamente um
mundo que nunca observamos.)

Fatos confirmados no suporte oficial pt-BR: **uma bolsa por continente**;
**estoque cheio = venda bloqueada**; entrega em 2h com os mercadores da própria
aldeia; continentes adjacentes rebalanceiam capacidade e estoque **diariamente**
(medido: a capacidade de madeira do K35 encolheu duas vezes no mesmo dia —
número de bolsa vale pelo dia em que foi lido); PP servem em qualquer mundo do
mesmo mercado.

**O que foi corrigido em 2026-08-20** (`do_premium_stuff`, herdado do upstream e
nunca exercitado nesta conta):

1. o "preço" era `stock × rate` — o valor em PP do estoque inteiro da bolsa
   (~330 PP), não o preço (~819). Isso zerava `n_to_sell` e abortava com
   *"Not worth trading"*: **uma recusa que parecia prudência e era erro de conta**;
2. passou a existir **limiar de taxa** (`premium_exchange.max_rate_per_point`,
   default 90) — a regra central da estratégia, que não existia nem como config;
3. **lote configurável** (`sell_batch` 1000, `min_sell_batch`), cada lote relendo
   a bolsa, porque a taxa piora dentro da própria venda. O piso existe porque um
   mercador carrega 1000 e leva 2h de ida e volta;
4. os **três recursos**, não só o mais abundante — o gate anterior era
   `get_plenty_off()`, pergunta certa para o mercado normal e errada aqui;
5. bolsa cheia checada por recurso; reserva (`requested`, `keep_*`) respeitada.

⚠️ **`exchange_begin`/`exchange_confirm` seguem NÃO validados em pt-BR.** A bolsa
do K35 está 100% cheia nos três recursos, então não há como exercitar uma venda
real. O formato de `result["response"][0]["rate_hash"]` é suposição herdada do
upstream — `_premium_extract_rate_hash()` aceita as formas plausíveis e despeja a
resposta crua em `cache/premium/` quando não acha. **Planejar supervisão humana
no primeiro envio real.** É exatamente o perfil da Feature 9, onde o caminho de
envio inteiro estava errado por nunca ter rodado.

**Compra/arbitragem** (`# twb never buys`) continua arquitetonicamente fora, e o
estudo dos concorrentes rebaixou o item para P3 (§7.4, `X-03`).

### 4.6 Bandeiras

Os 8 tipos do jogo, 9 níveis cada (`FLAG_TYPES` em `game/defence_manager.py`):

| Tipo | Efeito | Uso no bot |
|---|---|---|
| 1 | produção de recursos | preferida sem academia |
| 2 | velocidade de recrutamento | segunda opção |
| 3 | força de ataque | **manual** — o bot nunca equipa |
| 4 | força de defesa | automático sob ataque, sobrepõe tudo |
| 5 | sorte | **manual** |
| 6 | população | terceira opção |
| 7 | custo de cunhagem | preferida **com** academia |
| 8 | capacidade de saque | quarta opção |

**Política em vigor** (2026-08-31, `DefenceManager.preferred_flags()`):

| Situação | Ordem |
|---|---|
| Aldeia com academia | 7 › 1 › 2 › 6 › 8 |
| Aldeia sem academia | 1 › 2 › 6 › 8 |
| Sob ataque | 4, sobrepõe tudo |

Configurável em `world.flag_priority`, `world.flag_priority_academy` e
`world.flag_manual_types`. Antes disso a escolha era um id fixo e
`set_flag_not_under_attack = 1` era hardcoded — com o inventário da conta sem
nenhuma bandeira tipo 1 sobrando, `get_highest_flag_possible(1)` devolvia `None` e
**`flag_logic()` não fazia nada, nas 18 aldeias, todo ciclo**.

Estado medido em 2026-08-31, de `cache/managed/*.json` (não depende de log):
`manage_flags_enabled` 18/18, `flag_state_confirmed` 18/18, bandeira equipada
16/18, `upgrade_attempts` presas 0/18. Inventário da conta:
`{2:7, 3:7, 4:6, 5:7, 6:7, 7:4, 8:7}`.

---

## 5. Auditoria de código 2026-08-08 — índice residual

Leitura integral dos 34 `.py` (12.403 linhas na época), com análise por AST para
atributos de classe mutáveis. **Todos os itens estão fechados** (Lotes 1 a 7,
último em 2026-08-12). O índice permanece aqui porque **comentários no código
citam esses IDs**.

### P0 — crítico

| ID | Problema | Arquivo |
|---|---|---|
| P0-1 | `TWB.villages` atributo de classe → aldeias processadas em dobro após crash | `twb.py` |
| P0-2 | `ResourceManager.actual`/`requested` compartilhados entre aldeias | `game/resources.py` |
| P0-3 | Handler de crash do `main()` podia ele mesmo crashar | `twb.py` |
| P0-4 | Webmanager **apagava** cache do bot ao ler JSON parcial | `webmanager/utils.py` |
| P0-5 | `Simulator.simulate()` crashava exatamente quando o ataque falharia | `game/simulator.py` |

### P1 — funcionalidade morta ou quebrada em silêncio

| ID | Problema | Arquivo |
|---|---|---|
| P1-6 | Suporte entre aldeias era código morto (condição invertida) | `defence_manager.py` |
| P1-7 | `forced_peace_today` nunca virava `True` (variável local) — e o método era **órfão** | `village.py` |
| P1-8 | `farm_score` nunca calculado → Feature 5 inerte | `manager.py` / `attack.py` |
| P1-9 | Caminho de "noble extra" inalcançável | `attack.py` |
| P1-10 | `can_attack()`: condição de relatório antigo invertida | `attack.py` |
| P1-11 | `recruit()` crashava quando a requisição falhava | `troopmanager.py` |
| P1-12 | `can_recruit()` mutava dict durante iteração | `resources.py` |
| P1-13 | `SnobManager.attempt_recruit` crashava com regex sem match | `snobber.py` |
| P1-14 | Strings/regex em holandês num servidor pt-BR | `resources.py` |
| P1-15 | `Map.villages`/`map_pos` compartilhados + `get_map()` sem guarda de `None` | `map.py` |
| P1-16 | `send_resources()` sempre retornava `True` | `resources.py` |
| P1-17 | Hunter e PvP dependiam de `village.attack`, criado só dentro do farm | `village.py` |
| P1-18 | Flask com `DEBUG=True` e config via GET sem CSRF | `webmanager/server.py` |
| P1-19 | `check_update()` fora do try → falha de rede impedia o boot | `twb.py` |

### P2 — robustez (20 itens)

`P2-20` sync de `defense_states` iterando aldeias puladas ·
`P2-21` `.get("public", {})` devolvendo `None` ·
`P2-22` escolta reservando o exército inteiro e **parando o farm** ·
`P2-23` `BuildingManager.waits` lista de classe ·
`P2-24` `self.levels[entry]` sem guarda (prédio inexistente no mundo) ·
`P2-25`/`P2-26` `extra` de relatório sem guarda ·
`P2-27` prioridade de resource sharing por `last_run` (heurística sem sentido) ·
`P2-28` `is_active_hours` sem virada de meia-noite ·
`P2-29` **piso de moral do campo errado** ·
`P2-30` `do_premium_stuff` usando `data` antes de checar `None` ·
`P2-31` parse do overview derrubando o ciclo ·
`P2-32` `BotManager.pid` não persistido → dois bots simultâneos ·
`P2-33` `cache/reports` sem poda + custo O(farms × reports) ·
`P2-34` `print()` de debug no laço do simulador ·
`P2-35` `PvpConquestManager` instanciado uma vez **por aldeia** ·
`P2-36` `nearest_send_time` zerando o sleep entre ciclos ·
`P2-37` `scout()` retornando `None` no sucesso ·
`P2-38` GET da praça antes de validar `map_pos` ·
`P2-39` `evacuate()` escolhendo destino arbitrário (primeiro do dict).

### P3 — dívida técnica

Config declarado e nunca lido (`support_others_max_villages` ✅ ressuscitado;
`scout_first`, `find_player_owned`, `conquest.target` ✅ removidos — ver §6.5);
código morto (`get_daily_reward`, `SimCache.cache_customize`,
`SnobManager.level_system`, `DefenceManager.attacks`, rota `/app/js` apontando
para diretório inexistente); atributos de classe mutáveis; `FileManager` com
double-join de caminho e sem `encoding=`; recursões sem guarda de profundidade
(a mais arriscada é `village.py:341`, `run_quest_actions` → `self.run()`);
`send_farm` logando sucesso **antes** de saber o resultado.

### Ainda sem resposta (precisa de campo ou sessão logada)

- `"delete": "Verwijderen"` e `"support": "Ondersteunen"` funcionam em pt-BR? O
  caminho do apoio deixou de ser código morto, mas **`support_others` segue
  `false` em campo e nenhum envio real jamais aconteceu**. Acompanhar
  `[Support] ... duration` no log.
- `DefenceManager.manage_flags` assume que `raw_flags[type][level]` é iterável;
  se a API devolver `int`, vira `TypeError`.
- `TroopManager.research_time` assume `H:M:S` estrito.
- Nomes de campo do payload de `send_resources` nunca validados contra resposta
  real.

---

## 6. Aberto hoje

### 6.1 ⚠️ Rastreio de conquista sumiu sem explicação

Em 2026-08-12 às 19:46 o `ConquestManager._get_my_conquest()` devolveu `None`
para a Bárbara #40314 com `cache/conquest/40314.json` em `status: "train_sent"` e
mtime de 11:56 — nada tinha reescrito o arquivo no intervalo. Como `existing` veio
falsy, o `run()` seguiu para `find_target()`, reelegeu **o mesmo alvo** como novo e
disparou um segundo trem inteiro de 4 nobres.

A assinatura no log é `_build_escort()` aparecendo **duas vezes** seguido de
`sending noble train`. Não reproduzido, causa desconhecida: nenhum outro caminho
escreve nesse arquivo sem logar, não houve restart e o webmanager não estava
rodando. A trava de nobre em voo (`4c4229b`) impede o estrago **por não depender
de `status`** — mas isso é robustez, não diagnóstico. **Se um trem duplicado
reaparecer, é aqui que se puxa o fio.**

### 6.2 Validações pendentes

| Item | Como validar |
|---|---|
| Feature 12 (evacuação regional) | primeiro ataque real que dispare a regra |
| Feature 18 (moral/night no simulador) | isoladamente, nunca foi |
| Feature 27 (reserva cruzada na conquista bárbara) | próxima conquista bárbara com PvP ativo |
| Trem PvP falhado → `status: "failed"` | só no próximo train que realmente falhar |
| `support_others` | ligar em **uma** aldeia e observar `[Support] ... duration` |
| Venda na bolsa premium | exige bolsa com espaço — mundo novo |
| Marcas da torre de vigia na tela de chegadas | a BBM 002 já tem torre nível 8; falta capturar o markup |

### 6.3 Bandeiras — validação 1 de 18

O Bug 1 (troca constante de bandeira a cada ciclo) e o Bug 2 (loop de upgrade)
estão **corrigidos no código e não validados**. Com a política nova o caminho de
`flag_set` voltou a ser exercitado, então a contagem virou teste de verdade:
**esperado exatamente 3 trocas no primeiro ciclo** (BBM 003, 016, 017) e silêncio
depois. Mais que isso é o Bug 1 de volta.

Resultado até agora: a **BBM 001** logou `Current village flag: -22% nos custos
de moedas` (tipo 7, nível 7) e o bot **não trocou** — previsto, é uma das três
aldeias de cunhagem manuais com as quais a política concorda. As outras 17 não
rodaram no recorte observado (o ciclo da primeira aldeia levou mais de 30 min só
de farm). Evidência positiva independente: a BBM 018 está com tipo 4 nível 7 e
`can_change_flag: False` — `flag_logic(4)` executou `flag_set()` com sucesso em
campo e o cooldown de 24h está sendo respeitado.

Ao retomar: `grep -a` (o log tem bytes NUL) por `Current village flag` e
`Setting flag` em `cache/logs/session_latest.log`.

### 6.4 Sobrecomprometimento de tropa entre múltiplos alvos

O fix de 2026-08-07 garante que clear + escolta de **um mesmo alvo** nunca somem
mais que 100% da tropa disponível. **Não cobre** a mesma aldeia comprometida com
múltiplos alvos de PvP agendados ao mesmo tempo — cada `_step_simulate()` roda
isolado, sem enxergar o que outros alvos já reservaram via
`total_conquest_reserve()`. Só um alvo esteve ativo até hoje, então o caso nunca
foi exercitado. É a evidência local que sustenta o `FND-03` da §7.4.

Relacionado: o piso `max(1, int(qty*ratio) // noble_count)` na escolta ainda pode
pedir mais do que existe para unidade escassa (`ram`, `catapult`). O caso do
Paladino foi resolvido excluindo-o da escolta.

### 6.5 Dívida estrutural conhecida

- **`game/attack.py`** — `AttackManager` e `ConquestManager` duplicam montagem e
  envio de ataque (`attack_form`, `map_pos`, `post_url` de confirmação).
  Candidato a helper comum.
- **Varredura de diretório por ciclo** — `Hunter`, `ZoneManager`,
  `ConquestManager` e o `ReportReader` leem cache com `os.listdir` + `json.load`
  por arquivo. Padrão a copiar: `PvpConquestManager._scout_report_index()`
  invalida o índice pelo `frozenset` de nomes, o que **só é exato porque
  `ReportManager.read()` pula id já cacheado** (arquivo de relatório nunca é
  reescrito). Antes de reusar em outro diretório, conferir se vale a mesma
  premissa — **ela não vale para `cache/villages`**, que `Map.build_cache_entry()`
  reescreve in-place; ali o mtime é obrigatório. O `ReportReader` do webmanager
  já foi indexado: **8,3 s por request** com 1.056 relatórios, contra ~3 ms.
- **`farms.find_player_owned` removida** — no formato obrigatório de relato:
  *`find_player_owned` não existe e não funciona — mas `village.additional_farms`
  funciona e serve para isso*, com trava extra de 23h–8h (`attack.py:238`). O que
  não existe é o modo automático **sem lista**, que é a Feature 28.

---

## 7. Benchmark dos concorrentes e roteiro de evolução

> Síntese clean room dos estudos estáticos de **Nexus**, **PS Evolution** e
> **ACID**, confrontados com o código real. Data de corte: 2026-09-13.
> Nenhuma funcionalidade foi implementada; isto é backlog de produto.

### 7.1 Método e o que a evidência vale

Os três estudos são **públicos e estáticos**: nenhuma função concorrente foi
validada de ponta a ponta. A taxonomia usada em todo o material:

| Código | Classe de evidência | Peso |
|---|---|---|
| `O` / `R` | observado / reproduzido | forte / muito forte |
| `T` | estrutura técnica demonstrada estaticamente | média — prova superfície, não resultado |
| `D` | documentado pelo fornecedor | média-baixa |
| `A` | alegação comercial | **baixa** |
| `I` | inferência explicitada | depende das premissas |
| `N` | não testado | não pontua |

**Regra clean room:** reaproveitar problemas, critérios, resultados observáveis,
métricas e fluxos genéricos. **Não** reaproveitar código, texto, nomes
distintivos, identidade visual, layouts ou mecanismos internos não públicos.

### 7.2 Onde o TWB-ADC já está à frente

Auditabilidade e correção independente · fixtures de markup real e smoke com o
mesmo cliente do bot · lote nativo **medido** (115 ms) em vez de slogan de
milissegundos · deadline duro com recusa de envio vencido · farm por
lotação/aproveitamento com tratamento de observação censurada · modelagem de
mecânicas heterogêneas por mundo · conquista com revalidação de posse, lealdade e
nobre em voo · escolha territorial de torre por **tempo de aviso** e não por área ·
degradação conservadora em caminhos críticos · histórico explícito de falhas,
inclusive quando a instrumentação estava errada.

### 7.3 As doze lacunas reais

1. estado transacional uniforme, incluindo `UNKNOWN_OUTCOME`;
2. reconciliação antes de retry em toda ação irreversível;
3. reserva global entre todos os consumidores e múltiplos alvos;
4. frescor/proveniência uniforme para caches e decisões;
5. motor temporal comum a ataque, apoio, devolução e simulação;
6. workspace defensivo com incerteza e impacto;
7. lifecycle de apoio **depois** do envio;
8. perfis de aldeia que mudem por fase;
9. centro operacional alimentado por eventos, não por parsing de log;
10. backup/restore coerente e testado;
11. colaboração com TTL, revogação e fonte;
12. métricas operacionais comparáveis antes/depois.

O diagnóstico de fundo: **o problema não é falta de módulos**, é a ausência de
uma camada transversal que diga, de forma uniforme, qual era a intenção, que
estado foi observado, o que foi reservado, o que foi enviado, o que o servidor
confirmou e o que permanece desconhecido.

### 7.4 Backlog consolidado

| ID | Item | Fase | Pri. | Esforço | Estado hoje |
|---|---|---|---|---|---|
| `FND-01` | Contrato de estado, eventos e frescor | 1 | **P0** | L | parcial — schemas independentes |
| `FND-02` | Ledger idempotente de intenção e efeito | 2 | **P0** | XL | parcial por módulo |
| `FND-03` | Ledger unificado de reservas e precedência | 2 | **P0** | XL | parcial (§8.2) |
| `FND-04` | Snapshot canônico, proveniência, capability registry | 1–2 | **P0** | XL | `WorldConfig` forte; caches inconsistentes |
| `FND-05` | Gateway read/propose/act e preview imutável | 2 | **P0** | L | previews isolados, sem digest |
| `SEC-01` | Inventário de segredos e controle de egressos | 2 | P1 | L | arquivos ignorados; sem cofre/redação |
| `TIM-01` | Motor temporal unificado e calibrado | 3 | P1 | XL | Hunter forte, sem engine comum |
| `TIM-02` | Confirmação pós-ação e reconciliação temporal | 3 | P1 | L | resposta imediata + checks pontuais |
| `DEF-01` | Workspace defensivo explicável | 4 | P1 | L | manager existe, UI fragmentada |
| `DEF-02` | Ciclo de vida de apoio | 4 | P1 | XL | envio e ETA; sem chegada/retorno |
| `ECO-01` | Perfis progressivos e coordenação econômica | 5 | P2 | L | perfil fixo; combina Features 32b e 33 |
| `CAL-01` | Auto-calibração de parâmetros de farm por alvo | 5 | P2‡ | M | ausente — constantes fixas em template; ver §7.8 |
| `EXP-01` | Cobertura territorial e expansão assistida | 5 | P2† | L | torre fase 1; Feature 31 |
| `OPS-01` | Planner canônico de operações | 6 | P2 | XL | telas e caches específicos |
| `COL-01` | Colaboração local-first com proveniência | 6 | P2† | XL | ausente |
| `OBS-01` | Centro operacional e roteador de eventos | 7 | P2 | L | páginas + Telegram simples |
| `REC-01` | Backup local versionado e restore ensaiado | 7 | P2 | L | `config.bak` e JSON atômico |
| `UX-01` | Onboarding e catálogo por objetivo | 7 | P2 | M | helpfile rico |
| `X-01` | API local de operador somente leitura | 8 | P3 | L | ausente |
| `X-02` | Paladino ativo e inventário (Features 24b/25b) | 8 | P3 | L | fase 1 read-only |
| `X-03` | Cunhagem nativa e mercado avançado (Features 33/34 item 4) | 8 | P3 | M/L | mint local; compra fora |
| `R-01` | **Rejeitado** — catálogo de escala e conveniências | — | REJ | — | ver §7.5 |

† condicional: `EXP-01` espera o império crescer o suficiente para `min_spacing`
discriminar sítios; `COL-01` só sobe com pelo menos dois operadores recorrentes.
‡ condicional e **bloqueado por pré-requisito de medição**, não por esforço —
`CAL-01` só é implementável depois do baseline do passo 3 da §9. Detalhe em §7.8.

**Detalhamento dos cinco P0:**

- **`FND-01`** — envelope próprio com `event_id`, `correlation_id`, módulo,
  operação, aldeia/alvo, estado canônico, fonte, `observed_at`, TTL, motivo,
  severidade e versão de schema. *Aceite:* módulos críticos emitem evento; a UI
  não parseia texto para inferir estado; stale/unknown visíveis.
- **`FND-02`** — estados `PLANNED → APPROVED → DISPATCHING → ACKNOWLEDGED →
  UNKNOWN_OUTCOME → RECONCILED | CANCELLED | FAILED`, chave idempotente, outbox
  durável, **reconciliação antes de retry**. *Aceite:* zero duplicações em 10.000
  falhas injetadas após aceite remoto; nenhum `UNKNOWN_OUTCOME` vira sucesso sem
  evidência. *Evidência local decisiva:* o trem duplicado da §6.1.
- **`FND-03`** — reservas por dono/finalidade/alvo/janela, com quantidade,
  prioridade, expiração e liberação idempotente, para tropas, recursos,
  mercadores, nobres e slots temporais. *Aceite:* soma de reservas nunca supera
  disponibilidade; múltiplos alvos coexistem; terminal libera exatamente uma vez.
  *Evidência local:* §6.4 e o P2-22.
- **`FND-04`** — snapshot versionado por domínio/fonte/instante; capability
  registry do mundo; **nunca usar `or default` para dado válido igual a zero**.
- **`FND-05`** — capacidades `read`/`propose`/`simulate`/`act`, digest canônico do
  plano, commit só para a versão vigente. *Aceite:* mutação de alvo/tropa/tempo
  invalida o commit.

**Dependências** (a ordem importa mais que o score):

```
FND-01 ─┬─> FND-02 ─┬─> TIM-01 ─> TIM-02
        │           ├─> DEF-02
        │           ├─> ECO-01
        │           └─> OPS-01
        ├─> FND-04 ─┬─> DEF-01 / EXP-01 / COL-01
        └─> OBS-01a ──> OBS-01b
FND-03 ─> TIM-01, DEF-02, ECO-01, OPS-01
FND-05 ─> TIM-02, OPS-01, COL-01
SEC-01 ─> COL-01, REC-01, NT-02
FND-01 + baseline (§9.3) ─> CAL-01 ─ (acoplado a) ─ ECO-01
```

### 7.5 O que **não** fazer

Descartado com justificativa, não por falta de tempo:

- **multi-conta em massa, proxy/fingerprint, resolução automática de captcha** —
  blast radius enorme e desalinhado ao produto. Manter pausa, snapshot e retomada;
- **farm automático indiscriminado de aldeia de jogador (Feature 28)** —
  `additional_farms` cobre o caso útil com controle explícito; a automação tem
  dano político alto e nenhuma demanda medida;
- **replicar o Assistente de Saque nativo** — o motor próprio é diferenciador;
- **mensagens automáticas em nome do jogador**;
- **automações de evento, recompensas, renomeação, notas, relíquias** — sem
  gargalo medido;
- **muitos provedores de notificação antes do barramento** (`NT-01/02`);
- **aprendizado por reforço (RL) sobre a política do bot** — descartado em
  2026-09-16 após a pergunta "isso se beneficiaria de uma instância de RL?".
  Não por moda nem por esforço: o domínio nega as três pré-condições. (a) Um
  episódio é *um mundo* — meses — e não há simulador da economia/mapa (o
  `simulator.py` resolve batalha, não o resto), então não há amostra barata;
  (b) não existe reset, e exploração custa tropa irrecuperável; (c) o crédito
  não é atribuível — latência de horas entre ação e efeito, resultado dominado
  por vizinho humano não modelado, ambiente não-estacionário. **Razão adicional
  específica deste repo:** o histórico de falhas caras (§5 e os padrões do
  `CLAUDE.md`) é de *sensor*, não de política — regex que não casa,
  `attack_duration()` devolvendo 0, `_parse_locked_slots()` devolvendo `[]`,
  moral lida da tag errada. Uma política aprendida sobre sensor quebrado
  **aprende a compensar o bug** e o torna permanentemente invisível, porque
  passa a "funcionar". O que se quer de RL aqui — adaptação que não dependa de
  um LLM externo instável — é obtido por `CAL-01` (§7.8) sem abrir mão de
  auditabilidade.

E o que é **só posicionamento comercial**, e por isso não entra no modelo de
prioridade: contagem de ferramentas (27, 37, 41, 53…), precisão de "1–3 ms" sem
protocolo/amostra/percentis, "inteligente/tempo real/zero perda/24-7" sem SLO,
número de usuários sem método, escala de contas como sinônimo de qualidade.

### 7.6 Critérios de aceite transversais

Todo item que possa causar efeito, antes de canário:

- estado ausente/ambíguo produz abstenção ou `UNKNOWN_OUTCOME`, **nunca sucesso**;
- intenção e efeito têm correlação e chave idempotente;
- estado oficial é reconciliado antes de retry;
- preview e commit usam o mesmo digest;
- reservas são atômicas, com dono, prioridade e expiração;
- premissas mutáveis são revalidadas **perto do efeito**, não da decisão;
- deadline vencido falha explicitamente;
- falha parcial não vira sucesso do lote;
- fonte, idade, decisão, motivo e resultado são observáveis;
- teste determinístico cobre sucesso, limite, falha, reinício e concorrência;
- shadow mode e canário precedem ampliação;
- rollback não reexecuta intenção vencida.

### 7.7 Hipóteses e métricas

| Hipótese | Métrica de sucesso | Janela |
|---|---|---|
| verdade operacional reduz diagnóstico | mediana <60 s | 30 incidentes |
| ledger elimina duplicação | 0 em 10.000 faults | harness |
| reservas eliminam overcommit | 0 promessas > disponibilidade | 10.000 cenários |
| calibração melhora timing | p95 −40%, duplicação 0 | ≥1.000 execuções |
| classificador ajuda sem fingir certeza | FP −30% com recall acordado | dataset versionado |
| lifecycle de apoio protege defesa | −25% violações, sem mais aldeias indefesas | 100 cenários + canário |
| perfis progressivos reduzem ociosidade | −20% de fila ociosa | 30 dias de replay |
| roteador reduz ruído | −50% redundantes, ≥95% críticos em 5 min | 30 dias |
| backup reduz recuperação | RTO cumprido, 100/100 restores | ensaio mensal |

Métricas de timing **sempre** separam erro de dispatch, carimbo de chegada e
efeito. Métricas de farm só valem a partir da correção que passou a distinguir
tentativa de envio confirmado. Valor no teto de capacidade é **observação
censurada**, não observação.

### 7.8 `CAL-01` — auto-calibração (2026-09-16, possibilidade registrada)

> **Status: possibilidade, não decisão.** Nada disto foi implementado, nenhum
> número abaixo foi medido para este fim. É o desenho que sobrou depois de
> descartar RL (§7.5) — registrado para não se perder, com o gatilho explícito
> de quando ele deixa de ser prematuro.

**O problema que resolve.** Hoje os parâmetros de farm são constantes escritas
em arquivo: capacidade do pacote por estágio de template, intervalo de
revisita, limiar de abandono de alvo. O décimo quarto padrão do `CLAUDE.md`
já mostrou que constante escrita em relação a um estado do jogo **expira
sozinha** quando o outro lado da relação se move — foi assim que 100% dos
ataques de uma aldeia passaram a ser recusados sem ninguém tocar no código. E
o décimo primeiro mostrou que a calibração manual desses mesmos números é
propensa a inverter o sinal da conclusão quando a amostra é heterogênea.
`CAL-01` é a proposta de fechar esse laço dentro do bot.

**Recorte — por que só farm.** O critério de inclusão é *uma ação → uma
medição, em ~1h, sem confundidor*:

| Candidato | Feedback | Entra? |
|---|---|---|
| capacidade do pacote por alvo | saque do relatório, ~1h | **sim** |
| intervalo de revisita por alvo | acúmulo observado entre visitas | **sim** |
| limiar de abandono (`farm_score`) | série de saque por alvo | **sim** |
| ordem de construção | semanas, confundida | não |
| composição de tropa | n≈10, confundida | não |
| quando/onde nobrar | n≈10, vizinho humano decide | não |

Fora do farm o n é pequeno e o efeito é confundido; ali o certo continua sendo
regra explícita calibrada contra número lido do servidor (§4.1).

**Forma.** Estimador + política explícita, **não** caixa-preta:

1. estimador por alvo sobre `cache/reports` — taxa de acúmulo e capacidade
   provável, com os valores no teto tratados como **censurados** (§7.7:
   "voltou com 8.000" = "tinha ≥ 8.000", não "= 8.000");
2. escolha do pacote/intervalo por conta fechada a partir da estimativa;
3. o valor escolhido **e o motivo** vão para o log e para a UI, como qualquer
   outra decisão;
4. o parâmetro se move só dentro de uma faixa declarada em config, com o valor
   manual continuando a poder vetar.

Os itens 3 e 4 são o ponto inteiro do desenho: é o que separa isto de RL e de
LLM-na-malha. Adaptação sem perder o "sei de onde veio o número", que é o que
o projeto já pratica em §4.

**Quando implementar — três pré-requisitos, nenhum opcional:**

- **`FND-01`** (evento com fonte, `observed_at`, TTL). Sem proveniência
  uniforme, o estimador aprende sobre dado velho sem saber que é velho, e a
  falha é silenciosa — o segundo padrão do `CLAUDE.md` com outra máscara.
- **Baseline de 7–14 dias** (passo 3 da §9). Sem série anterior não há como
  dizer se a calibração melhorou ou piorou, e aí ela vira fé. Este é o
  bloqueio real: é medição, não código.
- **Sensor de farm confiável**, com tentativa distinguida de envio confirmado
  (já corrigido) e as recusas do jogo logadas com motivo (`error_box_text`, já
  existe). Calibrar em cima de "ataque que o bot achou que enviou" produz
  estimativa deslocada para baixo, sem erro nenhum aparecendo.

**Portanto: depois do baseline da §9 e de `FND-01`, junto ou logo após
`ECO-01`** — os perfis progressivos e a calibração mexem nos mesmos números e
brigam entre si se forem construídos separados. **Não antes:** implementado
hoje, o estimador roda sobre eventos sem proveniência e sem comparação
possível, e a primeira coisa que ele vai fazer é absorver um bug de parsing
como se fosse propriedade do mundo.

**Como saber que valeu.** Métrica candidata, a acrescentar na tabela da §7.7
quando o item sair do registro e virar trabalho: *saque por unidade de
população por hora*, comparado contra o baseline, com a fração de retornos no
teto de capacidade reportada junto — se essa fração não cair, a medição
continua censurada e o ganho aparente não é ganho.

---

## 8. Estudo complementar — inventário de estados e reservas (2026-09-14)

> Isto não estava nos relatórios do benchmark. O passo 2 dos "próximos passos"
> deles pede "transformar `FND-01` num ADR de schema, **com inventário dos
> estados atuais**". Este é esse inventário, levantado do código, e ele
> confirma o diagnóstico com evidência local em vez de convergência documental.

### 8.1 Cinco vocabulários de estado, nenhum compartilhado

| Subsistema | Arquivo | Estados |
|---|---|---|
| Conquista bárbara | `game/attack.py` | `train_sent`, `conquered`, `lost`, `assumed_done`, `extra_pending`, `invalid`, `manual` |
| Conquista PvP | `game/pvp_conquest.py` | `pending_scout`, `pending_sim`, `scheduled`, `complete`, `failed` (+ `fail_reason`) |
| Hunter | `game/hunter.py` | `pending`, `sent`, `failed` |
| Resource sharing | `game/resource_sharing.py` | sem campo de estado — o livro-razão é uma lista de remessas em voo com prazo |
| Aldeia | `cache/managed/<id>.json` | sem estado; só `last_run` e flags booleanas |

Três observações que decorrem disso:

1. **`complete`/`conquered`/`sent` significam coisas diferentes.** Em `attack.py`,
   `assumed_done` é explicitamente "presumido"; em `hunter.py`, `sent` é "o POST
   voltou 200". Nenhum dos cinco distingue *aceito pelo servidor* de *efeito
   observado* — que é exatamente o `TIM-02`.
2. **Não existe estado para resultado desconhecido.** `grep` por `UNKNOWN` nos
   managers: zero ocorrências. O caminho de falha de rede devolve `None`
   (`WebWrapper.get_url()` em **qualquer** exceção) e cada chamador decide sozinho
   o que isso quer dizer.
3. **Não existe `idempotency_key` nem `correlation_id`** em lugar nenhum do
   código — `grep` por `idempot|correlation|operation_id` retorna uma única
   ocorrência, e é um comentário. Confirma o `FND-02` como trabalho de fundação e
   não de refinamento.

### 8.2 Quatro mecanismos de reserva, quatro contratos

| Mecanismo | Onde | Escopo | Liberação |
|---|---|---|---|
| `TroopManager.conquest_reserve` + `total_conquest_reserve()` | `troopmanager.py:91,97` | tropa, por `owner_key` | quando o dono resolve (enviado/falho) |
| `PvpConquestManager._add_reserve` / `_release_reserve` / `_maybe_release_reserve` | `pvp_conquest.py:1061-1182` | tropa, por alvo | por resolução **ou fallback de tempo** (`arrival + 3600s`) |
| `ResourceManager.reserve_resources` + `requested` | `troopmanager.py:731`, `resources.py` | recurso, por aldeia | implícita, ao gastar |
| `cache/resource_sharing/pending.json` | `resource_sharing.py:54,672-736` | recurso em trânsito | por prazo lido da tela de confirmação |
| `village.keep_resources` | config | recurso, **manual** | nunca |

O único consumidor que enxerga a reserva de outro é `AttackManager` via
`total_conquest_reserve()` (`troopmanager.py:433`). **Mercadores, nobres e slots
temporais não têm reserva nenhuma.** Duas liberações são por **tempo** e não por
confirmação — e o fallback de 1h do resource sharing depende de
`_parse_travel_seconds` continuar casando; se ele parar, a reserva segura recurso
demais e a aldeia receptora fica subabastecida, **sem erro no log**.

### 8.3 Proveniência: três convenções

- `cache/managed/*.json` → `last_run` (int, epoch), escrito todo ciclo mesmo sem
  mudança — logo **não** serve para saber se o dado é novo;
- `cache/statue`, `cache/inventory` → `fetched_at` (23 ocorrências);
- `cache/reports`, `cache/villages` → sem carimbo; o mtime do arquivo é o único
  sinal, e para `cache/villages` ele é obrigatório porque o arquivo é reescrito
  in-place.

Nenhum dos três carrega **fonte** ou **TTL**. É o `FND-04` com endereço.

### 8.4 O que isso muda no roteiro

Nada na ordem — a ordem proposta (`FND-01 → FND-02/03/04/05`) continua certa. O
que muda é o **ponto de entrada barato**: os cinco vocabulários da §8.1 cabem num
único enum com mapeamento por adaptador, e os quatro mecanismos da §8.2 cabem
numa facade comum antes de qualquer migração de dados. Começar pelo **Hunter e
pelo apoio**, como o próprio roteiro sugere, é acertado por um motivo adicional
que o estudo não tinha: são os dois subsistemas com o vocabulário **mais pobre**
(três estados e nenhum), então o custo de migração é o menor e o ganho de
`UNKNOWN_OUTCOME` é o maior.

---

## 8.5 Coleta (scavenging) — prioridade imediata definida pelo usuário em 2026-09-17

**Contexto que motiva a prioridade:** a conquista está consumindo as bárbaras
próximas, e a §4 do post do SQUAD 02 manda noblar *todas* as bárbaras da região.
O fim natural disso é **ficar sem alvo de farm**. A coleta não depende de alvo
externo, não perde tropa e o bot já a executa bem — vira a saída principal de
recurso a partir daí. Formulação do usuário: *"vamos ficar sem bárbaras para
farmar, a coleta é melhor saída e o bot já faz isso bem"*.

### Estado medido em 2026-09-17 (não presumido)

Config real das 28 aldeias, lida de `config.json`:

| Chave | Valor em todas as 28 |
|---|---|
| `gather_enabled` | `false` |
| `gather_selection` | `1` |
| `advanced_gather` | `true` |

Ou seja: **a coleta está desligada no império inteiro**, e mesmo se ligada hoje
usaria só o nível 1.

Como funciona hoje (`TroopManager.gather()`, `game/troopmanager.py:398`; chamada
por `Village.do_gather()`, `game/village.py:1017`):

- `gather_enabled` (por aldeia, default `false`) liga ou desliga.
- `gather_selection` (1–4, default `1`) é o **teto manual** de qual nível usar.
- `advanced_gather` (default `true`) distribui a tropa entre os níveis
  `1..gather_selection` calibrando para que todos terminem em tempo parecido
  (`selection_map`/`batch_multiplier`, `troopmanager.py:452`).
- A tropa reservada por conquista é subtraída antes
  (`total_conquest_reserve()`, `troopmanager.py:433`), então coleta e trem de
  nobres não disputam a mesma tropa.

### P-COL-01 — Botão "ativar coleta em todas as aldeias" no webmanager

**Prioridade 2** (depois de `P-CONQ-RAIO`, o tópico 1).

Um POST no painel que grave `gather_enabled: true` nas 28 aldeias de uma vez.
Granularidade por aldeia fica para depois — pedido explícito do usuário.

Pontos de atenção ao implementar:

- Toda rota que escreve no painel é POST e passa pela guarda CSRF de
  `server.py:23` (`reject_cross_origin_writes`). Seguir o padrão das rotas
  existentes, não criar GET que escreve.
- A escrita é em `config.json`, que o bot **relê a cada ciclo**
  (`twb.py:577`) — então o efeito pega sem reiniciar o bot. Isso é uma
  vantagem real do botão e deve ser dito na interface.
- ⚠️ `gather_enabled` já existe em `village_template` (`config.example.json`),
  então não há chave nova a documentar — mas **confirmar** antes de assumir.
- Mostrar na tela o estado agregado (quantas das N estão ligadas), não só o
  botão: botão sem leitura de estado é o décimo quinto padrão do `CLAUDE.md`.

### P-COL-02 — O que o bot **não** faz bem na coleta

**Prioridade 3.** São dois buracos distintos, e só um deles é o que parece.

**(a) Não ajusta o nível usado conforme o que está desbloqueado.**
Formulação do usuário: *"não ajusta sozinho quais coletas fazer com base nas
que já estão desbloqueadas"*. Precisão necessária: o código **lê** `is_locked`
da resposta do jogo e pula opção travada (`troopmanager.py:475` e `:533`), então
ele não quebra nem tenta usar coleta travada. O que falta é o outro lado:
`gather_selection` é um **teto digitado à mão** e não sobe sozinho. Desbloquear
o nível 4 no jogo não muda nada enquanto alguém não editar a config — e o
sintoma é mudo, porque o bot segue coletando normalmente, só que no nível 1.
Correção provável: derivar o teto do maior nível não-travado que o próprio jogo
reporta, mantendo `gather_selection` como limite opcional para quem quiser
menos.

**(b) Não desbloqueia coleta automaticamente.**
Confirmado por varredura: **não existe nenhum código de desbloqueio**. O único
uso de `scavenge_api` é `send_squads` (`troopmanager.py:517` e `:565`) — enviar
tropa para coletar. Não há chamada para iniciar o desbloqueio de um nível.

⚠️ **O endpoint de desbloqueio precisa ser capturado do jogo antes de escrever
qualquer código.** Não inventar payload. As regras do repositório que se aplicam
aqui, e que já custaram caro antes:

- Fixture de markup/payload se copia do servidor (`CLAUDE.md`, 2º parágrafo de
  Convenções).
- **Sondar com os cabeçalhos que o bot usa de fato** (7º padrão): o mesmo
  endpoint devolveu envelopes diferentes com e sem `TribalWars-Ajax: 1`. Sondar
  chamando o próprio método do `WebWrapper`, não um `requests.Session()` montado
  à mão.
- O desbloqueio **consome recurso e leva tempo real**, então é ação com efeito
  diferido — vale o 6º padrão: separar "quando mandei" de "quando termina".

Decisão de produto ainda em aberto, a levar ao usuário antes de implementar:
desbloquear custa recurso que competiria com construção e recrutamento. Se deve
ser automático, sob que condição (excedente? aldeia madura? nível máximo
desejado?) é escolha dele, não default a inventar.

---

## 8.6 `P-CONQ-RAIO` — alcance e âncora do trem multi-origem (2026-09-17)

✅ **Corrigido em 2026-09-19.** Ver "O que foi feito" no fim da seção. O
diagnóstico abaixo fica como está porque ele estava **incompleto**, e o que
faltava é a parte que interessa: o raio era o segundo funil, não o primeiro.

**Prioridade 1.** Duas coisas no mesmo lugar: um número de config e um defeito
de desenho introduzido no `BarbarianTrainPlanner` em 2026-09-17.

### O defeito

`BarbarianTrainPlanner._anchor_village()` (`game/conquest_planner.py`) elege
como referência **a aldeia com mais nobres**, e `ConquestManager.find_target()`
aplica o filtro de `max_radius` a partir *dessa* aldeia apenas. O comentário que
escrevi para justificar dizia:

> *"ancorar em quem tem mais nobres aproxima o alvo de onde está a maior parte
> do trem, o que encurta a viagem mais longa"*

Isso é verdade sobre a **viagem** e falso sobre a **visibilidade**: o conjunto
de alvos candidatos passou a depender de onde os nobres se acumularam, que é
circunstância, não geografia.

### Medições de 2026-09-17 (cache real, 28 aldeias)

Bárbaras elegíveis conhecidas dentro do K25 (x 500–599, y 200–299, 100–1100
pontos): **46**.

| Medindo de… | Alcançáveis com raio 30 |
|---|---|
| Qualquer aldeia gerenciada | **46 de 46** |
| BBM 001 (577\|306, 3 nobres → âncora atual) | **35 de 46** |
| BBM 001, com raio 50 | 46 de 46 |

As 11 invisíveis são o bolsão oeste, vizinho da **BBM 023 (553\|300)**:
`#40382 543|296` (35,4 campos da BBM 001, **10,8** da BBM 023), `#41100
543|291` (37,2 / **13,5**), `#46535 553|285` (31,9 / **15,0**), entre outras.

### Dados de mundo confirmados no servidor

`interface.php?func=get_config` do br143 (público, sem autenticação):

```xml
<snob><max_dist>70</max_dist><no_barb_conquer/></snob>
```

- Alcance máximo do nobre: **70 campos**. Já lido pelo bot desde 2026-09-17
  (`WorldConfig._parse_snob` / `noble_max_distance`), e `max_radius` agora é
  limitado por ele em `ConquestManager._effective_radius()`.
- `no_barb_conquer` **vazia** = conquistar bárbara é permitido neste mundo.
- Pior caso origem → alvo entre todas as combinações: **BBM 024 (588|314) →
  543|291 = 50,5 campos**, dentro dos 70. Nenhuma aldeia seria recusada pelo
  jogo ao compor o trem multi-origem contra qualquer bárbara do K25.

### Efeito colateral já medido de aumentar o raio

A pontuação normaliza distância e centralidade por `max_radius`, mas o termo de
pontos (`pts_factor * 0.1`) é fixo. Com raio maior, **pontos pesam relativamente
mais**. Medido na lista real: com raio 70 a ordem diverge **a partir da 5ª
posição** — `#50833` (15,1 campos, 551 pts) cai da 5ª para a 8ª e `#53604`
(17,0 campos, 1001 pts) sobe para a 5ª.

Não é bug: troca ~2 campos de viagem por ~450 pontos de aldeia, o que é
defensável. Mas é mudança de preferência e precisa ser decisão consciente.
Com raio 50 o efeito é bem menor que com 70.

⚠️ **Registro de método:** ao medir isto pela primeira vez olhei só os 4
primeiros colocados, vi que não mudavam e afirmei que não havia efeito. A
divergência começa na 5ª posição. É o 11º padrão do `CLAUDE.md` outra vez —
conclusão tirada de recorte que não representa o conjunto.

### Buraco conhecido, não urgente

O planejador monta o trem com **todas** as aldeias que têm nobre, mas não
verifica se cada origem está dentro dos 70 campos do alvo. Hoje não pode
acontecer (teto medido de 50,5), e a falha seria segura — a sondagem de duração
não retorna valor e nada é agendado — mas sem dizer o motivo.

### O segundo funil, achado em 2026-09-19 — e que o diagnóstico acima não vê

`find_target()` não varre o snapshot compartilhado: ela itera sobre
`self.map.villages`, que é o **prefetch de mapa da própria âncora**. Com
`farms.map_sector_radius: 0` (o valor em campo) esse prefetch é pequeno e não
centrado na aldeia — o comentário em `map.py:56` já registrava 36 contra 220
aldeias entre duas aldeias a 8 campos uma da outra.

Sondado ao vivo com o `WebWrapper` do bot em 2026-09-19 (leitura pura, sem
escrever em `cache/`), sobre as **39** bárbaras elegíveis que o império conhece
hoje no K25 (eram 46 em 17/09; o cache andou):

| Fonte | aldeias | bárbaras elegíveis | delas no K25 |
|---|---|---|---|
| scan da BBM 001 (âncora) | 332 | 26 | **23** |
| scan da BBM 011 (a outra com nobre) | 332 | 26 | **23** |
| scan da BBM 023 | 239 | 34 | **30** |
| `cache/villages` (compartilhado) | 851 | 102 | **39** |

Contando como o `find_target()` real conta (área de interesse + raio), do ponto
de vista da âncora: **21** candidatos com raio 30 e **23** com raio 50 pelo
scan local, contra **31** e **67** pelo snapshot compartilhado.

Duas consequências que a medição de 17/09 não podia mostrar:

1. **Subir `max_radius` não alcançava 16 dos 39 alvos** — eles nunca chegavam a
   ser filtrados pelo raio, porque não estavam na lista. O raio filtra o que já
   entrou.
2. A tabela "qualquer aldeia gerenciada → 46 de 46" de 17/09 foi calculada
   sobre `cache/villages`, ou seja, **sobre um pool que o código não usava**. Ela
   media a correção certa por acidente e atribuía todo o ganho ao raio.

O painel, aliás, já contava pelo snapshot compartilhado
(`ConquestReader.area_of_interest`), então painel e bot vinham respondendo
números diferentes para a mesma pergunta.

### Efeito colateral do raio 50, medido (2026-09-19)

Sobre a lista real, com o pool compartilhado: o **alvo escolhido é o mesmo** com
raio 30, 50 e 70 — `#51991 570|293`, 990 pts. A ordem diverge a partir da **6ª**
posição de 30→50 (troca `#54895` ↔ `#51804`: ~1 campo por ~250 pontos) e da
**3ª** de 50→70. Bem menor que o efeito 30→70 registrado acima, como previsto.

### O que foi feito (2026-09-19)

- **`ConquestManager.find_target(cfg, reach_from=None)`** — `reach_from` são as
  coordenadas das aldeias que podem de fato despachar nobre. Com ela: o filtro
  de raio passa a usar a **menor** distância até qualquer origem, e o pool vira
  `cache/villages` **com o scan vivo da âncora por cima** (fonte fresca vence).
  A pontuação continua medindo da âncora, de propósito — é a viagem dela que
  costuma definir a chegada comum. Sem `reach_from`, comportamento histórico
  intacto (é o que o caminho por aldeia continua usando).
- **`ConquestManager._candidate_pool()`** — novo, com o porquê da fonte e o que
  ela tem de pior (dono/pontos podem estar velhos; a revalidação de posse em
  `_handle_existing()` continua sendo a rede de baixo). Custo medido: 851
  arquivos em 0,13 s, uma vez por ciclo.
- **`BarbarianTrainPlanner._reach_locations()`** — coordenada de cada origem,
  do `area.my_location` e, na falta, de `cache/managed/{vid}.json`. Aldeia sem
  coordenada sai da conta com WARNING em vez de virar `(0, 0)`, que é uma
  coordenada válida no mapa do jogo.
- **`_anchor_village()`** — só pontua agora; o comentário que justificava a
  âncora falando de viagem (certo) e a usava para visibilidade (errado) foi
  reescrito com essa distinção explícita.
- **Guarda de alcance por origem** (`_source_reaches`, `_noble_range`) — o
  buraco acima, fechado: origem além do `<snob><max_dist>` do mundo fica de fora
  do trem com log próprio. Dúvida (coordenada faltando, mundo sem limite
  publicado) deixa passar — falso negativo custa uma aldeia fora do trem, falso
  positivo custa um comando recusado sem tropa gasta.
- **`conquest.max_radius: 50`** no `config.json` (já estava aplicado pelo
  usuário). `config.example.json` segue em 20, que é o default conservador.
- **Testes:** `tests/test_conquest_target_reach.py` (novo, 10 casos, com as
  coordenadas reais do bolsão oeste) e 5 casos novos em
  `tests/test_conquest_planner.py`. Suíte inteira (37 arquivos) verde, e
  `cache/` byte a byte idêntico antes e depois.
- **Smoke ao vivo:** `tests/smoke_conquest_reach.py` (fora do glob `test_*.py`,
  vai à rede, só lê). Rodado em 2026-09-19: pool 332 → 851, candidatos na área
  26 → 102 (67 dentro dela), e o alvo eleito é o mesmo `#51991` nos três
  cenários — como a medição offline previa.

**Não validado em campo:** o primeiro trem multi-origem real ainda não
aconteceu. Isto continua sendo código que nunca despachou nobre de verdade.

---

## 9. Próximos passos

**Fila definida pelo usuário em 2026-09-17, à frente do que vem abaixo:**

0. ~~**`P-CONQ-RAIO`**~~ — ✅ **feito em 2026-09-19** (§8.6). Falta só a
   validação em campo: o primeiro trem multi-origem real ainda não saiu.
1. **`P-COL-01`** — botão de ativar coleta em todas as aldeias (§8.5).
2. **`P-COL-02`** — teto de coleta automático e desbloqueio automático (§8.5).

Depois disso, a fila anterior:

1. **Fechar as validações de campo da §6.2**, que não custam código: são
   observações no log de sessão do bot já rodando. A das bandeiras (§6.3) é a
   mais barata e a mais próxima de terminar.
2. **`FND-01` como ADR de schema**, usando o inventário da §8 como entrada.
3. **Capturar baseline de 7–14 dias** antes de qualquer refatoração: decisões,
   falhas, reservas, duração de ciclo, atraso do Hunter, alertas, tempo de
   diagnóstico. Sem baseline, nenhuma das hipóteses da §7.7 é verificável.
4. **Harness de fault injection** antes de tocar em executores.
5. Migração incremental de `FND-02/03` começando por **Hunter e apoio** (§8.4).
6. SLOs temporais **por operação**, nunca um número universal.
7. Rotular um corpus defensivo **antes** de construir classificador (`DEF-01`).
8. Rever prioridades por métrica, não por catálogo novo.

---

## 10. Ambiente de referência

Python 3.13, Windows 10. Servidor ativo: **br143.tribalwars.com.br** (18 aldeias
gerenciadas no recorte de 2026-08-31; 27 entradas em `config.villages`).

```powershell
python twb.py                       # bot, console visível
cd webmanager; python server.py     # painel em http://127.0.0.1:5000/
foreach ($t in (Get-ChildItem tests/test_*.py)) { python $t.FullName }
```

Fluxo de push: `git add . → git commit -m "msg" → git push origin master`.
