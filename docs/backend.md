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
> As **lições de método** (os vinte e cinco padrões de bug recorrentes) continuam
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

45 arquivos `test_*.py` em `tests/`, cada um roda sozinho sem `pytest`:

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
PvP, defaults da API, e a degradação do mapa quando a rede cai
(`test_map_fetch_guard.py`, §8.8 — inclui a parte que se erra sozinha: falha de
leitura **não** pode fechar a janela de 8 h de `fetch_delay`).
O arquivo `test_gather_controls.py` acrescenta seleção dinâmica de coleta,
fallback por opção ocupada/travada, escrita atômica em massa, contrato HTTP e a
garantia de que todas as aldeias compartilhem a mesma sessão autenticada.
`test_session_and_captcha.py` e `test_notification_safety.py` cobrem a §8.9
(sessão por arquivo, auto-resume de captcha e o `Notification` à prova de falha)
— os dois foram rodados contra o `HEAD` anterior numa árvore temporária, onde
falham 19 e 5 checagens respectivamente.

`test_flag_supply.py` cobre a §8.11: oferta por `(tipo, nível)` lida de fixture
verbatim do br143, o gate de frescor do inventário e o aviso único de oferta
zerada.

Fora do glob de propósito: `tests/smoke_bot_manager.py` (abre console de
verdade), `tests/smoke_flag_inventory.py` (lê o inventário real de bandeiras) e
`tests/smoke_flag_stale_probe.py` (instrumento de comparação entre duas árvores
— ver §8.11). **A maior parte do bot segue sem cobertura** — em especial tudo
que faz requisição.

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

**Não medido ainda, e barato (2026-09-20):**

| Pergunta | Por que importa | Onde olhar |
|---|---|---|
| Existe **limite de saque** (`Beutelimit`) neste mundo? | Se existir e não tratarmos, o farm bate num teto invisível e as recusas aparecem como falha sem motivo. O fork `Themegaindex` trata isso com margem configurável | `get_config` + `/page/settings`; na praça o contador aparece como "saqueado X / Y" |
| A fórmula de duração de coleta vale aqui? | Ela é a base para dimensionar corrida por tempo (§8.5, `P-COL-03`) e foi medida num mundo speed 2.0 | uma corrida real de opção IV, comparando previsto × observado |
| `map/village.txt` responde? | Fecha o funil de descoberta de alvo da §8.6 | `GET <endpoint sem /game.php>/map/village.txt` |

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

✅ **A pergunta abaixo foi RESPONDIDA e corrigida em 2026-09-20 — ver §8.11.**
Resposta curta: a política **não** contava a oferta, e o que segurava o Bug 1
não era ela. O texto original fica abaixo porque o raciocínio dele continua
valendo; o que mudou é que agora há medição no lugar da hipótese.

⚠️ **Pergunta a responder ANTES de fechar esta validação (2026-09-20).** O fork
principal reescreveu bandeiras do zero justamente por causa do nosso Bug 1, e o
diagnóstico dele é mais fundo que o nosso: **bandeira não é config por aldeia, é
inventário de conta.** Você possui N de cada tipo/nível, e cada uma está em
exatamente uma aldeia — dar uma à aldeia B é tirá-la da aldeia A. Não existe
"vinte aldeias na bandeira de recurso" possuindo três delas.

Nossa política ordenada por aldeia resolve o sintoma comparando *bandeira atual ×
desejada*, e isso basta **enquanto houver bandeira sobrando**. A pergunta é se ela
conta a **oferta**: se dez aldeias quiserem um tipo do qual possuímos três, o que
acontece? Se a resposta for "as sete últimas ficam pedindo todo ciclo", o Bug 1
volta no dia em que o inventário apertar, e a validação atual (três trocas, com
folga de bandeiras) mede só o caso fácil.

O passe deles serve de referência de desenho (`game/flags.py:356`, `allocate`):
oferta = possuídas **menos as que já estão em pé** (bandeira fazendo serviço
nunca conta como sobra); aldeia que já carrega o tipo certo não é tocada — e a
nota deles diz explicitamente que *isso*, não a contagem, é o que para o
embaralhamento; quem sobra vira **`unmet` reportado**, não é servido com bandeira
roubada. Respeitam também o cooldown de troca do jogo, reportando "em cooldown"
uma vez em vez de uma fileira de falhas idênticas.
**Atenção:** o módulo deles é alpha declarado e o parser de `setFlagCounts` nunca
rodou em conta viva — a arquitetura vale, o parser precisa de fixture do br143.

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

> As §§7.1–7.8 são a síntese clean room dos estudos estáticos de **Nexus**, **PS
> Evolution** e **ACID**, confrontados com o código real. Data de corte:
> 2026-09-13. Nada daquele recorte foi implementado; ele é backlog de produto.
> A §7.9 registra uma auditoria posterior de forks irmãos GPLv3 e separa o que
> foi incorporado, adiado ou rejeitado.

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

### 7.9 Auditoria dos cinco forks irmãos (2026-09-20)

Foram clonados e lidos os cinco repositórios indicados pelo usuário. Todos
publicam GPLv3, como este projeto; portanto código pode ser adaptado mantendo a
licença. Esta auditoria é **estática (`T`)**: datas e quantidades abaixo descrevem
os commits inspecionados, não provam que uma função funciona no jogo ou no
br143. Quando o branch default era antigo, foi estudado também o branch recente.

| Fork / ref inspecionado | O que acrescenta | Evidência e decisão local |
|---|---|---|
| `LazyTurtleStyle/TWBOT_LazyTurtle` `a2b13a8` (2026-09-19, principal) | relógio do servidor, scheduler, retomada após captcha manual, poller de comandos recebidos, bandeiras account-wide, balanceador e módulos operacionais | superfície mais ampla, mas **0 testes** e vários módulos declarados alpha/.nl. Foram adaptados o conserto de coleta e o defeito P0 de `deepcopy`; relógio, captcha e incoming entram no backlog seletivo. Extensão de cookie/dashboard exposto e módulos alpha não entram. |
| `Themegaindex/TWB` `aa48004` (2025-12-04) | smart farming, coordenador de armazéns com recursos em trânsito e tentativa de desbloquear coleta | **4 arquivos de teste**. As ideias de capacidade e ledger são úteis, mas o local já tem perfis de farm e resource sharing validados em campo. O payload de desbloqueio não foi capturado no br143 e não será transplantado por inferência. |
| `Trojanekkk/TWB` branch `develop`, `8665362` (2026-05-29) | login do painel, status explícito do bot, estatísticas de farm e retenção de cache | **0 testes**; há cache/runtime versionado, `DEBUG=True` e rotas GET mutáveis. A agregação 24h/7d é uma boa base para `OBS-01`/baseline; autenticação só vira prioridade se o painel deixar de ser exclusivamente localhost. Coletor genérico que apaga cache por idade foi rejeitado. |
| `KrzysztofKalisiak/TWB_plus` branch `NoDriverLogging`, `cebd75c` (2026-02-27) | automação de navegador, rotação/login e alerta de captcha | o único `test.py` contém credencial hard-coded e o runtime depende de `personal_config.SECRETS`; também preserva defaults mutáveis e caminhos HTTP frágeis. Rejeitado integralmente por segurança e confiabilidade. O `master` default para em 2024. |
| `felipewariat/kuzyn-plemiona` `78ea499` (2026-06-23) | tradução polonesa e integração com Assistente de Saque/paginação | **0 testes**; a maior parte é tradução sobre a base de 2024, preservando limitações já corrigidas aqui. O farm local, por capacidade e relatório, é mais auditável; nada foi copiado. |

**Incorporado agora, com teste local:**

- `twb.py` não faz mais `copy.deepcopy(Village(...))`. Uma aldeia continua sendo
  um objeto distinto, mas todas apontam para o mesmo `WebWrapper`; clonar a
  árvore duplicava `requests.Session`, cookies, pool e `last_response`. O fork
  principal registra uma queda observada de aproximadamente 767 MB para 85 MB
  em 41 aldeias após correção equivalente. Aqui a regressão é coberta sem rede
  por identidade do wrapper.
- A coleta passa por opções travadas ou já ocupadas em vez de abortar a aldeia,
  reduz o teto configurado ao maior nível realmente desbloqueado e, no modo
  básico, envia o exército para **uma** opção apenas. O painel recebeu uma ação
  em massa com uma única substituição atômica de `config.json`.
- As gravações de configuração do webmanager passaram pelo `FileManager`,
  herdando UTF-8 e `os.replace()` atômico em vez de truncar o arquivo in-place.

**Próximos candidatos, não transplantados:** `ServerClock`/scheduler após fixture
de tempo do br143; retomada de captcha preservando resultado desconhecido;
poller somente leitura de incoming; passe account-wide de bandeiras; métricas
24h/7d para o baseline; comparação do balanceador com o ledger já validado do
resource sharing. Cada um precisa de teste e canário local — o número de módulos
do fork não é evidência de qualidade.

### 7.10 Backlog tático do estudo dos forks (leitura independente, 2026-09-20)

Segunda leitura dos mesmos cinco repositórios, feita em paralelo à §7.9. Ela
concorda com a matriz acima; o que segue é o que ela acrescenta. **Auditoria
estática:** nada abaixo foi medido no br143, e o fork principal é jogado quase
só em mundos `.nl` — vale o décimo sétimo padrão para toda constante herdada
dali. Os cinco repos são GPLv3, igual a este, então adaptar código é legal
mantendo a licença.

Três correções de fato sobre a §7.9, porque mudam decisão:

1. **`KrzysztofKalisiak/TWB_plus` no `master` é byte-a-byte igual ao upstream.**
   `diff -rq --exclude=.git` não acusa um arquivo. Não é fork desatualizado, é
   espelho. O trabalho dele existe só no branch `NoDriverLogging` (`cebd75c`).
2. **A trava cross-process do fork principal é no-op no Windows.**
   `attack_scheduler.py::_Lock` faz `if fcntl is None: return self`, e `fcntl`
   não existe aqui. Os módulos listados como próximos candidatos na §7.9
   (bandeiras account-wide, scheduler) são **justamente** os que dependem dela.
   Qualquer transplante precisa reescrever a trava (`msvcrt.locking` ou rename
   atômico com retry). O `os.replace()` salva o leitor de ver meio arquivo, não
   salva o read-modify-write perdido.
3. **`map/village.txt` fecha o funil da §8.6** e não aparece na §7.9. Ver o
   bloco novo no fim daquela seção.

**Fila tática.** Ordenada por (valor × certeza) ÷ risco; `S` cabe numa sessão.

| # | Item | Origem | Esf. | Medir antes |
|---|---|---|---|---|
| 1 | ~~Captcha auto-resume + sessão lida de arquivo~~ ✅ **feito em 2026-09-20 (§8.9)** | LT `core/request.py:242,333,388` | S | nada, é lógica local |
| 2 | ~~`InstanceLock` por endpoint da conta~~ ✅ **feito em 2026-09-20 (§8.10)** — reescrito com `msvcrt`, não transplantado | LT `core/instance_lock.py` | S | nada |
| 3 | ~~`Notification`: config lazy + `try/except` no `send`~~ ✅ **feito em 2026-09-20 (§8.9)**; categorias ficaram de fora (exigem config nova → merge no config vivo) | LT `core/notification.py:22,74` | S | nada |
| 4 | Ler `map/village.txt` e `map/player.txt` do mundo | LT `game/worldvillages.py` | S | o arquivo responde 200 e traz > 100 linhas |
| 5 | Verificar os quatro bugs da auditoria deles (abaixo) | LT `CODE_REVIEW.md` | S | leitura |
| 6 | `ServerClock` + `GameClock` | LT `core/server_clock.py:54,137` | M | formato de data do rodapé do br143 |
| 7 | Auto-desbloqueio de coleta por nível de EP; saque previsto logado | LT `troopmanager.py:13,486` | M | §8.5 |
| 8 | Consolidação noturna da coleta | LT `village.py:800` | M | depende de 7 |
| 9 | ~~Bandeiras: a nossa política conta **oferta**?~~ ✅ **respondido e corrigido em 2026-09-20 (§8.11)** — não contava; a causa real era decidir sobre leitura velha | LT `game/flags.py:356` | M | §6.3 |
| 10 | `mode=call`: ler do servidor o que já está a caminho | LT `balancer.py:355` | M | fixture verbatim |
| 11 | Velocidade de mercador medida na página de confirmação | LT `balancer.py:683` | M | mesma fixture |
| 12 | Ícones A/B/C do `am_farm` + `data-units-forecast` | LT `attack.py:152` | M | br143 renderiza o atributo? |
| 13 | Paginação do `am_farm` (o nosso leitor segue páginas?) | kuzyn | S | leitura |
| 14 | Existe limite de saque (`Beutelimit`) no br143? | megaindex | S | `get_config` + `/page/settings` |
| 15 | Pacote de farm por capacidade equivalente | megaindex | M | interação com `min_attack_population` |
| 16 | Notas privadas de aldeia (`ajaxaction=village_note_edit`) | LT `villagenotes.py` | S | fixture do `info_village` |

Itens de painel (métricas 24h/7d, senha, extensão de sessão) foram para
`docs/frontend.md` §6.1.

**Os quatro bugs deles que viram verificação nossa** (o `CODE_REVIEW.md` do fork
principal é, na prática, uma segunda auditoria da mesma base que a §5 auditou;
sete dos onze itens já são coisas que fechamos):

- **B4** — `main()` faz `t.wrapper.reporter.report(...)` sem guardar que
  `t.wrapper` pode ser `None` num crash de startup. A exceção secundária escapa
  do laço de retry: o bot **nem tenta de novo nem notifica**. Mesma família do
  "logger que ainda não existe no caminho de erro" (corolário do Lote 4).
- **B8** — `report["extra"]["units_sent"]` acessado direto. Relatório com tabela
  de atacante malformada vira `KeyError` no meio do `farm_manager`, e os perfis
  das farms restantes param de ser atualizados.
- **B9** — overview que parseia **zero** aldeias faz **todas** serem marcadas
  "não disponível" e puladas, *parecendo saudável*. Temos
  `tests/test_village_purge_guard.py`, mas a pergunta específica é outra:
  distinguimos "logado, parseou zero" de "genuinamente zero"?
- **B10** — user-agent lido da seção errada do config (`server` em vez de `bot`),
  derrotando em silêncio o propósito de usar o UA real.

**Armadilhas a não copiar junto** (além da `_Lock` acima):

- **Separador de milhar como elemento.** O jogo escreve `23<span>.</span>000`,
  então qualquer regex que pare na primeira tag lê **23**. Eles caíram nisso três
  vezes, nas telas de mercado e academia — que nós também lemos, e em pt-BR o
  ponto é o nosso separador. **Fatiar a célula antes de ler os dígitos.**
- **`flags.py` nunca rodou em conta viva** (o próprio arquivo diz: `flags.manage`
  está off desde o fork). A arquitetura vale; o parser de `setFlagCounts` é
  palpite de formato e precisa de fixture do br143.
- **Fallback de regex frouxo:** o `get_farm_bag_state` do megaindex cai para
  `(\d+)\s*/\s*(\d+)` sobre a página inteira despida de tags — casa com qualquer
  "N/M" da tela. Décimo quinto padrão em pessoa; não reaproveitar o parser, só a
  pergunta que ele faz.
- **Restaurar a tela do jogador.** Dois commits deles existem só para devolver o
  overview a "Combinado" e a tela de relatórios a "Todos" depois de ler. Se nós
  trocamos `mode`/`group` para ler e não restauramos, o jogador encontra a tela
  mexida — e relatórios podem cair em grupos que o bot nunca lê.

**O que a leitura independente descartou:** painel sem autenticação exposto em
`0.0.0.0` (o Lote 5 já fechou; a auditoria interna deles registra que
`DEBUG=True` + bind aberto é RCE pelo debugger do Werkzeug), o `hunter.py` deles
(protótipo morto, o nosso é melhor), multi-mundo, snipe/c-snipe completos
(alpha), e o login automatizado do `TWB_plus` (credencial em texto plano,
`bypass_captcha()` é stub com `find('???')`, e o caminho está desligado no
próprio branch). Do `TWB_plus` sobra **só a ideia** de rotacionar a sessão em
intervalo aleatorizado, que casa com o conselho do fork principal de que "uma
sessão rodando 24 h seguidas é forte sinal de bot".

**Uma nota sobre evidência.** O fork principal tem **zero testes** (não existe
`tests/`) e é ele mesmo vibe-coded — prosa boa de docstring não é validação. Mas
vários módulos carregam, no docstring, **a medição que originou a correção**, com
data, mundo e número: a corrida de coleta prevista em 16h10 e observada em 16h09,
os dois snipes que provaram que `k` conta fronteiras de segundo, os 767 MB do
`py-spy`, o 4,01 min/campo contra o 1,0 banqueado. Não substitui teste; é
evidência **de campo**, que nenhum teste unitário nosso produz. As duas coisas
valem, e valem por motivos diferentes.

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

✅ **Implementado e testado em 2026-09-20; efeito no jogo ainda não observado.**

`POST /app/gather/bulk` aceita `enable`, `enable_all_unlocked` e `disable`. A
página `/villages` mostra quantas aldeias estão habilitadas e quantas têm teto
4, exige confirmação explícita e distingue **persistência confirmada** de
**efeito pendente do próximo ciclo**. A alteração cobre todas as entradas de
`config.villages` numa única gravação atômica; aldeias `managed: false` recebem
a preferência, mas continuam sem executar o bot.

Critérios fechados:

- POST passa pela guarda CSRF de `server.py`;
- nenhum campo de configuração novo foi criado;
- `DataReader.gather_bulk_set()` preserva os outros campos e salva uma vez;
- teste cobre enable, opção 4, disable, ação inválida, recibo HTTP, campo legado
  malformado e preservação do teto ao desligar.

### P-COL-02 — O que o bot **não** faz bem na coleta

**Prioridade 3.** São dois buracos distintos, e só um deles é o que parece.

✅ **(a) Ajuste ao nível desbloqueado corrigido e testado em 2026-09-20.**
Formulação do usuário: *"não ajusta sozinho quais coletas fazer com base nas
que já estão desbloqueadas"*. `gather_selection` continua sendo um teto seguro;
o novo modo em massa `enable_all_unlocked` grava teto 4 e, em cada leitura,
`effective_gather_selection()` o reduz ao maior `is_locked == false` que o jogo
publicou. Opção alta já em andamento não bloqueia uma inferior livre. No modo
básico, a primeira opção livre recebe a tropa e o laço para, evitando reaproveitar
as mesmas unidades em um segundo POST.

**(b) Não desbloqueia coleta automaticamente.** ✅ **Implementado em 2026-09-21
com o gate desligado** — ver "Implementado" mais abaixo. O diagnóstico original
segue registrado aqui porque é ele que explica as escolhas.

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

**Candidato a verificar, do estudo dos forks (2026-09-20).** O fork principal
implementa o desbloqueio em `game/troopmanager.py:486` (`unlock_scavenge`), e
duas coisas dele respondem às perguntas acima:

- **A forma da chamada** é `get_api_action(action="start_unlock",
  params={"screen": "scavenge_api"}, data={village_id, option_id, h})` — o mesmo
  `scavenge_api` que o nosso `send_squads` já usa. Isto é **candidato**, não
  resposta: continua valendo capturar do br143 com o próprio `WebWrapper` antes
  de escrever código. O valor de ter o candidato é saber o que procurar na
  captura.
- **A regra do jogo que o parser precisa respeitar:** só **uma** opção desbloqueia
  por vez. Eles checam `unlock_time` em qualquer opção antes de tentar, e
  disparam no máximo um desbloqueio por ciclo, sempre o mais baixo pendente.
- **Uma resposta possível para a decisão de produto**, que evita inventar
  default: amarrar o teto ao **nível do Edifício Principal** em vez de a um
  excedente de recurso (eles usam 1/5/8/15 para as opções I–IV, configurável por
  aldeia). E, quando o desbloqueio é desejado mas impagável, um flag
  `prioritize_scavenge_unlock` que **segura a construção** até juntar o recurso —
  o que transforma a competição descrita acima numa precedência explícita em vez
  de numa corrida. Continua sendo escolha do usuário; a contribuição aqui é que
  a escolha tem forma conhecida.

#### ✅ Captura feita em 2026-09-21 — o endpoint saiu da fonte, não de palpite

O candidato do fork acima **confere**, e agora tem procedência. A tela
`screen=place&mode=scavenge` não contém o endpoint; ele está no bundle público
`JsModuleBundles/Scavenging.dd2ec0.js`, servido pela CDN **sem autenticação**.
Recorte verbatim:

```js
startUnlockingOption:function(e,a,i,n){
  a={village_id:e.village_id,option_id:a};
  TribalWars.post("scavenge_api",{ajaxaction:"start_unlock"},a,
                  function(a){e.update(a.village,a.time_generated_ms) ...
```

E `TribalWars.post`, lido de `merged/game.d7017c.js`, faz três coisas que
decidem a implementação:

```js
post:function(a,e,t,...){ a=this.buildURL("POST",a,e), e=a.match(/&h=([a-z0-9]+)/);
  e&&... (a=a.replace(/&h=([a-z0-9]+)/,""), t.h=e[1]) , this.request("POST",a,t,...)}
request:... n={"TribalWars-Ajax":1}; $.ajax({url:e,data:t,type:a,dataType:"json",headers:n,...})
```

1. o `h` (csrf) **sai da URL e vai para o corpo**;
2. form-encoded (default do `$.ajax`), não JSON;
3. cabeçalho `TribalWars-Ajax: 1`.

É exatamente o que `WebWrapper.get_api_action` já monta (`core/request.py:369`),
inclusive o `h` vindo de `last_h`. **Nenhum método novo é necessário:**

```python
wrapper.get_api_action(village_id, "start_unlock",
                       params={"screen": "scavenge_api"},
                       data={"village_id": village_id, "option_id": option_id})
```

**A config do mundo também é server-side**, no 1º argumento de
`new ScavengeScreen(...)` na própria tela — custo e duração por opção, sem
precisar de tabela chumbada:

| opção | nome | `loot_factor` | `unlock_cost` | `unlock_duration_seconds` |
|---|---|---|---|---|
| 1 | Pequena Coleta | 0,10 | 25 / 30 / 25 | 30 |
| 2 | Média Coleta | 0,25 | 250 / 300 / 250 | 3.600 |
| 3 | Grande Coleta | 0,50 | 1.000 / 1.200 / 1.000 | 10.800 |
| 4 | Extrema Coleta | 0,75 | 10.000 / 12.000 / 10.000 | 21.600 |

O 2º argumento (`var village`) traz `options[N].is_locked`, `unlock_time` e
`scavenging_squad` **por aldeia** — é o que o `(a)` já consome.

#### O que a varredura das 30 aldeias diz sobre a política de gasto

Medido em 2026-09-21, com a sessão do bot, uma aldeia por vez:

| opção | trancada em | custo unitário | custo de fechar tudo |
|---|---|---|---|
| 1 e 2 | **0 aldeias** | — | — |
| 3 | 3 aldeias | 1.000/1.200/1.000 | 3k / 3,6k / 3k |
| 4 | **19 aldeias** | 10.000/12.000/10.000 | **190k / 228k / 190k** |

Três consequências para o desenho, que a discussão anterior não tinha como ver:

- **As opções baratas não existem como problema.** Qualquer política que
  comece por "desbloquear do mais baixo para o mais alto" já nasce sem trabalho
  a fazer aqui: o que falta é quase só a opção 4.
- **O usuário desbloqueia na mão**, e estava desbloqueando durante a medição
  (opção 4 em 44683, 41140, 40618; opção 3 em 46584 e 52755 — `unlock_time`
  preenchido). A automação precisa **conviver** com isso, não competir: checar
  `unlock_time` em qualquer opção antes de tentar (é também a regra do jogo de
  um desbloqueio por vez, que o fork já tinha apontado).
- **O número da decisão é 608k de recurso**, não "algum recurso". Isso é
  comparável ao saque de um único ciclo de farm do império (~700k no log de
  2026-09-20), o que torna a pergunta bem menos dramática do que parecia.

✅ **Canário executado em 2026-09-21 07:47, autorizado pelo usuário.** Opção 3
na 49709 (BBM 029), pelo **próprio cliente do jogo** no Chrome — não por um
POST meu à mão. Isso é de propósito: quem montou a requisição foi o jogo, então
o que se lê é o que o jogo faz, não o que eu acho que ele faz.

A requisição capturada:

```
POST game.php?village=49709&screen=scavenge_api&ajaxaction=start_unlock  ->  200
```

Confere com o derivado da fonte, e traz uma confirmação independente de
quebra: **não há `&h=` na URL**, exatamente como o `game.php` previa ao mover o
csrf para o corpo. A caixa de confirmação também validou o parse da config —
"1.000 / 1.200 / 1.000" e "3:00:00", que são o `unlock_cost` e os `10800 s` da
tabela acima. Depois do clique, a Grande Coleta passou a contar `2:59:56`.

✅ **Política de gasto decidida pelo usuário em 2026-09-21:** *"desbloqueia
quando der, coleta dá retorno muito rápido"*. Ou seja, **sem gate de excedente
e sem escalonamento por maturidade** — a condição é poder pagar. Implicações
para a implementação:

- Tentar o **mais baixo pendente** em cada aldeia, um por ciclo, e só quando os
  três recursos cobrem o `unlock_cost` lido da tela (nada de tabela chumbada).
- Respeitar o teto do jogo de **um desbloqueio por vez por aldeia** —
  `unlock_time` preenchido em qualquer opção significa pular a aldeia. É também
  o que faz o bot conviver com os desbloqueios manuais do usuário em vez de
  competir com eles.
- Interação com `keep_resources` / reserva de nobre: o desbloqueio não pode
  comer recurso poupado para nobre. A reserva automática (`required_resources`)
  some quando a aldeia já juntou o suficiente, então quem poupa precisa de
  `village.keep_resources` declarado — a mesma armadilha da Feature 9.
- Não precisa de config de "quando": precisa de um gate de liga/desliga
  (default off até rodar em campo) e de nada mais.

#### ✅ Implementado em 2026-09-21 — gate desligado, nenhum POST disparado ainda

O desbloqueio existe em código e está coberto por teste, mas
`gather_unlock_enabled` nasce `false` em todas as aldeias: **nada foi gasto no
jogo por esta feature até agora.** Ligar é decisão do usuário.

Peças:

| Peça | Onde | O que faz |
|---|---|---|
| `Extractor.scavenge_config()` | `core/extractors.py` | 1º argumento de `new ScavengeScreen(` — custo, duração e `prerequisite_option_ids` por opção |
| `TroopManager.choose_scavenge_unlock()` | `game/troopmanager.py` | decisão pura: qual opção desbloquear, ou `None` |
| `TroopManager.unlock_scavenge()` | `game/troopmanager.py` | o POST, montado por `get_api_action` |
| `gather_unlock_enabled` | `config.example.json` + `helpfile.py` | gate por aldeia, default `false` |

Três decisões que a captura mudou em relação ao plano:

- **`prerequisite_option_ids` existe na config do mundo** (`4→[3]`, `3→[2]`,
  `2→[1]`) e a decisão usa esse campo em vez de assumir que a ordem numérica
  basta. Hoje as duas coincidem; o campo é o que o servidor publica.
- **`unlock_time` é o timestamp de CONCLUSÃO**, não de início — medido: a
  BBM 029 marcava `1789998457` = 10:47:37, exatamente as 3h do canário disparado
  às 07:47. É o 6º padrão em dado publicado: o jogo já separa "mandei" de
  "termina", e a guarda de "um por vez" lê esse campo.
- **O campo é limpo ao terminar**, então a guarda não trava a aldeia para
  sempre. Evidência: a BBM 001 tem as quatro opções destrancadas e
  `unlock_time: None` nas quatro.

**Zero GET extra**: `unlock_scavenge()` recebe a resposta que `gather()` já
baixou, por causa do limite de taxa por conta descrito abaixo. O custo máximo da
feature é **um POST por ciclo por aldeia**, e só quando há algo a pagar.

Como consequência de ler a mesma página, o desbloqueio está preso a
`gather_enabled` — intencional, e registrado no `helpfile`.

⚠️ **Limite de taxa observado no mesmo dia, e ele restringe qualquer automação
aqui.** Sondando pelo navegador com o bot rodando, o servidor devolveu
*"Sua ação foi bloqueada porque você está fazendo muitos pedidos ao nosso
servidor"*. Não foi o desbloqueio que estourou — foi o **autocomplete** de um
campo de texto, que dispara uma requisição por tecla, somado ao tráfego normal
do bot. Vale como lembrete de que o orçamento de requisições é da **conta**, e
que uma feature nova disputa esse orçamento com o farm.

### P-COL-03 — O que a coleta ainda não sabe medir nem aproveitar (2026-09-20)

Três lacunas vistas no fork principal, em ordem de valor:

1. **Não sabemos quanto a coleta rende.** E não há como descobrir depois: o
   relatório de coleta concluída **não carrega saque**. A única janela é o
   instante do despacho, onde saque esperado = capacidade do esquadrão ×
   `{I: 0.10, II: 0.25, III: 0.50, IV: 0.75}`. Registrar isso num
   `cache/scavenge_log.json` é o que torna possível a pergunta "a coleta rendeu
   mais que o farm nas últimas 24 h", que hoje não tem resposta.
2. **Não dimensionamos a corrida pelo tempo.** A duração é
   `((carry² × 100 × fator²)^0,45 + 1800) × world_speed^-0,55` — fórmula da
   comunidade que eles verificaram contra uma corrida real de opção IV: 39.160 de
   capacidade previu 16h10, observado 16h09 (mundo NL, speed 2.0). Invertida, ela
   responde "qual o maior esquadrão que volta dentro de X", que é o que habilita
   o item 3. ⚠️ **Medir no br143 antes de usar:** o mundo deles é speed 2.0 e o
   nosso não, então este é exatamente o caso do décimo sétimo padrão — uma
   corrida real basta para separar as hipóteses.
3. **Consolidação noturna.** Dentro de uma janela configurável, mandar **uma**
   corrida longa na maior opção em vez de dividir, dimensionada para voltar
   quando a janela fecha — cobre a noite sem atenção. Com dois cuidados que eles
   pagaram para aprender: não iniciar consolidação se falta pouco para o fim da
   janela (corrida curta inútil), e **nunca consolidar sob ataque**, porque uma
   corrida longa com o exército inteiro é o oposto do que se quer com incoming.

Existe ainda uma quarta ideia, de valor menor e desenho bom: **política de coleta
por grupo do jogo** (`never` / `pause_attacked` / `always`, a mais restritiva
vencendo quando a aldeia está em vários grupos). Vale principalmente porque usa o
vocabulário que o jogador **já criou** no jogo, em vez de criar um segundo.

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

### O terceiro funil não tem cura local: `map/village.txt` (2026-09-20)

O conserto acima trocou o scan local pelo snapshot compartilhado, e isso subiu
o pool de 332 para 851. Mas `cache/villages` **também** é um funil: ele só
contém o que alguma aldeia nossa já escaneou algum dia. O mundo inteiro nunca
esteve disponível para o bot.

Está, e de graça. O TribalWars publica, **sem sessão e sem autenticação**:

```
<mundo>/map/village.txt   id,name,x,y,player_id,points,rank     (owner "0" = bárbara)
<mundo>/map/player.txt    id,name,tribe,villages,points,rank
<mundo>/map/ally.txt      id,name,tag,members,villages,points,…
```

Uma requisição responde "quem é o dono disto e onde fica" para o mundo todo
(~600 KB num mundo cheio). É a mesma fonte em que as ferramentas de mapa da
comunidade são construídas. Implementação de referência no fork principal:
`game/worldvillages.py`, 131 linhas, com três guardas que valem copiar junto —
recusar corpo acima de 40 MB, **recusar parse com ≤ 100 aldeias** (um mundo
sempre tem milhares, então um punhado significa que veio redirect e não o
arquivo), e devolver o cache velho em qualquer falha. TTL de 6 h, porque posse
muda na escala de conquistas.

O que isso muda aqui: `max_radius` volta a ser **decisão de alcance** e deixa de
ser peneira de descoberta; `_candidate_pool()` ganha uma terceira fonte, mais
completa que as duas atuais e mais velha que o scan vivo (a ordem de precedência
continua "fresca vence"); e o painel para de mostrar id cru para aldeia fora do
cache.

**Pré-requisito ✅ MEDIDO em 2026-09-20 — e o conserto está liberado.**

```
GET https://br143.tribalwars.com.br/map/village.txt
200 · 6.327.655 bytes · 130.664 linhas · sem sessão, sem cookie

1,011,631,531,7363091,10106,0
2,K46+004,600,423,919524568,9622,0
3,004+-+Voyage,489,470,7941477,2596,0
```

Formato confirmado (`id,nome,x,y,player_id,pontos,rank`), nome URL-encoded
(`K46+004`), e passa folgado na guarda das 100 linhas. **O mundo tem 130.664
aldeias e o bot conhece 851** — ou seja, `cache/villages` cobre **0,65%** do
mundo, e os 332 do scan local cobriam 0,25%. A ordem de grandeza do funil é maior
do que esta seção estimava.

### ✅ O que foi feito (`P-CONQ-MAPA`, 2026-09-20)

**`game/world_villages.py`** (novo) — `WorldVillages`, uma instância por
processo criada em `twb.py` e compartilhada pelo ciclo, com TTL de 6 h, cache
em disco (`cache/world/villages_<mundo>.txt`, o arquivo cru) e as três guardas
que esta seção pedia. Ligada em `ConquestManager._candidate_pool()` como
terceira camada e injetada pelo `BarbarianTrainPlanner`.

**Medido antes e depois pelo `find_target()` real** (`tests/smoke_conquest_pool_census.py`,
novo; ele intercepta a lista que o laço produziu em vez de recalcular os
filtros — 24º padrão):

| cenário | pool antes | pool depois | candidatos antes | depois | na área |
|---|---|---|---|---|---|
| só a âncora (histórico) | 332 | 332 | 23 | 23 | 20 |
| as 2 origens com nobre | 851 | **2.290** | 96 | **198** | 121 |
| as 30 gerenciadas | 851 | **4.097** | 96 | **387** | 181 |

O alvo eleito é o **mesmo** (`#51991 570|293`) nos três cenários, antes e
depois — alargar a descoberta não desestabilizou a escolha.

**Custo**: o pool não vai a 130.937 porque o recorte por caixa de coordenadas
(`_world_box()`) roda **antes** de qualquer pontuação. `find_target()` inteiro
custa **0,39 s** com as 30 origens, contra 0,33 s antes. A representação em
memória é tupla e não dict, com o nome decodificado só na saída: **42,4 MB** e
0,22 s de carga, contra 65,9 MB e 5,5 s na primeira versão (medido; ver o 25º
padrão do `CLAUDE.md`, que é sobre exatamente esse tipo de custo).

⚠️ **A precedência desta seção estava errada para POSSE, e a medição inverteu.**
O texto acima dizia que o village.txt é "o mais completo e o mais velho ao mesmo
tempo", logo nunca autoridade sobre dono/pontos. Cruzando as 851 entradas de
`cache/villages` com o village.txt do mesmo instante:

```
cache diz BARBARA e o mundo diz JOGADOR ....  38   (idade do cache: 20,6 dias)
cache diz JOGADOR e o mundo diz BARBARA ....   0
```

38 a 0 não é ruído: bárbara virar aldeia de jogador é o que conquista faz, e o
cache local não fica sabendo. Para **posse**, quem apodrece é o `cache/villages`.
Então são duas perguntas com duas precedências:

- **descoberta** (quem existe e onde) — village.txt é o piso, as outras somam;
- **posse e pontos** — scan vivo > village.txt > `cache/villages`.

Deixar o cache ganhar em posse manteria 38 bárbaras-fantasma elegíveis, ou seja,
o bot mandando nobre contra aldeia de gente: o incidente da §8.7 por outra porta.
Verificado depois da correção: as 38 saem corrigidas e **nenhuma** sobra.

⚠️ **O cliente é `requests` puro, não o `WebWrapper`** — e isso não é
desleixo. `WebWrapper.post_process()` roda em toda resposta e faz
`del self.headers['x-csrf-token']` quando não acha `<meta name="csrf-token">`.
village.txt é texto puro e não tem, então baixá-lo pelo wrapper **apagaria o
token de CSRF da sessão** e quebraria os POSTs seguintes do ciclo
(recrutamento, mercado, envio). De quebra o wrapper rodaria dois regex sobre
6,3 MB e guardaria o corpo inteiro em `last_response`. A implementação de
referência do fork usa o wrapper e teria esse defeito.

**Testes:** `tests/test_world_villages.py` (19 casos, sem rede, fixture
verbatim de 8 linhas reais do br143 — inclui `30375`/`34331`, duas das 38
fantasma). Um deles reprovou a primeira versão e achou um defeito real: com o
TTL vencido e o refresh falhando, `rows()` devolvia `{}` e descartava a lista
boa ainda carregada em memória. Corrigido no código.

**Não validado em campo:** nenhum trem foi montado com esse pool ainda.

---

⚠️ **Não é a mesma pergunta que a §8.7 responde, e as duas não se substituem.**
`village.txt` diz *quem é o dono e onde fica*; o quadro de reservas diz *quem
pediu a aldeia*. Alargar a descoberta **sem** o filtro de reserva multiplicaria
justamente o risco do incidente da §8.7 — mais alvos visíveis, mais chance de
pisar em reserva alheia. Por isso a Fase 1 da §8.7 entrou primeiro.

---

## 8.7 `P-CONQ-RESERVA` — o bot conquistou aldeia reservada por companheiro de tribo

**Relatado pelo usuário em 2026-09-20**, sobre uma conquista de poucos dias
antes. A descrição dele: *"ficou uma situação meio chata"*. Qual alvo foi não
está identificado, e tentar deduzir pelo log esbarra no **nono padrão**: o log
registra o que o *bot* fez, não o estado do mundo. A reserva foi feita por outra
pessoa, então ela é invisível aqui por construção.

### Por que aconteceu

O bot **não tem o conceito de reserva**. `ConquestManager.find_target()` elege
alvo por dono (bárbara), raio, pontuação e área de interesse
(`attack.py:1125–1229`), e nenhum desses filtros sabe que outro jogador da tribo
pediu aquela aldeia. Não é bug de implementação: é uma regra do mundo social que
nunca foi modelada. O `_prefer_area_of_interest` já codifica **uma** regra de
tribo (a formulação do fórum do SQUAD 02, `attack.py:1242`), o que prova que o
canal existe e que só esta regra ficou de fora.

### Custo de errar, e por que ele é assimétrico

Um falso negativo (pular alvo que não estava reservado) custa **uma bárbara** —
há dezenas no K25. Um falso positivo (nobrar reserva alheia) custa capital
social na tribo, é irreversível, e o bot já gastou 4 nobres e uma moeda para
causar isso. **Na dúvida, pular.** É o inverso da regra do `_source_reaches`, e
de propósito: lá o falso positivo só custava um comando recusado.

### A fonte existe, é oficial e é estruturada (respondido pelo usuário, 2026-09-20)

```
game.php?village=<vid>&screen=ally&mode=reservations
```

Sistema **oficial de reservas da tribo**, ligado no br143. Isso derruba o pior
cenário que esta seção antecipava (parser de texto livre sobre post de fórum) e
muda a solução de "não ofender" para **integração de mão dupla**, que é a
formulação do usuário:

> *"Se eu colocar uma aldeia manual na conquista pvp, o bot deve registrar a
> reserva caso ele não encontre ela já feita, mesma coisa para a aldeia bárbara.
> E caso ele encontre uma reserva para a aldeia bárbara que eu coloquei
> manualmente ou ele decidiu automaticamente, ele deve procurar outra aldeia."*

São duas obrigações distintas, e só a primeira é defensiva:

- **Ler** — alvo reservado por **outra pessoa** sai da seleção, em todos os
  caminhos. Isto é somente leitura e não tem efeito social nenhum.
- **Escrever** — alvo que o bot assume (automático **ou** enfileirado à mão) e
  que ainda não tem reserva, ganha uma **em nome da conta**. Isto **publica
  intenção num quadro compartilhado com outros humanos**, e é o inverso do
  incidente: em vez de o bot atropelar a tribo em silêncio, ele avisa.

⚠️ **Escrever tem custo social próprio, na direção oposta.** Sentar em reserva que
nunca vira conquista é tão mal visto quanto furar reserva alheia. Então a escrita
só se justifica junto com o **ciclo de vida completo**: reservar ao assumir o
alvo, e **liberar** ao abortar, perder o alvo (`status: lost`) ou concluir. E
liberar **apenas o que o bot criou** — reserva feita à mão pelo usuário é dado de
outra procedência e o bot não é dono dela (§8.3).

Isto é um **quinto mecanismo de reserva** no inventário da §8.2, e o único cujo
escopo é *outra pessoa*: os quatro atuais disputam recurso dentro da conta
(tropa, recurso, mercador, slot temporal); este disputa **alvo dentro da tribo**.
Não reutilizar o vocabulário de `_reserve`/`_release` do `conquest_planner` sem
qualificar — lá "reserva" é tropa. Dois significados para a mesma palavra no
mesmo módulo é como a §8.2 começou.

### ✅ A captura foi feita (2026-09-20) — e corrigiu três coisas que esta seção assumia

Capturada com o `WebWrapper` do próprio bot (7º padrão). Dump local em
`cache/debug/reservations_plain.html`; fixture verbatim em
`tests/test_tribe_reservations.py`. O que a tela respondeu:

- **Identifica pelos dois.** O alvo sai de `data-id` no
  `span.village_anchor`, e o nome traz `(x|y)` — então a exclusão funciona por
  id **e** por coordenada. ⚠️ O `id` do `<tr id="reservation_75920">` é o id da
  **reserva**, não da aldeia (`40808`); confundir os dois faria a exclusão nunca
  casar com `cache/conquest` e falhar calada.
- **Traz o reservante**, com id e nome (`info_player&id=919714218`), e a tribo
  dele quando tem. ⚠️ A célula tem **dois** links quando há tribo, e o da tribo
  vem primeiro — "o primeiro id da linha" traria a tribo; na linha de aldeia de
  jogador, "o último" traria o ícone de mapa.
- **Expira: 3 dias** (`Limite de tempo: 3 dias`, lido de
  `p#reservation_settings`; limite de 5 aldeias por jogador, espera 0). A coluna
  5 é **"Data de validade"**, não data de criação — o `<th>` ordena por
  `sort=expires_at`. Isso **derruba a preocupação** desta seção: 3 dias é muito
  maior que as ~4 h de um trem, então uma reserva do bot caducando no meio do voo
  não é o risco que se antecipava. A Fase 1 guarda o texto **cru**, sem parse: o
  servidor não lista o que já expirou, então estar na lista já significa
  reservada, e um parser de data relativa em português ("hoje às 07:45") seria
  fragilidade de graça.
- **A conta TEM o direito de reservar** (o formulário de configurações e o de
  criar reserva renderizam). O caso "sem direito" não foi observado, e o parser
  foi escrito para não depender disso: ele lê só as linhas
  `<tr id="reservation_N">`, nunca os formulários.

**Duas descobertas que a seção não previa, e que mudaram o desenho:**

1. **A lista é paginada, e é grande.** O default são 10 por página e havia **49
   páginas / 489 reservas**. Um GET ingênuo teria lido só as 10 primeiras e o bot
   acharia que 479 alvos estavam livres — um falso negativo em 98% do quadro, e
   silencioso. **`&page=all` traz tudo numa requisição** (707 KB, medido). O
   tamanho de página também é configurável na tela, mas por POST e a configuração
   é **compartilhada com a tribo inteira**: mexer nela mudaria a interface de
   outras pessoas para conseguir uma leitura (21º padrão).
2. **O quadro é compartilhado com tribos ALIADAS**, não só a própria — a tela tem
   filtro `[Sua]` / `[Tribo]` / `[Aliados]`, e das 489 só **1** era da conta
   (`group_id=creator_id&filter=5955651`). A exclusão respeita **todas**, porque
   "na dúvida, pular" e furar reserva de aliado custa o mesmo.

**A identidade sai do jogo, sem config nova:** `game_state.player.id`
(`5955651`) vem na própria resposta da tela de reservas, e é o mesmo número que o
filtro `[Sua]` usa — ou seja, o jogo concorda que é esse o campo que identifica o
criador. Uma chave de config com o id errado faria o bot furar reserva alheia
(achando que é sua) ou barrar os próprios alvos, sem nada no log denunciando.

#### ✅ Payload de escrita capturado em 2026-09-21

Não precisou de DevTools nem de criar reserva nenhuma: os formulários estão no
HTML da própria tela que a Fase 1 já baixa. Recorte verbatim de
`screen=ally&mode=reservations&page=all`:

```html
<form action="/game.php?village=41123&screen=ally&mode=reservations
             &action=new_reservation&group_id=all&filter=&h=32afa79e" method="post">
  <input type="hidden" name="x[]" id="inputx">
  <input type="hidden" name="y[]" id="inputy">
  <input type="radio" name="target_type" value="coord" checked="checked">
  <input type="radio" name="target_type" value="village_name">
  <input type="radio" name="target_type" value="player_name">
  <input type="text" name="input" class="target-input-field ...">
  <input id="save_reservations" class="btn" type="submit" value="Reservar esta aldeia" />
  <input class="comment_input" type="text" name="comment[]" placeholder="Comentário"/>
</form>
```

Criar: `POST action=new_reservation&h=<csrf>` com
`x[]`, `y[]`, `target_type=coord`, `input=`, `comment[]`. Os `[]` não são
enfeite — a tela cria **várias** reservas de uma vez.

⚠️ **Repare no formato do destino:** coordenada em campos `x`/`y` separados, e
não um `village_id`. É a mesma forma que o envio de recursos da Feature 9
exigia, e que custou uma reescrita inteira quando foi assumido como
`target_village`. Vale como confirmação de que este jogo endereça aldeia por
coordenada nos formulários de ação.

Remover, de brinde no mesmo HTML: `POST action=submit` com `ids[]=<id>` (um por
reserva) e o botão `delete_claims`. Há também `export_claims`, que exporta as
selecionadas — possivelmente uma leitura mais barata que o HTML de 633 KB, a
avaliar se a lista crescer.

**E uma regra da tribo que ninguém tinha lido — ela muda o desenho da Fase 2.**
O formulário `action=save_reservation_settings` publica a configuração vigente:

```html
<input id="reservation_limit"    name="reservation_limit"    value="5" />
<input id="reservation_time"     name="reservation_time"     value="3" />
<input id="reservation_cooldown" name="reservation_cooldown" value="0" />
```

**Limite de 5 reservas simultâneas por jogador**, validade de 3 (dias, a
confirmar contra `/page/settings`), sem espera entre uma e outra. Ou seja, a
Fase 2 não é "reservar o que o planejador eleger": é gastar um recurso escasso
de 5 vagas que **expiram**, competindo com as reservas manuais do próprio
usuário. Um gate `reserve_targets` que reservasse livremente encheria as 5
vagas com alvos de bárbara e deixaria o usuário sem conseguir reservar nada —
sem erro, só recusa.

#### ✅ Canário executado em 2026-09-21, e ele respondeu três coisas

Autorizado pelo usuário, feito pelo cliente do jogo no Chrome.

**1. Criar funciona, e o payload está certo.** `582|289` (Aldeia-bonus, 1.007
pontos, dono `---`, bárbara de fato) foi reservada:

```
POST game.php?village=49709&screen=ally&mode=reservations
     &action=new_reservation&group_id=all&filter=   ->  200
```

Validade `em 24.09. às 07:49`, criada às 07:49 de 21/09 — os **3 dias** de
`reservation_time` medidos, não deduzidos.

**2. Alvo já reservado é recusado pelo servidor, e a vaga NÃO é consumida.**
Tentando `546|377`, reservada por um aliado, a resposta verbatim foi:

> ⛔ **Um aliado já reservou MadaraSupremo de aldeia (546|377)!**

A lista continuou com as mesmas 3 reservas. Isso é melhor do que o desenho
assumia: a Fase 2 **não precisa** checar o quadro antes de tentar para evitar
desperdiçar vaga — o jogo é a autoridade e recusa de graça. O quadro continua
valendo para *não gastar requisição* e para escolher alvo, mas deixa de ser uma
trava de correção. Note o "aliado": a mensagem para alvo de companheiro da
própria tribo pode ter outra redação, e um parser que case só esta frase erra
o outro caso (15º padrão ao contrário — detector que nunca dispara).

**3. O quadro é da ALIANÇA, não da tribo.** A tela informa
*"Sistema de reservas compartilhado com: Os Randola, Inquisition"*. A §8.7
inteira fala em "companheiro de tribo"; o conjunto real de gente cuja reserva
nos bloqueia é maior que isso.

⚠️ **E o argumento de que "o bot não encheria as 5 vagas" não sobreviveu à
medição.** No momento do canário o usuário **já tinha 2 reservas manuais**
(JULIET 557|293 e 000 555|288); com a do canário, **3 de 5 ocupadas**, e as
três expiram sozinhas em até 3 dias. A Fase 2 não entra num quadro vazio —
entra num quadro que já está 60% cheio de decisões manuais do próprio usuário.
Qualquer gate precisa de teto próprio (ex.: o bot nunca ocupa mais que N vagas)
e de respeito à expiração, senão ele compete com o dono da conta.

### Faseamento

**Fase 1 — somente leitura, e é ela que fecha o incidente.** ✅ **Implementada em
2026-09-20.** `core/extractors.py::tribe_reservations` / `own_player_id`,
`game/reservations.py::ReservationBoard` (TTL de `reservation_cache_seconds`,
default 600 s, com graça de 6× para não transformar soluço de rede em bloqueio
total), config `conquest.respect_tribe_reservations` (default **true**) e
`conquest.excluded_targets`. Um quadro por ciclo, compartilhado, instanciado em
`twb.py`. Testes: `tests/test_tribe_reservations.py` (parser + quadro) e
`tests/test_conquest_reservation_gate.py` (os caminhos).

Exclusão **dura** — não preferência, ao contrário da área de interesse. Onde
entrou, e ⚠️ **a correção de uma coisa que esta seção dizia errado**: o texto
abaixo mandava ligar no `ConquestManager.find_target()` como se ele fosse o lugar
onde a conquista começa, mas desde a Feature 27 o `ConquestManager.run()`
**não monta mais trem** — quem chama `find_target()` é o
`BarbarianTrainPlanner`. São os mesmos caminhos, com um quinto que a seção não
listava (16º padrão: este documento é memória, não especificação).

- `ConquestManager.find_target()` — a guarda "sem leitura não inicia conquista"
  fica **antes** de tudo, porque a fila manual tem prioridade absoluta logo
  abaixo e uma guarda depois dela deixaria o caminho manual passando às cegas;
- `ConquestManager._candidate_pool()` / laço de `find_target()` — eleição
  automática, alvo reservado sai da lista;
- `ConquestManager._get_manual_target()` — alvo enfileirado à mão pode ter sido
  reservado **depois** de entrar na fila. Vira `status: blocked`, **não**
  `invalid`: a causa é externa e reversível (expira em 3 dias, e pode ser solta
  antes), enquanto `invalid` é para alvo que nunca vai servir;
- `ConquestManager._handle_existing()` — conquista **já em andamento**. Sexto
  padrão: reconferir a premissa no momento de agir. Encerra como `blocked` e para
  de comprometer nobres novos, sem desfazer nada — nobre que saiu não volta,
  igual ao caminho `lost`;
- `BarbarianTrainPlanner._cancel_reserved_targets()` — **o caminho que a seção
  não previa, e o único onde ainda dá para evitar a ofensa em vez de só parar de
  piorar.** Em `train_scheduled` nada saiu: o Hunter está dormindo até o
  `send_time`. Marcar o registro como bloqueado **sem apagar o schedule** seria
  bloqueio cosmético — o Hunter não conhece conquista, só manda ataque na hora
  marcada, e despacharia o trem inteiro contra a reserva alheia com o
  `cache/conquest` já dizendo `blocked`. Os dois morrem juntos, e o cancelamento
  roda **antes** de `_release_orphan_reserves()` de propósito, senão a reserva de
  **tropa** sobreviveria mais um ciclo;
- `PvpConquestManager.run()` — por decisão do usuário o sistema vale para **toda**
  conquista. Vira `status: failed` e não um estado novo, porque é `failed` que faz
  `_sync_source_locks()` soltar as travas de origem; inventar status exigiria
  reler todo consumidor (P2-22).

**Reserva de ALVO ≠ reserva de TROPA.** `game/reservations.py` abre com esse
aviso: `_reserve`/`_release`/`conquest_reserve` são **tropa**, e nada no módulo
novo usa esses nomes. Dois significados para a mesma palavra no mesmo módulo é
como a §8.2 começou.

Junto, e barato: `conquest.excluded_targets` (id ou `"xxx|yyy"`) como **válvula
de escape manual**, para reserva combinada fora do jogo ou alvo que o usuário
quer barrar por qualquer outro motivo. Deixa de ser a solução e passa a ser o
override; com a leitura oficial funcionando, tende a ficar vazia.

Registrar em `cache/conquest/*.json` **por que** o alvo foi barrado e **quem**
reservou — sem isso, daqui a um mês ninguém sabe se a exclusão ainda vale.

**Fase 2 — escrita, com gate próprio e canário.**
Ao assumir um alvo sem reserva, criar uma em nome da conta; liberar ao abortar,
perder ou concluir, e **só o que o bot criou**. Como isso é visível para outras
pessoas da tribo:

- config próprio (`conquest.reserve_targets`), **default off**;
- primeira execução é canário de **uma** reserva, conferida a olho no jogo antes
  de liberar o resto — o mesmo protocolo da validação de bandeiras;
- falha do POST nunca vira sucesso presumido; sem confirmação, o alvo **não**
  conta como reservado.

### Aceite

Estado em 2026-09-20 — ✅ = coberto por teste, ⏳ = falta campo.

- ✅ Nenhum alvo reservado por terceiro é eleito, enfileirado ou mantido em
  conquista — nem pelo `ConquestManager`, nem pelo `PvpConquestManager`.
- ✅ Barrar um alvo **em andamento** encerra a conquista com status próprio
  (`blocked`) e libera as reservas de **tropa**, sem deixar reserva órfã. Não foi
  reimplementado: `_release_orphan_reserves()` já solta toda reserva
  `barb_train:*` cujo alvo saiu de `train_scheduled`, e é por isso que o
  cancelamento roda antes dela. Reusar o mecanismo que já existe para o P2-22 é
  melhor que escrever um segundo.
- ✅ Falha ao ler a tela **não** libera geral. Na dúvida = não iniciar conquista
  nova (`_may_start_new_conquest()`); conquista já em andamento **segue**, porque
  abortar por falha de leitura joga fora tropa real. Os dois lados têm teste, e o
  segundo é o que mais fácil se escreveria errado.
- ✅ Teste sem rede cobrindo os cinco caminhos, exclusão por coordenada além de
  por id, e "reservado por mim" contra "reservado por outro".
- ⚠️ Fixture: **duas das três linhas são verbatim.** A terceira ("reservado por
  mim") é derivada — a captura dela foi interrompida. O que é medido: o filtro
  `[Sua]` devolve exatamente 1 linha, logo a conta tem uma reserva própria e o
  jogo a identifica por `creator_id=5955651`. O que não foi observado: essa linha
  renderizada. **Trocar pela real na próxima captura**, porque markup suposto é o
  que fez `loyalty_from_report()` falhar. Está anotado no topo do arquivo de
  teste, não só aqui.
- ✅/⏳ **Primeira observação em campo: 2026-09-20, dois ciclos (10:03 e
  12:16).** Dos três sinais previstos:
  1. ✅ `Reservations: 480 reservas no quadro da tribo (1 minhas, 479 de
     terceiros)` e, no ciclo seguinte, 482 (1 / 481). Não vieram 10 — o
     `&page=all` pegou;
  2. ✅ **na metade que o log consegue provar, e é a metade que importa.** O
     `own_player_id` foi lido do `game_state` ao vivo e casou com **exatamente
     1** das 480 reservas, que é o número real da conta. Era isso que a fixture
     derivada não provava: a separação "minha" × "de terceiro" funciona sobre o
     quadro real. O que ainda **não** foi exercitado é o gate em si — ver abaixo;
  3. ✅ zero ocorrências de `sem leitura do quadro de reservas`.
- ⏳ **O gate nunca rodou.** Nenhuma linha de `Conquest:` no log inteiro: o
  `BarbarianTrainPlanner` roda depois do laço de aldeias, e nos dois ciclos ele
  não foi alcançado — o ciclo 1 morreu às 12:15 num crash e o ciclo 2 ainda
  estava na 28ª aldeia quando o bot parou. Ou seja, "a reserva própria não
  apareceu como bloqueio" é verdade e **vazio**: nada foi bloqueado porque nada
  foi avaliado.
- ✅ **Crash "não relacionado" que era a causa de o gate nunca rodar — corrigido
  em 2026-09-20.** Ver §8.8.

---

## 8.8 ✅ `P-MAPA-REDE` — 14 segundos de DNS custavam o ciclo inteiro (2026-09-20)

**Escolhido como próxima implementação porque não era um item de backlog: era o
motivo pelo qual três features prontas seguiam sem validação em campo.** A §8.7
o classificava como "crash não relacionado". Ele é o oposto de não relacionado —
o `BarbarianTrainPlanner` roda **depois** do laço de aldeias, então qualquer
exceção no meio do laço mata justamente o que estava esperando observação.

### O incidente

`session_latest.log`, 2026-09-20:

```
12:15:47 - Requests - WARNING - GET .../screen=map: ... [Errno 11001] getaddrinfo failed
I crashed :(   'NoneType' object has no attribute 'text'
  game/village.py:950  in ensure_map_loaded -> self.area.get_map()
  game/map.py:53       in get_map           -> Extractor.game_state(res)
  core/extractors.py:144 in game_state      -> res = res.text
12:16:01 - Requests - DEBUG - GET .../screen=overview [200]
```

**A rede voltou 14 segundos depois.** O custo foi o ciclo das 28 aldeias, o
planejador de conquista e, por tabela, a validação de `P-CONQ-RAIO`,
`P-CONQ-MAPA` e do gate de reservas. É o **2º padrão** em caminho quente:
`get_action` devolve `None` em qualquer exceção e ninguém guardava.

### A segunda metade, que é onde a correção ingênua erraria

`Map.fetch_delay` é **8 h** e a instância de `Map` **sobrevive entre ciclos**
(`village.py:945`), enquanto `last_fetch` era estampado **antes** de saber o
resultado (`map.py:51`). Um `if res is None: return False` seco teria trocado o
crash por um **apagão silencioso de 8 horas**: bot vivo, sem mapa, logo sem farm
e sem eleição de alvo, e nada no log dizendo isso depois da primeira linha —
exatamente o 15º padrão (detector que não detecta) com outra máscara. A janela
agora só fecha com **leitura bem-sucedida**; restaurar o valor anterior é seguro
porque só se chega à requisição quando ela já venceu, e há um único chamador por
ciclo.

### O que mudou

- `Map.get_map()` — guarda de `res is None` com WARNING nomeando a consequência,
  retorno `False` (o falsy que `attack.py:1210` e `conquest_planner.py:265` já
  tratavam) e `last_fetch` restaurado;
- idem quando a leitura falha por outro motivo (200 de login/bot protection):
  `get_map_old()` devolvendo `False` também não fecha a janela;
- `Map._fallback_location()` — os dois pontos que indexavam
  `game_state["village"]["x"]` sem guarda. `Extractor.game_state` tem
  `return None` implícito, então um 200 fora da tela de mapa derrubaria o ciclo
  aqui também. Degrada para `my_location = None`, que os consumidores tratam.

**Não** mexi em `Extractor.game_state`: guardar lá esconderia a mesma classe de
falha nos ~20 outros consumidores, que querem saber. A guarda fica no chamador.

### Testes

`tests/test_map_fetch_guard.py`, com o recorte do log real na motivação. Os seis
casos foram rodados **contra a versão pré-correção** (cópia do `HEAD` numa árvore
temporária, sem stash destrutivo): **12 asserções falham lá e passam aqui**,
incluindo o `AttributeError` idêntico ao de produção. Guarda que não pode falhar
é o 21º padrão de cabeça para baixo.

⏳ **Falta campo:** o próximo ciclo completo tem que alcançar o
`BarbarianTrainPlanner`. O sinal de que esta correção funcionou não é ausência de
crash — é a **presença** de linhas `Conquest:` no log, que nunca apareceram.

---

## 8.9 ✅ `P-SESSAO-INPUT` — os dois `input()` do caminho quente (2026-09-20)

Itens **1 e 3** da fila tática da §7.10, feitos juntos porque o segundo é
pré-requisito silencioso do primeiro (ver "Por que os dois juntos" abaixo).

### O defeito

`core/request.py` tinha dois `input()` num programa que o painel sobe sem
console:

```
core/request.py:79   input("Press any key...")               # captcha
core/request.py:115  input("Enter browser cookie string> ")  # sessão vencida
```

O segundo tem prova em disco desde **30/06/2026**: o `bot_output.log` registra
duas tentativas seguidas de iniciar pelo painel, ambas terminando na linha
`Enter browser cookie string> ` com o processo **vivo, com pid válido e parado
para sempre** — e o painel, que só olhava o pid, dizendo "rodando" (22º padrão).
Ninguém leu porque o sintoma visível era "iniciar pelo painel não é confiável", e
não um erro.

O do captcha era pior por três razões independentes:

1. **Quem resolve o captcha resolve no navegador**, não no console do bot. A
   tecla só era apertada quando alguém passava na frente da máquina — o prompt
   não observava a coisa que dizia esperar.
2. O `input()` estava **dentro do `try`**, então um stdin fechado levantava
   `EOFError`, era engolido pelo `except Exception` e virava `GET ...: EOF when
   reading a line` no log. O motivo real (captcha) sumia — 2º padrão com outra
   máscara.
3. **O POST não tinha guarda nenhuma.** Construção, recrutamento, coleta e envio
   de ataque passam por `post_url`, e a página de bot protection volta com
   **200**: o chamador a tratava como ação aceita. Um captcha durante um ciclo
   era um no-op silencioso em toda ação de escrita — 15º padrão na forma de
   detector que nunca dispara.

### O que mudou

**Captcha → `WebWrapper._await_captcha_clear()`.** O bot reconfere a página a
cada `CAPTCHA_POLL_SECONDS` (60 s) e retoma sozinho. A espera é **sem limite** de
propósito: desistir devolveria `None` para todo mundo e faria os managers
decidirem sobre dado ausente, e o captcha não se resolve sozinho. Cada tentativa
loga, então a idade da última linha do log — o único sinal honesto de atividade
(22º padrão) — continua andando enquanto o bot espera.

Duas decisões que a versão ingênua erraria:

- **A página bloqueada não passa por `post_process()`.** Ela não tem
  `csrf-token` nem `&h=`, e o `elif` do `post_process` **apaga** o token quando
  não acha um — o bot voltaria do captcha sem conseguir agir.
- **O POST bloqueado devolve `None` e a ação NÃO é refeita.** As duas
  alternativas são erradas em direções opostas: devolver a página de captcha faz
  o chamador achar que a ação foi aceita; reenviar o POST às cegas duplica ataque
  ou construção — exatamente o estrago da §8.7. `None` é o valor de falha que os
  chamadores já tratam, e a ação fica para o próximo ciclo.

**Sessão → `cache/cookies.txt`.** Ordem: `cache/session.json` →
`cache/cookies.txt` → espera o arquivo aparecer (poll de 15 s, instrução
reimpressa a cada 10 min). Nada é persistido antes de a sessão ser **provada**
com um GET logado, então um cookie vencido colado por engano não sobrescreve mais
o `session.json` que funcionava — a versão antiga gravava incondicionalmente logo
depois do `input()`.

O prompt não foi mantido nem para quem tem console, e o motivo é do fork
LazyTurtle: **o buffer de linha do `cmd.exe` é menor que um cookie de Tribal
Wars**, então colar ali trunca a string em silêncio — o bot aceita, o servidor
não, e todo ciclo seguinte diz "sessão inválida" sem dizer por quê. Arquivo não
tem limite de linha, pode ser escrito de fora do processo e é lido como
`utf-8-sig` (o BOM do Bloco de Notas corromperia o **primeiro** cookie, e só
ele). O parser tolera o prefixo `cookie:` colado inteiro do DevTools.

**De brinde, o user-agent.** `twb.py` aplicava `headers["user-agent"]` **depois**
de `start()`, então a única requisição que validava a sessão saía com o UA falso
do default da classe — 7º padrão, sondar com o cliente errado. Agora o UA é
aplicado antes, o que importa mais do que antes porque `start()` passou a poder
emitir várias requisições.

### Por que os dois juntos

O caminho de captcha **chama** `Notification.send`, e ele está dentro do `try` do
`get_url`. Com o `send` propagando — e ele propagava: não havia `try/except`
nenhum e `telegram` faz rede —, um timeout do Telegram no instante do captcha
viraria um "GET falhou" genérico e a espera inteira seria pulada. Corrigir o item
1 sem o 3 seria construir a guarda em cima do mesmo alçapão.

`core/notification.py` ficou: config **preguiçoso** (nada de I/O no `import`, que
é o 20º padrão — o módulo instancia o objeto no corpo, e `twb.py`, o webmanager e
vários testes o importam) e `send()` que **nunca** propaga. O outro chamador é
`twb.py`, que notifica de dentro de um `except` no handler de crash: uma exceção
secundária ali escapa do laço de retry e o bot **sai** em vez de reiniciar. O
fork registra isso acontecendo em 2026-08-03. Efeito colateral bom da preguiça:
`notifications.enabled` passou a valer **ao vivo**, sem reiniciar o bot.

**Não** implementado de propósito: o filtro por categoria (`notify_<categoria>`)
que o fork tem. Ele exige chaves novas em `config.example.json` e, por tabela,
bump de `build.version` — o que dispara o merge no `config.json` vivo de 27
aldeias, e `merge_configs()` descarta chave global que só exista lá. Fatia
própria, não brinde desta.

### Testes

`tests/test_session_and_captcha.py` (19 checagens) e
`tests/test_notification_safety.py` (5). Sem rede, sem relógio real e sem tocar
`cache/session.json` ou `cache/cookies.txt` reais — `FileManager`, `time` e
`Notification` são substituídos no namespace do módulo (21º padrão: um teste não
obtém sua verificação escrevendo no artefato de produção).

Rodados **contra a versão pré-correção**, numa árvore temporária do `HEAD`:
falham **19 e 5** checagens lá e passam aqui. Entre elas, as duas que são o
incidente em pessoa: `o caminho de captcha chamou input(): ['Press any key...']`
e `test_start_espera_arquivo_aparecer levantou EOFError: stdin fechado (bot sem
console)`.

⏳ **Falta campo:** nenhum captcha real aconteceu desde a mudança. O sinal de que
funciona é a sequência `Bot protection!` … `Bot protection saiu apos Ns,
retomando` no `session_latest.log`, sem intervenção. O caminho de
`cache/cookies.txt` também só será exercitado quando a sessão atual vencer.

---

## 8.10 ✅ `P-TRAVA-INSTANCIA` — dois `twb.py` na mesma conta (2026-09-20)

Item 2 da fila tática da §7.10 e item 7 da §9. **Local, sem rede.**

### O buraco que sobrou

O 22º padrão fechou "o painel sobe um segundo bot": `BotManager.is_running()`
varre `psutil.process_iter` pelo cwd do repositório, então um bot iniciado no
`cmd` é detectado e o botão Iniciar não sobe outro. O que ele **não** cobre é o
caminho sem painel — dois `cmd` abertos na mão, ou um `python twb.py` novo com o
anterior minimizado. Aí rodam duas sequências de requisições concorrentes na
mesma conta (risco de ban, que é o que o P2-32 existia para matar) e dois
processos escrevendo no mesmo `cache/`.

### Por que não dá para transplantar a do fork

`attack_scheduler.py::_Lock` do fork principal faz `if fcntl is None: return
self`. No Windows `fcntl` não existe, então a trava é **no-op** — uma guarda que
nunca dispara, que é o 15º padrão de cabeça para baixo. Reescrita aqui com
`msvcrt.locking` no Windows e `fcntl.flock` no resto.

### Desenho, e as três decisões que não são óbvias

`core/instance_lock.py`. A trava é uma **região de 1 byte** de um arquivo,
travada pelo SO.

1. **Região do SO, não PID file.** O SO solta a trava quando o processo morre,
   inclusive em `kill -9`. PID file precisa de detecção de staleness, que erra
   nos dois sentidos: PID reciclado = trava eterna, processo vivo mal lido =
   dois bots. Coberto por `test_lock_dies_with_the_process_even_without_release`,
   que mata o dono com `os._exit(0)`.
2. **Metadados a partir do byte 1**, fora da região travada. No Windows uma
   trava exclusiva impede até a **leitura** da região — medido: um `f.read()`
   do arquivo inteiro levanta `PermissionError(13)`, e `f.seek(1); f.read()`
   funciona. É isso que permite ao segundo processo dizer *quem* está segurando
   (pid, hora de início, cwd) em vez de só "ocupado".
3. **Arquivo no temp do usuário, não em `cache/locks/`.** A trava é *por conta*;
   se morasse no checkout, dois clones apontando para a mesma conta não se
   enxergariam — e a chave ser o endpoint viraria decoração, porque só existe um
   `config.json` por checkout. O temp do usuário é o menor escopo que cobre
   "mesma pessoa, mesma conta, qualquer pasta".

**Política de falha, deliberadamente assimétrica:** conflito de trava **fecha**
(`sys.exit(1)` com o dono identificado); erro inesperado de I/O na própria trava
**abre** com WARNING, porque um mecanismo de guarda quebrado não pode ser o que
impede o bot de rodar. `acquire()` distingue os dois (`degraded`).

### Onde a verificação entra — e por que no topo do arquivo

No `if __name__ == "__main__":` de `twb.py`, **antes do tee de log**. Não é
estética: o tee abre `cache/logs/session_latest.log` com `open(..., "w")`, que
**trunca**. Verificação mais adiante deixaria um segundo `python twb.py`
destruir o log do bot que está rodando antes de ser recusado — o estrago do 20º
padrão entrando por outra porta. Custo aceito e registrado no código: é o único
import de projeto acima do tee, então um erro de sintaxe nele não apareceria no
arquivo de log; o módulo é só stdlib, é coberto por teste, e o import falha
**fechado**.

### Medido, não suposto

- Conflito no Windows 10 / Python 3.13 devolve `PermissionError(errno 13)`, sem
  `winerror` — **não** o `EDEADLOCK (36)` que a documentação do CRT sugere. Os
  dois entram no `except`, mas 13 é o observado com dois processos reais.
- A suíte (46 arquivos) passa. `tests/test_instance_lock.py` cobre slug,
  recusa cross-process, isolamento entre contas diferentes, release, morte do
  dono, reaquisição no mesmo processo (o `main()` recria `TWB` até 3 vezes) e a
  ordem trava-antes-do-tee no fonte de `twb.py`.
- **A guarda foi provada capaz de falhar** (21º padrão): com
  `_lock_first_byte` neutralizado numa cópia do módulo, os dois processos
  adquirem — que é exatamente o no-op do fork. Sem esse passo, um teste verde
  não distinguiria "funciona" de "não faz nada".

### Testes

`tests/test_instance_lock.py` (na suíte; usa subprocessos locais e
`tempfile`, nunca `cache/locks`). Trava de arquivo é **reentrante dentro do
mesmo processo**, então teste in-process não conseguiria distinguir trava real
de no-op — subprocesso não é luxo aqui.

`tests/smoke_instance_lock_twb.py` (**fora** do glob `test_*.py`, rodar na mão):
ponta a ponta contra o `twb.py` de verdade. Copia o repositório para um temp,
toma a trava da conta real, roda `python twb.py -i` **na cópia** e verifica
código 1, mensagem com o pid do dono, e uma sentinela intacta no log de sessão
da cópia. A cópia existe justamente para não rodar `twb.py` no repositório real:
o tee truncaria o log do bot em produção, ou seja o teste seria a própria coisa
que ele existe para impedir (21º padrão). O que a cópia **não** isola é a trava,
e esse é o ponto — passar prova que ela atravessa pastas diferentes.

### ⏳ Limitação de transição, que vale enquanto o bot atual não reiniciar

O bot em execução no momento da mudança (pid 11936, iniciado antes) **não segura
trava nenhuma**. Até o próximo restart, a proteção não vale para ele: um
`python twb.py` agora adquiriria a trava normalmente e subiria o segundo bot.
O aceite é reiniciar o bot e confirmar que um segundo `python twb.py` é recusado
citando o pid do primeiro.

---

## 8.11 ✅ `P-BAND-OFERTA` — a política de bandeira não contava a oferta (2026-09-20)

Item 9 da fila tática da §7.10, e a pergunta que a §6.3 marcava como
pré-requisito para fechar a validação de bandeiras. **Local depois da medição;
a decisão que mudou é qual dado autoriza mover uma bandeira.**

### As duas medições que responderam a pergunta

**1. Bandeira equipada SAI do inventário.** `setFlagCounts` do br143, lido ao
vivo em 2026-09-20 (`tests/smoke_flag_inventory.py`):

```
tipo 1 (produção)  -> todos os níveis "0"
tipo 2 (recrut.)   -> todos os níveis "0"
tipo 7 (cunhagem)  -> todos os níveis "0"
tipo 6 (população) -> nível 2: 1, nível 3: 2, nível 4: 1
```

E, no mesmo instante, **28 das 30 aldeias usam justamente um dos tipos 1, 2 ou
7**. Os dois fatos só fecham de um jeito: o que a tela publica é a **sobra**, e
`flag_set` não copia bandeira — ele **move** a única que existe. O fork estava
certo no diagnóstico de fundo (§6.3): bandeira é inventário **de conta**, então
dar uma à aldeia B é tirá-la da aldeia A.

**2. O bot descartava a quantidade.** `manage_flags()` colapsava o inventário em
`{tipo: maior nível com amount > 0}`. "Tenho uma sobrando" e "tenho cinco" eram
o mesmo dado — e a resposta à pergunta "dez aldeias querem um tipo do qual
possuímos três" era *cair em silêncio para o próximo tipo da lista*.

### O que realmente segurava o Bug 1, e por que isso é frágil

Com o inventário real, **as 30 aldeias escolhem o mesmo `(tipo 6, nível 4)`** —
e existe exatamente **uma** bandeira tipo 6 nível 4 na conta. O único motivo de
não haver vaivém hoje é a **guarda de rebaixamento**: quase toda aldeia já usa
um tipo mais alto na preferência, e por isso retorna antes. Não é a oferta que
protege; é um acidente da alocação atual. Uma aldeia recém-conquistada (sem
bandeira) ou uma usando tipo fora da preferência cai direto no `flag_set`.

### A causa real não era a quantidade — era decidir sobre leitura velha

O servidor **já é** o ledger de oferta, justamente porque a bandeira equipada
sai do inventário. O que faltava era não decidir sobre uma foto antiga dele:
`manage_flags()` só lê de fato a cada 3 a 8 runs (randomização) e o
`DefenceManager` **sobrevive entre ciclos** (`village.py`: `if not self.def_man`),
enquanto `flag_logic()` roda **todo** ciclo.

Evidência de que a crença envelhece **errado**, medida no `cache/managed` real:

```
BBM 029 acreditava: tipo 6 -> nível 7 disponível
servidor no mesmo dia: tipo 6 não passa do nível 4
onde foi parar a de nível 7: equipada na BBM 030
```

Agir sobre essa crença arrancaria a bandeira da BBM 030, que voltaria a pedir no
ciclo seguinte. É o **6º padrão** (reconferir a premissa no momento de agir, não
no de decidir) num recurso que outra aldeia pode levar no meio do caminho.

### O que mudou

- **Gate de frescor em `flag_logic()`** — `flag_set` só é alcançado se o
  inventário foi lido **neste `update()`**. `_flags_fresh` é zerado no topo de
  `update()` e só levantado no **fim** de `manage_flags()`, depois do parse
  completo; cada `return` antecipado (randomização, `result is None`, regex que
  não casou, gestão desligada) é por construção uma leitura que não aconteceu.
  Erro assimétrico e a guarda fecha só de um lado: agir com inventário velho
  tira bandeira de quem estava certo; **não** agir custa esperar a próxima
  leitura, contra um cooldown de troca que já é de 24 h.
- **`manage_flags(force=True)`** — dois chamadores precisam furar a
  randomização. O caminho de **ataque** em `update()` (a bandeira de defesa não
  pode esperar 3 a 8 runs, que aqui são horas) e a **releitura pós-upgrade**,
  que antes re-sorteava a randomização e podia simplesmente não acontecer,
  deixando `self.flags` com a contagem **anterior** ao upgrade que a releitura
  existia para refletir. Esse segundo era um bug latente, achado ao mexer.
- **`self.flag_supply`** — a oferta por `(tipo, nível)`, acumulando a lista de
  amounts que o jogo publica em vez de sobrescrever. Mais `flag_type_supply()`.
- **Aviso de oferta zerada, uma vez por aldeia por processo** — hoje as 30
  aldeias caem do tipo 7/1/2 para o 6 sem uma linha dizendo por quê. Agora sai
  `preferência [7, 1, 2] sem oferta no inventário da conta (tipo 7: 0
  disponível(is), …)`. Uma vez, não por ciclo: alerta que nunca cala é
  indistinguível de alerta quebrado (15º padrão).
- **`cache/managed`** ganha `flag_supply` e `flags_read_this_cycle`. O nome
  `flag_supply` foi escolhido para não colidir com método de dict no Jinja2
  (8º padrão). ⚠️ **Publicado e ainda não consumido:** `flags.html` é a fatia 16
  da migração e não foi tocada aqui.

**Não** implementado de propósito: um ledger de oferta compartilhado entre
aldeias. Seria um segundo mecanismo de reserva (§8.2) para um recurso cujo
dono autoritativo já é o servidor — a leitura fresca resolve com zero estado
novo. Reavaliar só se aparecer vaivém com o gate ativo.

### Testes

`tests/test_flag_supply.py` (18 casos, sem rede; fixture **verbatim** do
`setFlagCounts` do br143, inclusive os tipos 1/2/7 zerados que são a prova da
medição 1). `tests/test_flag_policy.py` teve só o helper ajustado, porque a
política ganhou uma entrada nova.

**A guarda foi provada capaz de falhar** (21º padrão), e isso importa aqui mais
que o normal: um gate que apenas desligasse a troca de bandeira passaria em
todo teste de "não trocou". `tests/smoke_flag_stale_probe.py` roda as quatro
asserções comportamentais sem usar nenhuma API nova, então roda igual numa
árvore do `HEAD` anterior:

```
ARVORE ATUAL          4 de 4 passaram
ARVORE PRE-CORRECAO   2 de 4 falharam  (inventario velho movia a bandeira)
```

Os **controles** ("inventário fresco move a bandeira") passam nas **duas**
árvores — é isso que separa "guarda funcionando" de "feature desligada".

⏳ **Falta campo.** O sinal esperado no `session_latest.log`: as linhas
`preferência [...] sem oferta no inventário da conta` aparecendo uma vez por
aldeia, e a contagem de `Setting flag` **não** subindo em relação ao previsto
pela §6.3. A validação das 3 trocas continua aberta e agora tem um segundo
indicador: `flags_read_this_cycle` em `cache/managed` separa "não trocou porque
estava certo" de "não trocou porque não leu".

**Parcial de 2026-09-21 08:00, com o bot no ar desde 07:13 — 6 de 30 aldeias.**
O ciclo está levando ~8 min por aldeia, então o quadro só fecha perto das 11:15;
o que existe até agora **não** decide nada. Estado: 6 leituras, 6 linhas de
oferta zerada, **0 `Setting flag`**, e `flags_read_this_cycle: true` no
`cache/managed` das seis — ou seja, o silêncio é "não trocou porque estava
certo", não "porque não leu". O indicador novo está funcionando.

⚠️ **Mas a previsão da §6.3 já não bate, e vale conferir antes de contá-la como
validada.** A **BBM 003** (44683) é uma das três trocas previstas e foi
processada às 07:36 **sem trocar**. O motivo está no código e é legítimo: ela já
usa `current_flag: [7, 4]`, que é o **topo** da preferência dela (`[7, 1, 2, 6,
8]`), e a guarda de rebaixamento (`defence_manager.py:642`) a segura. A previsão
das 3 trocas foi escrita em 2026-08-31, contra um inventário que mudou desde
então — é o 16º padrão outra vez (documento é memória, não especificação), com o
agravante de que aqui o documento é o **critério de aceite**. Reconferir o
previsto contra o `cache/managed` atual antes de tratar "3 trocas" como o número
certo.

⚠️ **Achado de lambuja: a linha de log mente sobre o que vai acontecer.**
`_log_unmet_preference()` roda **antes** da guarda de rebaixamento, então ela
escreve `usando tipo 2 nível 1` para uma aldeia que vai **continuar com o tipo
7**. As 6 linhas observadas dizem isso, e nenhuma delas descreve uma ação real.
Não é bug de comportamento — o bot faz a coisa certa — mas é uma mensagem que
induz o leitor a contar trocas que não houve, exatamente na validação que
depende de contar trocas. Corrigir a redação (ou mover a chamada para depois da
guarda) antes da próxima leitura de log.

---

## 9. Próximos passos

**Fila definida pelo usuário em 2026-09-17, à frente do que vem abaixo:**

0. ~~**`P-CONQ-RAIO`**~~ — ✅ **feito em 2026-09-19** (§8.6). Falta só a
   validação em campo: o primeiro trem multi-origem real ainda não saiu.
   **Motivo medido em 2026-09-20 23:00**, e não é código: o log diz
   `Conquest: 1/4 nobres no imperio inteiro (74690:1) -- aguardando`. Falta
   **nobre**; o planejador está sendo alcançado e decidindo certo.
1. ~~**`P-COL-01`**~~ — ✅ **feito, testado e observado em campo**
   (2026-09-20 22:58, §8.5). O ciclo real logou
   `Using troops for gather operation: 2`, `Gather operation 1 is ready to
   start` e `Current Haul: 60855 = Gather Batch (4057) * Batch Multiplier 1
   (15)` — o saque previsto logado era o aceite. **Fechado.**
2. ~~**`P-COL-02(b)`**~~ — ✅ **implementado e testado em 2026-09-21** (§8.5),
   com o gate `gather_unlock_enabled` **desligado**: nenhum recurso foi gasto
   por esta feature. Captura, canário, política do usuário e código estão
   fechados; `P-COL-02(a)` já estava ✅.
   **Resta uma coisa, e é do usuário: ligar o gate em uma aldeia e observar.**
   A candidata natural é uma das 3 que só têm a opção 3 pendente (1.000/1.200/
   1.000, 3h) em vez de uma das 19 da opção 4 (10k/12k/10k, 6h) — mesmo custo
   de aprendizado, um décimo do recurso. O sinal no log é
   `Unlock: iniciada coleta N (...)`, e a confirmação independente é
   `unlock_time` aparecendo na tela no ciclo seguinte.

**Acrescentado em 2026-09-20, depois do estudo dos forks:**

3. ~~**`P-CONQ-RESERVA` Fase 1**~~ — ✅ **feita em 2026-09-20** (§8.7): captura,
   parser com fixture, exclusão dura nos cinco caminhos e
   `conquest.excluded_targets`. **⏳ Leitura validada em campo em 2026-09-20
   (480/482 reservas, 1 própria separada corretamente), gate ainda não
   exercitado** — o planejador não foi alcançado em nenhum dos dois ciclos. Ver
   o Aceite da §8.7. **Fase 2 (o bot criar reserva) segue aberta**, com
   gate `conquest.reserve_targets` default off e canário de uma reserva.
   **Payload ✅ capturado em 2026-09-21** (§8.7): estava no HTML da própria tela
   que a Fase 1 já baixa — `action=new_reservation` com `x[]`/`y[]`/
   `target_type=coord`/`comment[]`, e `action=submit` + `ids[]` +
   `delete_claims` para remover. **Achado que muda o desenho:** a tribo limita
   a **5 reservas simultâneas** por jogador, com validade de 3, então a Fase 2
   gasta vaga escassa que compete com as reservas manuais do usuário — não dá
   para reservar tudo que o planejador eleger. Continua sem resposta o que o
   jogo faz com alvo já reservado por outro: não há texto de recusa na página,
   só na resposta da tentativa.
4. ~~**`P-CONQ-MAPA` — fechar o terceiro funil com `map/village.txt`**~~ —
   ✅ **feito em 2026-09-20** (§8.6, "O que foi feito"). `game/world_villages.py`,
   terceira camada em `_candidate_pool()`, recorte por caixa antes da pontuação.
   Candidatos 96 → 387 e o alvo eleito inalterado. De brinde, 38 bárbaras-fantasma
   do cache local deixaram de ser elegíveis. **⏳ Nenhum trem montado com esse
   pool ainda.**
5. ~~**`P-MAPA-REDE`**~~ — ✅ **feito em 2026-09-20** (§8.8). Era o que impedia o
   ciclo de chegar ao planejador de conquista, e portanto o pré-requisito das
   validações de campo dos itens 0, 3 e 4 acima. **✅ Aceite cumprido em
   2026-09-20 23:00:42:** `ConquestPlanner - INFO - Conquest: 1/4 nobres no
   imperio inteiro (74690:1) -- aguardando`. O ciclo completo chega ao
   planejador. **Fechado.**
6. ~~**Itens 1 e 3 da fila tática da §7.10**~~ — ✅ **feitos em 2026-09-20**
   (§8.9): captcha com auto-resume, sessão lida de `cache/cookies.txt` e
   `Notification.send` à prova de falha. Com isso **nenhum `input()` sobrou no
   caminho de runtime** — o único que resta é o `twb.py::manual_config`, que só
   roda quando não existe `config.json`. **⏳ Falta campo:** nenhum captcha real
   desde a mudança, e a sessão atual ainda não venceu.
7. ~~**Item 2 da fila tática da §7.10**~~ — ✅ **feito em 2026-09-20** (§8.10):
   `core/instance_lock.py`, trava de região de 1 byte pelo SO (`msvcrt.locking`
   no Windows, `fcntl.flock` no resto), chave = endpoint da conta, arquivo no
   temp do usuário, verificação **antes** do tee de log em `twb.py`. A `_Lock`
   do fork era no-op no Windows e não foi transplantada. Smoke ponta a ponta em
   `tests/smoke_instance_lock_twb.py`. **⏳ Falta campo:** o bot que está
   rodando subiu antes da mudança e não segura trava; o aceite é reiniciá-lo e
   ver um segundo `python twb.py` ser recusado citando o pid do primeiro.

8. ~~**Item 9 da fila tática da §7.10**~~ — ✅ **feito em 2026-09-20** (§8.11):
   a política de bandeira **não** contava a oferta, e a medição mostrou que o
   que segurava o Bug 1 era a guarda de rebaixamento, não o inventário. Gate de
   frescor em `flag_logic()`, `manage_flags(force=True)` para defesa e para a
   releitura pós-upgrade (bug latente achado no caminho), `flag_supply` com a
   quantidade que o código descartava, e aviso único de oferta zerada.
   **⏳ Falta campo:** as linhas de oferta zerada e a contagem de trocas.

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
