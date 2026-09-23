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
| 34 | Troca Premium | ⛔ **morta (2026-09-21)** — código mantido, gate off | nunca validada e não será — §4.5 |
| 37 | Painel: série Saqueado/Coletado do próprio jogo | ✅ 2026-09-22 | ⚠️ não — ver §8.17 |
| 38 | Painel "Em voo" (comandos no ar, hora do servidor) | ✅ 2026-09-22 | ⚠️ não — ver §8.18 |

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

> ⛔ **MORTA — o usuário encerrou a Feature 34 em 2026-09-21.** Não há mais
> interesse em vender na bolsa premium, em nenhum mundo, inclusive em mundo
> novo. Isto **cancela** o gatilho que estava registrado ("esperar abrir mundo
> novo para validar o envio em pt-BR") e retira a linha correspondente da §6.2.
>
> **O código NÃO foi removido, de propósito.** `do_premium_stuff`,
> `PremiumExchange`, `_premium_extract_rate_hash()` e os configs
> `premium_exchange.*` / `trade_for_premium` continuam onde estavam — arrancá-los
> tocaria `game/resources.py`, que é caminho quente de mercado, e o risco de
> quebrar o bot é maior que o ganho de faxina. O que impede execução são os dois
> gates, **medidos no `config.json` em 2026-09-21**: `world.trade_for_premium`
> é `false` e `village.trade_for_premium` é `false` nas 30 aldeias. O caminho
> exige os dois ligados (§6.4 do `frontend.md`), então está duplamente morto.
>
> **O que isso custa saber:** `exchange_begin`/`exchange_confirm` continuam sem
> nunca terem rodado em pt-BR, e agora nunca vão rodar. Se alguém religar o gate
> um dia, trate o caminho de envio como **não validado** — é o perfil exato da
> Feature 9, onde o envio inteiro estava errado por nunca ter sido exercitado.
> O texto abaixo fica como registro do que foi medido, não como trabalho pendente.

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
| `support_others` | a chave já está `true` em 22 de 30 aldeias; o bloqueio é que ninguém **pede** apoio sem ataque real chegando. Exercitar com ataque mínimo de aldeia própria **distante** contra uma com `request_support_on_attack` (ver `CLAUDE.md`) |
| ~~Venda na bolsa premium~~ | ⛔ **cancelada em 2026-09-21** — Feature 34 morta, §4.5 |
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

⚠️ **A previsão "exatamente 3 trocas (BBM 003, 016, 017)" venceu — 2026-09-22.**
Ela é de 2026-08-31, quando havia bandeira sobrando no inventário. Na sessão das
19:14, as quatro primeiras aldeias (BBM 001–004) logaram bandeira de cunhagem
equipada (−12%, −22%, −16%, −14%) e a mesma linha de oferta: `preferência de
bandeira [7, 1] sem oferta no inventário da conta (tipo 7: 0, tipo 1: 0);
usando tipo 2 nível 1`. Nenhum `Setting flag` — a guarda de rebaixamento de
`flag_logic()` manteve o tipo 7, que está acima do 2 na preferência. A BBM 003,
uma das três "esperadas", já está com cunhagem −16% e sem oferta não tem para
onde ir. **Com o inventário de hoje, o esperado para o ciclo é zero trocas**;
qualquer `Setting flag` que rebaixe uma aldeia de cunhagem é o bug.
Defeito de texto achado no caminho: a linha diz *"usando tipo 2 nível 1"*, mas
`_log_unmet_preference()` roda **antes** da guarda de rebaixamento, então
anuncia uma troca que em seguida não acontece. Reescrever para "melhor
disponível: tipo 2 nível 1".
✅ **Corrigido em 2026-09-22:** a linha agora diz *"melhor disponível: tipo 2
nível 1 (equipada: tipo 7 nível 4)"* — nunca "usando". A chamada continua antes
das guardas, de propósito: a escassez é fato do inventário e vale reportar
mesmo quando a aldeia fica como está. Quem anuncia troca é só `Setting flag`.
Regressão em `tests/test_flag_supply.py` com o caso de campo, provada falhando
contra a redação antiga.

❌ **Previsão de 22:50 de 2026-09-22 retirada às 23:00 — estava errada, e o
"esperado: zero trocas" acima continua valendo.** Eu tinha previsto 3 trocas
para cima dentro do tipo 2 (BBM 028, 029, 030) a partir de `flag_supply 2: {4: 2}`
no `cache/managed/39449.json`. Esse arquivo ainda era **da sessão anterior**:
`set_cache_vars()` só o regrava no **fim** da execução da aldeia (22:56), e eu o
li às 22:49, com a aldeia ainda rodando. Conferi o mtime das cinco aldeias da
tabela e não o da fonte da premissa. Relido depois de regravado: `2: {1: 1}` —
uma tipo 2 sobrando, nível 1, exatamente o que as 26 linhas de oferta da noite
já diziam (`melhor tipo 2 nível 1`). Com isso 028 (2/3), 029 (2/1) e 030 (2/1)
já estão no melhor nível disponível ou acima, e `already_best` as deixa quietas.
A BBM 027 confirmou às 22:57: 2/4 equipada, oferta zerada, nenhuma troca.
**O log era a fonte certa e o cache era a errada** — 24º padrão do `CLAUDE.md`
com outra roupa: medir a partir do que o código lê *neste* ciclo, não de um
arquivo que só parece fresco.

⏳ **As quatro restantes (BBM 028–031) ficam para o ciclo de 2026-09-23:**
`active_hours` é `6-23` e o laço de aldeias checa a janela **por aldeia**
(`twb.py:1234`, `is_village_active_hours`), então às 23:00 as que faltam são
puladas e o ciclo seguinte recomeça pela BBM 001. Esperado: zero `Setting flag`,
salvo mudança de inventário até lá.

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

### 6.4 ✅ Sobrecomprometimento de tropa entre múltiplos alvos

> ✅ **Corrigido em 2026-09-22 (§8.20)**, junto com o piso da escolta do segundo
> parágrafo. O texto abaixo é o diagnóstico original.


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

**Consumidor de UI registrado (2026-09-21):** `frontend.md` §6.1.2 descreve um
painel **"Em voo"** (o que está no ar agora, com hora de chegada e proveniência
dessa hora) que consome `FND-02` e `DEF-02`, e uma exposição da **razão de
exclusão/recusa de alvo de farm** que não depende de contrato nenhum — o dado já
é produzido por `Extractor.error_box_text` e `min_attack_population` e hoje é
descartado. O painel "Em voo" é a contraparte visível da evidência que motivou
`FND-02`: o trem duplicado da §6.1.

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
| 5 | ~~Verificar os quatro bugs da auditoria deles (abaixo)~~ ✅ **feito em 2026-09-22 (§8.19)** — B4/B8/B10 já fechados; B9 tinha uma metade aberta (leitura **parcial**) e foi corrigida | LT `CODE_REVIEW.md` | S | leitura |
| 6 | `ServerClock` + `GameClock` | LT `core/server_clock.py:54,137` | M | formato de data do rodapé do br143 |
| 7 | Auto-desbloqueio de coleta por nível de EP; saque previsto logado | LT `troopmanager.py:13,486` | M | §8.5 |
| 8 | Consolidação noturna da coleta | LT `village.py:800` | M | depende de 7 |
| 9 | ~~Bandeiras: a nossa política conta **oferta**?~~ ✅ **respondido e corrigido em 2026-09-20 (§8.11)** — não contava; a causa real era decidir sobre leitura velha | LT `game/flags.py:356` | M | §6.3 |
| 10 | `mode=call`: ler do servidor o que já está a caminho | LT `balancer.py:355` | M | fixture verbatim |
| 11 | Velocidade de mercador medida na página de confirmação | LT `balancer.py:683` | M | mesma fixture |
| 12 | Ícones A/B/C do `am_farm` + `data-units-forecast` | LT `attack.py:152` | M | br143 renderiza o atributo? |
| 13 | ~~Paginação do `am_farm`~~ ✅ **respondido em 2026-09-22: não se aplica** — o bot não lê o assistente de saque (`grep am_farm` em `*.py`: zero ocorrências); o farm envia por `screen=place` | kuzyn | S | leitura |
| 14 | ~~Existe limite de saque (`Beutelimit`) no br143?~~ ✅ **não existe** — `get_config` público dá `<farm_limit>0</farm_limit>` (lido em 2026-09-22); `<hauls>1` é o saque normal (unidade carrega recurso), não um teto | megaindex | S | `get_config` + `/page/settings` |
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

1. **Não sabemos quanto a coleta rende** — ⚠️ **parcialmente falsificado em
   2026-09-21, ver §8.13.** O que continua verdade: o relatório de coleta
   concluída **não carrega saque**, e a única janela *por operação* é o instante
   do despacho, onde saque esperado = capacidade do esquadrão ×
   `{I: 0.10, II: 0.25, III: 0.50, IV: 0.75}`. O que era falso: a frase
   original dizia que "não há como descobrir depois". Há — a tela
   `screen=info_player&mode=stats_own` publica a série **`Coletado`** por dia,
   separada por recurso, nos últimos 7 dias, e com ela a pergunta "a coleta
   rendeu mais que o farm nas últimas 24 h" **já tem resposta hoje**, porque a
   mesma tela traz `Saqueado` ao lado. O `cache/scavenge_log.json` segue valendo,
   mas por outro motivo: granularidade (qual aldeia, qual operação, qual opção)
   e retenção além de 7 dias — não por ausência total do dado.
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

**Fase 2 — escrita, com gate próprio e canário.** ✅ **Implementada em
2026-09-21, com o gate DESLIGADO — falta o canário.**
`game/reservations.py::ReservationWriter`, configs
`conquest.reserve_targets` (default **false**), `conquest.reserve_max_slots`
(default **1**) e `conquest.reserve_comment`. Testes:
`tests/test_reservation_writer.py` (25 casos, fixtures verbatim de 2026-09-21).

#### As três medições que decidiram o desenho

**1. Renovação não tem cliente, e o problema real é o inverso.** A janela entre
`scheduled_at` e a conquista foi de **7,21 h** (alvo 49709) e **10,68 h**
(52755) — os dois únicos registros de `cache/conquest` que têm os dois
timestamps — contra os **72 h** de validade. E há um argumento estrutural que
não depende do n=2: `ConquestPlanner.run()` (`conquest_planner.py:145`)
**retorna antes** de `_pick_target()` quando o império tem menos de 4 nobres, ou
seja a espera por nobre acontece **antes** de existir alvo. Por isso a reserva
nasce no agendamento do trem, inclusive para alvo manual, e **não há renovação**
— que exigiria remover e recriar, com uma janela entre os dois POSTs em que o
alvo fica livre para outra pessoa.

O que a medição achou no lugar: o intervalo mediano entre duas conquistas é de
**~37 h** (22 gaps, de 3,6 h a 128,6 h). Uma reserva sobrevive ao motivo dela
por ~60 h, então **deixar expirar sozinha faria o bot segurar ~2 das 5 vagas em
regime permanente**. Remoção ativa ao concluir é número, não faxina.

**2. Teto de vagas.** `ConquestPlanner` mantém um trem bárbaro por vez no
império (`active_conquests()`), então **1 vaga basta** e é o default. Sem teto o
bot encheria o quadro e o dono da conta não conseguiria reservar nada — sem
erro, só recusa.

**3. Procedência: o jogo publica a resposta, e o cache local não precisava ser
a fonte.** A captura de 2026-09-21 (441 reservas, 3 da conta) mostrou que a
linha da reserva **própria** traz um link
`action=delete_reservations&id=<reserva>&…&h=<csrf>` que **não existe** nas dos
outros — 3 linhas em 441, exatamente as da conta. É uma afirmação **do
servidor** sobre quem pode remover o quê, e a Fase 2 a usa em vez de montar URL
(o POST em lote `action=submit`+`ids[]`+`delete_claims`, que a captura anterior
tinha achado, ficou **de fora**: aceita vários ids de uma vez e só ampliaria o
estrago de um bug). O que separa "do bot" de "do usuário" continua sendo o
**comentário**, lido de volta do jogo por `ajax=load_comment` — contrato tirado
do `ReservationManager.js`, buscado do CDN estático (sem sessão, logo sem gastar
o limite de taxa da conta).

#### ⚠️ A captura pegou um bug meu antes de ele rodar

A primeira versão do flag "tem comentário" casava
`id="show_reservation_comment_<id>"`. Medido nas 441 linhas: o link casa **16** e
só **13** têm comentário — e as 3 falsas positivas são **exatamente as 3
reservas da conta**, porque nas próprias o jogo renderiza esse link mesmo sem
comentário (o dono pode *editar*). Ou seja, 100% de erro nas únicas linhas de
que a procedência depende: 15º padrão, detector que dispara onde não devia. O
sinal certo é a imagem (`show_comment.png` × `show_comment_disabled.png`, 13 +
428 = 441). Guarda em `test_flag_de_comentario_nao_casa_o_link`, que roda o
regex **errado** contra o markup real e exige que ele erre.

**A mesma captura fechou o ⏳ da fixture derivada** (era item de aceite da Fase
1): a linha #76156 foi substituída pela #79340 real, e a inventada errava três
coisas — sem link de tribo na célula do reservante, sem link de apagar, e a
tribo da conta hoje é "Os Randolinhos" e não "SQUAD 02".

#### Orçamento de requisição, e o que não foi feito

Uma escrita por ciclo (`MAX_WRITES_PER_CYCLE`), porque o limite de taxa é da
conta e a Fase 2 disputa requisição com o farm. Ciclo completo de uma conquista
= 1 POST + 1 GET (criar) + 1 GET + 1 GET (remover), a cada ~37 h. A varredura
custa **zero requisição** no caso normal: reserva sem comentário é descartada
sem perguntar nada ao servidor.

**PvP conquest ficou fora da escrita** (continua respeitando a leitura):
`cache/pvp_conquest/` está vazio, o ciclo `pending_scout → pending_sim →
scheduled` é semi-manual e pode durar dias — é justamente ali que os 3 dias
poderiam morder, e não há **uma única** medição para calibrar. Escrever
renovação especulativa para um caminho sem dado seria inventar o limiar que o
18º padrão proíbe.

**Regras respeitadas:** `reservation_limit` / `reservation_time` /
`reservation_cooldown` e o tamanho de página **nunca** são escritos — são
configuração da aliança inteira (21º padrão); a leitura usa `page=all` na
querystring.

#### ⏳ Falta o canário

Nada foi escrito no quadro ainda. Protocolo, o mesmo da validação de bandeiras:
ligar `conquest.reserve_targets`, deixar **uma** reserva ser criada, conferir a
olho no jogo (linha presente, comentário visível, vaga contabilizada), e só
então deixar rodar. Sinais no log: `Reservations: alvo X (x|y) reservado no
quadro da alianca` e, ao concluir, `reserva N de X liberada`.

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
- ✅ Fixture: **as três linhas são verbatim desde 2026-09-21.** A terceira
  ("reservado por mim") era derivada e foi trocada pela real (#79340) na captura
  da Fase 2. A linha inventada errava três coisas, todas do lado que importa —
  ver o bloco da Fase 2 acima. Era exatamente o risco que a nota anterior aqui
  antecipava, e ele se realizou nos três pontos.
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

### ✅ Limitação de transição — encerrada em 2026-09-22

O bot em execução no momento da mudança (pid 11936, iniciado antes) **não segurava
trava nenhuma**. O aceite era reiniciar o bot e confirmar que uma segunda
instância é recusada citando o pid do primeiro.

**Cumprido em 2026-09-22 às 19:46**, com o bot reiniciado às 19:14. Em vez de
subir um segundo `twb.py` (que, se a trava falhasse, rodaria de fato dois bots
na conta), um processo separado instanciou `InstanceLock` com a **mesma chave**
(o `server.endpoint` do `config.json`) e chamou `acquire()`: devolveu `False`,
`degraded=False`, e `describe_holder()` respondeu *"Outro processo já está
rodando esta conta (...): pid 11880, iniciado em 2026-09-22 19:14:34, cwd
C:\Users\User\Desktop\TWB-CLAUDE"* — o pid bate com o `python.exe` vivo no
`tasklist`. É a mesma chamada que `twb.py` faz antes do tee. O caminho da
mensagem impressa pelo `twb.py` em si continua coberto pelo
`tests/smoke_instance_lock_twb.py`, não por este teste.

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
guarda) antes da próxima leitura de log. ✅ **Redação corrigida em 2026-09-22** (§6.3):
"melhor disponível", com a bandeira equipada entre parênteses; a chamada ficou
onde estava.

---

## 8.12 ✅ Ajustes decididos em 2026-09-21, implementados em 2026-09-22

Dois itens aprovados pelo usuário nesta sessão. Ficam aqui, e não num documento
novo, porque foi a proliferação de arquivos que enterrou uma lição verdadeira
antes (8º padrão do `CLAUDE.md`).

**Os dois foram implementados em 2026-09-22** — o que mudou, e o que a
implementação descobriu que o diagnóstico não sabia, está no fim de cada
subseção.

### `P-TMPL-SCOUT` — o estágio de espião gateado no ferreiro da cavalaria pesada

`templates/troops/watchtower_support.txt` (reescrito pelo usuário em 2026-09-13
para que as aldeias de torre produzam **espião** em vez de apoio rápido) tem o
primeiro estágio que constrói alguma coisa gateado em **`smith:15`**:

```json
{"building": "smith", "level": 15, "upgrades": {"spy": 1},
 "build": {"stable": {"spy": 440}}}
```

**O 15 não é requisito do Explorador — é o da cavalaria pesada**, herdado do
template anterior. Medido na captura real da tela do ferreiro
(`cache/_smith_br143.html`, recorte verbatim):

```
Ferreiro (Nível 7) ... Explorador  Pesquisado
Cavalaria pesada    Requisitos em falta: Ferreiro (15)
Catapulta           Requisitos em falta: Oficina (2) Ferreiro (12)
```

Ou seja, com ferreiro **7** o Explorador já está pesquisado. Isso prova que o
requisito real é **≤ 7**; o mínimo exato não foi medido e não precisa ser para
concluir que 15 está errado.

**Consequência esperada, e é do tipo que não faz barulho:** aldeia abaixo de
ferreiro 15 não bate em nenhum estágio construível e produz **zero** espiões,
sem erro no log. A candidata a sofrer isso é a **52755**, conquistada em
2026-09-19 e hoje com 0 espiões — contra ~2.550 nas outras duas de torre, que
passaram do estágio quando o ferreiro delas já era alto. Confirmar essa
consequência contra a semântica do consumidor de template antes de tratar como
fato: aqui está medido o *requisito*, não o comportamento do motor.

É o **12º padrão** outra vez — "ao adicionar mais um de algo, ler os irmãos
antes" —, agora com a variação de que o irmão lido foi o *próprio arquivo na
versão anterior*, e o número herdado veio junto.

#### ✅ O que foi feito (2026-09-22)

**A consequência era exatamente a prevista, e agora está medida no consumidor,
não deduzida.** `TroopManager.get_template_action()`
(`game/troopmanager.py:232`) percorre os estágios **em ordem** e devolve `last`
no **primeiro** cujo nível exigido não foi atingido — não pula estágio. Com
ferreiro abaixo de 15, a aldeia para no estágio 0 (`stable:1`, `build: {}`),
pede zero unidade, e nada é logado. Os estágios `watchtower:10`/`watchtower:20`
ficam inalcançáveis **mesmo se a torre já estiver alta**, porque o `smith:15`
está antes deles na lista.

O gate passou de `smith:15` para **`stable:3`**. Por que `stable:3` e não outro
número: é onde **todos os sete templates irmãos** de `templates/troops/` põem o
primeiro estágio que constrói espião, e nenhum deles gateia espião em `smith`.
O requisito de ferreiro medido é ≤ 7 e as três aldeias de torre estão em 9, 20 e
20 — ou seja, o ferreiro deixou de ser a variável que decide.

Estado real das três aldeias de torre, lido de `cache/managed/*.json` em
2026-09-22 (a chave é `buidling_levels`, com o typo do código):

| id | nome | estábulo | ferreiro | torre | espiões | estágio antes → depois |
|---|---|---:|---:|---:|---:|---|
| 38409 | BBM 002 | 20 | 20 | 10 | 2.790 | `watchtower:10` (1.500) → igual |
| 38412 | BBM 023 | 12 | 20 | 0 | 2.597 | 1º estágio (440) → igual |
| 52755 | BBM 030 | 5 | 9 | 0 | **0** | estágio 0 (**zero**) → 1º estágio (440) |

Só a 52755 muda de comportamento, e é a que estava em zero. As outras duas
entram na tabela porque a correção **não pode rebaixar ninguém** — quem já
alcançava um estágio alto continua alcançando.

Regressão em `tests/test_watchtower_spy_gate.py`, com quatro testes: os níveis
reais das três aldeias pedindo espião; o template **antigo** (único diff:
`smith:15` no lugar de `stable:3`) rodado contra os mesmos níveis exigindo que a
52755 pare no estágio 0 — sem isso, o teste principal passaria também com o
template quebrado se alguém subisse o ferreiro da aldeia, e a asserção viraria
verdadeira pelo motivo errado (é a mesma técnica do regex antigo em
`tests/test_incoming_commands.py`); a propriedade "nenhum estágio que constrói
espião é gateado em `smith`"; e a monotonicidade da progressão.

**Não validado em campo ainda.** O que observar: a 52755 logando recrutamento
de espião no `stable`, e `spy` saindo de 0 no `cache/managed/52755.json`.

### `P-PVP-SCOUT` — a espia deve sair da aldeia com mais espiões, e no máximo

**Decisão do usuário, 2026-09-21.** Hoje `PvpConquestManager._step_scout()`
(`game/pvp_conquest.py:451`) itera `self.villages.items()` e pega a **primeira**
aldeia com `spy >= scout_amount` que tenha o alvo no `map_pos`, enviando
exatamente `scout_amount` (5, do config). Não é a que tem mais espiões, não é a
mais próxima: é a primeira da ordem do dict.

O que passa a valer:

- **origem** = a aldeia com o maior número de espiões (entre as que alcançam o
  alvo), não a primeira encontrada;
- **quantidade** = o máximo disponível, não o `scout_amount` fixo.

Racional da quantidade: 5 exploradores contra aldeia de jogador defendida
morrem sem relatório, e relatório que não chega é o que faz o alvo cair em
`scout_deadline_missed`. Ao implementar, decidir o que fazer com
`pvp_conquest.scout_amount` — ele vira piso, ou chave morta? Remover sem
responder isso seria o 4º padrão.

⚠️ **Isto mexe numa conta que já foi usada.** O agendamento do alvo PvP 44155
(555|288, chegada 2026-09-23 10:00) foi dimensionado com a folga da espia
calculada sobre a escolha **atual**: pior caso elegível a 42,0 campos = 6h30, e
a proposta inicial (22/09 19:00) tinha só 6,3 h de folga — foi essa medição que
empurrou a chegada para 23/09 10:00, com 19,7 h. Trocar a regra de origem muda
a distância da espia e, portanto, esse número. Medido no dia: das 30 aldeias, 29
têm ≥5 espiões, os máximos são **80** (34597 a 35,0 campos e 35059 a 38,4), e a
primeira da ordem de id é a **32056** (50 espiões, 34,7 campos). A aldeia com
mais espiões é **mais distante** que a escolhida hoje — então a regra nova
tende a **aumentar** o tempo da espia, não a diminuir.

#### ✅ O que foi feito (2026-09-22)

`_step_scout()` virou três partes: `_scout_candidates()` monta e **ordena** as
origens, `_scout_floor()` isola a leitura da config, e o passo em si tenta as
melhores em ordem. Ordem = **mais espiões primeiro, empate desfeito pela menor
distância** — a distância entra como desempate, não como peso, porque foi isso
que a decisão diz: entre duas origens que mandam a mesma quantidade, a mais
perto entrega a informação mais cedo. A consequência medida acima (a origem nova
é mais distante que a antiga) está codificada como asserção em
`tests/test_pvp_scout_origin.py::test_o_recorte_real_das_30_aldeias`, com as
coordenadas que reproduzem 34,7 / 35,0 / 38,4 campos.

**`pvp_conquest.scout_amount` virou PISO, não chave morta.** Ele sempre foi as
duas coisas ao mesmo tempo — `if spies < scout_amount: continue` era o filtro de
elegibilidade e `troops={"spy": scout_amount}` era o envio. Passando a enviar o
máximo, só um dos dois papéis podia sobrar; o piso preserva o significado da
chave ("menos que isto não vale a viagem") em vez de deixá-la inerte, que é o
4º padrão. O texto em `webmanager/helpfile.py` foi reescrito para dizer isso em
voz alta — a redação antiga ("número de espiões usados no scout") passaria a
descrever algo que o código não faz mais.

**Três coisas que a implementação obrigou e o diagnóstico não previa.**

1. **A contagem tem que ser relida ao vivo antes de enviar, senão a mudança
   troca uma espia lenta por NENHUMA espia.** Os objetos `Village` sobrevivem
   entre ciclos e este passo **abre** o ciclo (§8.14), então `units.troops` aqui
   é a foto do fim do ciclo passado — até ~4h de idade com 30 aldeias. Mandar 5
   de uma contagem velha quase nunca falha; mandar "todos os 80" de uma contagem
   velha falha **sempre que o farm scout gastou algum no meio**, e o jogo recusa
   o ataque **inteiro** em vez de mandar menos. `units.update_totals()` custa
   duas requisições e é feita só para a origem escolhida; se ela caiu abaixo do
   piso, a próxima da lista assume. É o 6º padrão (separar "quando eu decidi" de
   "quando isso acontece", e reconferir a premissa no momento de agir) numa
   latência de horas em vez de minutos.
2. **A elegibilidade antiga era mais estrita que o próprio envio.** O teste era
   `target_id not in village.area.map_pos`, mas `AttackManager._resolve_position()`
   tem uma **segunda fonte**: a coordenada do snapshot compartilhado
   `cache/villages`, usada quando o alvo está fora do prefetch daquela aldeia.
   Com `farms.map_sector_radius = 0` (o valor em campo) e `SECTOR_SIZE = 20`, o
   prefetch cobre pouco mais de um bloco de 20×20 alinhado — a BBM 030 (572|289)
   cai no setor (560,280) e o alvo 44155 (555|288) no setor (540,280), **setores
   diferentes**. Ou seja, "a aldeia com mais espiões" podia nunca ser
   considerada por um motivo que não tem nada a ver com alcance, e isso tornaria
   a regra nova quase indistinguível da antiga. O alcance passou a ser resolvido
   uma única vez por `_target_location()`, extraído de `_block_if_reserved()`,
   que já fazia exatamente essa busca de duas fontes.
3. **A reserva de conquista é descontada.** Hoje nenhum dono reserva `spy`
   (`_build_clear_units()` e `_build_noble_attacks()` excluem espião), então a
   subtração é inócua no estado atual — mas enviar *o máximo disponível* é
   precisamente o caminho que transformaria uma reserva futura de espião em
   tropa gasta sem aviso.

Teto de **5 tentativas** (`SCOUT_MAX_ATTEMPTS`). Cada tentativa custa duas
requisições de leitura mais duas de envio, e as origens estão em ordem
decrescente de espião: se as cinco primeiras falharem, o problema não é "esta
aldeia" e varrer as outras 25 só gasta orçamento num ciclo que já vai terminar
sem espia. O log passou a dizer quantas origens eram elegíveis, as três
melhores com espiões e campos, e quantas foram tentadas — antes ele dizia só
"no village with spies available", que não separa "nenhuma candidata" de "todas
recusadas".

**⚠️ O que isto faz com o alvo 44155, que já está agendado.** A chegada
(2026-09-23 10:00) foi dimensionada contra a escolha antiga. Com a regra nova a
origem passa a ser a 34597 (80 espiões, 35,0 campos) em vez da 32056 (50
espiões, 34,7 campos) — 0,3 campo **mais longe**, dentro do ruído da folga de
19,7 h que a §8.12 mediu. O pior caso elegível citado lá (42,0 campos) não muda,
porque o teto de tentativas só percorre as cinco com mais espiões.

**Não validado em campo ainda.** O que observar no `session_latest.log`:
`PvpConquest: N origem(ns) elegivel(is) para espiar ...` com a lista das três
melhores, e em seguida `scout sent from ... (N spies, X.X campos)` com `N` bem
acima de 5. Regressão em `tests/test_pvp_scout_origin.py` (13 testes).

---

## 8.13 `P-STATS-JOGO` — o jogo já publica a série histórica, e ninguém lia (2026-09-21)

Levantado pelo usuário em 2026-09-21: *"o próprio jogo já fornece uma tela de
estatísticas"*. **Não estava registrado em lugar nenhum** — `mode=stats_own` não
aparecia no repositório, e `screen=info_player` só existia como *link* dentro de
outros parsers. Capturado no mesmo dia por `tests/smoke_capture_stats_own.py`.

### O que a tela entrega

`game.php?village=<vid>&screen=info_player&mode=stats_own`, 1 GET, ~90 KB.

**Os números estão no HTML, server-side.** Não é canvas nem XHR: vêm embutidos
como arrays JS (`InfoPlayer.Stats.createGraph(...)` e blocos `data.push({label,
data, details})`). Um `re` resolve — não precisa de navegador. Isso é o oposto
do `StatuePage` (quinta metade do quinto padrão), onde o texto só existia depois
do JS: aqui a resposta HTTP já traz tudo.

| Série | Forma | Resolução | Janela |
|---|---|---|---|
| Pontos do jogador | linha | 6 h | 14,2 d |
| Aldeias do jogador | linha | 6 h | 14,2 d |
| Classificação do jogador | linha | 6 h | 14,2 d |
| Pontos da tribo | linha | 6 h | 14,2 d |
| Aldeias saqueadas | barra | 24 h | 13 d |
| Unidades mortas (inimigas) | barra | 24 h | 13 d |
| Unidades ganhas / perdidas | barra | 24 h | 13 d |
| **Recursos saqueados**: `Saqueado`, `Coletado` | barra rica | 24 h | 7 d |
| **Recursos gastos**: `Unidades`, `Edifícios`, `Notabilidade`, `Pesquisa`, `Coleta de Recursos`, `Comércio` | barra rica | 24 h | 7 d |

As duas séries ricas trazem `wood`/`stone`/`iron`/`total`/`percent` por dia.
**Semântica medida, não suposta** (o smoke verifica as duas em toda execução, em
todos os dias): `total == wood + stone + iron`, e `percent` é a **participação
daquela série no total do dia**, não no período nem no máximo da janela —
`Saqueado 25,997%` + `Coletado 74,003%` fecham 100% em 21/09. Confundir esse
campo com "% de aproveitamento" seria o quinto padrão outra vez (número real,
lido do servidor, do campo errado).

### Por que isso vale mais do que parece

**É a única fonte do sistema que enxerga o que o usuário faz na mão.** O nono
padrão diz que o log registra as ações do *bot*, não o estado do mundo. Esta
tela registra o **resultado**, venha de onde vier — e a captura já provou o
ponto: a série `Coleta de Recursos` (gasto) mostra **204.240 em 20/09 e 105.600
em 21/09** desbloqueando níveis de coleta, enquanto o `gather_unlock_enabled`
está `false` no `config.json` e o `session_latest.log` tem **zero** linhas
`Unlock:`. Os dois fatos são compatíveis e a conclusão é direta: foi o usuário,
manualmente. Nenhuma outra fonte do repositório teria mostrado isso.

Segundo uso, barato e imediato: **conferência cruzada de graça** (corolário do
vigésimo quarto padrão). O saque diário medido pelo nosso `ReportReader` e o
`Saqueado` desta tela respondem a mesma pergunta por caminhos independentes; se
divergirem, um dos dois está errado e hoje ninguém saberia qual.

### O que ela **não** resolve — e é o que decide o desenho

1. **É conta inteira, não por aldeia.** Nenhuma série é segmentada. Não
   substitui `ReportReader` nem `farmscores` para decisão por alvo ou por
   aldeia; serve de **agregado de controle**, não de instrumento operacional.
2. **Retenção curta.** 7 dias nas séries ricas, ~14 nas demais. Para série mais
   longa que isso, é preciso **acumular localmente** — o que transforma a tela de
   "fonte" em "semeadora" de um histórico nosso.
3. **Não tem atribuição de causa.** `Saqueado` é um total; não separa por
   template, capacidade ou alvo. Portanto **não serve para `CAL-01`** e não
   resolve a censura do décimo primeiro padrão — o baseline exigido pela §9.3
   continua dependendo dos relatórios.
4. **É saldo, não evento.** Não dá `observed_at` por operação, não fecha
   `FND-01`/`FND-02` e não diz nada sobre o que está *em voo*.

### Correção que isto obriga

O item 1 da §8.5 `P-COL-03` afirmava que **"não sabemos quanto a coleta rende, e
não há como descobrir depois"**. Isso está **falsificado no nível de conta/dia**:
a série `Coletado` publica exatamente isso, separado por recurso, para os
últimos 7 dias — e mostra `0` em 19/09 contra `274.159` em 20/09 e `413.448` em
21/09, ou seja, a coleta aparece ligando na janela em que `P-COL-01` entrou. A
parte da afirmação que **continua de pé** é a granularidade: o jogo não diz
*qual aldeia*, *qual operação* nem *qual opção* rendeu, e é isso que o
`cache/scavenge_log.json` proposto resolveria. Texto da §8.5 corrigido no mesmo
passo (décimo sexto padrão).

Décimo sexto padrão de novo, sobre o método: a afirmação "não há como descobrir
depois" foi escrita a partir do **relatório de coleta**, que de fato não carrega
saque. A conclusão pulou de "esta tela não tem" para "o servidor não tem" — que
é exatamente a quarta metade do quinto padrão, e desta vez a fonte que faltava
nem era obscura: é um item do menu do próprio perfil do jogador.

### Estado

Capturado e medido; **nada consumido pelo bot ainda**. Candidato de painel
registrado em `frontend.md` §6.1.2, item 6. Não entra na fila da §9 sem decisão
do usuário.

---

## 8.14 ✅ `P-PVP-TROPA` — a simulação julgava o exército que estava fora (2026-09-21)

### O incidente

Alvo PvP **#44155** ("000", 555|288), cadastrado às 13:42 com chegada desejada
para 23/09 10:00 e limpeza pela **BBM 018 (#39472)**. Às 14:18 o bot escreveu
`fail_reason: "simulation_failed"` e fechou a operação para sempre. A
simulação registrada:

| campo | valor |
|---|---|
| `att_power` | 3.192 |
| `att_total` / `att_losses` | 144 / 144 |
| `def_total` / `def_losses` | 16.398 / 6 |

144 tropas atacando 16.398 — perda total, muralha 20 intacta. Só que a
**BBM 018 tem 1.486 machados, 739 cavalarias leves e 120 aríetes**. O que a
simulação viu foi `available_troops`: `{axe: 46, spy: 59, light: 16, ram: 120}`.
`_build_clear_units()` aplica `clear_ratio` 0.8 sobre isso e dá exatamente
`36 + 12 + 96 = 144`. **O número bate à unidade**: a viabilidade foi decidida
contra ~3% do exército, com os outros 97% no ar, em ataques de farm.

### Por que a suspensão existente não segurou

`FARM_SUSPEND_STATUSES` + `Village.run_farming()`/`do_gather()` já paravam farm
e coleta nas aldeias de origem — isso funciona e não era o bug. O que a
suspensão **não faz é trazer tropa de volta**: um farm despachado antes de o
alvo ser cadastrado ainda tem horas de viagem. E a máquina de estados simulava
no mesmo instante em que conseguia ler a tropa, sem esperar nada.

Duas causas em série, e a segunda é de ordem de execução:

1. **`units` e `area` só existem depois que a aldeia roda.** `PvpConquestManager`
   só era chamado de dentro de `village.run()`, uma vez por aldeia. Com 30
   aldeias o ciclo mediu **~4h** em 2026-09-21 (13:42 → 17:56 no
   `session_latest.log`), e o log tem cinco
   `clear village 39472 has no troop data` seguidos — o alvo esperou a vez
   daquela aldeia e foi julgado no minuto arbitrário em que ela chegou.
2. **`_prepare_departure_deadlines()` nunca produziu nada**, porque ela desiste
   se *qualquer* aldeia de origem ainda não tem `units`. Por isso o
   `departure_deadlines` não existia no cache e o painel mostrava
   "Não calculada" — a funcionalidade de horário de saída por aldeia estava
   escrita e inalcançável.

Isto é o sexto padrão do `CLAUDE.md` outra vez: decidir num instante sobre um
estado que muda durante horas. E o décimo primeiro: a média ("tropa da aldeia")
misturava dois conjuntos, tropa em casa e tropa possuída, que o código já
publica separados (`units.troops` vs `units.total_troops`).

### O que foi feito

- **Estágio novo `pending_troops`**, entre `pending_scout` e `pending_sim`
  (`game/pvp_conquest.py::_step_wait_troops`). Segura a simulação enquanto a
  população de combate em casa das origens estiver abaixo de
  `pvp_conquest.troops_home_ratio` (0.9). Sai por três portas: exército em
  casa, `sim_lead_seconds` (1800) antes da primeira saída obrigatória, ou
  `max_troop_wait_hours` (6). As duas últimas gravam
  `troops_wait_forced_reason` — a espera nunca vira impasse silencioso, e
  simular tarde seria pior que simular pessimista, porque
  `_fail_if_scout_deadline_missed()` mata o alvo quando a saída vence.
- **`Village.prime_for_conquest()`** — init mínimo e somente-leitura
  (`village_init` → `update_pre_run` → `units.update_totals` →
  `ensure_map_loaded` → `ensure_attack_manager`), sem builder, recrutamento,
  mercado, farm ou coleta.
- **`TWB.prime_conquest_sources()` + PvP no início do ciclo** (`twb.py`). Roda
  em dois tempos: `run()` escolhe e trava as origens usando o snapshot de
  `cache/managed` (sem rede), o prime lê **só** as origens escolhidas
  (~4 requisições por aldeia, tipicamente 2 a 5 aldeias), e o segundo `run()`
  decide com número vivo e consegue sondar os tempos de viagem. A chamada por
  aldeia continua existindo — é ela que dá prioridade sobre o farm daquela
  aldeia.
- **Painel**: estágio novo com rótulo/cor/ordem, bloco "Exército em casa" com o
  percentual por aldeia de origem, e a seção "Deadlines de saída" finalmente
  alimentada, com horário formatado e duração da viagem por comando.

### Medição do gate

O `_home_troop_ratio()` mede **população de combate** (`UNIT_POP`), excluindo
espião, nobre e paladino — as mesmas exclusões de `_build_clear_units()`. Três
cuidados que já custaram bug neste repositório:

- devolve `None`, não `0.0`, quando nenhuma origem tinha leitura — valor de
  falha distinguível de resposta legítima (sexto padrão);
- `total_troops` só é preenchido quando `can_recruit` é verdadeiro
  (`TroopManager.update_totals()` retorna antes), então dicionário vazio
  significa "não lido" e cai no snapshot de `cache/managed`, não em "sem
  exército";
- `home` é limitado por `owned`: apoio estacionado na aldeia podia pôr a razão
  acima de 1.0 e satisfazer qualquer limiar em silêncio.

### Estado

Código e testes prontos (`tests/test_pvp_troop_wait.py`, 16 casos, incluindo o
snapshot real do #44155). Config em `pvp_conquest`: `troops_home_ratio`,
`max_troop_wait_hours`, `sim_lead_seconds` — `build.version` 4.4 → **4.5** só
no `config.example.json`, para o merge injetar a seção no `config.json` vivo.
O alvo #44155 foi recadastrado em `pending_scout`.

**Não validado em campo ainda.** O que observar no próximo ciclo: o alvo
passando por `pending_troops`, o `troops_home_pct` subindo entre ciclos, e o
`departure_deadlines` finalmente aparecendo no cache e no painel.

---

## 8.15 `P-CONQ-INICIO` — a conquista bárbara passa a abrir o ciclo (2026-09-22)

Mesma mudança de posição que a §8.14 fez na conquista PvP, agora na bárbara.

### O que estava acontecendo

`BarbarianTrainPlanner` já rodava **uma vez por ciclo**, mas no *rabo* do
`while` de `twb.py`, depois do laço das 30 aldeias. A posição resolvia a
visibilidade de graça — quando o laço termina, toda aldeia já tem `units` e
`area` — e deixava dois problemas de pé:

1. **A reserva de tropa do trem nascia tarde demais.** `_reserve()` grava em
   `units.conquest_reserve` para farm e coleta não gastarem a escolta entre o
   agendamento e o disparo do Hunter. Gravando no fim do ciclo, ela só passava
   a valer no ciclo **seguinte** — ou seja, no ciclo em que o trem foi montado
   a escolta ficou desprotegida o tempo todo. O mesmo valia para
   `_reserve_toward_escort()`, que existe justamente para a aldeia *juntar*
   escolta.
2. **Acompanhamento e agendamento aconteciam num minuto arbitrário.** Um ciclo
   completo mediu ~4h com 30 aldeias em 2026-09-21 (§8.14). O planejador
   disparava quando o laço terminasse, fosse lá quando fosse.

### O que mudou

- `TWB.run_barbarian_conquest()` roda no início do ciclo, logo depois do bloco
  da conquista PvP, e faz **acompanhar → planejar**, nessa ordem.
- `TWB.prime_barbarian_sources()` faz a leitura mínima (o mesmo
  `Village.prime_for_conquest()` da §8.14) das aldeias que a decisão depende,
  antes do planejador. Quem entra: a aldeia `reserved_by` de um registro ativo
  em `cache/conquest`, mais toda aldeia que **pode** ter nobre livre.
- `Village.run_conquest()` saiu de `Village.run()`. Continua existindo e
  continua sendo chamado — por `run_barbarian_conquest()`, e só para as
  âncoras.
- `BarbarianTrainPlanner` deixou de ser construído no fim do `while`.

### Duas decisões que não são detalhe

**A ordem "acompanhar antes de planejar" virou explícita.**
`BarbarianTrainPlanner.run()` desiste cedo quando `active_conquests()` não está
vazio (um trem por vez no império), e quem tira um alvo dali é o
acompanhamento: posse confirmada, alvo perdido para outro jogador, alvo
reservado pela tribo. No modelo antigo o laço de aldeias rodava antes do
planejador e essa ordem valia **por acidente** de layout. Invertida, uma
conquista que acabou de terminar bloquearia a próxima por um ciclo inteiro — e
um ciclo aqui mede horas.

**A lista do prime é um superconjunto de propósito.** O planejador conta nobre
por `village.units.troops`, e no início do ciclo esse número é a foto do fim do
ciclo passado (os objetos `Village` sobrevivem entre ciclos). Por isso o
candidato sai da **união** de duas fontes: o que o objeto em memória ainda
carrega e o `troops` do snapshot `cache/managed/{vid}.json`. A assimetria é o
argumento: aldeia que entra na lista e não tem mais nobre é corrigida pela
leitura viva e sai sozinha; aldeia que fica **de fora** nunca é corrigida e
some da contagem em silêncio. Errar para o lado de primar demais custa ~4
requisições; errar para o outro adia um trem inteiro por um ciclo.

**Chamar `run_conquest()` só para as âncoras não é amostragem.**
`ConquestManager._get_my_conquest()` casa exatamente por `reserved_by`, então
as outras 29 aldeias que chamavam o método dentro do laço sempre saíam no
primeiro `return False`. Manter a chamada dentro de `run()` *além* da nova
daria, para a âncora, um segundo passe de `_handle_existing()` no mesmo ciclo —
um segundo caminho capaz de comprometer nobre pelo mesmo alvo, que é a classe
de bug que custou 527 tropas e uma moeda em 2026-08-12.

### Estado

Suíte inteira verde. ✅ **Validado em campo em 2026-09-22**, na sessão das
19:14: `Conquest: primed 3/3 source village(s) before the cycle` às 19:16:47,
seguido na mesma hora do acompanhamento da conquista ativa (`4 nobre(s) ja a
caminho de 51540`) e do `ConquestPlanner` (`ja existe conquista barbara em
andamento`) — tudo antes do `Village cycle done` da BBM 001 (19:26:00). O
critério original era esse: as linhas da conquista na abertura do ciclo, não
depois da última aldeia.

---

## 8.16 ✅ `P-FARM-MOTIVO` — o bot já sabia por que não atacou, e jogava fora (2026-09-22)

Item 2 da §6.1.2 do `frontend.md`, que o próprio documento marcava como a melhor
razão valor/esforço da lista *"porque o dado já é produzido e jogado fora"*.

### O defeito

`AttackManager` calcula o motivo de cada descarte — dono, pontos, raio,
`_unknown_ignored`, janela 23h–8h, intervalo entre ataques, relatório de espião,
e o texto do `error_box` que o servidor devolve numa recusa. Tudo isso morria em
linhas de `DEBUG` (que não vão para o `session_latest.log` em nível normal) ou
não era escrito em lugar nenhum. O que sobrava era uma linha por ciclo:

```
Farm targets: 23 Ignored targets: 316
```

O custo já foi pago em campo: em 2026-08-19 uma aldeia teve **100% dos ataques
recusados** e ninguém soube por quê até alguém instrumentar a falha na mão — o
motivo (limite de ataque falso do mundo) estava no `error_box` da resposta o
tempo todo. É o décimo terceiro e o décimo quarto padrões do `CLAUDE.md`.

### Três coisas que apareceram ao implementar, e nenhuma estava no plano

**1. `attack()` devolve `False` para três coisas diferentes.** Alvo sem
coordenada, timeout de rede e recusa do jogo — e só na última `last_refusal`
fica preenchido. Um registro ingênuo (`"o jogo recusou: " + last_refusal`)
apresentaria "não sei o que aconteceu" como diagnóstico, que é pior do que não
registrar nada, porque parece resposta. Daí o `AttackManager.last_attack_failure`
novo: código do motivo, zerado no início de todo `attack()`, ao lado do
`last_refusal` que continua sendo o texto do servidor. Caminho que falhe sem
publicar código degrada para `falha_de_rede` com a palavra *desconhecido* no
detalhe — legível como ausência de resposta, não como recusa.

**2. Ausência de linha significava duas coisas opostas.** Um alvo cortado pelo
teto de `max_farms` e um alvo que o laço **nem alcançou** (porque o `break` de
falta de tropa disparou antes) apareceriam idênticos: sem registro. Viraram dois
códigos próprios, `fora_do_teto` e `ciclo_encerrado_sem_tropa`. É o vigésimo
sexto padrão com outra roupa — lista curta é indistinguível de lista completa.

**3. `scout()` devolve `False` sem levantar quando faltam espiões**, e os três
chamadores em `can_attack()` descartavam esse retorno. "Explorou antes de
atacar" (etapa normal do fluxo) e "quis explorar e não tinha espião" (alvo
travado até haver) são opostos para quem lê e eram invisíveis da mesma forma.
Viraram `espiao_enviado` e `sem_espiao`.

### O que foi escrito

`game/farm_exclusions.py` — vocabulário fechado de 21 códigos, cada um com fase
(seleção / tentativa), rótulo em pt-BR, explicação e **qual chave de config
mexe nele** (ou `None` quando não há nada a mexer, que é metade dos casos). Mais
o `FarmExclusionLog`, que acumula o ciclo e grava
`cache/farm_exclusions/<village_id>.json` no fim do `run()`.

Três decisões de contrato:

- **Snapshot do último ciclo, não log acumulado.** O arquivo é reescrito
  inteiro. Motivo do sexto padrão: "intervalo entre ataques" e "aguardando
  relatório" expiram sozinhos em horas, e uma lista acumulada teria a maioria
  das linhas já falsa sem nada distinguindo as vivas das mortas. Série histórica
  exige contrato de evento com `observed_at` por ocorrência — que é o `FND-01`.
- **`observed_at` por entrada**, e a página mostra a idade.
- **O teto de entradas corta só a fase de seleção** (400). As de tentativa são
  no máximo `max_farms` e são as únicas com valor diagnóstico; um teto global as
  perderia primeiro, porque são registradas depois. O `summary` conta **tudo**,
  truncado ou não, e `truncated: true` diz que houve corte.

### Testes

`tests/test_farm_exclusions.py` (24 checagens, sem rede, sem tocar em `cache/`
— `village_id=None` faz `flush()` virar no-op). **A guarda foi provada
quebrando o mapeamento de propósito**: trocando `code = self.last_attack_failure`
por `"recusado_pelo_jogo"` fixo, três testes falham, entre eles
`test_timeout_nao_vira_recusa`. Guarda que não pode falhar é o décimo quinto
padrão de cabeça para baixo.

`tests/smoke_village_page.py` (fora do glob, lê `cache/` real) renderiza
`/village` pelo test client do Flask — Jinja2 só falha em runtime, então é o
único jeito barato de pegar erro de template sem subir o servidor. Cobre os dois
ramos: sem arquivo e populado (com payload sintético **em memória**, porque não
se fabrica arquivo dentro de `cache/`, que é estado real do bot).

### Estado

Suíte verde. O aceite é abrir `/village?id=<uma aldeia>` e ver a contagem por
motivo somar com `Farm targets` + `Ignored targets` do log do mesmo ciclo. Se
divergirem, há um caminho de descarte não instrumentado — e descobrir isso é
metade do valor da feature.

⏳ **Observado em campo em 2026-09-22, aceite NÃO fechado — e a divergência
apareceu, como a frase acima previa.** Os arquivos nasceram para as quatro
primeiras aldeias da sessão das 19:14. Comparando **alvos distintos** em
`targets` (não `summary`, que conta registros e passa do total quando um alvo
é tentado com mais de um pacote) contra a linha do log:

| Aldeia | Log (farm + ignorados) | `targets` no arquivo |
|---|---|---|
| BBM 001 (41123) | 19 + 313 = 332 | 331 |
| BBM 002 (38409) | 19 + 313 = 332 | **312** |
| BBM 003 (44683) | 19 + 313 = 332 | 331 |
| BBM 004 (39292) | 2 + 155 = 157 | 156 |

- **BBM 002: 19 alvos sem linha nenhuma — caminho não instrumentado achado.**
  O template dela é `watchtower_support`, que tem `"farm": []` em todos os
  estágios **de propósito** (aldeia de espionagem não farma). Com
  `self.template == []`, `_ordered_templates()` devolve `[]`, o laço do
  `run()` não entra em `send_farm()` para nenhum alvo, e nada é registrado.
  No log isso aparece como `Farm targets: 19` seguido de silêncio — nenhuma
  requisição a `screen=place`. Correção pequena e ainda não feita: registrar
  um código próprio (ex.: `sem_pacote_de_farm`, knob `villages.<id>.units`)
  quando não há pacote, ou nem calcular alvos nesse caso.
- **Diferença de 1 nas outras três:** ainda sem explicação. Suspeita não
  verificada: `self.ignored` contando o mesmo id duas vezes (313 ignorados
  contra 312 registros de seleção). Conferir antes de declarar resolvido.
- ✅ **Os dois fechados no código em 2026-09-22 (fim do dia).**
  - **BBM 002:** alvo avaliado sem pacote nenhum agora registra
    `sem_pacote_de_farm` (fase tentativa, knob `villages.<id>.units`). De
    brinde, `_ordered_templates()` passou a descartar pacote vazio (`{}` ou só
    zeros): `_legalize()` o devolvia intacto (população 0) e
    `enough_in_village()` aprovava por nada faltar — um template com
    `"farm": {}` mandaria ataque sem tropa. Nenhum template atual tem isso.
  - **Diferença de 1:** era a **própria aldeia**, não id duplicado. Conferido
    nos quatro arquivos antes de mexer: ela está ausente de `targets` em todos,
    e `selecao` = ignorados do log − 1 (312/313 e 154/155). Ela caía em
    `dono_jogador`, entrava em `self.ignored` (que alimenta o log) e ficava fora
    do arquivo pelo `if not own`. Agora sai do laço antes de qualquer filtro.
    Junto, o `Ignored targets` do log passou a ser contagem **do ciclo**: vinha
    de `len(self.ignored)`, lista que atravessa ciclos (existe para não repetir
    DEBUG), nunca perde aldeia que saiu do scan e não inclui
    `janela_noturna_jogador` nem `bloqueado_pelo_jogo` — três outras formas de
    o aceite divergir. Ninguém faz parse dessa linha (grep em `.py/.html/.js`).
  - Testes em `tests/test_farm_exclusions.py` (+4, 1 ajustado); os cinco que
    tocam o código novo **falham contra o `attack.py` do HEAD** (rodado).
  - **⏳ Aceite de campo:** depois de reiniciar o bot, `Farm targets` +
    `Ignored targets` = alvos distintos de `targets`, exato, em toda aldeia; e
    a BBM 002 com 19 linhas `sem_pacote_de_farm`.
- O caminho de recusa funcionou em campo: a BBM 004 registrou
  `recusado_pelo_jogo` com o texto do `error_box` (limite de ataque falso,
  56 × 48 habitantes). Foi essa linha que levou ao `P-PONTOS-ZERO` (§8.23):
  a recusa não deveria ter acontecido.

---

## 8.17 ✅ `P-STATS-PAINEL` (Feature 37) — a série que o jogo publica virou card (2026-09-22)

Item 6 da §6.1.2 do `frontend.md`, sobre a medição da §8.13 (`P-STATS-JOGO`):
o jogo já agrega `Saqueado`/`Coletado` por dia, conta inteira, dentro do HTML
de `screen=info_player&mode=stats_own` — e até aqui nada do bot consumia isso.

### O que foi escrito

- **`Extractor.stats_own_series(res)`** (`core/extractors.py`) — parseia os
  blocos `data.push({label: '...', ..., details: [...]})` por label (não por
  ordem, que a §8.13 já registrava como não garantida). Devolve `None` quando
  a página não tem nenhum bloco reconhecível — login, bot-protection, ou
  markup que mudou — para o chamador distinguir "sem série" de "erro de
  rede". Cada linha malformada é pulada sem derrubar a série inteira, e cada
  bloco com JSON quebrado é pulado sem derrubar os outros blocos.
- **`game/player_stats.py::PlayerStats`** — lê a tela no máximo a cada
  `player_stats.cache_seconds` (default 6h: a resolução da série é diária,
  reler por ciclo só gastaria orçamento de requisição da conta, mesmo
  raciocínio do TTL do `WorldVillages`, §8.6). Guarda só `Saqueado`/`Coletado`
  — as séries de gasto (`Unidades`, `Edifícios`, ...) não têm consumidor
  ainda, e gravá-las seria dado morto no cache. **Uma leitura ruim nunca
  apaga uma leitura boa anterior**: falha de rede, markup irreconhecível ou
  resposta sem as séries de interesse deixam `_series` intocado — mesmo
  raciocínio de `WorldVillages.rows()` (§8.6), para um soluço do servidor não
  fazer o painel regredir de "tenho dado de ontem" para "sem dado nenhum".
  Escreve `cache/player_stats.json` (`FileManager.save_json_file`, atômico).
- **`TWB.player_stats`** (`twb.py`) — instanciado uma vez por processo, como
  `WorldVillages`/`ReservationBoard`, e `refresh()`ado no início de cada
  ciclo com qualquer aldeia gerenciada como endereço do GET (a resposta é da
  conta inteira, não daquela aldeia). Gate `player_stats.enabled` (default
  **true** — é leitura pura, sem efeito de jogo, ao contrário da maioria dos
  gates deste projeto que nascem `false`).
- **`webmanager/utils.py::PlayerStatsReader`** — lê
  `cache/player_stats.json` e formata por dia, mais recente primeiro. O dia
  mais recente é marcado `maybe_partial`: a resposta não diz se aquele dia já
  fechou, e apresentar como total definitivo violaria o contrato (d) da
  §6.1.2 do `frontend.md` ("é saldo, não evento").
- **Card em `/empire`** (`empire.html`) — tabela Saqueado × Coletado por dia,
  com decomposição por recurso no `title` de cada célula. Legenda no próprio
  card repete os contratos (a)/(b) da §6.1.2: conta inteira, não substitui os
  relatórios de farm, retenção de 7 dias.
- **Config**: seção `player_stats` nova (`enabled`, `cache_seconds`) em
  `config.example.json` e `webmanager/helpfile.py`, `build.version` 4.5 →
  **4.6** só no exemplo, para o merge injetar a seção no `config.json` vivo.

### O que a captura real ensinou, e o que ficou de fora

O fixture de `Extractor.stats_own_series` é recorte **verbatim** de
`cache/debug/stats_own.html` (capturado em 2026-09-21 pela §8.13), inclusive
os três dias com `Coletado.total == 0` de antes da Feature "coleta em massa"
ligar — confirma que `0` sobrevive ao parse como inteiro, não vira `None` nem
é descartado por engano (`if not total` teria apagado exatamente o dado mais
interessante da série). A participação no total do dia (`percent`) **não** é
repassada ao webmanager: ela soma com as séries de gasto que este card não
lê, e expor o campo sem consumidor certo seria convite para alguém rotulá-lo
"aproveitamento" mais tarde — o quinto padrão do `CLAUDE.md` outra vez.

### ⚠️ O que a revisão do mesmo dia achou, e que os testes originais não pegavam

A primeira versão foi escrita e "aprovada" com 83 checagens verdes. Uma
releitura crítica no mesmo dia achou **três defeitos**, e o primeiro é do tipo
que este repositório mais paga caro.

**1. O parser pareava `label` com `details` atravessando blocos.** A
formulação era uma varredura do documento inteiro:

```
label:\s*'([^']+)'.*?details:\s*(\[\{.*?\}\])     (re.S)
```

Um bloco com `label:` e **sem** `details:` — que é exatamente a forma de uma
série de *linha* (pontos, aldeias, classificação) — faz o `.*?` pular a
fronteira e casar aquele label com os números do bloco **seguinte**; e o label
legítimo **desaparece**, porque o match já o consumiu. Medido contra um caso
construído: `Saqueado` sumiu e os números dele saíram rotulados `Pontos`.
Nenhum erro, nenhum log — o card de `/empire` mostraria coletado como se fosse
saqueado, **invertendo a única pergunta que ele existe para responder**.

Na página de hoje os 8 blocos têm os dois campos e o pareamento sai certo —
por sorte, não por construção. Corrigido recortando um bloco `data.push(...)`
por vez **antes** de procurar os campos, o que torna o vazamento
estruturalmente impossível. De quebra, `details` passou a sair por
`balanced_slice` em vez de `\[\{.*?\}\]`: o lazy para no primeiro `}]` e
truncaria a lista se o jogo aninhasse um objeto por ponto — e o docstring do
`balanced_slice`, neste mesmo arquivo, existe por causa dessa armadilha.
Guarda em `test_o_regex_antigo_erra_este_caso_a_guarda_pode_falhar`, que roda
a formulação **antiga** contra o markup e exige que ela erre.

**2. Convenção de nome inventada.** A classe do bot chamava-se
`PlayerStatsReader`, igual à do webmanager, e o comentário dizia que isso
seguia "a mesma convenção". Medido: era o **único** nome de classe duplicado
entre `game/`+`core/` e `webmanager/` em todo o repositório — a convenção real
é o oposto (`ConquestManager`/`ConquestReader`,
`DefenceManager`/`FlagReader`, `FarmExclusionLog`/`FarmExclusionReader`).
Renomeada para **`PlayerStats`**, seguindo `WorldVillages`, que é o análogo
direto. É o 16º padrão aplicado ao próprio comentário recém-escrito: uma
afirmação sobre o código que soa forte por citar um precedente, e que ninguém
tinha conferido.

**3. O merge do `build.version` não tinha sido simulado** antes de bumpar —
passo que o `CLAUDE.md` exige explicitamente, porque `merge_configs()` usa o
template como base e **descarta chave global que só exista no `config.json`
vivo**. Simulado depois, contra o config real: **0 chaves descartadas, 1 seção
acrescentada** (`player_stats`). O resultado é o melhor possível; o problema é
que ele foi descoberto depois de já ter bumpado, não antes.

O que os três têm em comum: os testes verdes mediam o caminho feliz com o
markup de hoje. Nenhum deles teria falhado com o parser quebrado da forma do
item 1, porque a fixture real não exercita o caso.

### Testes

`tests/test_stats_own_extractor.py` (37 checagens, fixture verbatim + os três
casos adversariais do item 1 acima), `tests/test_player_stats_reader.py` (33
checagens, TTL/gate/degradação com wrapper falso) e
`tests/test_player_stats_webmanager.py` (19 checagens, `CACHE_PATH` trocado
por arquivo temporário, nunca toca `cache/` real). Suíte inteira (57 arquivos)
verde; `/empire` renderizado via `app.test_client()` sem crash.

✅ **Leitura validada em campo em 2026-09-22:** `PlayerStats: 7 dia(s) de
Coletado/Saqueado lidos` às 19:15:00, no primeiro minuto da sessão, e
`cache/player_stats.json` reescrito pelo bot no mesmo minuto. O card de
`/empire` com esse arquivo não foi aberto no navegador.

---

## 8.18 ✅ `P-VOO-PAINEL` (Feature 38) — o que está no ar virou painel (2026-09-22)

Item 1 da §6.1.2 do `frontend.md`, descrito lá como **"o mais valioso, e o
único que não é cosmético"**, e o buraco de observabilidade que deixou o
`_get_my_conquest()` devolver `None` com quatro nobres no ar sem ninguém ver
(§6.1). Até aqui nada no bot lia a tela de comandos do jogo.

### A decisão de fonte, que é o que faz os dois contratos se resolverem sozinhos

Os contratos do item 1 são: (a) a hora precisa ser **de chegada**, dizendo se
veio confirmada ou estimada; (b) a lista **nunca** pode sair do campo `status`
do cache de conquista — foi esse campo que dizia `"complete"` com quatro
nobres voando.

Ler `screen=overview_villages&mode=commands` resolve os dois sem esforço: o
que volta é o que o **jogo** diz que está no ar, com a hora que o **servidor**
calculou. Não há opinião nossa no meio, e `cache/conquest` não é aberto em
momento algum. A alternativa — estimar com `Extractor.attack_duration()` —
seria construir o painel sobre a função que devolve **0** quando o regex
falha, fazendo o nobre nascer "já pousado" (sexto padrão).

### As três coisas que a captura real ensinou, e que não são óbvias no markup

**1. A tela é paginada e o contador do cabeçalho mente.** Sem `page=-1` vieram
**25 linhas, e o `<th>` dizia "Comando (25)"** — o contador conta a *página*,
não o total. Com `page=-1` vieram **65**: 40 comandos (62%) eram invisíveis no
default, e nada na resposta denunciava isso. Um painel "Em voo" que esconde a
maioria do que voa é pior que nenhum, porque ele parece completo. É o 26º
padrão, e aqui ele quase entrou pela porta da frente: eu tinha aberto a tela e
escrito o regex da linha **antes** de contar quantas linhas existiam.
Consequência de desenho: `declared` **não** é exposto como total. Ele vira
guarda contra o *parser* perder linha (divergência = warning), que é a única
coisa que ele de fato detecta.

**2. As colunas de unidade variam por mundo.** br143 não tem arqueiro, então
são **10** colunas (`spear sword axe spy light heavy ram catapult knight
snob`). Num mundo com arqueiro são 12. Qualquer ordem chumbada passaria a
rotular tropa errada **em silêncio** — e o teste mede o caso concreto: com a
ordem do br143 aplicada a um mundo com arqueiro, o `zip` trunca, o arqueiro
some e `snob` recebe o valor da 10ª célula. O painel anunciaria trem de
conquista que não existe. Por isso a ordem é lida do próprio cabeçalho, pelo
nome do ícone `unit_<X>.webp` — o mesmo sinal independente de idioma que
`INCOMING_SUPPORT_SPEED_ICON` já usava.

**3. Não existe timestamp absoluto aqui.** Ao contrário do widget de comandos
*recebidos* (que traz `data-endtime`), esta tela só tem texto renderizado
("hoje às 16:24:23"). Logo a hora é resolvida contra o relógio do **servidor**,
publicado na própria página em `#serverDate`/`#serverTime`. Usar o relógio da
máquina "funcionaria" no br143 — os dois coincidem — e quebraria calado num
mundo de outro fuso: é o 17º padrão, em que o ambiente de medição não separa
as duas hipóteses, então vale a que é estruturalmente correta. Sem relógio na
página, `arrival_ts` sai **`None`**, nunca 0.

### Um achado de brinde: o jogo marca nobre duas vezes

A contagem crua deu **69** `data-command-type` para **65** linhas. As 4 extras
não eram lixo: são exatamente as 4 linhas de nobre, que ganham um **segundo**
`<span class="own_command">` com `data-icon-hint="Com nobre"` e ícone
`snob.webp`. Como os dois atributos são idênticos (mesmo tipo, mesmo id), ler
o primeiro é seguro — mas o ícone é uma **leitura independente** do fato mais
caro de errar neste painel. `has_snob` passou a ser `coluna OR ícone`, e
**discordância entre os dois vira warning** em vez de um lado vencer calado.
Efeito colateral útil, coberto por teste: com a coluna de tropa quebrada, o
nobre continua visível pelo ícone.

### O que foi escrito

- **`Extractor.own_commands(res)`** e **`Extractor.server_clock(res)`**
  (`core/extractors.py`). `own_commands` devolve `None` quando a tabela não
  existe (login, bot-protection, markup novo) e **lista vazia** quando não há
  comandos — duas coisas diferentes, e "nada no ar" é legítimo e comum.
- **`game/in_flight.py::InFlight`** — uma instância por processo (como
  `WorldVillages`/`PlayerStats`: a resposta é da conta inteira), TTL curto
  (`in_flight.cache_seconds`, default **600**) e leitura ruim que nunca apaga
  a boa anterior. Escreve `cache/in_flight.json`.
- **`TWB.in_flight`** (`twb.py`) — `refresh()` no **início** do ciclo, antes do
  laço de aldeias: assim a leitura descreve o estado com que o ciclo começou,
  e não um meio-termo entre o que já foi enviado neste ciclo e o que não foi.
- **`webmanager/utils.py::InFlightReader`** + card de largura cheia em
  `/empire`.
- **Config**: seção `in_flight` (`enabled`, `cache_seconds`) em
  `config.example.json` e `helpfile.py`; `build.version` 4.6 → **4.7** só no
  exemplo. **Merge simulado antes de bumpar** (o passo que a §8.17 registrou
  ter feito na ordem errada): 0 chaves descartadas, 1 seção acrescentada.

### ⚠️ Escopo deliberado: isto é observabilidade, não decisão

Nada aqui muda o que o bot faz, e a tentação de mudar é real — este é
exatamente o dado que faltava quando `_get_my_conquest()` devolveu `None`.
Cruzar a lista com `ConquestManager` para uma segunda trava de nobre em voo
**não foi feito**: mexer ali mexe em tropa real, e a trava atual por tempo de
chegada já funciona. O valor desta feature é alguém **olhar e ver**.

### O dado que envelhece mais rápido do cache inteiro

Todo o resto do `cache/` descreve estado que muda em horas; este descreve
coisas que **pousam**. Um comando cuja chegada já passou pode ter chegado — ou
o bot pode só não ter relido. Como não dá para saber qual, ele vai para um
balde próprio (`landed`), **nunca somado aos que voam nem escondido**:
esconder seria mentir por omissão, deixar em "no ar" seria mentir por
afirmação. A idade da leitura é publicada junto e fica vermelha acima de 30
min. Pelo mesmo motivo, "tropa no ar" soma só o que ainda voa.

### Testes

`tests/test_own_commands_extractor.py` (58 checagens, fixture **verbatim** das
linhas de farm, de nobre e de retirada, mais o caso do mundo com arqueiro, a
guarda da ordem chumbada, a discordância dos dois sinais de nobre e a
exigência de que a falha de hora seja `None` e não 0) e
`tests/test_in_flight.py` (50 checagens, wrapper de mentira, `CACHE_PATH`
temporário nos dois lados, `page=-1` verificado **na URL pedida** — é o único
parâmetro cuja ausência quebraria a feature sem quebrar nenhum teste de
parser). Suíte inteira (59 arquivos) verde. `/empire` renderizado por
`app.test_client()` nos **dois** ramos (com dado real da captura: 64 no ar, 1
pousado, 4 nobres; e sem arquivo: "sem leitura ainda").

✅ **Leitura validada em campo em 2026-09-22:** `InFlight: 49 comando(s) no ar
(4 com nobre)` às 19:15:07, e `cache/in_flight.json` sobrescrito pelo bot no
mesmo minuto (o arquivo da captura saiu de cena). Os 4 nobres batem com o trem
da 51540 registrado em `cache/conquest` (3 da 41123 + 1 da 74690), e as duas
fontes são independentes: uma é a tela do jogo, a outra o nosso cache. O card
de `/empire` com esse arquivo não foi aberto no navegador.

## 8.19 ✅ `P-PURGE-PARCIAL` — os quatro bugs do fork, e a metade do B9 que sobrou (2026-09-22)

Item 5 da fila tática da §7.10. Resultado da verificação, bug a bug:

| Bug | Aqui | Onde |
|---|---|---|
| B4 — `t.wrapper` `None` no handler de crash | ✅ já fechado (P0-3) | `twb.py::main`, guarda + `try` em volta do report e da notificação |
| B8 — `extra["units_sent"]` direto | ✅ já fechado (P2-25/P2-26) | `reports.py::safe_to_engage`, `manager.py` — tudo por `.get(...) or {}` |
| B9 — overview com zero aldeias | ✅ metade vazia fechada em 2026-08-22 | `purge_refusal_reason` |
| B9 — overview **parcial** | ❌ **aberto até hoje** | ver abaixo |
| B10 — user-agent da seção errada | ✅ nunca existiu | `twb.py` lê `config["bot"]["user_agent"]` |

**O buraco.** `OverviewPage` pede `game.php?screen=overview_villages` sem
`group` nem `page`, e o jogo serve o grupo e a página que o **jogador** deixou
selecionados no navegador. Com a visão geral filtrada num grupo de 10 aldeias,
a interseção com o config não fica vazia, as duas recusas de
`purge_refusal_reason` não disparam, e a limpeza apagava do `config.json` e do
`cache/managed` as outras 20. O usuário joga na mesma conta (9º padrão), então
filtrar por grupo é uso normal, não caso exótico.

**Por que não foi corrigido pondo `group=0&page=-1` na URL.** Duas razões: (a)
o grupo escolhido na interface fica gravado como preferência do jogador, e é
provável que o escolhido por querystring também fique — **não medido** —, caso
em que o bot passaria a desfazer o filtro do usuário a cada ciclo (a armadilha
"restaurar a tela do jogador" da §7.10); (b) a sessão do `cache/session.json`
estava vencida e o bot parado (log parado às 16:50:56 de 2026-09-22), então não
havia como capturar o markup de grupo/paginação, e fixture se copia, não se
inventa. A sonda ficou em `cache/_probe_overview.py` para quando houver sessão.

**O que mudou.** A limpeza deixou de tratar "ausente da visão geral" como
"perdida". `TWB.confirm_lost_villages(stale, found, world_rows)` só confirma
perda quando o `map/village.txt` público (`WorldVillages.rows()`, o mesmo
objeto da conquista, reaproveitado se já existir) dá a aldeia com **outro
dono**. O nosso id sai do próprio arquivo: é o dono **majoritário** das aldeias
que a visão geral acabou de listar. Maioria e não unanimidade porque o arquivo
atrasa — medido: no `villages_br143.txt` de 20/09, 30 das 31 aldeias do config
dão `5955651` e a **44167 (JULIET)**, conquistada depois, ainda dá o dono
anterior `919832469`. Arquivo indisponível, aldeia ausente dele, ou dono ainda
nosso: a aldeia **fica**, com um WARNING que diz o motivo
(`... NAO sera removida: ainda nossa na lista do mundo -- a visao geral
provavelmente esta filtrada por grupo ou paginada`).

**Custo, dito às claras.** (1) A perda real passa a ser limpa com até
`conquest.world_village_list_ttl` (6h) de atraso. Não há dano nisso: no mesmo
intervalo o laço principal já pula a aldeia por `found_villages`. (2) Com
`conquest.use_world_village_list: false` a lista vem vazia e **nenhuma**
limpeza acontece — o WARNING avisa. Troca deliberada: a limpeza é destrutiva, e
na dúvida o certo é não apagar.

**Testes.** `tests/test_village_purge_partial.py`, com linhas **verbatim** do
`village.txt` do br143: grupo filtrado não apaga nada, perda real é confirmada,
lista indisponível e aldeia ausente não apagam, conquista recente não troca "quem
somos", e uma guarda textual contra a comparação antiga em `twb.py`. A guarda
foi provada reprovando: com a lógica antiga injetada, o cenário de grupo
devolve `['35059', '36294']` como perdidas. Suíte inteira verde.

---

## 8.20 ✅ `P-PVP-RESERVA` — um alvo PvP não enxergava a tropa do outro (2026-09-22)

Fecha a §6.4. Escolhido nesta data porque era o único item aberto de risco
real (tropa em jogo) que dava para fechar **sem sessão**: o bot estava parado
desde 16:50:56 com o `cache/session.json` vencido, e todo o resto da fila ou
pedia captura, ou pedia campo.

**O defeito, em quatro lugares.** `_build_clear_units()`,
`_build_noble_attacks()`, `_select_noble_attack_plan()` e
`_select_clear_village()` liam `units.troops` cru. Com dois alvos, o B
simulava e agendava contra a tropa que o A já tinha reservado para os
comandos dele no Hunter; o comando que saísse por último seria recusado pelo
servidor, horas depois da decisão. A reserva do trem bárbaro
(`barbarian_conquest`) era igualmente invisível. E nobre é pior que tropa:
dois alvos em preparação podiam **travar os mesmos nobres**, porque em
preparação não existe reserva, só a trava no cache.

**O que mudou.**
- `_reserved_elsewhere(village, target_id)` — tudo que está no
  `conquest_reserve` da aldeia **menos** a chave `pvp:<este alvo>` (senão uma
  re-simulação se bloqueia com a própria reserva). Clear, escolta, ranking da
  aldeia de limpeza e plano de nobres descontam isso.
- `_snob_claims_of_other_targets()` — nobres travados por **outros alvos ainda
  em preparação** (`noble_villages` no cache). Alvo `scheduled` fica de fora
  de propósito: os nobres dele já estão na reserva em memória, e contar os dois
  descontaria o mesmo nobre duas vezes.
- `_sync_scheduled_reserves()` no início do `run()` — **a reserva vivia só na
  memória** do `TroopManager` e sumia a cada reinício (sessão vencida é o
  reinício de todo dia), enquanto o agendamento dura horas em disco. Agora ela
  é reconstruída a partir de `cache/hunter/schedules.json`, e só com comandos
  `pending`: reservar a tropa de um comando `sent` descontaria da tropa em casa
  uma tropa que não está mais em casa. Arquivo vazio/ilegível, ou sem os
  agendamentos daquele alvo, **não mexe em nada** — perder o arquivo não pode
  ser lido como "todos os comandos já saíram".
- **Piso da escolta.** `max(1, int(qty*ratio) // noble_count)` dava 1 unidade
  de cada tipo a **cada** ataque: 2 aríetes, razão 0,5, 4 nobres → pedia 4 de 2.
  Agora a sobra vai uma por ataque só enquanto o orçamento da aldeia
  (`int(livre*ratio)`) durar. **A prova da regressão achou um caso a mais**, que
  ninguém tinha descrito: na aldeia que também é a de limpeza, 3 cavalarias
  leves viravam 2 na limpeza + 1 em cada uma das 2 escoltas = 4 de 3.
- **Limpeza vazia espera, não falha.** Com o desconto, `{}` virou resposta
  normal de `_build_clear_units()` (2ª metade do 3º padrão: o domínio de
  retorno alargou). Os dois consumidores foram relidos:
  `_prepare_departure_deadlines` já saía cedo; `_step_simulate` não — com
  relatório de espionagem fecharia o alvo como `simulation_failed` para sempre
  por uma reserva que é temporária, e pelo caminho de override agendaria os
  **nobres sem limpeza**. Agora ele espera; o limite é o prazo de saída ou,
  como esse prazo só é sondado com limpeza não vazia, a própria
  `arrival_time` (`fail_reason: no_free_clear_troops`, com rótulo no painel).

**O que ficou de fora, e por quê.** Tropa de limpeza de um alvo **ainda em
preparação** não é descontada: antes da simulação não existe número exato, e
inventar um seria reservar palpite. Quem agenda primeiro reserva; o segundo vê
o resto e simula contra ele — ou espera. `_select_clear_village()` devolvendo
`None` continua sendo falha terminal (`no_clear_village`), como antes.

**Testes.** `tests/test_pvp_cross_target_reserve.py`, 15 casos, sem rede nem
`cache/` real. Provado reprovando: com `_reserved_elsewhere` devolvendo `{}`,
o piso antigo e sem as travas de preparação, **9 dos 13** casos originais
falham (os 4 restantes são guardas que valem nos dois códigos: reserva
própria, arquivo ilegível, alvo terminal e a aritmética do piso). Suíte
inteira verde.

**⏳ Falta campo:** só existe um alvo PvP de cada vez hoje, então o caso de dois
alvos segue não exercitado. O sinal visível agora é a reidratação depois de um
reinício: `reserva de <alvo> na aldeia <id> alinhada ao Hunter`.

## 8.21 ✅ `P-CICLO-MEDIDA` — para onde vão as ~4h de um ciclo (2026-09-22)

**Por que este e não outro.** Com a fila da §9 inteira em "⏳ falta campo", o
próximo item da fila anterior é o baseline (item 3): *"duração de ciclo ...
sem baseline, nenhuma das hipóteses da §7.7 é verificável"*. E o ciclo de ~4h
com 30 aldeias já tinha custado duas reorganizações (§8.14, §8.15) sem que
ninguém soubesse **onde** essas 4h estavam — o código não media tempo em
lugar nenhum (`grep time.time|perf_counter` em `twb.py`/`village.py`: só o
timestamp de `last_run`).

**O que o log já dizia, e não bastava.** `get_url`/`post_url` dormem
`randint(3·delay, 7·delay)` antes de **cada** requisição, e o `config.json`
vivo tem `bot.delay_factor = 3` (nenhuma aldeia sobrescreve): 9–21 s por
requisição. O `session_latest.log` de hoje mostra requisições a 13–17 s uma da
outra. Logo a duração do ciclo é quase inteira *número de requisições × ~15 s*
— ~930 requisições em 4h, ~30 por aldeia — e encurtar o ciclo é **cortar
requisição**. O log tem cada GET em DEBUG, mas não diz a que fase ele
pertence, e é truncado a cada reinício.

**O que foi escrito.**
- `core/cycle_meter.py::CycleMeter` — pilha de fases; cada requisição vai para
  a fase do **topo**, e o tempo de parede é **exclusivo** (subfase não é
  contada de novo na mãe), então a soma dos baldes fecha o total e os
  percentuais somam 100%. O que roda fora de fase nomeada cai em `(sem fase)`
  em vez de sumir — balde grande ali é instrumentação faltando. Subfase herda a
  aldeia da mãe; o Hunter passa `village=False` porque é da conta inteira
  mesmo quando chamado do checkpoint de uma aldeia.
- `WebWrapper` ganhou `self.meter` e registra, por requisição: método, sono,
  rede, tempo preso em captcha e falha. O registro nunca levanta.
- Fases em `Village.run()`: `init`, `defesa`, `missoes`, `construcao`,
  `recrutamento`, `nobre`, `mercado`, `compartilhamento`, `mapa`, `pvp`,
  `farm`, `coleta`; em `twb.py`: `overview`, `reservas_tribo`, `estatisticas`,
  `em_voo`, `pvp_inicio`, `conquista_barbara`, `aldeia` (resto de
  `village.run`), `estatua`, `inventario`, `hunter`, `perfis_farm`.
- Fim de ciclo (antes do sono): duas linhas `CycleMeter - INFO - Ciclo: ...` e
  `Ciclo por fase: ...` no log, e `cache/cycles/<inicio>.json` com todos os
  baldes `(aldeia, fase)`, o sono seguinte e as requisições feitas **entre**
  ciclos (Hunter pós-sono). Poda em 300 arquivos (~50 dias). Ciclo abortado por
  overview indisponível também é gravado, com `aborted`.

**Escopo deliberado:** só observabilidade. Nada muda o que o bot faz, nem o
ritmo — nenhuma chave de config nova. O que cortar vem **depois** de ler uns
dias de `cache/cycles/`, e com o 11º padrão em mente: agregar por fase **e**
por aldeia antes de concluir, porque aldeia de farm e aldeia de apoio não são
o mesmo conjunto.

**Testes.** `tests/test_cycle_meter.py`, 11 casos, relógio falso, sem rede nem
`cache/` real (a poda roda num diretório temporário). Provado reprovando: sem o
débito do tempo na entrada da subfase e com a requisição indo para a base da
pilha, 10 problemas acusados. Um achado no caminho: `test_session_and_captcha`
troca o `time` do `request.py` por um relógio falso sem `monotonic`, então o
registro usa `time.time()`, como o resto do arquivo. Suíte inteira verde
(62/62).

**⏳ Falta campo:** o bot que está rodando subiu às 18:38 com o código antigo.
O aceite é, depois de reiniciar, a primeira linha `Ciclo: ...` com `(sem fase)`
pequeno e o primeiro arquivo em `cache/cycles/`.
**Atualização 2026-09-22 19:20:** o bot foi reiniciado às 19:14 com o código
novo, e o primeiro arquivo já nasceu — `1790115248.json`, um ciclo **abortado**
(`overview_unavailable`, 1 requisição, 5 s) às 19:14:08, antes da sessão que
subiu às 19:14:37. Isso prova a gravação do caminho de aborto; o aceite do
ciclo completo continua aberto.

## 8.22 ✅ `P-CICLO-PAINEL` — a medição virou página (2026-09-22)

**Por que este.** Com toda a §9 em "⏳ falta campo", o próximo item é o
baseline (item 3), e a §8.21 parou de propósito em gravar: "o que cortar vem
depois de ler uns dias de `cache/cycles/`". Sem leitor, isso seria abrir até
300 JSONs na mão — e agregar do jeito errado, que é o risco do décimo
primeiro padrão.

**O que foi escrito.** `webmanager/utils.py::CycleReader` + rota `/cycles` +
`templates/cycles.html` (detalhe de tela em `frontend.md` §2.7). Só leitura:
nenhuma chave de config, nada muda no bot. O leitor:
- tira ciclo **abortado** de toda mediana e o conta a parte, com o motivo;
- dá a média por aldeia **por ciclo em que ela apareceu**, com
  `cycles_present` — aldeia fora do horário ativo não pode parecer barata;
- agrega por fase **e** por aldeia (e "Conta inteira" para `village=None`),
  com participação que fecha 100% porque o tempo do medidor é exclusivo;
- segundos por requisição é **razão das somas**, não média das razões;
- alerta `(sem fase)` acima de 5%;
- relê o diretório só quando `(nomes, maior mtime)` muda, reaproveitando
  `ReportReader._dir_signature`; arquivo ilegível é contado, não derruba.

**Testes.** `tests/test_cycle_reader.py`: os resumos são gerados pelo
**próprio `CycleMeter`** com relógio falso, não escritos a mão — se o formato
do produtor mudar, o teste quebra junto. Cobre abortado fora da mediana, média
por presença, fechamento em 100%, limiar de `(sem fase)` nos dois lados,
janela, arquivo ilegível, invalidação de cache e a página nos três ramos.
Provado reprovando: com o abortado dentro de `complete` e a média por aldeia
dividida pelo total de ciclos, 6 problemas acusados. Suíte inteira verde
(63/63).

**⏳ Falta campo:** o primeiro ciclo **completo** gravado. Até lá a página
mostra o ramo "nenhum ciclo completo na janela" com o abortado das 19:14.

---

## 8.23 ✅ `P-PONTOS-ZERO` — o piso de ataque falso estava desligado no império inteiro (2026-09-22)

### O sintoma

Às 19:44:56 da sessão das 19:14 o jogo recusou um farm da BBM 004 (39292 →
39503): *"A força de ataque precisa do mínimo de 56 habitantes. Você está
tentando enviar 48 fazendeiros."* O pacote era `{'light': 12}`. O
`AttackManager._legalize()` existe exatamente para crescer esse pacote até o
piso (§ do limite de ataque falso, 2026-08-19), e o log não tinha **nenhuma**
linha `crescido para` na sessão inteira.

### A causa, em três passos medidos

1. `_legalize()` não age quando `min_attack_pop` é 0, e
   `WorldConfig.min_attack_population()` devolve 0 quando não sabe os pontos.
2. `cache/managed/*.json`: **31 de 31 aldeias com `points: 0`**, em todos os
   `last_run` do dia. Não era a BBM 004; era todo mundo.
3. A única fonte de `Village.points` era `twb.py`, copiando de
   `OverviewPage.villages_data`. Um probe só-leitura com o próprio wrapper
   (`cache/_probe_overview_points.py`, resposta em
   `cache/_overview_points.html`) rodou o parser real sobre a tela: a
   visão geral desta conta abre no modo **Combinado** (`combined_table`), e
   `parse_production_table()` só conhece `production_table`. Resultado:
   `villages_data` vazio, nenhuma atribuição, `points` no default de classe.
   A tabela combinada **não tem coluna de pontos** — ler outra tabela não
   resolveria.

A captura que já estava em disco (`cache/_overview_default.html`, 18:11) era
a página de login, de uma sessão vencida — antes de concluir qualquer coisa
sobre markup a partir dela, conferir o `<title>`.

### O que o zero desligava, calado

- o piso de ataque falso em **todas** as aldeias (a BBM 001 tem 9.898 pontos,
  mínimo 98 — qualquer pacote abaixo disso era recusado e bloqueado pelo resto
  do ciclo);
- a estimativa de moral do PvP (`pvp_conquest.py:916` pula a conta sem
  `attacker_points`);
- a pontuação do resource sharing (`resource_sharing.py:538` caía para o nível
  do edifício principal).

Mesma família do segundo padrão do `CLAUDE.md`: o valor de falha (0) é
indistinguível de um valor legítimo, e o consumidor o trata como "o mundo não
tem limite".

### O que mudou

`Village.points_from_game_data()` lê `game_data.village.points` (um `int`,
presente em toda tela do jogo; conferido na captura: BBM 001 = 9898) e é
chamado no fim de `village_init()` — que roda antes de `set_farm_options()` e
também no `prime_for_conquest()`. Leitura ruim preserva o valor anterior em
vez de zerar. A atribuição por `villages_data` em `twb.py` ficou, com um
comentário dizendo que só funciona no modo Produção.

**Não** se trocou o modo da visão geral para Produção: o jogo lembra o último
modo aberto, então o bot mudaria a tela do usuário (armadilha registrada na
§7.10).

### Efeito colateral registrado, sem mudança

`OverviewPage.is_premium` sai do mesmo `parse_production_table()`, então a
autodetecção gravou `world.premium_account: false`. Hoje isso só controla
`building.auto_queue_len`, que está `false` — sem efeito. Se alguém ligar o
`auto_queue_len`, conferir `premium_account` à mão primeiro.

### Testes

`tests/test_village_points.py` (17 checagens): o helper com leitura boa e seis
leituras ruins, e a cadeia pontos → piso → `_legalize()` com o caso exato de
campo (48 → 56). Inclui o caso `points=0` exigindo que o pacote **não**
cresça — é a assinatura do bug. O caminho `village_init()` em si faz
requisição e não está coberto. Suíte inteira (64 arquivos) verde.

**⏳ Falta campo:** reiniciar o bot e ver `points` diferente de 0 no
`cache/managed` e as primeiras linhas `crescido para` no log. Enquanto o bot
atual não reiniciar, a correção não vale.

---

## 8.24 ✅ `P-FARM-CONQUISTA` — o farm atacava o alvo da própria conquista (2026-09-22)

### O incidente

A primeira conquista multi-origem deu certo: o trem da Bárbara #51540 (582|289),
agendado às 10:53 com `sources: {41123: 3, 74690: 1}`, pousou às 21:23:50 e a
lealdade lida dos quatro relatórios foi 69 → 38 → 3 → −35 (estimativa do bot:
0). É também a primeira validação em campo da leitura de lealdade por
relatório com um trem inteiro.

Só que o farm continuou tratando o alvo como uma bárbara qualquer enquanto o
trem voava. O reporter (`cache/logs/twb_*.log`) tem, depois do agendamento,
cinco farms contra a 51540: BBM 001 às 11:04, 16:03 e 18:51, BBM 010 às 12:30
e 20:32. Os três primeiros pousaram antes do trem (14:01, 19:00 e 15:24 —
inofensivos, a aldeia ainda era bárbara); os dois últimos chegam **depois**:

| Envio | Origem | Chegada | Efeito |
|---|---|---|---|
| 18:51:30 | BBM 001, 70 leves | 21:48:41 | relatório 152227464: as 70 leves morreram contra a escolta que ficou de guarnição, e a guarnição perdeu 6 lanceiros, 293 bárbaros, 131 leves, 4 aríetes e 3 catapultas |
| 20:32:35 | BBM 010, 70 leves | ~23:27 (calculado: 17,46 campos × 10 min) | no ar no momento do registro; comando velho demais para cancelar |

O farm só deixaria a aldeia depois que o mapa mostrasse dono — tarde demais
para o que já estava no ar. É o sexto padrão do `CLAUDE.md` com uma roupa nova:
a decisão de farmar olhava o estado do alvo **agora**, e o efeito acontece
horas depois, num mundo em que o trem já pousou.

### O que mudou (decisão do usuário: o farm nunca ataca aldeia da lista de conquista)

- `ConquestCache.farm_blocked_targets()` devolve `{alvo: motivo}` de toda
  aldeia na lista de conquista: bárbara via `active_conquests()` (agendada,
  em voo, nobre extra pendente, **e** nobre no ar mesmo com status errado) e
  PvP com status em `PvpConquestManager.FARM_SUSPEND_STATUSES`.
- `AttackManager.run()` relê a lista no início de cada farm, e
  `get_targets()` exclui o alvo **antes de todo outro filtro** — inclusive de
  `additional_farms`, porque um alvo PvP pode estar na lista manual e a
  conquista vence. Código novo `alvo_de_conquista` no `/village` e uma linha
  INFO `Farm: X fora do farm -- alvo de conquista (...)` por aldeia por ciclo.
- **Falha fechada:** se a lista não puder ser lida, o farm daquela aldeia não
  roda no ciclo (WARNING). Um JSON corrompido em `cache/conquest` já derruba o
  planejador hoje, então isso não abre um modo de falha novo.

### O que isto não cobre, e por quê

- **Ataque já no ar não volta.** O bloqueio começa quando o alvo entra na
  lista (`train_scheduled`), então farm novo não sai mais depois disso. Um
  farm enviado **antes** do agendamento só chegaria depois dos nobres se a
  viagem dele fosse maior que a espera até o trem mais a viagem do nobre —
  cavalaria leve (10 min/campo) contra nobre (35 min/campo), na prática não
  acontece. Não foi implementado cancelamento de comando.
- **Depois da conquista** o status fica `train_sent` até o próximo ciclo, e
  continua bloqueado; quando o `ConquestManager` confirma a posse, o mapa já
  mostra dono e o filtro de aldeia de jogador assume.

### Testes

`tests/test_farm_conquest_exclusion.py` (17 checagens): o que entra e o que não
entra na lista (inclusive `complete` com nobre no ar), o alvo fora de
`get_targets()` mesmo em `additional_farms`, a volta ao farm quando a
conquista termina, e `run()` sem farm quando a lista é ilegível. Inclui o caso
sem lista exigindo que o alvo **seja** farmado — é a assinatura do incidente.
As três leituras de disco são fixtures; nada toca `cache/`. Leitura real, só
de leitura, contra o `cache/` vivo: `{'51540': 'conquista barbara, status
train_sent'}`. Suíte inteira (65 arquivos) verde.

**⏳ Falta campo:** reiniciar o bot e, no próximo trem, ver a linha
`fora do farm -- alvo de conquista` para o alvo e nenhum `Attacking ... -> alvo`
no reporter entre o agendamento e o pouso.

---

## 8.25 Estudo extensivo da interface do jogo (2026-09-22/23, conta premium + gerente de conta)

**Pedido do usuário:** com o bot dormindo, vasculhar toda a interface — comum,
premium e gerente de conta —, ver dados e configurações **sem alterar nada**, e
usar a base de conhecimento oficial
(`support.innogames.com/kb/TribalWars/pt_BR`). Objetivo declarado: a otimização
do ciclo ("funcionalidade: módulos que rodam sempre, no início do ciclo, várias
vezes por dia"), com futuros botões "premium ativado" / "gerente ativado".

**Método.** Inventário de links da tela inicial (~110 destinos) e depois de
cada tela capturada (sub-modos, `ajaxaction`, `action`); lotes de captura
só-GET com o `WebWrapper` do bot (HTML em disco, fora do repo); bundles de JS
da CDN (`Scavenging`, `VillagePlace`, `Farming`, `game`) para achar endpoints
sem tocar a conta; a KB inteira (240 artigos) baixada e lida nos pontos
relevantes. **Nenhum POST, nenhum clique que mude estado.**

⚠️ **Incidente: o estudo provocou captcha (`data-bot-protect="forced"`) às
~00:00 de 23/09.** ~60 GETs pelo wrapper + ~15 navegações no Chrome em ~15 min
(~5 req/min; o bot faz ~3,7). O delay do wrapper, mesmo com 4–9 s extras,
**não bastou**: o limite é da conta e soma todos os clientes. O script ficou
preso em `_await_captcha_clear` sem saída visível, porque só conferia
`data-bot-protect` depois do retorno. O usuário resolveu o captcha. Regra
registrada na memória: varredura ≤ ~2 req/min somando todos os clientes.

### O que o bot já usa e o que nunca tocou

Já usados: `place` (+`units`, `scavenge`), `scavenge_api`, `overview`,
`overview_villages` (+`commands`), `market` (`send`, `other_offer`,
`own_offer`, `all_own_offer`, `exchange`), `flags`, `statue`, `snob`,
`inventory`, `report/all`, `main`, `smith`, `new_quests`, `info_village`,
`info_player` (+`stats_own`), `info_ally`, `ally/reservations`.

Nunca tocados, com o que entregam — em ordem de impacto no ciclo:

> ⚠️ **Leia com a restrição da §9 (2026-09-23):** o bot é para conta **sem**
> recurso pago. A coluna "Exige" separa o que vale numa conta gratuita (só
> a cunhagem automática e, com confiança média, o filtro de relatório) do que
> fica para a camada ativável por detecção.

| Tela | Exige | Entrega | Hoje o bot faz |
|---|---|---|---|
| `am_farm` (assistente de saque) | assistente | envio A/B **sem confirmação**: `POST am_farm&mode=farm&ajaxaction=farm&json=1`; C = `ajaxaction=farm_from_report`, o **servidor** dimensiona pela última espionagem (`data-units-forecast`). Só bárbaras (KB) | ~4,5 req por ataque (praça → confirm → popup) |
| `place&mode=scavenge_mass` | premium? (a confirmar) | 32 aldeias num GET: recursos, `res_rate`, armazém, tropa em casa, estado das 4 opções. Envio `scavenge_api` `send_squads` com **todos** os pendentes num POST (`squad_requests[0..n]`, JS verificado) | 1 GET + 1 POST **por esquadrão** (116 req/ciclo) |
| `overview_villages&mode=units` | premium | por aldeia: próprias / na aldeia / fora / em trânsito / total | `place/units` 57×/ciclo |
| `overview_villages&mode=buildings`, `tech` | premium | níveis de edifício e pesquisa de todas (⚠️ **25/pg**, usar "todos") | `main` 34×, `smith` 27× |
| `train&mode=mass` | premium? (a confirmar) | recursos, fazenda, tropa, máximo recrutável de todas (⚠️ 25/pg) | quartel/estábulo/oficina 35× |
| `snob` → cunhagem automática | **grátis** (≥ 5 aldeias) | `POST snob&action=start_auto_minting_session`, 8 h por aldeia, roda offline, confere a cada minuto (KB 6014); `snob&mode=coin` cunha em massa | `snob&action=coin` por moeda |
| `am_village` / `am_troops` / `am_research` | gerente | construção / recrutamento / pesquisa **no servidor, 24 h** | `BuildingManager` / `TroopManager` (duplo comando, abaixo) |
| `am_warehouse` (Estoque) | gerente | balanceamento automático "várias vezes por dia" | `resource_sharing` (~84 req/ciclo) |
| `place&mode=call` (apoio em massa) | premium? (a confirmar) | tropas de todas ordenadas por distância ao destino, envio único | `DefenceManager` apoio por aldeia |
| `market&mode=call` (Pedido) | premium? (a confirmar) | puxa recurso de todas para uma | — |
| `report&mode=filter` | comum | o jogo **deixa de gerar** tipos de relatório | lê e abre tudo |
| `premium&mode=feature_log` | — | prazo de cada funcionalidade | — |

Outras telas mapeadas sem efeito direto no ciclo: `relic_system` (Tesouraria —
relíquias com bônus por **raio**, inclusive capacidade de saque e velocidade de
construção; cada bárbara conquistada entrega uma; até 2 por dia em batalha e
coleta; teto de 20% por atributo), `relic_trade`, `info_player&mode=daily_bonus`
(baús diários com itens), `reqdef` (pedido de apoio ao fórum), `am_market`
(entregas agendadas — nenhuma criada), `am_notify` (e-mail em ataque),
`place&mode=templates` (modelos Fake, Nobre, Farm1), `place&mode=neighbor`,
`place&mode=sim`, `market` `traders` / `transports` / `mass_create_offers`,
`settings/*`.

### Os achados que mudam o desenho

1. **Detecção de premium/gerente custa zero requisição.** Todo `game_data`
   (que o bot já parseia em toda tela) traz
   `"features": {"Premium": {"active": true}, "AccountManager": {...},
   "FarmAssistent": {...}}`, além de `player.incomings` (conta inteira),
   `new_report`, `villages`. Os botões "premium ativado"/"gerente ativado"
   podem ser **leitura**, não configuração. Prazo em
   `premium&mode=feature_log` (hoje os três vencem **08/out 01:16**).
2. **Duplo comando em construção e recrutamento.** O gerente de construção está
   ativo em 27 das 32 aldeias com modelos cujos níveis finais são **idênticos**
   aos do bot (`ADC - DEFENSIVA` = `purple_predator_into_def`,
   `ADC - OFENSIVA BOT` = `purple_predator_into_off`, `ADC - TORRE` =
   `watchtower_support`); o gerente de tropa idem (`ADC - OFENSIVA` =
   `off_no_archer`, `ADC - DEFENSIVA` = `def_no_archer`, `ADC - TORRE` =
   `watchtower_support`). O bot também constrói nelas (BBM 004 `garage 5 -> 6`
   às 19:40 com o modelo do gerente ativo). Gerente: até 50 ordens por aldeia e
   depois **pausa** (BBM 030 em 29/50); põe armazém/fazenda sozinho; pode
   demolir acima do alvo.
3. **Duplo comando no transporte.** `am_warehouse` ativo (escassez < 23%,
   excedente > 69%, viagem ≤ 24 h, reserva 0 comerciantes, sem grupos
   excluídos) **e** `resource_sharing` do bot.
4. **Relatório se corta na fonte.** Dos 1.000 relatórios em cache,
   **460 (46%) são `ReportTrade`** — transporte, quase todo entre as nossas
   aldeias — mais 37 `ReportAccept`, 7 `ReportAMemptyQueue`, 6
   `ReportAMStockpileDistribution`. O filtro do jogo ("Transportes entre as suas
   aldeias", "As tropas retornaram com recursos", "ordens do gerente
   concluídas"…) os elimina antes de existirem. **Não** filtrar "seus ataques
   sem perdas": é o relatório de farm. O jogo também já separa pastas
   `[Coletando]` e `[Assistente de saque]`. Configuração: decisão do usuário.
5. **A cunhagem automática já é usada à mão** (15 `ReportAutoMintingSessionEnd`
   no cache) enquanto o bot cunha moeda a moeda.
6. **Módulo que depende da vez da aldeia.** Às 23:49 o planejador dizia "já
   existe conquista bárbara em andamento (51540)", 2h26 depois da conquista:
   quem fecha é o `run_conquest()` da `reserved_by` (BBM 001), que só roda às
   6h. Planejador bloqueado a noite toda. Exemplo concreto do item 4 do
   usuário.
7. **Ciclo noturno medido:** 0 aldeias, 35 req, 89% `conquista_barbara`.

### Respostas aos itens do usuário (conversa de 22/09)

- **Item 1 (relatórios desnecessários):** achado 4 — corte na fonte pelo filtro
  do jogo; o que sobrar se tria pela lista (ícone de comando e pasta vêm no
  markup: `attack_small|medium|large`, `farm`, `snob`, `spy`, `support`).
- **Item 2 (premium/gerente):** achado 1 — detecção automática; a tabela acima
  diz o que cada cenário libera.
- **Item 5 ("Comércio" 1,1%, 7 dias: 312.260 / 83.210 / 11.610):** **não conta
  envio entre as nossas aldeias.** `cache/resource_sharing/history.json` (300
  envios, 18/09 18:38 → 22/09 23:02, janela **menor**) soma 738.230 madeira,
  **1.050.100 argila**, 584.400 ferro aceitos entre aldeias próprias — 12× a
  argila do "Comércio". É mercado com outros jogadores (a visão de transportes
  mostra trocas com Bling, Woodrow Mitchell4, Vinnie Barton25).

### Hipóteses NÃO testadas (exigem ação real, decisão do usuário)

- `send_squads` com N esquadrões de aldeias diferentes, cada um com seu
  `unit_counts`, num POST (o JS do jogo manda N pendentes, mas com o mesmo
  `candidate_squad`).
- Assistente de saque aceitar os mesmos alvos que o bot usa hoje e respeitar o
  piso de ataque falso (`fake_limit`).

### Evento de campo durante o estudo

23:50: ataque de *Black 029 (570|277)*, **michelon97**, contra a **BBM 032
(582|289)**, chegada 00:05:07. BBM 032 com **lealdade 27** (widget do gerente)
e 0 tropa em casa; bot dormindo até 00:23 e sem snapshot dela. Avisado ao
usuário na hora; nenhuma ação tomada. O painel mostrava "0 sob ataque"
(`frontend.md` §2.8).

Captura lenta depois que o usuário resolveu o captcha (3 GETs, ~45 s de
intervalo): a lista de defesas traz **"michelon97 (Black 029) visitou BBM
032"** — o título não fala em conquista (relatório não aberto). Na mesma lista,
**nosso apoio estacionado em aldeias de outros jogadores está sendo atacado**
(BBM 001 em "Aldeia-bonus", BBM 020 em "Odisseia_004" ×3); o bot não acompanha
apoio fora de casa. Nos relatórios de comércio, **39 de 50 (78%) são entre as
nossas aldeias**, o que reforça o achado 4.

---

## 9. Próximos passos

**Fila definida pelo usuário em 2026-09-17, à frente do que vem abaixo:**

0. ~~**`P-CONQ-RAIO`**~~ — ✅ **feito em 2026-09-19** (§8.6) e ✅ **validado em
   campo em 2026-09-22**: o primeiro trem multi-origem real saiu às 10:53 contra
   a Bárbara #51540 (582|289), com `sources: {41123: 3, 74690: 1}` em
   `cache/conquest/51540.json`. Confirmação independente pela tela do jogo
   (`cache/in_flight.json`, 19:15): quatro comandos com nobre para 582|289, um
   da BBM 011 e três da BBM 001, todos pousando às 21:23:50 com 100 ms de
   intervalo — o mesmo `scheduled_arrival` do nosso cache. **✅ Conquistou:**
   lealdade 69 → 38 → 3 → −35 nos quatro relatórios de nobre. Custo colateral
   de fogo amigo registrado na §8.24.
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
   **Gate LIGADO nas 31 aldeias em 2026-09-22 ~19:50, por decisão do usuário**
   (o `village_template` segue `false`, então aldeia conquistada depois não
   herda). A BBM 004 já estava ligada antes e rodou às 19:46 sem linha
   `Unlock:` — esperado se não podia pagar ou nada estava pendente, porque a
   decisão de não gastar é silenciosa. O `config.json` é relido no começo de
   cada ciclo (`twb.py`, `config = self.config()` no laço), então vale a partir
   do ciclo seguinte sem precisar de restart. **⏳ Falta campo:** a primeira
   linha `Unlock: iniciada coleta`.

**Acrescentado em 2026-09-20, depois do estudo dos forks:**

3. ~~**`P-CONQ-RESERVA` Fase 1**~~ — ✅ **feita em 2026-09-20** (§8.7): captura,
   parser com fixture, exclusão dura nos cinco caminhos e
   `conquest.excluded_targets`. **⏳ Leitura validada em campo em 2026-09-20
   (480/482 reservas, 1 própria separada corretamente), gate ainda não
   exercitado** — o planejador não foi alcançado em nenhum dos dois ciclos. Ver
   o Aceite da §8.7. **Fase 2 (o bot criar reserva) segue aberta**, com
   gate `conquest.reserve_targets` default off e canário de uma reserva.
   **✅ Fase 2 implementada em 2026-09-21** (§8.7), e o **gate foi LIGADO no
   `config.json` no mesmo dia** — `reserve_targets: true`, `reserve_max_slots: 1`.
   Ligar já é o canário: com teto de 1, o bot não consegue criar uma segunda
   reserva nem se quisesse. **⏳ Ainda não exercitado:** o único alvo bárbaro na
   fila (582|289) **já está reservado à mão pelo usuário**, e nesse caso
   `claim_target()` devolve `None` sem postar nada. O primeiro exercício real
   será o próximo alvo sem reserva prévia. Sinal no log:
   `Reservations: alvo X (x|y) reservado no quadro da alianca`.
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
   do cache local deixaram de ser elegíveis. ✅ **Primeiro trem montado com esse
   pool em 2026-09-22 às 10:53** (o da 51540, item 0). Vale dizer o limite da
   prova: o alvo eleito é o mesmo que já era eleito antes da terceira camada
   (582|289), então o trem prova que o pool novo não quebrou nada, não que ele
   achou um alvo que o antigo não acharia.
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
   `tests/smoke_instance_lock_twb.py`. ✅ **Validado em campo em 2026-09-22
   19:46:** com o bot reiniciado às 19:14, um `acquire()` de outro processo
   na mesma chave foi recusado citando o pid 11880 (o bot vivo). Detalhe em
   §8.10.

8. ~~**Item 9 da fila tática da §7.10**~~ — ✅ **feito em 2026-09-20** (§8.11):
   a política de bandeira **não** contava a oferta, e a medição mostrou que o
   que segurava o Bug 1 era a guarda de rebaixamento, não o inventário. Gate de
   frescor em `flag_logic()`, `manage_flags(force=True)` para defesa e para a
   releitura pós-upgrade (bug latente achado no caminho), `flag_supply` com a
   quantidade que o código descartava, e aviso único de oferta zerada.
   **⏳ Falta campo:** as linhas de oferta zerada e a contagem de trocas.
   ✅ **Metade vista em 2026-09-22:** a linha de oferta zerada apareceu nas
   quatro primeiras aldeias (tipos 7 e 1 com 0 disponíveis), e nenhuma troca
   aconteceu nelas — a guarda de rebaixamento segurou. A contagem de trocas do
   ciclo inteiro fica aberta, e o esperado agora é **zero**, não três (§6.3).
   Às 22:22, **22 de 31 aldeias lidas, zero `Setting flag`**, 22 linhas de
   oferta zerada. Faltam 9 para fechar o ciclo.
   Às 22:57, **27 de 31, zero `Setting flag`**. As 4 restantes (BBM 028–031)
   foram cortadas pela janela das 23h e rodam no ciclo de 2026-09-23; esperado
   continua zero (§6.3 — uma previsão de 3 trocas feita às 22:50 foi retirada,
   estava baseada em cache velho).

**Acrescentado em 2026-09-21 (§8.12), decidido pelo usuário:**

9. ~~**`P-TMPL-SCOUT`**~~ — ✅ **feito em 2026-09-22** (§8.12). Gate do estágio
   de 440 espiões de `smith:15` → `stable:3`. A suspeita sobre a 52755 foi
   **confirmada contra o consumidor**: `get_template_action()` devolve o
   estágio anterior no primeiro nível não atingido e não pula estágio, então
   com ferreiro 9 a aldeia parava no estágio 0 (`build: {}`) e pedia zero
   unidade, sem nada no log. Regressão em `tests/test_watchtower_spy_gate.py`.
   **⏳ Falta campo:** `spy` sair de 0 no `cache/managed/52755.json`.
10. ~~**`P-PVP-SCOUT`**~~ — ✅ **feito em 2026-09-22** (§8.12). Origem = maior
   número de espiões (empate pela menor distância), quantidade = o máximo em
   casa menos a reserva, `scout_amount` virou **piso**. Três coisas apareceram
   ao implementar: a contagem precisa ser relida ao vivo antes de enviar (senão
   o jogo recusa o ataque inteiro e a mudança troca espia lenta por nenhuma
   espia), a elegibilidade antiga por `map_pos` era mais estrita que o próprio
   envio, e a reserva de conquista tinha de ser descontada. O efeito no alvo
   44155 é +0,3 campo, dentro do ruído da folga de 19,7 h. Regressão em
   `tests/test_pvp_scout_origin.py`. **⏳ Falta campo:** a linha
   `scout sent from ... (N spies, X.X campos)` com `N` bem acima de 5.

**Acrescentado em 2026-09-22:**

11. ~~**`P-FARM-MOTIVO`**~~ — ✅ **feito em 2026-09-22** (§8.16). O motivo de
   exclusão de cada alvo de farm passou a ser escrito em
   `cache/farm_exclusions/` e publicado em `/village`. Três defeitos apareceram
   no caminho e nenhum estava no plano: `attack()` devolvendo `False` para três
   coisas diferentes, ausência de registro significando "cortado pelo teto" e
   "nem alcançado" ao mesmo tempo, e `scout()` falhando por falta de espião sem
   que nenhum dos três chamadores olhasse o retorno. ⏳ **Observado em campo em
   2026-09-22, aceite não fechado:** o arquivo nasceu para as quatro primeiras
   aldeias, e a comparação com o log achou um caminho sem registro — aldeia
   com template sem pacote de farm (`watchtower_support`, BBM 002) deixa os 19
   alvos selecionados sem linha nenhuma. Mais uma diferença de 1 alvo sem
   explicação nas outras três. Tabela e correção proposta na §8.16.
   ✅ **Os dois corrigidos no mesmo dia** (`sem_pacote_de_farm`; a diferença
   de 1 era a própria aldeia contada no log). **⏳ Falta campo:** reiniciar e
   conferir a soma exata.
12. ~~**`P-STATS-PAINEL`**~~ — ✅ **feito em 2026-09-22** (§8.17, Feature 37).
   A série `Saqueado`/`Coletado` que o jogo já publica por dia
   (`screen=info_player&mode=stats_own`, medida em §8.13) virou
   `Extractor.stats_own_series()` + `PlayerStatsReader` (bot, TTL de 6h,
   conta inteira) + card em `/empire`. ✅ **Leitura validada em campo em
   2026-09-22 19:15:** `PlayerStats: 7 dia(s) de Coletado/Saqueado lidos`.

13. ~~**`P-VOO-PAINEL`**~~ — ✅ **feito em 2026-09-22** (§8.18, Feature 38). O
   item 1 da §6.1.2 do `frontend.md` ("o mais valioso, e o único que não é
   cosmético"). `Extractor.own_commands()` + `game/in_flight.py` + card em
   `/empire`, com a hora de chegada vinda do **servidor**. Três achados de
   captura: a tela é paginada e o contador do cabeçalho conta a página (25 de
   65), as colunas de tropa variam por mundo, e o jogo marca nobre um segundo
   vez por ícone. ✅ **Leitura validada em campo em 2026-09-22 19:15:**
   `InFlight: 49 comando(s) no ar (4 com nobre)`, com os 4 nobres batendo com o
   trem da 51540 no `cache/conquest`.

14. ~~**Item 5 da fila tática da §7.10**~~ — ✅ **feito em 2026-09-22** (§8.19).
   Dos quatro bugs do fork, três já estavam fechados aqui; o B9 tinha a
   metade **parcial** aberta — visão geral filtrada por grupo apagaria do
   config as aldeias fora do grupo. A limpeza agora só remove o que o
   `map/village.txt` confirma com outro dono. **⏳ Falta campo:** nenhuma perda
   real de aldeia desde a mudança; o sinal é `Removed lost village` só depois
   de o arquivo do mundo virar de dono.

15. ~~**`P-PVP-RESERVA` (§6.4)**~~ — ✅ **feito em 2026-09-22** (§8.20). Alvo
   PvP passa a descontar o que outros alvos e o trem bárbaro reservaram, a
   reserva sobrevive a reinício (reconstruída do Hunter), e o piso da escolta
   parou de pedir mais que a aldeia tem. De brinde, dois itens da §7.10 foram
   respondidos sem código: o 13 não se aplica e o 14 (limite de saque) não
   existe no br143. **⏳ Falta campo:** dois alvos PvP ao mesmo tempo.

16. ~~**`P-CICLO-MEDIDA`**~~ — ✅ **feito em 2026-09-22** (§8.21). Primeira
   metade do item 3 da fila abaixo (baseline): tempo e requisições por
   `(aldeia, fase)` em cada ciclo, em `cache/cycles/`. **⏳ Falta campo:**
   reiniciar o bot e juntar alguns dias antes de decidir o que cortar.
   (Bot reiniciado às 19:14 de 2026-09-22 — o relógio dos "alguns dias"
   começou.)

17. ~~**`P-CICLO-PAINEL`**~~ — ✅ **feito em 2026-09-22** (§8.22). `/cycles`
   lê `cache/cycles/` por fase e por aldeia, com abortado fora das medianas e
   média por presença. É onde a decisão do item 16 vai ser tomada.

18. ~~**`P-PONTOS-ZERO`**~~ — ✅ **feito em 2026-09-22** (§8.23). A recusa da
   BBM 004 levou a `points: 0` em todas as 31 aldeias: a visão geral da conta
   abre no modo Combinado e o parser só lia o de Produção. Pontos agora saem
   do `game_data`. Religa o piso de ataque falso, a moral do PvP e a pontuação
   do resource sharing. **⏳ Falta campo:** reiniciar e ver `crescido para`
   no log. Segunda recusa com a mesma assinatura na sessão velha, às 20:46:
   BBM 011, mínimo 98, enviados 80.

19. ~~**`P-FARM-CONQUISTA`**~~ — ✅ **feito em 2026-09-22** (§8.24). A primeira
   conquista multi-origem (51540, 21:23:50) foi seguida de fogo amigo: um farm
   mandado com o trem já no ar chegou 25 min depois e bateu na guarnição. O
   farm agora nunca ataca aldeia da lista de conquista, bárbara ou PvP, desde
   o agendamento. **⏳ Falta campo:** o próximo trem, com o bot reiniciado.

**Acrescentado em 2026-09-23 (§8.25, frontend §2.8) — nada implementado.**

⚠️ **Restrição de projeto, dita pelo usuário em 2026-09-23:** o bot é feito
para uma conta **sem** premium, **sem** gerente de conta e **sem** assistente
de saque (os três pagos). Ordem obrigatória: **(1) otimizar o tempo com o que é
grátis; (2) depois, um sistema ativável quando o recurso pago for detectado.**
A conta de hoje tem os três ativos (vencem 08/out), e isso não é o alvo. A
§8.25 foi ranqueada por impacto sem essa separação; a lista abaixo a corrige.

**Camada 1 — grátis (vale numa conta sem nada pago):**

20. **Cortar requisição que o próprio bot repete.** Não depende do jogo:
    visão geral lida ~3× por aldeia (88 no ciclo de 22/09), lista de
    relatórios (que é da conta inteira) baixada uma vez **por aldeia** (30),
    ofertas do mercado consultadas em toda aldeia todo ciclo (~62). Medir por
    fase no `/cycles` antes de cortar.

    **20a. `P-OVERVIEW-SOMBRA` — primeiro passo, decidido com o usuário em
    2026-09-23.** A "visão geral lida ~3×" é `game.php?village=N&screen=overview`
    (a tela principal da aldeia, grátis), lida em três pontos por aldeia:
    `Village.village_init()` (`village.py:141`, início),
    `TroopManager.update_totals()` (`troopmanager.py:130`, antes de recrutar) e
    `Village.go_manage_market()` (`village.py:1187`, depois do mercado). As
    aldeias de origem de conquista somam mais duas leituras pelo
    `prime_for_conquest()` (`village.py:979`), por isso BBM 001/010/011 tiveram 5.
    Log de 22/09: BBM 002 leu às 19:26:11, 19:27:42 e 19:31:31.

    *Por que não basta apagar:* navegar direto para o próximo endereço é
    inofensivo, porque o jogo não exige passar pela visão geral. Mas cada
    releitura atualiza o `game_data` (recursos, fazenda, pontos) **depois de
    ações que gastaram recurso** (construir, recrutar, coletar). Sem ela,
    recrutamento e mercado decidem com recurso já gasto (6º padrão): recusa do
    jogo, que custa a requisição igual, ou o pior caso, mercado ou
    compartilhamento enviando uma sobra que não existe mais.

    *Por que dá para cortar:* **toda tela HTML** do jogo traz o mesmo
    `TribalWars.updateGameData(...)` (conferido nas capturas de `main`, `place`,
    `market`, `snob`, `report`, `train`, `am_farm`, `scavenge_mass`), e
    `Extractor.game_state()` (`extractors.py:264`) funciona em qualquer uma.
    O dado fresco provavelmente já está na última resposta recebida.
    **Não verificado:** as ações por AJAX/JSON (construir via
    `get_api_action`, `send_squads`) trazem o recurso já descontado? Pelo 7º
    padrão o envelope muda com o cabeçalho `TribalWars-Ajax`. Se não trouxerem,
    a releitura depois delas continua necessária.

    *Plano (modo sombra, sem cortar nada):*
    1. Guardar o `game_data` da última resposta HTML/JSON que o wrapper recebeu
       para a aldeia (ou os recursos extraídos dela), com o horário.
    2. Nas releituras 2 e 3, **continuar fazendo o GET**, mas antes comparar o
       que o bot já tinha com o que a releitura trouxe, e logar uma linha por
       comparação: aldeia, ponto (`update_totals` / `market`), recursos
       anteriores × lidos, diferença, idade do dado anterior e de qual tela ele
       veio.
    3. Um ou dois ciclos diurnos completos depois, ler as linhas. Onde a
       diferença for sempre zero (ou só a produção do intervalo, que é
       previsível por `res_rate`), a releitura sai. Onde não for, ela fica, ou
       é trocada pela leitura da resposta certa.

    *Aceite:* nenhuma decisão de corte sem ao menos um ciclo diurno completo de
    linhas de sombra; ganho esperado ~50–60 requisições/ciclo (~15 min),
    confirmado pela fase `init` e pelas fases que contêm as releituras no
    `/cycles`. Teste pontual da comparação (lógica pura). O modo sombra não muda
    nenhuma decisão do bot.

    *Campo:* a implementação não precisa do bot parado nem de horário. A
    validação precisa: aldeia só roda dentro de `active_hours` (6–23), e o
    ciclo noturno tem 0 aldeias, logo nenhuma linha de sombra. Reiniciar o bot
    para carregar o código; as linhas começam no primeiro ciclo depois das 6h.

    ✅ **Modo sombra implementado em 2026-09-23** (passos 1 e 2; o 3 é campo).
    - `core/game_data_shadow.py`. O `WebWrapper.post_process` guarda, em
      `game_data_seen[village_id]`, um recorte do `game_data` de **toda**
      resposta: HTML via `updateGameData` e JSON via o envelope
      `{"response", "game_data"}` do `TribalWars-Ajax`. A aldeia sai do próprio
      `game_data.village.id`, não da URL. Usa `*_float`, `*_prod` e
      `time_generated` (relógio do servidor).
    - Os três GETs de visão geral (`init` em `village_init`, `update_totals`,
      `market`) capturam o recorte **antes** do GET e comparam depois. O
      esperado é anterior + `*_prod` × intervalo, com teto no armazém.
      Veredito: `igual`, `producao` (só a produção do intervalo) ou `diverge`
      (resíduo > 1,5 em algum recurso, ou `pop`/`pop_max`/`storage_max`/
      `trader_away` mudou). `init` entrou além do plano porque custa zero e
      mostra se a leitura do `run()` logo depois do `prime_for_conquest()` é
      redundante; filtrar por `age_sec` na análise.
    - Saída: linha `OverviewShadow - INFO - Sombra <ponto> aldeia <id>: <veredito> | anterior de <tela>[ (ajax)] ha Ns | ...`
      e a mesma coisa em `cache/shadow/overview.jsonl` (sobrevive ao restart,
      que trunca o `session_latest.log`). ~90 linhas por ciclo diurno.
    - A pergunta "não verificada" acima (a ação AJAX traz o recurso já
      descontado?) passa a ser respondida pelo próprio dado: linhas com
      `source_ajax: true` e `verdict` `igual`/`producao` dizem que sim.
    - Nada decide com isso. Leitura ruim ou wrapper de mentira vira no-op.
      Teste: `tests/test_overview_shadow.py` (fixture verbatim de
      `cache/debug/ally_index.html`; provado quebrando o ramo JSON).
    **⏳ Falta campo:** reiniciar o bot e juntar um ciclo diurno completo de
    linhas antes de decidir qualquer corte.
21. **Filtro de relatório na fonte** (achado 4): 46% do cache é transporte. A
    KB descreve o filtro sem restrição premium (no mesmo artigo em que cita as
    restrições de publicar e arquivar) → grátis com confiança média, **a
    confirmar numa conta gratuita**. Configuração do jogo, feita pelo usuário.
22. **Cunhagem automática** no lugar da cunhagem moeda a moeda — **grátis pela
    KB 6014** ("não está bloqueado para uma subscrição Premium"), exige ≥ 5
    aldeias (condição de jogo, detectável).
23. **Módulos de conta fora do laço de aldeias**: fechar conquista que pousou
    sem esperar a vez da `reserved_by` (achado 6), e ler
    `game_data.player.incomings` (grátis, toda tela) para defesa e painel.
24. **Hipótese a testar, possivelmente grátis:** o endpoint `scavenge_api`
    `send_squads` que o bot **já usa** aceitar N esquadrões num POST. A tela
    de coleta em massa talvez seja premium (KB não diz), mas o endpoint não
    necessariamente. Um envio real resolve; exige autorização.
25. **Painel**: os cinco itens de gravidade alta da `frontend.md` §2.8 — todos
    independem de recurso pago.

**Camada 2 — ativável por detecção** (`game_data.features.*.active`, custo
zero; prazo em `premium&mode=feature_log`):

26. **Premium:** visões gerais de conta (tropas, edifícios, pesquisa,
    produção), recrutamento em massa, apoio em massa, "Pedido" no mercado.
27. **Gerente de conta:** decidir quem manda por aldeia (achados 2 e 3 —
    construção, recrutamento e transporte hoje sob duplo comando); quando
    ativo, o bot pode ceder essas fases e economizar as requisições.
28. **Assistente de saque:** envio de farm em 1 requisição e dimensionamento
    pelo servidor (botão C). Canário com autorização.

Depois disso, a fila anterior:

1. **Fechar as validações de campo da §6.2**, que não custam código: são
   observações no log de sessão do bot já rodando. A das bandeiras (§6.3) é a
   mais barata e a mais próxima de terminar.
2. **`FND-01` como ADR de schema**, usando o inventário da §8 como entrada.
3. **Capturar baseline de 7–14 dias** antes de qualquer refatoração (a parte de
   duração de ciclo já grava sozinha desde a §8.21): decisões,
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
