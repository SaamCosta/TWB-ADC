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
| `game/zone_manager.py` | zonas geográficas centradas nas torres de vigia (Feature 11, §8.45) |
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
| 25b | Inventário — fase 2 (ativar boosts) | ⬜ pendente | o POST de `consume` já existe e rodou em campo na cunhagem (§8.55, 05/10); falta a política (§8.57) |
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

**Custo.** Raio ≈ `1,1 × 1,1475^(nível−1)` (a tabela exata, arredondada a 0,1, está em
`screen=watchtower` e foi copiada para `game/zone_manager.py` em 2026-10-03; a
fórmula erra na borda — 9,94 contra 10 no nível 17, §8.45); custo cresce ~17% por nível. O custo
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
| Feature 12 (evacuação regional) | **já disparou**: 17 `TWB_ZONE_EVACUATE` em 30/08 (`twb_1788131605.log`, "1/17 vizinho(s) de zona sob ataque"). Falta conferir o efeito (a tropa frágil saiu mesmo?). Desde §8.45 a zona é a da torre mais próxima |
| Feature 18 (moral/night no simulador) | isoladamente, nunca foi |
| Feature 27 (reserva cruzada na conquista bárbara) | próxima conquista bárbara com PvP ativo |
| Trem PvP falhado → `status: "failed"` | só no próximo train que realmente falhar |
| `support_others` | a chave já está `true` em 22 de 30 aldeias; o bloqueio é que ninguém **pede** apoio sem ataque real chegando. Exercitar com ataque mínimo de aldeia própria **distante** contra uma com `request_support_on_attack` (ver `CLAUDE.md`) |
| ~~Venda na bolsa premium~~ | ⛔ **cancelada em 2026-09-21** — Feature 34 morta, §4.5 |
| Marcas da torre de vigia na tela de chegadas | a BBM 002 já tem torre nível 8; falta capturar o markup |

### 6.3 Bandeiras — validação 1 de 18

O Bug 1 (troca constante de bandeira a cada ciclo) e o Bug 2 (loop de upgrade)
estão **corrigidos no código e não validados**. ⚠️ O Bug 2 **não estava
corrigido**: o laço voltou em campo em 05/10 e a correção real é a §8.54. Com a política nova o caminho de
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

**Releitura em 2026-10-06 (`97ded44`, 55 commits a mais):** §8.56. Traz as
medições de precisão de horário que o `ServerClock` acima vai precisar e a
estratégia `P-SNIPE-TREM` para cortar trem de nobres inimigo.

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
"restaurar a tela do jogador" da §7.10). *(2026-09-29, §8.37: medido para
`mode`, não para `group`. A aba passada na querystring **fica** gravada: o
`mode=commands` do `InFlightTracker` fez a leitura seguinte, sem `mode`, vir na
aba Comandos.)* (b) a sessão do `cache/session.json`
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

## 8.26 ✅ `P-APOIO-RECRUTA` — apoio enviado sumia do total e o bot recrutava para repor (2026-09-23)

Relato do usuário: o bot recrutava para cobrir uma lacuna de fazenda que não
existia. `TroopManager.update_totals()` somava `place&mode=units` com
`Extractor.units_in_total`, cujo `re.sub(r'<span class="village_anchor.+?</tr>')`
apaga toda linha com âncora de aldeia. A intenção era esconder o apoio
**recebido** em `units_home`, mas as linhas de `units_away` (tropa **desta**
aldeia apoiando outra) também abrem com `village_anchor` e sumiam junto.
Medido na BBM 006 (captura verbatim, `cache/_probe_place_units.py`): 1000
lanceiros, 1000 espadachins e 300 pesadas na SFC 002 fora do total — com
template defensivo, o bot recrutaria exatamente isso de novo. A coleta já era
contada (tabela sem âncora).

Correção: `Extractor.units_owned_total` separa a tabela `units_away` e soma
todas as linhas dela; o resto segue pelo parser antigo. `units_in_total` ficou
intocado porque `reports.py` o usa sobre recortes de relatório. Consumidores de
`total_troops` que mudam de valor: recrutamento (o alvo), `Snobber.troops_are_short`
(cujo docstring já **afirmava** que o total incluía apoio — não incluía até
aqui), `PvpConquestManager` (população própria) e o `cache/managed` lido pelo
painel. Teste: `tests/test_units_owned_total.py`.

Não verificado: tropa de apoio **ainda em trânsito** (antes de chegar) e tropa
em ataque de farm não aparecem em nenhuma das duas tabelas desta captura; se o
jogo não as lista nesta tela, continuam fora do total.

## 8.27 ✅ `P-FILA-ESPERA` — alvo manual reservado por outro espera em vez de sair da fila (2026-09-23)

Pedido do usuário: a **74694** (583|308, 10.285 pts, "Abandonada") estava
reservada por Asshai [RANDOW] com vencimento em 23/09 às 17:31, e deveria entrar
na fila de conquista **se** a reserva vencer e ninguém nobrar.

O que existia não servia. `_get_manual_target()` via reserva de terceiro e
gravava `status: "blocked"`. O comentário dizia que a causa era "reversível",
mas **nenhum caminho do código tirava um alvo de `blocked`**. Na prática,
enfileirar um alvo reservado era o mesmo que descartá-lo, e ele não voltava
nem depois que a reserva vencia. Além disso, o alvo não passaria pela seleção
automática: 10.285 pontos passa do `max_points: 1100`, e y=308 fica fora da
`area_of_interest` (270–299).

Mudança (`game/attack.py::_get_manual_target`):
- Reserva de **companheiro de tribo** mantém o alvo em `manual`, anota
  `waiting_reservation` (quem reservou, tribo e vencimento) e o **pula**. O
  arquivo só é regravado quando a reserva muda, não a cada ciclo. Pular não
  congela a seleção automática: o que congelava era um alvo manual
  *devolvido* que nunca sai, e este não é devolvido.
- A reserva saiu do quadro: a anotação é apagada, com a linha `reserva de X
  sobre o alvo manual N saiu do quadro -- alvo liberado`, e o alvo segue o
  caminho normal.
- O dono passa a ser conferido em **duas fontes**, e basta uma dizer que a
  aldeia tem dono: `cache/villages` e `map/village.txt` (`_world_owner`). Para
  posse, o `village.txt` é a fonte mais nova (27º padrão), e quem reservou é
  justamente quem pode ter nobrado sem o cache local ficar sabendo. Se o
  `village.txt` não puder ser lido, a checagem volta a ser só a antiga.
- `conquest.excluded_targets` continua gerando `blocked`, porque ali quem
  disse "nunca" foi o próprio usuário.
- Painel (`ConquestReader._status_label`): "Na fila — aguardando reserva de X
  (vence …)" e "Bloqueado (motivo)". Antes, `blocked` aparecia com o nome cru
  do status.

Testes em `tests/test_conquest_reservation_gate.py`. O teste antigo, que
exigia `blocked`, foi trocado por sete novos: espera, próximo da fila entregue,
sem regravação, liberação, nobrada pelo dono → `invalid`, `village.txt`
ilegível não bloqueia, e a exclusão por config continua bloqueando. A guarda
foi provada desligando o ramo novo: dois testes falharam.

A 74694 foi enfileirada às 11:44:49 de 23/09 por `ConquestReader.add_manual_target`.

⚠️ **O bot que está rodando subiu às 09:01 com o código antigo.** Enquanto a
50833 estiver ativa, o planejador nem chega à fila (um trem por vez). Mas o
primeiro ciclo depois do pouso (18:15) vai consultar a fila. Se até lá o bot
não tiver sido reiniciado e a reserva tiver sido renovada, o código antigo
grava `blocked`. Nada é enviado nesse caso, mas o registro precisa ser voltado
para `manual` à mão.

**O que isto NÃO resolve.** Fila não é reserva. Assim que a reserva de Asshai
vencer, qualquer outro membro da tribo pode reservar a aldeia antes do nosso
trem, e aí ela volta a esperar. O bot só reserva quando agenda um trem
(`reserve_targets`), e agendar exige 4 nobres livres e nenhuma outra conquista
ativa. Os 4 nobres atuais estão voando para a 50833. Segurar a vaga no quadro
enquanto os nobres se juntam é outra feature, e ela esbarra em
`reserve_max_slots: 1` e em `_release_finished_target_claims()`: esse método
soltaria na hora uma reserva de alvo que ainda não está em
`active_conquests()`. → Resolvido no mesmo dia, na §8.28.

## 8.28 ✅ `P-RESERVA-TIMER` — reservar no minuto em que a reserva do aliado vence (2026-09-23)

Decisão do usuário, a partir da 74694: *"aldeias em disputa devem ser
reservadas assim que a reserva do aliado vencer"*. Três partes:

1. **O timer** (`game/reservation_sniper.py`, gate
   `conquest.snipe_expiring_reservations`). Para cada alvo da fila manual
   reservado por outra pessoa, o timer lê a validade no quadro, marca a hora e,
   nesse minuto, tenta reservar para a conta. Os formatos de validade foram
   medidos nas 441 linhas de `cache/debug/reservations_all.html`: `hoje às
   HH:MM`, `amanhã às HH:MM` e `em DD.MM. às HH:MM`. O parser entende as 441,
   e a conta é feita a partir da hora em que o quadro foi **lido**, não da hora
   atual. O timer usa o mesmo gancho do Hunter (`hunter_service_callback`, que
   o farm chama antes de cada alvo), dorme até o horário quando faltam ≤ 90 s,
   e o `twb.py` encurta o sono entre ciclos para acordar a tempo. Tenta 2 s
   depois do minuto virar, repete a cada 60 s e desiste depois de 8 tentativas,
   por causa do captcha, que o jogo aplica pela taxa da conta. Casos cobertos:
   reserva renovada → rearma para o novo horário; aldeia com dono (cache ou
   `village.txt`) → desarma sem reservar; reserva já nossa → desarma. A reserva
   feita pelo timer grava `target_claim.source = "reservation_timer"` no
   `cache/conquest` e **não tira o alvo da fila**.
   O timer passa por fora do limite de 1 escrita por ciclo do
   `ReservationWriter` (`budget_exempt`), porque perder o minuto porque o
   planejador já escreveu no ciclo seria perder a aldeia. O limite próprio dele
   são as 8 tentativas.
2. **A rotina que devolve vagas passou a respeitar a fila.**
   `_release_finished_target_claims()` soltava toda reserva do bot cujo alvo
   não estivesse em `active_conquests()`, e soltaria a reserva do timer no
   ciclo seguinte. Agora a fila manual (`_manual_queue_ids`) também conta como
   "quero manter". Um alvo que sai da fila (conquistado, cancelado ou
   inválido) continua liberando a vaga.
3. **`reserve_max_slots: 3`** no `config.json`, por decisão do usuário: ele
   espera ter 3 trens de nobres disponíveis na maior parte do tempo. O
   `config.example.json` segue com 1.

Testes: `tests/test_reservation_sniper.py` (18 casos: parser, armar, disparar,
renovação, dono, teto de tentativas) e mais um em `tests/test_reservation_writer.py`
(a varredura não solta alvo da fila). Os testes que já existiam dessa varredura
passaram a trocar a fila por um dublê, porque sem isso liam o `cache/conquest`
de produção (21º padrão). A guarda foi provada por mutação: forçar
`budget_exempt=False` e desligar a renovação derrubam um teste cada.

**Premissa corrigida no caminho.** Vários docstrings de `reservations.py` e a
§8.7 dizem que a reserva "vale 3 dias". Na mesma captura, 141 reservas vencem
em 07/12 e 101 em 25/12, então a validade **não é fixa** por reserva. A folga
de "6,7×" do docstring do `ReservationWriter` continua valendo para as
reservas que o próprio bot cria. O que não se sustenta é a leitura de que toda
reserva alheia some em até 3 dias.

**Não resolvido, e pedido pelo usuário:** a invariante de **um trem bárbaro
por vez no império** (`BarbarianTrainPlanner.run`, `active_conquests()`). Com 3
trens disponíveis ela é o gargalo da expansão. Fica como item próprio na §9.

⏳ **Falta campo:** reiniciar o bot depois que o ciclo de 23/09 fechar (o
usuário precisa do ciclo completo para a medição) e antes das 17:31. O sinal no
log é `Reserva-timer: alvo 74694 (583|308) armado para 23/09 17:31`, e depois
`reservado Ns depois do vencimento` ou `renovou a reserva`.
✅ **Armado em campo às 14:14:33 de 23/09**, no terceiro reinício. O primeiro
(14:09) subiu desarmado porque o `config.json` tinha perdido as duas chaves:
ver §8.29. ⏳ Falta o disparo das 17:31.

## 8.29 ✅ `P-CONFIG-HERANCA` — herdar config de aldeia nova apagava edições do meio do ciclo (2026-09-23)

Achado ao conferir o timer da §8.28: depois do reinício das 14:09, o
`config.json` tinha `reserve_max_slots: 1` e nenhuma
`snipe_expiring_reservations`, embora as duas tivessem sido gravadas às 11:5x.
O mtime do arquivo era 13:58:47, o mesmo segundo do `Read game state` da BBM
032, que é a 51540 conquistada em 22/09 rodando pela primeira vez.

Causa: `Village.apply_nearest_village_inheritance()` gravava o `config`
**inteiro** a partir da cópia carregada no início do ciclo (09:01), e um ciclo
dura horas. Toda edição feita no arquivo nesse intervalo, pelo usuário, pelo
painel ou por outra sessão, era desfeita sem nenhum log. O caminho sem aldeia
doadora tinha um segundo defeito: relia o disco e gravava os três campos do
fallback, e logo depois `clear_flag()` gravava a cópia da memória por cima,
desfazendo o fallback que acabara de escrever.

Correção: `Village._persist_village_config()` relê o `config.json` e troca só
`villages[<esta aldeia>]`. Os três pontos de gravação da herança passam por ele.
Se o arquivo não puder ser lido, ele não grava nada, porque escrever a cópia
velha seria o próprio bug. Teste: `tests/test_village_config_persist.py`; com o
código antigo, os três casos falham.

Continua valendo, e está fora do escopo: `twb.py` só relê a config no
**início** de cada ciclo, então uma mudança no arquivo leva até um ciclo
(~5h) para valer. Mudança urgente continua exigindo reinício.

## 8.30 ✅ `P-EXTRACTOR-NONE` — um soluço de rede derrubava o bot inteiro (2026-09-23)

Às 14:1x de 23/09, no ciclo que começou às 14:14, `TroopManager.attempt_upgrade()`
recebeu `None` de `get_action` (a rede caiu, e o bot logou em seguida
`Internet seems to be down`), e `Extractor.smith_data(None)` levantou
`AttributeError: 'NoneType' object has no attribute 'text'`. O `main()` pegou
a exceção e reiniciou o laço às 14:29:53, e o timer da §8.28 rearmou. O ciclo
das 14:14, porém, foi abortado no meio.

É o 2º padrão do CLAUDE.md, e a varredura da classe (12º padrão) achou **24
parsers** do `Extractor` com o mesmo `res = res.text` sem guarda. Correção na
raiz: `_page_text()` devolve `""` para `None`, e cada parser devolve o próprio
valor de "não casou". Esse valor é o mesmo que ele já devolvia para uma
resposta 200 com outra tela (sessão expirada, bot protection), caso que os
chamadores já tratam. A distinção entre "sem rede" e "tela sem o dado" não
existe aqui. Quem precisa dela olha o `res` antes de chamar o parser.
`get_daily_reward`, que não tem nenhum chamador, também quebrava em qualquer
página sem o bônus (`.group` sobre `None`) e ganhou a guarda.

Teste: `tests/test_extractor_none_response.py`. Ele varre a classe inteira em
vez de listar nomes e tem uma guarda contra a varredura voltar vazia. Com o
código antigo, os dois testes principais falham.

Não coberto: os chamadores que fazem `res.text` direto, fora do `Extractor`.
Esta correção fecha só a porta dos parsers.

## 8.31 ✅ `P-FARM-PROPRIA` — o farm atacou a aldeia recém-conquistada (2026-09-23)

A 50833 pousou às 18:15:06 (os 4 nobres do trem da §8.28 / §9 item 19). Às
19:19:30 foi marcada `conquered` ("confirmed as ours via village cache") e com
isso **saiu** de `active_conquests()`, a lista de exclusão do farm da §8.24.
Às 19:31:32 a BBM 001 (41123) mandou `{'light': 35}` contra ela, com chegada
prevista por volta das 22:01. O scan de mapa da BBM 001 era de antes do pouso
e ainda mostrava a aldeia como bárbara, e o filtro `dono_jogador` lê o dono
desse mapa. É o 3º corolário do 6º padrão pelo outro lado: a exclusão nascia
com a intenção, mas **morria antes de o mapa ficar sabendo do efeito**.

Duas camadas:
- `AttackManager.get_targets()` pula qualquer aldeia de `config["villages"]`
  (`own_villages`, reatribuído pela `Village` antes de cada `run()`), com o
  motivo `aldeia_propria` no `cache/farm_exclusions`. A lista da conta não
  atrasa, e o dono no mapa atrasa.
- `ConquestCache.farm_blocked_targets()` também bloqueia conquista
  `conquered`/`assumed_done` com pouso nos últimos 3 dias
  (`RECENT_CONQUEST_SECONDS`), o que cobre a aldeia que ainda não entrou no
  config. A janela é limitada para não arrastar o histórico inteiro de
  `cache/conquest`.

Teste: casos novos em `tests/test_farm_conquest_exclusion.py` (25 checks). Com
o código antigo eles falham. `own_villages` tem padrão `frozenset()` na classe
(imutável) porque sete testes criam o manager sem `__init__`.

**Achado da mesma sessão sobre o timer (§8.28), fechado:** ✅ às 17:30:03 o
timer dormiu 58 s. A tentativa 1 (17:31:20) ainda viu a reserva de Asshai no
quadro, e a tentativa 2 reservou às **17:33:12, 62 s depois do vencimento**
(reserva 83085, `em 26.09. às 17:32`, 2 de 3 vagas). O minuto de validade do
quadro não é o minuto em que a reserva some. A margem de 8 tentativas foi
necessária.

## 8.32 Auditoria completa do bot (2026-09-26)

Segunda auditoria integral, 45 dias depois da primeira (§5). Nada foi corrigido
nesta sessão: é só o diagnóstico, com a ordem sugerida no fim.

### Escopo e método

- **Lidos linha a linha:** `twb.py`, `core/request.py`, `core/extractors.py`,
  `core/filemanager.py`, `pages/overview.py`, `game/village.py`,
  `game/attack.py`, `game/conquest_planner.py`, `game/hunter.py`,
  `game/pvp_conquest.py`, `game/defence_manager.py`, `game/troopmanager.py`,
  `game/buildingmanager.py`, `game/map.py`, `game/reports.py`, `manager.py`,
  `game/snobber.py`; e as partes que decidem algo em `core/world_config.py`,
  `game/resources.py` (mercado), `game/resource_sharing.py` (plano e envio),
  `game/reservations.py` (escrita) e `webmanager/server.py` (segurança).
- **Não lidos por inteiro:** `webmanager/utils.py`, `reservation_sniper`,
  `world_villages`, `in_flight`, `player_stats`, `pages/statue|inventory`,
  `core/templates|cycle_meter|game_data_shadow|instance_lock`,
  `game/simulator`, `zone_manager`, `new_world_setup` e a parte premium de
  `resources.py`. São os mais novos e quase todos têm teste; ficam para uma
  passada própria se for o caso.
- **Varredura por AST** (script descartável): nenhum atributo de classe mutável
  novo com mutação compartilhada; nenhum nome indefinido real (só os do
  `from core.exceptions import *`); funções sem chamador listadas no A26-21.
- **Suíte:** 70/70 verde. **Log da sessão de 26/09 (18:23→):** zero ERROR,
  zero traceback.
- **Evidência de campo:** `cache/logs/twb_*.log` (91 `TWB_EXCEPTION` desde
  23/08), os 28 registros de `cache/conquest/` e o `config.json`.

### P1 — derruba o bot ou arrisca nobre

**✅ A26-01 — Uma exceção em qualquer aldeia derruba o ciclo inteiro, e a terceira
mata o processo.** *(Corrigido em 2026-09-27, §8.33.)* Confirmado por código e por campo. `twb.py:1300` chama
`village.run()` sem `try`, e `main()` (`twb.py:1492`) tenta três vezes **na vida
do processo**: sem pausa entre as tentativas e sem zerar o contador depois de
um ciclo bom. O reporter registra 91 quedas desde 23/08, todas de `None`, com
quatro no mesmo dia em 23/08, 26/08 e 15/09. Três bastam para o processo
encerrar. A última foi em 25/09 às 15:48, na BBM 034. Cada queda também joga
fora o estado em memória: reservas de escolta, `wait_for`, frescor das
bandeiras. **Correção:** isolar cada aldeia em `try/except` com traceback no
log (a aldeia é pulada, o ciclo segue), pausar entre as tentativas e zerar o
contador ao fim de cada ciclo completo. É essa rede que tira a fatalidade dos
itens seguintes.

**✅ A26-02 — Cinco caminhos de `None` em `Village` sobreviveram à §8.30**
*(corrigido em 2026-09-27, §8.33; o `e` derrubou o bot naquele dia)*, que
fechou os parsers mas não os chamadores (a própria §8.30 avisa isso). Eles casam
a assinatura de 76 das 91 quedas. Parte das 45 `'text'` era o `smith_data`, que
a §8.30 já corrigiu.
- a) O GET da visão geral falha numa aldeia que já rodou antes. `game_data`
  continua com a foto do ciclo anterior, o `if not self.game_data` passa, e
  `setup_defence_manager(data=None)` faz `data.text` (`village.py:381`):
  `'NoneType' object has no attribute 'text'`. Antes de cair, `resman.update()`
  já decidiu com o recurso de horas atrás (6º padrão).
- b) O mesmo GET falha na primeira execução do objeto. `self.logger` ainda é o
  `None` da classe, e o `self.logger.error(...)` de `village.py:1260` é a própria
  queda: `'error'` (21 ocorrências, a última em 15/09).
- c) Resposta 200 que não é tela de jogo (login, captcha): `game_state()`
  devolve `None` e `self.game_data["village"]` quebra em `village.py:150`.
- d) `get_quest_rewards()` (`village.py:1388`): `get_api_data` devolve `None` com
  rede ruim e um `Response` quando o JSON não parseia, e os dois quebram em
  `result["response"]`. Roda em toda aldeia, todo ciclo (`quests_enabled: true`).
- e) `go_manage_market()` (`village.py:1202`) atribui `game_state(res)` sem
  guarda, e o `None` chega a `set_cache_vars()` (`village.py:1827`).

A queda de 25/09 (`not subscriptable`, cerca de 110 s depois do `TWB_START` da
BBM 034) é d ou e. Sem o traceback não dá para saber qual: o
`session_latest.log` daquela sessão já foi sobrescrito.

**✅ A26-03 — Risco de autoconquista.** *(As 3 correções feitas em 2026-09-27:
`_target_is_mine()` na §8.33, `repman` e piso do mundo na §8.35.)* O mecanismo está confirmado no código,
mas ainda não aconteceu em campo. A proteção pela lealdade real do relatório
está morta, e a estimativa que sobra diz 0.
- Nenhum dos dois construtores de `ConquestManager` passa `repman`
  (`village.py:887`, `conquest_planner.py:318`), então `_get_real_loyalty()`
  sempre devolve `None`. Nos 28 registros de `cache/conquest`,
  `loyalty_source` é `"estimate"` em todos, e `confirmed_by: "noble_report"` não
  aparece em nenhum. É o 3º padrão: a correção de `loyalty_from_report()`
  (13/08) funciona e nunca é chamada neste caminho.
- `_promote_scheduled_trains()` (`conquest_planner.py:910`) usa
  `conquest.loyalty_drop_per_noble` (25) no lugar do piso do mundo (20) e grava
  `loyalty_after_train: 0`. Os 7 trens do planejador têm 0; os 21 do caminho
  antigo têm 20. O comentário fala em "piso da faixa", mas o número usado não é
  o piso.
- Juntando os dois: depois do pouso, se `cache/villages/{alvo}` ainda disser
  bárbara, `_handle_existing()` cai na estimativa `0 + horas × 1`, que dá mais
  que zero, e **manda um nobre extra contra a aldeia que acabou de
  conquistar**. É o incidente de 12/08. Esse cache pode estar velho porque o
  mapa só é relido a cada 8 h (`map.py:26`) e, com `map_sector_radius: 0`, a
  âncora pode nem enxergar o alvo. Até hoje não aconteceu porque a âncora não
  tinha nobre sobrando na hora. Com três trens em paralelo (§9 item 19a),
  deixa de depender de sorte.
- **Correção**, três coisas baratas. Antes de tudo, `_target_is_mine()` checa
  `target_id in config["villages"]`: a visão geral da conta roda no início do
  ciclo e é a prova de posse mais fresca que o bot tem. Depois, passar `repman`
  nos dois construtores e usar `self._drop_min` do mundo no planejador.

**✅ A26-04 — Um trem agendado que o Hunter não chega a disparar trava a conquista
bárbara para sempre.** *(Corrigido em 2026-09-27, §8.35.)* Confirmado por código. Quando a chegada passa,
`Hunter.run()` marca o schedule como `failed` (`hunter.py:209` e `:247`), mas
deixa os ataques em `pending`. `_promote_scheduled_trains()` só age quando
nenhum ataque está `pending` (`conquest_planner.py:889`), então o registro fica
em `train_scheduled` indefinidamente. Consequências:
- `active_conquests()` nunca esvazia, e o planejador para ("um trem por vez");
- a reserva `barb_train:*` nunca é solta, e farm e coleta perdem essa tropa em
  silêncio;
- o alvo fica fora do farm.

O caminho real é o bot parado, ou morto pelo A26-01, durante a janela de cerca
de 9 h de um trem. Hoje a única saída é o botão de limpar do painel.
**Correção:** ao marcar o schedule como `failed`, marcar também os ataques
`pending` como `failed`, com `fail_reason: arrival_passed`.

### P2 — decisão errada ou perda silenciosa

**✅ A26-05 — O Hunter serve os schedules um de cada vez e pode perder o comando de
outro schedule.** *(Corrigido em 2026-09-27, §8.36.)* `hunter.py:240-340` ordena os schedules pelo primeiro envio,
mas processa cada um até o fim, dormindo até 120 s por comando. Exemplo:
schedule A com envios em T+10 e T+100, schedule B com envio em T+50. O Hunter
dorme até T+100 dentro de A, e o comando de B vira `send_time_missed`. A
conquista PvP grava clear e nobres em schedules separados, que é exatamente
esse caso. **Correção:** achatar os ataques pendentes numa lista única,
ordenada por `send_time`.

**✅ A26-06 — `market.trade_max_per_hour` faz o contrário do nome.** *(Corrigido em
2026-09-27, §8.36: o código passou a seguir o nome.)*
`resources.py:677` usa o valor como **horas entre trocas**, enquanto
`helpfile.py:90` diz "máximo de trocas por hora". O `config.json` tem 12, que na
prática é uma troca a cada 12 h por aldeia.

**✅ A26-07 — Ao aceitar oferta do mercado, o bot não confere a proporção.**
*(Corrigido em 2026-09-27, §8.36.)*
`check_other_offers()` (`resources.py:781`) aceita qualquer oferta que entregue
o recurso que falta e peça até todo o excedente. Uma oferta de 1.000 de ferro
por 20.000 de madeira passa. `auto_trade` está `true` em campo. **Correção:**
exigir `wanted_amount <= offer_amount × trade_multiplier_value`.

**✅ A26-08 — `DefenceManager.supported` nunca é zerado** *(corrigido em
2026-09-27, §8.36)* (`defence_manager.py:426`,
`:436`, `:453`). Depois de apoiar `support_others_max_villages` aldeias (2), a
doadora nunca mais apoia ninguém até o bot reiniciar, e também não volta a
apoiar a mesma aldeia num ataque futuro. Hoje está latente, porque nenhum apoio
real saiu até agora, mas é justamente o caminho que a §6.2 manda exercitar.

**A26-09 — Resposta de erro de ação AJAX é contada como sucesso.** Ainda não
verificado contra o servidor. `get_api_action` devolve o JSON inteiro e nenhum
chamador procura chave de erro (grep por `"error"` em `game/` e `core/`: zero).
Afeta:
- `popup_command`: farm e apoio contam como enviados;
- `research`;
- `start_unlock`: desconta o recurso localmente;
- `assign_flag`: `flag_logic()` grava `current_flag` sem olhar o retorno
  (`defence_manager.py:692`).

O `try=confirm` anterior filtra a maior parte dos casos, então o buraco fica
entre confirmar e enviar. **Antes de mexer:** capturar uma resposta de erro real
com os cabeçalhos do wrapper (7º padrão, skill `twb-sondar`). Há um cruzamento
de graça para medir o tamanho do problema: `cache/in_flight.json` (o que o jogo
diz que está no ar) contra as linhas `Attacking` do log.

**✅ A26-10 — `internet_online()` só trata `Timeout`** *(metade corrigida em
2026-09-27, §8.33: pega `RequestException`. Segue testando contra o github.com.)* (`twb.py:240`). Falha de DNS
ou conexão recusada levanta `ConnectionError` e vira queda (A26-01). Além disso,
o teste de internet depende do github.com a cada ciclo. **Correção:** pegar
`requests.RequestException` e testar contra o próprio endpoint do jogo.

**A26-11 — A moral do PvP é calculada com pontos de aldeia.** Latente, porque o
gate está desligado. `_step_simulate()` usa `clear_village.points` e os pontos
da aldeia-alvo (`pvp_conquest.py:915-919`), mas a moral do TW sai dos pontos
dos **jogadores**. Com `dynamic_moral_night_bonus: false`, como está em campo,
a simulação usa moral 100 e ignora o bônus noturno (no br143,
`night.active: 2`, defesa ×2). Os dois erros superestimam o ataque, que é o
lado perigoso. Confirmar a regra no servidor antes de corrigir (5º padrão:
dizer de qual campo o número vem).

**✅ A26-12 — `cache/hunter/schedules.json` não tem trava entre processos.**
*(Corrigido em 2026-09-27, §8.36.)* O
Hunter lê o arquivo, dorme até 120 s dentro da janela de envio e grava tudo de
volta. Se o painel editar o arquivo nesse intervalo (`/hunter/add`, `delete` ou
`toggle`), a edição é desfeita, ou um schedule apagado volta. É o mesmo desenho
da §8.29, em outro arquivo.

### P3 — eficiência, ruído e dívida

- **A26-13** — O recrutamento faz um lote de no máximo 25 de uma unidade por
  prédio, por visita (`troopmanager.py:181-217`). A fila mediana desses lotes é
  de 140 min (57 lotes medidos), contra um ciclo de 4 a 5 h, então o quartel
  fica ocioso na maior parte do tempo quando há recurso. É decisão de produto,
  não bug.
- ✅ **A26-14** *(§8.35)* — O planejador sonda a duração da viagem e grava o schedule com
  `send_time: None`; o Hunter sonda de novo (2 requisições por origem, por
  trem). Cada sonda extra é mais uma chance de falhar e cair no A26-04. Passar
  adiante a duração já medida.
- **A26-15** — O WARNING `queue out-of-sync` (recrutamento e construção) sai em
  toda aldeia com fila depois de cada reinício, porque `wait_for` e `waits` só
  existem em memória. O texto fala em "manual actions" para uma fila que é do
  próprio bot (15º padrão).
- **A26-16** — `run_quest_actions()` chama `self.run()` inteiro e, quando volta,
  o `run()` de fora continua: a aldeia roda duas vezes no mesmo ciclo
  (`village.py:509` e `:1288`).
- **A26-17** — Com a rede fora e o TTL vencido, `WorldConfig.get()` refaz o
  fetch (timeout de 30 s) em cada chamada, e são dezenas por ciclo. Guardar a
  tentativa que falhou.
- ✅ **A26-18** *(§8.33, de tabela; banner acrescentado em 2026-10-04)* —
  `Hunter.run()` devolve `priority_mode` a `False` num `finally`, e o código
  já citava este item. A lista continuava dando-o como aberto.
  O Hunter liga `priority_mode` e só desliga no fim do schedule,
  fora de `try/finally` (`hunter.py:291` e `:339`). Uma exceção no envio deixa
  o bot sem pausa entre requisições, que é o gatilho de captcha por taxa.
- **A26-19** — Tropa evacuada ou mandada de apoio nunca é chamada de volta:
  machado e nobre evacuados ficam na aldeia de destino até alguém agir à mão.
- **A26-20** — `Extractor._command_arrival()` converte a hora do servidor em
  epoch com o fuso da máquina (`.timestamp()` sobre datetime ingênuo), que é
  justamente o que o docstring diz evitar. No br143 não faz diferença.
- **A26-21** — Código morto confirmado pela varredura: `get_daily_reward`,
  `FileManager.read_lines`, `ReservationWriter.bot_claim_for`,
  `Simulator.update_with_real_levels/grab_cache/cache_customize`,
  `SnobManager.level_system`, `ZoneManager.get_zone_members/zone_under_attack`,
  e `distance_to`/`is_full`/`calculate_remaining_capacity`/`parse_coordinates`
  em `pages/overview.py`. Nenhum tem efeito; remover segue o formato do 4º
  padrão.

### O que foi conferido e está bem

`FileManager.save_json_file` é atômico. A trava de instância segura. O
`WebWrapper` espera o captcha sem `input()`. `ReservationWriter.release_claim`
só apaga reserva com carimbo do bot. O painel escuta só em localhost, recusa
POST de outra origem e passa nomes de template por `basename`. A ordem de
`safe_to_engage` foi remedida: continua 0 divergências em 40 alvos, então
segue como ressalva de documentação (§5), não como bug.

### Ordem sugerida

1. ~~**Lote A, estabilidade**~~ (não muda nenhuma decisão de jogo): A26-01,
   A26-02 e A26-10. ✅ **Feito em 2026-09-27** (§8.33), junto com dois achados
   novos da mesma queda (`A26-22`, `A26-23`).
2. ~~**Lote B, nobre**~~ (antes de ligar o §9 item 19a): A26-03, A26-04 e
   A26-14. ✅ **Feito em 2026-09-27** (§8.35).
3. ~~**Lote C:**~~ A26-05, A26-06, A26-07, A26-08 e A26-12. ✅ **Feito em
   2026-09-27** (§8.36).
4. A26-09 e A26-11 só depois de sondar o servidor.

## 8.33 ✅ `P-QUEDA-HUNTER` — a rede caiu e o 4º nobre não saiu (2026-09-27)

**O incidente.** Trem de 4 nobres contra a Bárbara #55647 (582|288), agendado
às 12:46:08 com pouso comum às 23:59:47 e origens `41123 ×2, 74689 ×1, 74690 ×1`.
Os três primeiros saíram pelo Hunter às 12:55:54 e 13:05:57. O da BBM 011
(74690), marcado para 14:38:41, foi recusado:
`Hunter: refusing late attack 74690 -> 55647; send_time passed 102.145s ago`.
O usuário mandou o quarto nobre na mão.

**Não foi o captcha.** O bot ficou em bot protection de 13:20:55 a 14:09:24 e
retomou sozinho, 29 minutos antes da saída. A sequência que perdeu o nobre
(`session_latest.log`):

| Hora | Evento |
|---|---|
| 14:26:58 | `ConnectionResetError` no mercado da BBM 006, e depois timeout de conexão |
| 14:27:23 | `go_manage_market()` grava `None` em `game_data`; `set_cache_vars()` quebra em `village.py:1827` — é o **A26-02 e** |
| 14:27:23 | Pelo **A26-01**, o processo cai. `main()` sobe outro `TWB`, que vê a rede fora e dorme `active_delay` + jitter **sem consultar o Hunter**: `Dead for 11.07 minutes (next run at: 14:38:37)` |
| 14:38:41 | Hora de saída. O bot acordou 4 s antes |
| 14:38:45 → 14:40:23 | O processo novo faz login, visão geral, reservas, estatísticas, comandos no ar e o prime das 3 origens. Só depois vem o primeiro `Hunter.run()` |

Sem a queda, o checkpoint cooperativo do Hunter dentro do laço teria disparado
a 74690 por volta de 14:36:41.

Efeito colateral que a tabela não mostra: o `return False` da espera por rede
em `TWB.run()` voltava para o `for _ in range(3)` de `main()` como se fosse mais
uma tentativa. A queda e a espera gastaram duas das três, e o processo seguiu o
resto do dia na última.

**Achados novos, fora da auditoria:**

- **`A26-22` — sono cego.** Dos quatro caminhos que dormem, só o sono entre
  ciclos (`twb.py`, bloco `# Feature 10`) encurtava pela
  `hunter.nearest_send_time()`. As duas esperas por rede e a espera de "Overview
  unavailable" dormiam o `active_delay` inteiro. E um processo recém-reiniciado
  nem tem `self.hunter`, então não teria como perguntar.
- **`A26-23` — Hunter tarde demais no início do ciclo.** O primeiro
  `Hunter.run()` do ciclo vinha depois das reservas, das estatísticas, dos
  comandos no ar e do prime da conquista, cerca de 100 s medidos. Num processo
  novo não dava para simplesmente adiantá-lo: a aldeia de origem ainda não
  tinha `attack`, e `_send_attack_batch()` marcaria o comando como falho.

**Correção.**

- *A26-01:* cada `village.run()` roda em `try/except` com traceback no log
  (`logging.exception`; `VillageInitException` sai como WARNING, sem traceback).
  A aldeia é pulada e o ciclo segue. Se a rede caiu, o ciclo termina ali
  (`aborted: network_lost` no medidor) em vez de pagar timeout nas outras 30
  aldeias. `main()` conta só quedas **seguidas**: um processo que fechou pelo
  menos um ciclo recomeça do 1. Há 30 s de pausa entre as tentativas
  (`CRASH_RESTART_PAUSE`), e uma volta normal de `t.start()` encerra o processo
  em vez de consumir tentativa.
- *A26-02:*
  - a/c: `village_init()` zera `game_data` quando o GET falha ou a tela não é de
    jogo, em vez de manter a foto do ciclo anterior;
  - b: o log de erro de `run()` usa um logger de reserva;
  - d: `get_quest_rewards()` aceita só `dict` com `dialog` string;
  - e: a releitura do mercado só troca `game_data` quando a leitura vem boa.
- *A26-10 (metade):* `internet_online()` pega `requests.RequestException`.
  Continua testando contra o github.com.
- *A26-22:* `TWB._hunter_capped_sleep()` lê `cache/hunter/schedules.json` direto,
  sem depender de `self.hunter`, e acorda
  `Hunter.window + Hunter.WAKE_MARGIN` (120 + 120 s) antes da próxima saída.
  O piso é de 30 s (`BLIND_SLEEP_FLOOR`): com a rede fora não há o que cruzar,
  e sem piso o laço reconferiria a rede sem pausa. `nearest_send_time(after=)`
  ignora horário vencido, para um schedule velho não prender a espera no piso.
  A espera por rede do início de `run()` virou laço interno e não devolve mais
  `False` para `main()`.
- *A26-23:* o Hunter roda logo depois da visão geral, antes de tudo o resto.
  Ele também passa a primar a aldeia de origem que ainda não tem
  `AttackManager` (`Hunter._ensure_source_ready()`, o mesmo
  `prime_for_conquest()` somente-leitura da conquista), e reconfere o atraso
  **depois** do prime: prime que atravessa a saída é recusa, nunca ataque
  atrasado. Há checkpoint do Hunter entre as aldeias do prime da conquista e
  trava de reentrada. `priority_mode` volta a `False` num `finally` (pega de
  tabela o caso de exceção do A26-18).
- *A26-03, 1ª das três correções:* `_target_is_mine()` aceita
  `config["villages"]` como prova de posse. Entrou agora por causa da 55647:
  os quatro nobres pousam hoje, e a conquista está em `extra_pending` com
  `loyalty_source: "estimate"`.

**Rodando o mesmo caso com a correção:** a queda às 14:27:23 não derruba o
processo. O ciclo termina, e o sono seguinte é encurtado para acordar às
14:34:41, 4 minutos antes da saída.

**Testes:** `tests/test_crash_resilience.py` (31 checks). Cobre o sono
encurtado no caso real (678 s até a saída, sono de 664 s), o prime da origem
num processo novo, o prime que atravessa a saída, reentrada e `priority_mode`,
as quedas seguidas de `main()`, os caminhos a/c/d/e e a posse por config. Para
provar que o teste pega o bug, rodei com o `village.py` anterior: falha em
`A26-02 a`. Suíte: 71/71.

**Não coberto:** o timer de reserva (§8.28) também tem hora marcada, e os
sonos cegos não o consultam. Os horários armados dele vivem só em memória, então
um processo recém-reiniciado não tem como saber deles sem reler o quadro. O
custo de perder um é menor, porque a reserva segue disponível para a próxima
leitura, mas continua sendo o 28º padrão em aberto.

**Não validado em campo.** Isso só acontece na próxima queda de rede com envio
agendado. No log, procurar `Hunter: sono (rede fora) encurtado` e
`Hunter: aldeia X ainda nao rodou neste processo -- lendo antes do envio`.

## 8.34 ✅ `P-TELEGRAM-AVISOS` — o que deu errado passa a chegar no celular (2026-09-27)

**Motivo.** O 4º nobre da 55647 foi recusado às 14:40 da §8.33, e o usuário só
soube depois, lendo o log. O `Notification` (§8.9) já era seguro e já avisava
captcha, captcha resolvido, queda do processo e início do bot. Não estava
ligado, e não sabia de Hunter, conquista nem rede.

**Avisos novos.** O texto é em pt-BR e cita aldeia pelo nome quando ele é
conhecido.

| Origem | Quando |
|---|---|
| `Hunter` | comando que não saiu (recusa por atraso, com os segundos, ou envio falho), marcando se levava nobre; operação que expirou com comando pendente |
| `BarbarianTrainPlanner` | trem agendado (origens e pouso); os N nobres saíram; **trem incompleto** ("só 3 de 4… se quiser mandar na mão, é agora"); nenhum nobre saiu; alvo cancelado por reserva da tribo |
| `ConquestManager._handle_existing` | conquistada (pela lista de aldeias ou pelo relatório do nobre); perdida para outro jogador; abandonada por reserva; **sem confirmação** (a estimativa de lealdade zerou); nobre extra enviado |
| `twb.py` | queda de rede, avisada **na volta** com início, fim e duração (com a rede fora o Telegram também não chega); erro numa aldeia que foi pulada (A26-01), menos `VillageInitException`, que é timeout rotineiro |

**Dois cuidados de desenho.**

- **O Hunter acumula e envia no fim do `run()`.** `send()` faz rede e pode
  levar segundos. Dentro da janela de envio, cada segundo pertence ao próximo
  comando do mesmo trem.
- **`Notification.arm()`**. Os avisos novos moram em caminhos que a suíte
  exercita, e os testes rodam da raiz do repo, ou seja, contra o `config.json`
  real. Com o Telegram ligado, rodar a suíte mandaria mensagem ao canal. Agora
  `send()` só age depois de `arm()`, e só `twb.main()` chama. Import, teste,
  webmanager e ferramentas nunca armam. Foi o 20º padrão (efeito que dispara
  onde ninguém previu) aparecendo antes de acontecer.

**Verificado.** Com um token falso, o `send()` chegou à API do Telegram e voltou
`Unauthorized` duas vezes seguidas, reusando o mesmo loop. Com o token do
`config.json`, só leitura (`getMe`, `getChat`, `getChatMember`): o bot existe e é
administrador do canal com permissão de postar. **Nenhuma mensagem foi
enviada.** Falta só `notifications.enabled: true`, que vale ao vivo, sem
reiniciar.

**Testes.** `tests/test_telegram_notes.py` (14 checks) cobre:
- o texto e o momento dos avisos do Hunter, sem repetir no run seguinte;
- os três desfechos da promoção do trem e a conquista confirmada;
- a queda de rede avisada uma vez, com o início preservado.

Em `tests/test_notification_safety.py` entrou o caso "sem `arm()` não lê config
nem monta bot". O `tests/test_session_and_captcha.py` passou a armar o notifier
real, senão o teste de captcha passaria sem exercitar o `send()`. Suíte: 72/72.

**Fora, de propósito:**
- filtro por categoria (`notify_<categoria>`), pelo mesmo motivo da §8.9: exige
  config nova e bump de `build.version`;
- avisos da conquista PvP. As falhas de envio dela já chegam pelo Hunter, e o
  desfecho fica para quando ela sair do semi-manual.

## 8.35 ✅ Lote B da auditoria — nobre extra, trem preso e sonda dobrada (2026-09-27)

Fecha os três itens do Lote B da §8.32. Nenhum aconteceu em campo, mas dois
deles deixam de depender de sorte assim que o §9 item 19a (trens em paralelo)
for ligado.

**A26-03, 2ª e 3ª correções (a 1ª está na §8.33).**
- *`repman`.* `Village.run_conquest()` passa o `ReportManager` da aldeia (e cria
  se faltar, sem requisição), e o `_manager_for()` do planejador passa o da
  origem. Só isso não bastava. O acompanhamento roda no **início** do ciclo
  (§8.15), então a última leitura de relatórios da âncora é do ciclo anterior,
  horas antes do pouso. Por isso `_get_real_loyalty()` chama `repman.read()` uma
  vez por instância antes de procurar o relatório do nobre. Ele só é alcançado
  depois da trava de nobre em voo, então a leitura só acontece quando há pouso a
  conferir. `read()` é incremental, e a aldeia reaproveita o mesmo objeto no
  próprio `update_pre_run()`: os relatórios baixados aqui seriam baixados de
  qualquer forma, só mais tarde no ciclo. Leitura que falha loga WARNING e fica
  com o que havia em memória. Vale também para nobre mandado na mão: o
  relatório dele entra igual, porque o filtro é `dest` + `snob` enviado.
- *Piso do mundo.* `ConquestManager.world_drop_range(config)` virou estático, e o
  planejador usa o mesmo número. O agendamento grava `loyalty_drop_per_noble` e
  `loyalty_drop_range` no registro, como o `_send_train` já fazia, e a promoção
  cai no piso do mundo quando o registro é antigo. Um trem de 4 no br143 grava
  `loyalty_after_train: 20`, e não mais 0.

**A26-04.** Duas guardas independentes, de propósito:
- `Hunter._expire_schedule()`: ao passar a chegada, o schedule e cada ataque
  ainda `pending` viram `failed`, com `fail_reason: arrival_passed`. Os que
  saíram ficam `sent`.
- `BarbarianTrainPlanner._schedule_over()`: a promoção trata `pending` como "não
  saiu" quando a chegada já passou ou quando o schedule não está mais `pending`.
  Não depende de o Hunter ter feito a parte dele (6º padrão), e resolve também
  os registros gravados antes da correção. Promovido, o registro sai de
  `train_scheduled`, o `_release_orphan_reserves()` solta a `barb_train:*` e o
  planejador volta a montar trem.

Achado no caminho: a reserva PvP (`pvp_conquest.py`, reconstrução pelo Hunter)
soma a tropa dos ataques `pending`. Com o schedule vencido, ela também ficava
presa para sempre. A primeira guarda corrige esse caso de tabela.

**A26-14.** O planejador passa `duration_seconds` (a duração que acabou de sondar),
e `HunterReader.add_schedule()` grava `send_time = arrival_time - duração`, que
é a mesma conta do Hunter. Sem duração, continua `None` e o Hunter sonda como
sempre. São duas requisições a menos por origem em cada trem, e uma chance a
menos de falhar e cair no A26-04.

**Testes.**
- `tests/test_conquest_loyalty_and_expiry.py` (15 checks) cobre:
  - a expiração no Hunter, com aviso único;
  - o `repman` entregue por `run_conquest`;
  - a leitura única, e a falha de leitura;
  - o caso ponta a ponta: relatório que só aparece na leitura nova, com
    lealdade −7, fecha como `noble_report` sem chamar `_available_nobles()`.
- Em `tests/test_conquest_planner.py`, os dois testes de promoção **afirmavam o
  bug** (0 e 25, o piso da config). Foram corrigidos para 20 e 40. Entraram mais
  cinco:
  - o piso gravado vence o do mundo;
  - o agendamento grava a faixa;
  - chegada vencida com `pending` promove, com o schedule ainda `pending`;
  - schedule `failed` herdado promove;
  - `send_time` sai da duração, passando pelo `HunterReader` real com o arquivo
    em memória.
- Provado por mutação:
  - com os fontes anteriores (stash), falham o Hunter e 6 testes do planejador;
  - tirar `repman=` do `run_conquest` derruba o check do `repman`;
  - tirar a leitura derruba o da lealdade.
- Suíte: 73/73.

**Estado em campo no momento da correção.** Nenhum schedule preso. A única
conquista ativa é a 55647 (`extra_pending`, `loyalty_after_train: 25` pelo piso
antigo, pouso às 23:59:47). Depois do reinício, o acompanhamento dela lê os
relatórios, inclusive o do 4º nobre, mandado à mão. **Sinal no log:**
`Noble report ... loyalty after = ...` seguido de `nosso relatorio marca
lealdade` ou `real loyalty from report`, no lugar de `no report data, using
estimate`.

## 8.36 ✅ Lote C da auditoria: Hunter, mercado e apoio (2026-09-27)

Cinco achados da §8.32, todos P2. Nenhum tinha causado dano medido em campo.

**A26-05, fila única no Hunter.** O `_run()` agora junta os comandos pendentes
de **todos** os schedules numa lista só, ordenada por `send_time`. Antes a ordem
era por schedule, e cada um era servido até o fim. O `sort` por "primeira saída
do schedule" que já existia resolvia a ordem **entre** schedules, mas não a
intercalação. Com A em T+10 e T+100 e B em T+50, o comando de B continuava
morrendo. O fechamento do status de cada schedule (`complete`/`failed`) saiu
do laço e roda uma vez no fim. `priority_mode` desliga no fim do laço, e o
`finally` do `run()` continua cobrindo exceções.

**A26-12, trava e merge no `schedules.json`.** Há três escritores: o Hunter, o
planejador bárbaro (cancelamento por reserva de tribo) e o painel
(`HunterReader.add_schedule`/`delete_schedule`, usado também pelo PvP e pelo
planejador para criar). A correção tem três peças:
- `core/file_lock.py`: trava do SO sobre `schedules.json.lock`, com as mesmas
  primitivas do `InstanceLock`. Bloqueia com timeout de 10 s. Se o tempo
  estourar, **segue sem a trava**, com WARNING. A trava é proteção e não pode
  ser o motivo de um nobre não sair.
- A trava cobre só o trecho curto de reler, mesclar e gravar, e **nunca a
  espera de até 120 s** (senão o painel congelaria). Quem espera tem que
  mesclar: `Hunter._save_schedules(schedules, baseline)` relê o disco e aplica
  `merge_schedule_changes()`, que grava só o que este processo mudou desde a
  leitura. Um schedule criado por outro lado continua no arquivo. Um schedule
  apagado por outro lado não volta, e se o Hunter tinha mudado ele, loga que
  descartou a mudança.
- Depois da espera, antes de disparar, o Hunter relê o arquivo e **não envia**
  se o schedule sumiu (6º padrão: reconferir no momento de agir). Se a
  releitura falhar (JSON corrompido, arquivo vazio), envia assim mesmo.

O painel passou a gravar de forma atômica (antes era `open(..., "w")`). Com
arquivo ilegível, `add`/`delete` recusam em vez de trocar tudo por um arquivo
com um schedule só.

**A26-06, `trade_max_per_hour`.** O código passou a seguir o nome e o
helpfile: o intervalo entre trocas de uma aldeia é `3600 / valor`, e `0` ou
negativo desliga as trocas. Com o default 1 as duas leituras coincidem, e é
por isso que o bug veio do bot base sem ninguém notar (17º padrão).
⚠️ **Muda o comportamento em campo:** o `config.json` tem `12`. Até aqui isso
era uma troca a cada 12 h por aldeia. Agora é até uma a cada 5 min, e na
prática uma por visita da aldeia ao mercado (uma vez por ciclo). Para manter a
cadência antiga, o valor equivalente é `0.083`.

**A26-07, proporção da oferta.** Nova `ResourceManager.offer_is_acceptable()`.
A oferta de outro jogador só é aceita se `wanted_amount <= offer_amount ×
trade_bias`. `trade_bias` é a mesma proporção que o bot usa para criar a
própria oferta (`market.trade_multiplier_value`, ou 1:1 com o multiplicador
desligado). Em campo está `true`/`1.0`, então o teto é 1:1. As quatro regras
antigas continuam valendo.

**A26-08, `supported`.** O laço de apoio saiu de `update()` para
`DefenceManager._support_others()`. No começo dele,
`_release_finished_supports()` tira da lista quem não está mais sob ataque em
`my_other_villages`. A lista continua impedindo apoio dobrado **no mesmo
ataque**. Consequência aceita: ondas seguidas, sem nenhum ciclo limpo entre
elas, contam como um ataque só.

**Testes.**
- `tests/test_hunter_schedule_queue.py` (8): a intercalação A/B/A, `priority_mode`,
  o merge puro, schedule criado durante a espera que sobrevive, schedule
  apagado durante a espera que nem sai nem volta (os dois com arquivo de
  verdade num diretório temporário), releitura corrompida que não segura o
  comando, `remove_schedule`, e a trava entre dois processos reais.
- `tests/test_market_trade_rules.py` (8) e `tests/test_support_release.py` (6).
- Os dublês de `_save_schedules` e `_load_raw` em 6 testes antigos ganharam os
  parâmetros novos. `test_conquest_reservation_gate` troca
  `Hunter.remove_schedule` pelo dict em memória, e `test_conquest_planner`
  troca a trava por `nullcontext`, para nenhum dos dois tocar em `cache/hunter`.
- Provado por mutação: com os fontes anteriores, falham 6 dos 8 do Hunter
  (inclusive os três comportamentais: B perdido, schedule do painel apagado,
  schedule apagado enviado), 8 de 8 do mercado e 6 de 6 do apoio. Tirar o
  `try` da releitura derruba o teste dela.
- Suíte: 76/76.

**Sinal no log.** O apoio ainda não foi exercitado em campo (§6.2). Quando for,
procure `vaga de apoio liberada`. No mercado, `oferta ... recusada pela
proporcao` aparece em DEBUG.

## 8.37 ✅ `P-OVERVIEW-ABA` — o próprio bot trocava a aba da visão geral e depois não achava aldeia (2026-09-29)

**Sintoma.** Às 13:57 e às 14:08 de 2026-09-29, `get_overview` logou "a tela de
visao geral nao devolveu NENHUMA aldeia, mas o config tem 38" e o bot dormiu
~10 min a cada vez. Voltou sozinho às 14:18. O usuário já tinha visto isso
antes e ligou à troca de aba da visão geral.

**Causa.** `OverviewPage` pedia `screen=overview_villages` **sem `mode`**, e o
jogo serve a última aba aberta. A aba passada na querystring também fica
gravada, e `InFlightTracker` (§8.25, Feature 38) lê `mode=commands&page=-1`
todo ciclo. A leitura seguinte da visão geral recebia a tela de Comandos, que
não tem nenhum `quickedit-vn`. A guarda do B9 (`purge_refusal_reason`)
segurou: nada foi apagado, só se perdeu o ciclo. Voltou quando alguém reabriu
outra aba no navegador.

**Segunda metade, que não gerava erro.** Mesmo na aba Combinado, que lista as
aldeias, falta a `production_table`. Dela saem os pontos por aldeia
(`villages_data`, §8.23) e o `is_premium`. Então, fora da aba Produção, o bot
lia as aldeias e perdia os pontos em silêncio.

**Correção.** `_get_overview_villages_data()` pede `mode=prod`, a aba para a
qual o parser foi escrito e a única que existe em conta sem premium. Sondado
com o `WebWrapper` do bot: 38 ids e `production_table` presente.
`tests/test_overview_mode.py` exige o `mode=prod` e falha sem a correção.
Suíte: 77/77.

**Efeito colateral aceito.** O bot já gravava a aba do jogador (Comandos). Agora
ela fica em Produção ou em Comandos, conforme quem leu por último. Não piorou,
mas o navegador do usuário continua abrindo na aba que o bot deixou.

## 8.38 ✅ `P-MAPA-WEB` — /map transposto e identificação de aldeias com a legenda do jogo (2026-09-29)

**Orientação.** Dos três mapas do webmanager, só o `/map` estava com a
orientação errada, e estava **transposto** (espelhado na diagonal).
`MapBuilder.build` montava `grid[x][y]` e o `map.html` desenha a primeira
chave como linha, então x ia para a vertical. De quebra, o `range(min, max)`
exclusivo cortava a última linha e a última coluna, e a aldeia central ficava
fora do meio. Agora é `grid[y][x]`, inclusivo, com `origin` exposto e rótulos
de coordenada a cada 5 campos para dar para conferir de olho. Conferido na
página renderizada: 209 aldeias em posição certa, 0 divergências, BBM 020
(574|317) em `[15][15]`.
`/empire` e `/zones` já tinham o eixo certo (y cresce para o sul, como no
jogo), mas esticavam x e y por fatores diferentes. Nas zonas isso fazia o halo
de raio não bater com a distância real entre as aldeias. Os dois passaram a
usar a mesma escala nos dois eixos.

**Identificação.** O `/map` pintava tudo que não fosse seu ou da sua tribo
como "Inimigo", e chamava a própria tribo de "Tribo aliada". Agora usa a
legenda e a paleta do jogo: Aldeia atual, Suas aldeias, Amigos, Sua tribo,
Bárbaros, Outros, Aliados, PNA e Inimigos.

- **Fonte:** a tela `screen=map`, que `Map.get_map()` **já baixava** (8h por
  aldeia), traz inline `TWMap.colors[...]`, `TWMap.allyRelations[id] =
  'partner'|'nap'|'enemy'` e `TWMap.friends[id] = true`. Zero requisições
  novas. `Extractor.map_relations` lê isso e `Map.save_diplomacy` grava
  `cache/diplomacy.json`, que o webmanager lê por `DiplomacyReader`.
- **Completude conferida** (26º padrão): 71 tribos em `allyRelations`, 71 na
  tela `screen=ally&mode=contracts`, o mesmo conjunto, sem paginação. Os
  amigos batem com `screen=buddies`: 2 e 2. A terceira linha daquela tela é a
  própria conta, destacada no ranking.
- **Precedência lida do JS do jogo, não da legenda:** `TWMap.getColorByPlayer`
  em `merged/map.js` decide personalizada → sua aldeia → sua tribo → relação da
  tribo → **amigo** → outros. Amigo vem *depois* da relação, então um amigo
  numa tribo aliada aparece como Aliado. Pela ordem da legenda eu teria
  chutado o contrário, e os dois amigos atuais estão justamente na tribo 16,
  que é `partner`. Cores personalizadas (`villageColors`/`playerColors`/
  `allyColors`, as linhas "Próprias/Outros" da legenda do jogo) e `sleep` não
  foram implementadas: estavam vazias na captura.
- Sem `cache/diplomacy.json`, o `/map` cai em dono/tribo da aldeia central e
  avisa na legenda que aliados, PNA, inimigos e amigos aparecem como Outros.

Testes em `tests/test_map_relations.py`, com fixture verbatim
`tests/fixtures/map_relations_br143.txt`: parser, precedência (incluindo o
caso do amigo em tribo aliada), orientação da grade e "tela errada não
sobrescreve a leitura boa". Probe em `cache/_probe_diplomacy.py`, só leitura.

**Relevante para o apoio a membros da tribo** (próximo assunto):
`cache/diplomacy.json` já carrega `player_id` e `ally_id`, e o cache de aldeias
carrega a tribo de cada aldeia. Com isso, dá para identificar "aldeia de membro
da tribo" sem nenhuma requisição nova.

## 8.39 ✅ `P-APOIO-TRIBO` — apoio a membros da tribo: pedido do fórum, origem segura, aprovação (2026-09-29)

**O que o usuário pediu.** Uma interface para apresentar as aldeias que
precisam de apoio (colando o link do tópico do fórum ou o texto do pedido), em
que o bot calcula **de quais aldeias próprias é mais seguro tirar tropa**. No
br143 o apoio só vai para membro da própria tribo. Três decisões dele:
segurança é propriedade da **origem**; o bot **propõe e ele aprova**; a falta é
a **tabela menos as respostas postadas depois da última edição dela**.

**O pedido real** (fórum Defesa, `forum_id=2513&thread_id=1639`, "BLINDAGEM
FIXA - APOIO"): 36 aldeias de 8 jogadores, **todos membros da tribo 987**
(conferido em `screen=ally&mode=members`, sem paginação), em K57/K47, a
**213–293 campos** das aldeias do usuário (K25/K35). Viagem: explorador ~32 h,
pesada ~39 h, lança ~64 h, espada ~78 h. O organizador mantém a tabela no
primeiro post e a edita; quem envia responde `NN/lança/espada/exp/pesada`.
Tópico de página única (`Forum.is_last_page = true`, 20 por página).

### Bug encontrado no caminho: o `support()` montava ATAQUE

O formulário da praça tem dois botões de envio, e `Extractor.attack_form`
recolhe os dois:

```
<input id="target_attack" ... name="attack" type="submit" value="Ataque" />
<input id="target_support" ... name="support" type="submit" value="Apoio" />
```

`DefenceManager.support()` mandava os dois no POST de `try=confirm`: o mesmo
par de chaves que `AttackManager.attack()` manda e que o jogo trata como
ataque no farm, todo dia. Sondado com autorização do usuário (3 POSTs em
`try=confirm`, que só renderiza a confirmação; 1 explorador de BBM 001 para
BBM 002; nenhum comando criado):

| POST com | Resposta do jogo |
|---|---|
| só `support` | *"Confirmar apoio para BBM 002"*, duração 764 s |
| só `attack` | recusa de ataque: *"É necessário enviar o mínimo de 5 Exploradores"* |
| os dois (código antigo) | **a mesma recusa de ataque** |

O terceiro caso podia ter desmentido a hipótese (13º padrão) e não desmentiu.
O apoio entre aldeias próprias (`support_other`, ligado em 22 de 30 aldeias) e
a evacuação (`evacuate`, que também chama `support()`) nunca tinham disparado
em campo, então isso nunca virou comando real. Correção em duas travas
independentes: o POST leva só `support`, e a confirmação precisa ser
reconhecida como apoio por `Extractor.command_confirm_kind` antes do passo que
cria o comando. A âncora é `<input type="hidden" name="support" value="true" />`
dentro do `command-data-form` (fixture
`tests/fixtures/place_confirm_support_br143.html`). Confirmação ilegível também
para.

### Como ficou

- `core/support_request.py` — lê o tópico (tabela `bbcodetable`, colunas pelo
  cabeçalho em português, respostas, "Editado por X hoje às HH:MM" com a data
  do servidor de `id="serverDate"`), BBCode e texto livre. `remaining()`
  aplica a regra da falta. Resposta no mesmo minuto da edição conta como não
  descontada e sai marcada `ambiguous`.
- `core/support_planner.py` — segurança da origem: ataque chegando exclui;
  ameaça = soma de hostis num raio (inimigo 3, "outros" 1; aliado, PNA, amigo
  e a própria tribo não contam), por tamanho e proximidade; faixas segura /
  atenção / exposta (≥ 2,0, fora do plano salvo pedido). Reserva por unidade
  (padrão 20%). Dentro da faixa, a origem que cobre **mais** vem antes (menos
  comandos). Teto de viagem opcional por unidade. `split_fast` separa
  pesada/explorador de lança/espada.
- `core/support_store.py` — `cache/support/request.json` (só o painel
  escreve) e `cache/support/plan.json` (painel e bot, sob `file_lock`, relendo
  antes de gravar). Linha: `proposed → approved → dispatching → sent|failed`.
  `dispatching` é gravado **antes** de tocar na praça e nunca é reclamado de
  novo: queda no meio vira "resultado desconhecido", não reenvio. Aprovação
  vale 24 h.
- `Village.run_tribe_support()` — fase `apoio`, antes do farm e da coleta.
  Reconfere na hora: ataque chegando adia sem gastar a aprovação; tropa em
  casa abaixo de plano + reserva faz a linha falhar em vez de mandar menos.
- `/support` no webmanager (item "Apoios" da navegação, que era "futuro") —
  busca o tópico com o `WebWrapper` do bot (um GET, no máximo a cada 30 s; o
  captcha vira erro na hora em vez de congelar a página). Mostra a falta por
  aldeia, o ranking das origens, o plano com seleção, o andamento e o texto de
  resposta para o tópico. O painel **não posta** no fórum.

### O que os dados reais mostraram e mudaram

A primeira rodada contra o tópico ao vivo expôs três coisas que a fixture não
mostrava:

1. **As 175 "hostis" eram quase todas de 26 pontos**, de contas sem tribo
   abandonadas no início. Todas as 38 origens saíam "atenção", com "hostil a 1
   campo". Com o piso de 500 pontos (`min_hostile_points`): 11 seguras e 27
   em atenção.
2. **111 envios, muitos de 10 a 50 unidades**: as origens "mais seguras" eram
   as de pouca tropa, e o guloso espalhava cada pedido por uma dúzia delas.
   Pacote mínimo de 100 de população (que não barra um pedido inteiro menor
   que isso) e preferência pela origem que cobre mais dentro da faixa: 85
   envios, já com `split_fast`.
3. **O limiar de "exposta" em 3,0 não pegava nem uma inimiga a 2 campos**
   (dava 2,6). Baixado para 2,0.

A oferta cobre pouco do pedido: as origens podem ceder ~18 mil lanças, ~19 mil
espadas, ~8 mil exploradores e ~4,6 mil pesadas, contra ~63 mil pesadas
pedidas. 34 das 36 aldeias ficam sem cobertura total, e o painel lista a falta
que sobra. As linhas 25 e 26 do tópico são a mesma aldeia (779|536); o painel
avisa.

Fixtures em `tests/fixtures/forum_support_thread_br143.html` (jogadores
anonimizados, porque o repositório é público e o fórum da tribo não) e
`place_confirm_support_br143.html` (tokens `h`/`ch` redigidos). Testes em
`tests/test_tribe_support.py` e `tests/test_support_urgency_gate.py`.

### Primeira rodada em campo (2026-09-29, 20:29 em diante)

O usuário aprovou 83 envios. **O primeiro apoio real do bot foi validado de
ponta a ponta**: BBM 001 → La Rochelle, 80 exploradores; a confirmação leu
42,5 h, o `popup_command` foi aceito, e a lista de comandos do jogo
(`overview_villages&mode=commands&page=-1`, a mesma URL do InFlight, para
não mudar o filtro que o jogo grava) mostrou *"Apoio para La Rochelle
(737|540) K57"* com o ícone `command/support` e chegada em 01/10 15:01:13.

E expôs um erro de premissa: **24 das primeiras 35 linhas falharam com "em
casa 0"**. Todas as 38 aldeias têm coleta ligada, e a tropa da coleta passa
6-7 h fora entre ciclos. Pior, o `available_troops` do cache/managed mostrava
essa tropa como "em casa": `TroopManager.gather()` relia a praça antes de
mandar a coleta e não descontava o que mandou (BBM 003: cache com 1.925
lanças e 750 pesadas, em casa 25 e 0, total inalterado). A trava da hora de
agir segurou tudo; nada saiu pela metade.

### A coleta tem prioridade, com fatia

Decisão do usuário: *"a coleta é prioridade"*, e logo depois *"não precisa
cortar completamente, só definir uma taxa, 0,2 ou algo assim, faça umas
contas"*. As contas saíram da fórmula do próprio jogo, lida no
`Scavenging.js` do br143 (`calcLoot` e `calcDurationSeconds`), com os
parâmetros da tela (`duration_exponent` 0,45, `duration_initial_seconds`
1800, `duration_factor` 1; o `loot_factor` 1,2 é o bônus premium):

    saque = capacidade × fator      duração = (100·cap²·fator²)^0,45 + 1800 s

A duração cresce com cap^0,9, então o saque por hora quase não depende do
tamanho da tropa. Com as tropas reais das 38 aldeias e a divisão 15:6:3:2 do
bot na seleção 4:

| Fatia | Coleta (rec/h) | Perda | Libera (lança / espada / pesada) |
|---|---|---|---|
| 10% | 120.523 | −1,3% | 4.845 / 4.814 / 1.233 |
| **20%** | **118.770** | **−2,7%** | **9.701 / 9.638 / 2.471** |
| 30% | 116.826 | −4,3% | 14.558 / 14.460 / 3.709 |
| 50% | 112.091 | −8,2% | 24.272 / 24.114 / 6.191 |

Implementado com 20% como padrão (`gather_share`, ajustável no painel):

- `core/templates.py::GATHER_UNITS` é a lista única das unidades da coleta.
  A coleta monta a lista dela daqui, e o apoio as trata como da coleta.
- Planejador: em aldeia que coleta, unidade da coleta cede até
  `gather_share` do **total** (não do que está em casa); explorador segue a
  regra de casa + reserva.
- Executor (`support_store.line_readiness`): acima da fatia falha; dentro da
  fatia mas coletando, a linha **espera** aprovada e a fatia vira
  `conquest_reserve["tribe_support"]`, que `gather()` e o farm já
  respeitam. Quando a tropa volta, a coleta deixa a fatia em casa e o apoio
  sai no ciclo seguinte. A reserva é recalculada a cada ciclo e some quando
  não há linha esperando.
- `gather()` desconta o que mandou (`_deduct_gathered`), e o cache deixa de
  mostrar como "em casa" a tropa que está coletando.

### Revisão de 2026-09-30

O bot dormiu às 22:59 depois da BBM 023 e foi reiniciado às 07:50 já com a
fatia. Estado: 31 enviados, 29 falhas (todas "tropa em casa", do código
antigo) e 23 linhas ainda aprovadas. **Os 31 envios conferem 1 a 1 com o
jogo**: origem e destino de cada linha `sent` contra os 31 comandos de apoio
do `cache/in_flight.json` das 07:51, sem sobra nem falta.

Dois furos achados na revisão, ambos sobre linhas e planos anteriores à
fatia:

- **Linha aprovada sem `gather_share` era lida como 0%**, e toda lança,
  espada ou pesada falharia com "acima da fatia (0%)". O executor passou a
  usar `support_store.DEFAULT_GATHER_SHARE` (0,2) quando a linha não traz o
  campo, e as 23 linhas pendentes ganharam o campo no `plan.json` (sob a
  trava), para o processo já em execução aplicar a regra sem reinício. Das
  23, 12 cabem (saem ou esperam a coleta) e 11 passam dos 20% e vão falhar
  com o motivo registrado (ex.: BBM 028, 1.040 lanças contra teto de 260).
- **A fatia não era acumulada.** Apoio enviado continua no total da aldeia,
  então cada recálculo ofereceria outros 20% por cima do que já saiu (a BBM
  020 mandou 812 lanças pela regra antiga). O painel agora soma, por aldeia,
  o que está `sent` e o que está `approved`/`dispatching` no plano, e o
  planejador desconta isso da fatia (e o pendente, do explorador em casa).


## 8.40 ✅ `P-CONQ-EMPATE` — trem que pousa no mesmo segundo: o bot lia a lealdade do PRIMEIRO nobre (2026-09-30)

**Sintoma.** O trem de 4 nobres contra a Bárbara #61947 (583|285) pousou às
07:27:42 de 2026-09-30. Os quatro relatórios (166237693/695/696/697) traziam
lealdade 79, 49, 23 e **1**, todos com o mesmo `when`. O bot logou *"real
loyalty from report: 79.0"* e decidiu por nobres extras contra uma aldeia a 79.

**Causa.** `ConquestManager._get_real_loyalty()` escolhia o relatório de maior
`when` com `>` estrito. Trem pousa no mesmo segundo, então todos empatam e
vencia o primeiro da iteração do dict, que aqui era o do primeiro nobre. O
estrago aqui foi zero só porque a aldeia dona (BBM 010) não tinha nobre em
casa. No caso inverso, com o último nobre conquistando (lealdade ≤ 0), a
mesma leitura errada mandaria nobre extra contra a aldeia já nossa, que é a
autoconquista do A26-03 entrando por outra porta.

**Correção.** A chave passou a ser `(when, -lealdade)`: no mesmo instante a
lealdade só cai, então o empate fica com a **menor**. Teste em
`tests/test_conquest_loyalty_and_expiry.py` com os quatro relatórios reais nas
24 ordens de iteração (com o código antigo sairiam quatro valores diferentes)
e um relatório posterior vencendo o trem. Depois do reinício das 08:05 o bot
logou *"real loyalty from report: 1.0"*.

**Nobre extra do mesmo episódio, enviado à mão.** Com lealdade 1, regeneração
de 1/h e ~12h40 de viagem, um nobre só bastaria com certeza (queda mínima 20)
se saísse até ~13:45. O bot só tira o nobre extra da aldeia dona
(`reserved_by`), e os 3 nobres da BBM 010 estavam voltando (chegam às 20:03).
O usuário mandou 1 nobre da BBM 001 (chegada 20:49:58), e ele foi registrado
em `cache/conquest/61947.json` (`noble_arrivals`, `status: extra_pending`,
bloco `manual_extra`) para a trava de nobre em voo, que só enxerga nobre
registrado pelo bot, não mandar outro por cima. ~~**Aberto:** o nobre extra
poder sair de qualquer aldeia de origem do trem, não só da dona.~~ ✅ §8.41.

---

## 8.41 ✅ `P-CONQ-EXTRA-ORIGEM` — nobre extra de qualquer aldeia, pela chegada, com prazo (2026-09-30)

**Sintoma.** O do fim da §8.40: com a 61947 a lealdade 1, o nobre extra só
podia sair da dona (`reserved_by`, BBM 010), cujos nobres estavam voltando,
enquanto a BBM 001 — que também era origem do trem — tinha nobre em casa. O
usuário mandou à mão.

**Causa.** `_handle_existing` usava `_available_nobles()`, `_build_escort()` e o
`_attack_manager` da própria dona. Desde a fase 2 o trem é multi-origem
(§8.6), mas o acompanhamento continuou com a visão de uma aldeia só.

**O que mudou** (`game/attack.py`, `game/village.py`, `game/conquest_planner.py`,
`twb.py`):

1. **Origem.** `ConquestManager` recebe `villages` (o dict do `twb.py`, via
   `Village.run_conquest`). O nobre extra sai da aldeia que **pousa primeiro**
   entre as gerenciadas que passam no portão, têm nobre livre e fecham a
   escolta. Nobre e escolta são contados pelo `ConquestManager` **daquela**
   aldeia, então as reservas de outros sistemas (`pvp:*`, `barb_train:*`,
   `tribe_support`) continuam descontadas pela regra de sempre. O envio usa o
   `AttackManager` da própria `Village` (que tem a paz forçada), direto, sem
   Hunter: é um comando só, não há o que sincronizar, e a chegada gravada é a
   da confirmação do jogo. Sem o dict (testes, chamadas antigas) a única
   candidata é a dona — o comportamento anterior.
2. **Portão único.** `conquest_origin_block_reason()` (`conquest_enabled:
   false`, sem dado de tropa/mapa, origem de PvP) é o mesmo para o trem do
   planejador e para o extra. Ele saiu de `Village.run_conquest`, onde barrava
   também o **acompanhamento** — posse, alvo perdido, leitura de lealdade — de
   uma dona travada pelo PvP. Agora ele barra só quem **manda**.
3. **Prazo.** `rank_extra_noble_origins()` ordena pela chegada (distância ×
   velocidade do nobre, que é a unidade mais lenta do comando) e dá, por
   origem, a lealdade prevista **na chegada**, o veredito (`certo` ≤ queda
   mínima, `chance` ≤ queda máxima, `insuficiente`) e a última saída em que um
   nobre só ainda basta. A regeneração conta do `when` do relatório, não do
   `last_hit_timestamp` (que é a chegada *prevista* do último nobre
   registrado; 6º padrão).
4. **Política** (decidida pelo usuário): manda em `certo` e `chance` — nobre que
   não conquista volta para casa (`units_losses` vazio nos quatro relatórios do
   trem da 61947), então errar custa tempo, não o nobre. Em `insuficiente`
   manda só se o golpe derruba mais do que a viagem regenera (`queda mínima >
   regen × horas de voo`); senão cada extra pousaria numa lealdade maior que o
   anterior, e o aviso sugere dois nobres juntos à mão.
5. **Falha de envio.** Recusa **antes** do POST final (`last_attack_failure`
   marcado, ou paz forçada) significa que o comando não existe, e a próxima
   origem tenta no mesmo ciclo. Falha **no** POST final é ambígua — o comando
   pode ter saído — e para tudo até o próximo ciclo. Só um nobre por chamada.
6. **Avisos** (Telegram, uma vez por pouso e por tipo, marca `extra_alert` no
   registro): nenhuma aldeia com nobre livre (com o prazo e a origem mais
   rápida com alcance), e sem progresso. O aviso de envio diz a origem, a
   lealdade prevista e o veredito.
7. **Prime.** `prime_barbarian_sources` inclui as `sources` do trem e a
   `extra_source_village_id` quando nenhum nobre está no ar: são as aldeias
   para onde os nobres voltam, e memória e snapshot delas dizem 0 porque foram
   lidas com o nobre fora.

O registro ganha `extra_source_village_id` e `extra_prediction`
(`loyalty_at_arrival`, `verdict`, `single_noble_deadline`, `sent_at`).
`reserved_by` não muda: a dona só acompanha. Nenhuma chave de config nova.

**O que continua valendo.** A trava `_noble_flight_guard` roda antes de tudo e
é por **alvo**, por chegada e não por `status`: com nobre nosso no ar nada sai,
venha de onde vier. Chegada 0 da confirmação vira `null`, que trava por tempo
indeterminado.

**Conferido sem rede.** Com `cache/managed` e a config de mundo em cache, o
ranqueamento para a 61947 às 08:05:34 dá a BBM 001 pousando às 20:49 com
lealdade prevista 14,4 (`certo`) e saída máxima às 13:43:19; o envio manual
real saiu às 08:05:34 e pousou às 20:49:58. A BBM 010 teria até 13:52:11.
Não houve sondagem: nenhuma tela nova, o envio é o mesmo `AttackManager.attack()`.

**Testes.** `tests/test_conquest_extra_origin.py` (50 checks, números reais da
61947): prazo, ordem, alcance, vereditos, os portões, reservas PvP e
`tribe_support` pelo `TroopManager` de verdade, trava em voo, chegada 0,
falha ambígua × recusa limpa, aviso único por pouso, sem progresso, sem o
dict de aldeias, e a regen pela hora do relatório ponta a ponta. Provado por
mutação: cada guarda desligada à mão derruba o teste. Ajustados:
`test_conquest_cycle_start.py` (prime das origens do trem pousado),
`test_conquest_planner.py` (isola o `FileManager` de `attack.py`, de onde vem a
coordenada agora) e `test_pvp_farm_suspension.py` (a trava do PvP é conferida
no portão de origem, não mais no `run_conquest`).

**⏳ Falta campo:** a linha `nobre extra enviado de <origem> contra <alvo>` com
uma origem diferente da `reserved_by`. Limite conhecido, fora deste escopo: a
trava só enxerga nobre que o bot registrou; nobre mandado à mão ainda precisa
ser registrado à mão (como o `manual_extra` da 61947). Ler isso dos comandos do
jogo (`cache/in_flight.json`) é outra tarefa.

## 8.42 ✅ `P-PAINEL-CAMPO` — os cinco achados graves da auditoria do painel (2026-09-30)

Os cinco de gravidade alta da `frontend.md` §2.8 (23/09), que eram o item 25 da
§9: o painel contradizia o jogo. Todos reconferidos contra o código e o
`cache/` atuais antes de mexer. Nenhum toca decisão do bot.

- **W7 `/cycles`.** `CycleReader.load()` separa o ciclo **ocioso** (não
  abortado e sem nenhuma aldeia: janela fora de `active_hours`, só os sistemas
  de conta) e o conta à parte, fora de medianas, fases e aldeias, como já fazia
  com o abortado. Dois reais na janela de 14 dias (22/09 23:40, 8m55, 35 req;
  23/09 00:23). O ciclo cortado pela janela das 23h (26/09 22:27, 7 aldeias)
  **fica**: é um ciclo de verdade, só menor.
- **W10 `/farmscores`.** Das 155 entradas de `cache/attacks`, **33 eram
  aldeias nossas** (BBM 003…038, ex-farms conquistados) e 106 o mapa dava com
  dono, sem nenhuma em `additional_farms` do config. O ranking caiu para 16
  bárbaras. "Própria" usa a mesma fonte do farm (`config["villages"]`, que não
  atrasa) mais `cache/managed`. O dono vem de `cache/villages` (27º padrão: aí
  "jogador" é confiável, "bárbara" não). As duas listas ficam recolhidas abaixo
  do ranking, com a contagem. **Achado de brinde, fora da auditoria:** a 61947,
  2ª do ranking, era o alvo da conquista ativa, que o farm não ataca desde a
  §8.24. O painel agora usa a própria `ConquestCache.farm_blocked_targets()` e
  a marca como "Alvo de conquista". Se essa leitura falhar, a página avisa em
  vez de mostrar tudo sem selo. O cabeçalho dizia "loot ÷ distância, menor =
  mais eficiente", errado nas duas metades: `farm_score` é saque médio (maior
  = melhor) e a ordem por distância ÷ score é a do bot, não a da página.
- **W11 `/hunter`.** `pending` com chegada no passado ganhou `expired`. Sai de
  "agendadas", da tabela de ativos e dos próximos deadlines, e entra em
  atenção e no histórico. **Não reproduzi o "30 × 0" literal**: o template não
  muda desde 14/09 e os dois números usam o mesmo contador. Hoje o
  `schedules.json` tem 10 registros, todos terminais. O que foi corrigido é a
  hipótese da própria auditoria, que é real no código.
- **W6 `/conquest`.** Achado ao abrir o template: a regra de "atenção" estava
  escrita **duas vezes** (contador e lista), e a cópia da lista não conhecia
  `train_scheduled`. Todo trem agendado aparecia na lista como "status fora do
  contrato", sem entrar no contador. Agora é uma função só,
  `ConquestReader.attention_reason()`, e o template só lê o motivo. Ela
  acrescenta a chegada vencida sem fechamento: `train_sent` com o último nobre
  pousado há mais de 15 min, e `train_scheduled` com a chegada planejada
  vencida. `extra_pending` fica de fora de propósito, porque pouso no passado é
  o normal dele e o registro não guarda quando foi a última leitura.
- **W1/W4 `/` e `/villages`.** `core/account_pulse.py`: o `WebWrapper` passa o
  `game_data` de toda resposta, e o pulso grava `player.incomings`/`supports`
  com a hora do servidor em `cache/account_pulse.json` (quando muda, ou a cada
  60 s). O painel mostra "Ataques chegando (jogo)" com a idade, e "Leitura
  velha" acima de 30 min. Arquivo ausente ou ilegível aparece como "Não lido",
  nunca como 0. Fica desarmado até `account_pulse.arm()`, que só `twb.main()`
  chama: rodar a suíte inteira não criou o arquivo (conferido). No W4, aldeia
  `managed` no config sem snapshot passa a contar em "dados incompletos" (hoje
  são 0 de 38).
  ⚠️ **Semântica não medida:** `"incomings":"0","supports":"0"` aparecem
  verbatim em todas as capturas de `cache/debug/`, mas **nenhuma tem valor
  diferente de zero**. "Contador de ataques chegando da barra do jogo" é
  leitura do nome e do lugar do campo. Por isso o painel diz "segundo o jogo",
  e nada no bot decide com isso.

**Testes.** `tests/test_panel_field_audit.py` (pulso com o recorte verbatim do
`test_overview_shadow.py`, trava de desarmado, as três páginas renderizadas,
motivo de atenção com o caso real de 2h38, contador × lista, farmscores com os
ids reais, Hunter vencido pela rota) e um caso novo em
`tests/test_cycle_reader.py`. **Provado por mutação:** cada uma das oito
correções, desligada à mão, derruba o teste.

**⏳ Falta campo:** reiniciar o bot. `cache/account_pulse.json` nasce na
primeira tela, e o primeiro ataque real recebido responde a semântica do
`incomings`.

## 8.43 ✅ `P-CONQ-PARALELO` — mais de um trem bárbaro ao mesmo tempo (2026-10-03)

O §9 item 19a, pedido pelo usuário em 23/09. Os Lotes B (§8.35) e a §8.41 eram
pré-requisito declarado.

**A medição que o item pedia antes de implementar.** Feita só com o `cache/`
(sem rede), em 2026-10-03:
- De 22/09 a 03/10 saíram **10 trens em 12 dias**, nunca dois no mesmo dia.
  Os 12 registros do planejador levaram de 7h13 a 22h51 entre agendar e
  pousar (mediana ~11 h; a 53691, agendada às 10:57, pousa em 04/10 às
  09:48), e a janela ativa é das 6h às 23h. Com a trava, o segundo trem do dia
  não cabia nunca.
- Às 15:32, os snapshots de `cache/managed` davam **8 nobres em casa**:
  41123 com 4, 74689 com 3 e 37318 com 1. Quatro estavam reservados para o
  trem da 53691, e **quatro estavam livres e parados**. O planejador logava
  `ja existe conquista barbara em andamento (53691)` a cada ciclo.
- Num trem, só o nobre que conquista é consumido; os outros três voltam. A
  conta de nobres cresce, e a trava não acompanhava.

**O que mudou.**
1. **Teto configurável.** `conquest.max_parallel_trains` (padrão **1**, que é
   o comportamento anterior; valor ilegível, zero ou negativo cai em 1 com
   WARNING). Conta como vaga toda entrada de `active_conquests()`: agendada,
   em voo, esperando nobre extra, ou com nobre no ar sob status errado. É a
   mesma fonte do farm e do `find_target()`.
2. **Um trem novo por ciclo, no máximo.** Com ciclo de ~4 h e trem de 7 a
   23 h, um por ciclo já enche o teto. Também cabe no orçamento de uma escrita
   por ciclo do quadro da tribo (`MAX_WRITES_PER_CYCLE = 1`): um segundo trem
   no mesmo ciclo encontraria o orçamento gasto e voaria sem reserva
   anunciada, sem nada que tentasse de novo depois.
3. **A reserva `barb_train:*` sobrevive a reinício.** Este é o ponto que
   decidia se dava para ligar. A reserva mora no `TroopManager` (memória), e o
   agendamento mora em disco por horas. Sessão vencida reinicia o bot quase
   todo dia. Com a trava, perder a reserva só expunha a escolta ao farm. Sem a
   trava, os nobres esperando o `send_time` contariam como livres e entrariam
   num segundo trem. `BarbarianTrainPlanner._sync_scheduled_reserves()` agora
   reconstrói a reserva a cada ciclo a partir do `cache/hunter/schedules.json`,
   no mesmo desenho do `PvpConquestManager._sync_scheduled_reserves` (§8.20).
   Só comando `pending` reserva. Arquivo vazio ou schedule ausente não solta
   nada. De brinde, a reserva encolhe quando o trem sai aos pedaços, o que
   antes só acontecia na promoção. Roda depois da promoção, do cancelamento e
   da limpeza de órfãs, e **antes** de contar nobre.
4. **O acompanhamento atende todas as conquistas da âncora.**
   `_get_my_conquest()` devolvia o **primeiro** registro com `reserved_by`
   igual. A âncora é quem manda mais nobres, então tende a ser a mesma aldeia
   em dois trens. O segundo ficaria sem confirmação de posse, sem leitura de
   lealdade e sem nobre extra, e nada no log diria que ele existia. Agora é
   `_get_my_conquests()` (lista), e o `run()` chama `_handle_existing()` para
   cada uma.
5. **O nobre extra desconta da memória a tropa que mandou**
   (`_discount_sent_troops`, a mesma conta do Hunter depois de despachar).
   `AttackManager.attack()` não mexe em `troopmanager.troops`. Com duas
   conquistas na mesma chamada, a segunda veria livre o nobre que a primeira
   acabou de mandar. O jogo recusaria na confirmação, mas só depois de gastar a
   requisição, e o log diria "falta tropa" numa aldeia que o bot acha que tem.

**O que já estava certo e foi conferido, sem mudança.**
- `_noble_sources()` e `_available_troops()` já descontam `barb_train:*` de
  outro alvo (só a chave `barbarian_conquest` fica de fora).
- `find_target()` exclui `all_reserved()` e os alvos com nobre no ar. Alvo
  manual agendado sai de `manual`, e o próximo da fila é o que entra.
- `_promote_scheduled_trains`, `_cancel_reserved_targets`,
  `_release_orphan_reserves`, `_release_finished_target_claims`,
  `prime_barbarian_sources`, `farm_blocked_targets` e o Hunter (fila única
  desde a §8.36) já iteravam sobre todos os registros.
- O painel `/conquest` lista todos.

**Troca de risco que vale saber antes de subir o teto.** Um trem novo pode
levar os nobres que uma conquista anterior usaria como nobre extra, se o trem
dela pousar curto. Essa conquista então espera um nobre voltar, e o aviso de
Telegram de sempre sai com o prazo. Não reservei nobre para extra: com 8 em
casa, reservar 1 por trem ativo impediria o segundo trem. A frequência medida
é baixa: dos 11 trens do planejador que já pousaram, só a 61947 precisou de
extra, e a 55647 saiu incompleta (3 de 4, o 4º à mão).

**Config.** Chave nova em `config.example.json` (`build.version` 4.7 → 4.8,
**só** no exemplo) e em `helpfile.py`. O merge foi conferido antes contra o
`config.json` vivo: nenhuma seção ou entrada existe só nele, então nada some.
O merge também injeta o `bot.reuse_game_data_max_age`, que faltava ali (60,
igual ao padrão do código). **O merge entrega 1**, ou seja, nada muda até o
usuário subir o valor. Para três trens: `conquest.max_parallel_trains: 3`, e
`reserve_max_slots` já está em 3.

**Testes.**
- `tests/test_conquest_parallel.py` (15 casos) cobre o teto e a leitura
  tolerante, e um trem por ciclo. Cobre também o caso de campo depois de um
  reinício (8 nobres, 4 no trem da 53691, e o trem novo sai com 41123 ×3 e
  74689 ×1), o caso sem sobra que não monta trem, e as guardas da
  reconstrução (só `pending`, arquivo vazio, schedule ausente, trem já
  promovido, reserva de outro dono, aldeia sem `units`).
- `tests/test_conquest_extra_origin.py` ganhou dois casos: duas conquistas com
  um nobre só (manda uma vez, e a segunda avisa), e a âncora acompanhando as
  duas dela.
- Provado por mutação: desligar a reconstrução, voltar a trava antiga, deixar
  `sent` reservar, devolver só a primeira conquista e tirar o desconto. Cada
  uma derruba o teste correspondente.
- Suíte: 82/82.

**⏳ Falta campo:** reiniciar o bot e subir o teto. Os sinais no log são, nesta
ordem:
1. `reserva do trem contra <alvo> na aldeia <id> alinhada ao Hunter`, logo
   depois do reinício, com o trem da 53691 ainda agendado;
2. `trem de 4 nobres agendado` com outra conquista ainda ativa;
3. depois do pouso, a mesma âncora acompanhando duas conquistas no mesmo
   ciclo.

## 8.44 ✅ `P-MISSAO-POPUP` — o popup de missões só quando há recompensa (2026-10-03)

§9 item 20 (Camada 1, grátis): cortar requisição que o próprio bot repete.

**A medição.** Em `cache/cycles/` (50 ciclos, até 02/10), a fase `missoes`
fez **946 GETs** de `new_quests ajax=quest_popup` e **5** `claim_reward`.
`Village.get_quest_rewards()` baixava o popup em toda aldeia, todo ciclo: ~39
por ciclo diurno, ~12 s cada com o sono entre requisições, ou ~8 min de ciclo.
Os 5 resgates (29/09 09:21, 30/09 12:12, 01/10 10:30 e 19:28, 03/10 10:58)
foram todos na primeira aldeia a rodar depois de a recompensa aparecer.

**Dois candidatos medidos e descartados antes deste, no mesmo passo.**
- *A lista de relatórios por aldeia* (`report/all`, ~40 por ciclo). A
  hipótese era que cada aldeia rebaixava relatório que outra já tinha lido.
  Falsa: o `ReportManager` já é **um só** para o ciclo (`twb.py`, `rm`), e a
  conferência por data de criação × modificação em `cache/reports` deu **0
  relatórios reescritos** nos quatro últimos ciclos. A leitura da lista por
  aldeia é o que mantém os relatórios frescos para o farm da aldeia seguinte;
  cortar pioraria decisão.
- *53 `upgrade_flag` numa aldeia só* (52876, ciclo de 01/10). Parecia o laço
  de upgrade antigo. Não era: o inventário dela hoje não tem nenhum nível com
  3 ou mais bandeiras e `upgrade_attempts` está vazio. Foi uma cascata única
  (3 de nível N → 1 de N+1, tipos 3/4/5/6/8 até o 7), custo de uma vez.
  ⚠️ **Revisto em 05/10 (§8.54):** provavelmente era o laço de upgrade sem
  `confirm`, que nunca subia nada. O estado "nenhum nível com 3, tentativas
  vazias" é o que o laço deixa.

**O dado de custo zero, e o que ele significa.** Toda tela HTML do jogo traz
`RewardSystem.setUnlockableRewardsCount(N)` (27 capturas em `cache/`, todas
com 0). O nome sugere "recompensas a desbloquear", e isso seria inútil. O JS
do jogo (`merged/game.47097f.js`) diz outra coisa: a função grava a variável
`m`, a mesma que, depois de um resgate, recebe `unlocked_rewards_count` do
servidor; `m` vira o badge "(N)" da aba de recompensas e o ícone de recursos
no botão de missões. A sonda de 03/10 (`cache/_probe_reward_gate.py`, só
leitura, dois GETs com o wrapper do bot) separou as duas leituras: o popup da
41123 trazia **4** recompensas em `setUnlockableRewards` (futuras, presas a
nível de edifício) e **0** prontas, e o N da tela era **0**. Se N contasse as
futuras, seria 4. O que nenhuma fonte deu ainda é um N > 0 ao lado de uma
recompensa pronta.

**O que mudou.**
- `Extractor.unlocked_rewards_count()` lê N. Ausência devolve `None`, não 0.
- `core/reward_gate.py`. O `WebWrapper` anota N **por aldeia** de toda
  resposta que traz a chamada (`post_process`). Resposta AJAX não traz e não
  apaga o anterior. `Village.get_quest_rewards()` só faz o GET quando não há N
  desta aldeia, quando ele tem mais de 600 s, ou quando N > 0.
- **Rede de proteção:** com N = 0, uma conferência de verdade a cada 3 h,
  para o império inteiro. Se ela achar recompensa pronta, sai um WARNING e o
  gate se desliga até reiniciar. O bot volta então ao GET em toda aldeia. O
  pior caso é uma recompensa resgatada até 3 h mais tarde, e é a conferência
  que vai produzir a evidência que falta.
- Wrapper sem gate (mock, teste antigo) faz o GET como antes.

**Testes.** `tests/test_reward_gate.py`: parser com o recorte verbatim da
praça e ausência ≠ zero, decisão (sem contador, velho, positivo, conferência
e sua janela, outra aldeia), desligamento só no caso que perderia recompensa,
o fio wrapper → gate, e `get_quest_rewards()` sem GET com N = 0. A variante
N > 0 só troca o dígito do recorte, porque não há captura com N > 0. O
diálogo de recompensa do último caso é montado, não capturado, e testa o
gate, não o `get_quest_rewards` do Extractor. Provado por mutação: decisão que
sempre busca, `check` que não desliga, `observe` no-op e parser que devolve 0
derrubam 12, 3, 15 e 9 checagens. Suíte: 83/83.

**⏳ Falta campo.** Reiniciar o bot. No `/cycles`, a fase `missoes` cai de
~39 para 1 ou 2 requisições por ciclo. No log,
`Recompensas: conferencia na aldeia X -- contador 0 e popup sem recompensa
pronta` uma ou duas vezes por ciclo. O sinal que importa é o próximo resgate:
ele tem que sair com o motivo `contador_positivo`, numa aldeia cuja tela
dizia N > 0, e nunca pelo WARNING de gate desligado.

## 8.45 ✅ `P-ZONA-TORRE` — zonas centradas nas torres de vigia (2026-10-03)

**Como era.** `ZoneManager.build()` não calculava centro. Pegava a aldeia de
**menor id** ainda sem zona, abria uma zona com ela e puxava toda aldeia livre a
até `zones.radius` campos **dela**. A fronteira dependia de qual aldeia era mais
antiga, não do mapa. Com `radius: 16` saíam 6 zonas, e duas eram artefato: a
BBM 018 (588|309) fica a 2 campos da BBM 013, que estava na zone_1, mas a 16,1
da semente (BBM 020), e abria a zone_3. A zone_5 era o mesmo caso dentro da
zone_4.

**Como ficou** (decisão do usuário: torre mais próxima + `covered`).
- Centro = toda aldeia com `"profile": "watchtower"` no config, a mesma fonte do
  `Village.get_watchtower_sites()` da Feature 30. Cada aldeia gerenciada entra na
  zona da torre mais próxima. Empate fica com o menor id de torre. O nome da zona
  é `zone_<id da torre>`.
- Uma torre designada com edifício no nível 0 (hoje a BBM 030) **é** centro de
  zona, porque foi escolhida pela posição, mas não cobre nada.
- `covered` = alguma torre alcança a aldeia com o nível de **hoje**, e não
  necessariamente a da própria zona: uma aldeia perto de uma torre de nível 0
  pode ser vista por uma torre alta mais distante. `covered_by` diz qual.
- O nível sai de `cache/managed/<id>.json` → `buidling_levels.watchtower` (o
  erro de grafia é a chave que o cache grava).
- **Alcance por nível:** tabela copiada da própria tela `screen=watchtower`
  (sondada com o wrapper do bot nas aldeias de nível 16 e 10; as duas publicam os
  20 níveis, `cache/_probe_watchtower.py`). Não usa a fórmula da §4.4, que no
  nível 17 dá 9,94 contra os 10 do jogo, e a borda é exatamente onde `covered`
  muda.
- Sem nenhuma torre designada, o agrupamento antigo por `zones.radius` continua
  como fallback, com `covered: false` em tudo. `zones.radius` passou a valer só
  nesse caso (helpfile e painel dizem isso).
- `cache/zones.json` ganhou `mode`, `towers` (id, x, y, nível, alcance por zona) e
  `villages` (torre, distância, `covered`, `covered_by` por aldeia). `zones` e
  `village_zone` mantêm o formato, então a evacuação regional (Feature 12) e o
  filtro de doador de herança não mudaram de código.
- `/zones`: halo do alcance real em volta de cada torre, tracejado do nível 20,
  torre desenhada como quadrado, aldeia sem cobertura esmaecida e com selo, e
  contagem "N/40 cobertas" no topo.

**Resultado com o cache de 03/10:** 3 zonas — BBM 002 com 24 aldeias, BBM 023
com 3 e BBM 030 com 13. **14 das 40 cobertas** (13 pela 002 com nível 16 e
alcance de 8,7, mais a própria 023). Toda aldeia fica a até 13,5 campos da sua
torre, então com as três no nível 20 a cobertura seria total.

⚠️ **Efeito colateral na evacuação regional.** `evacuate_on_zone_attack` está
`true` nas 40 aldeias, com `zone_attack_threshold: 1` e janela de 4 h. A maior
zona passou de 19 para 24 aldeias, e BBM 011/012/014/018 entraram nela. Um
ataque dentro da janela em qualquer uma das 24 evacua a tropa frágil das outras
23. Antes já era 1 contra 18; ficou um pouco mais sensível, não mudou de
natureza. Fronteiras apertadas: a BBM 027 fica a 10,4 da torre 030 e a 10,8 da
002, e a BBM 025 a 9,2 da 002 e a 10,0 da 030. Uma torre nova pode mudar as duas
de zona.

**Testes.** `tests/test_zone_watchtower.py` (29 checagens): tabela de alcance
contra o recorte verbatim de `screen=watchtower` (com guarda provada: trocar o
nível 17 pelo valor da fórmula derruba o teste com `{17: (9.9, 10.0)}`), torre
mais próxima, desempate, cobertura por torre que não é a mais próxima, torre de
nível 0, torre sem cache, fallback por raio, `tower_levels()` e as 40 aldeias
reais (24/3/13, 14 cobertas). Suíte inteira verde.

**⏳ Falta campo.** O processo do bot carregou o `zone_manager` antigo. Até
reiniciar, cada ciclo regrava `cache/zones.json` no formato velho (6 zonas por
raio), e o painel volta ao desenho antigo sozinho, porque lê `mode` com default
`radius`. Depois de reiniciar, o log mostra
`ZoneManager (watchtower): 40 village(s) → 3 zone(s), 14 covered`.

## 8.46 ✅ `P-RELATORIO-LISTA` — relatório de comércio deixa de ser aberto (2026-10-04)

§9 item 20 (Camada 1, grátis): cortar requisição que o próprio bot repete. O
maior candidato que sobrava depois das releituras da visão geral (§9 item 20a)
e do popup de missões (§8.44) era `report/all/view`.

**A medição.** `cache/cycles/`: os ciclos diurnos de 01/10 a 03/10 abriram
**89, 92, 102, 125 e 139** páginas de relatório cada, a ~15,3 s por requisição
(sono + rede). `ReportManager.read()` abre **todo** relatório novo da lista, e
para tudo que não é `ReportAttack` grava só o tipo, com `origin`, `dest` e
`extra` vazios. Nenhum consumidor do bot lê esse tipo: `safe_to_engage`,
`farm_manager`, o índice de exploração do PvP e a lealdade do nobre olham só
`attack`/`scout`; o painel só mostra o rótulo. Dos 780 relatórios criados em
`cache/reports` de 01/10 a 03/10, **534 eram `ReportTrade` e 26
`ReportAccept` (72%)**.
Uma armadilha de medição no caminho: contei primeiro por mtime ("793 em 7
dias") e o número não fechava com 100+ aberturas por ciclo. O
`manager.farm_manager` poda `cache/reports` em `bot.max_cached_reports`
(1.000) por ctime, então o diretório guarda só ~4 dias. O ritmo real é de 240
a 300 relatórios por dia, e nenhum é reaberto (0 arquivos com mtime > ctime).

**A captura** (`cache/_probe_report_list.py`, um GET com o wrapper do bot,
`cache/debug/report_list_all.html`). A linha da lista já diz o que é:
relatório de combate traz os ícones de comando (`graphic/command/attack_small`,
`spy`); relatório que não é de combate traz uma miniatura
`graphic/icons/report_*.webp` com `class="report-thumb"`. Cruzado contra o tipo
gravado em `cache/reports` para as 50 linhas da página: `report_trade` → 27
`ReportTrade` e **1 `ReportAccept`**. Ou seja, a miniatura não é o tipo. O
rótulo da linha distinguiria ("forneceu" × "aceitou a sua oferta"), mas é texto
renomeável (`quickedit`), então não serve de chave.

**Achado de brinde: a lista tem 50 por página, e o código assumia 12.**
`read()` paginava com `new == 12` e `from=page*12`. Com 50, uma página inteira
nova (50 novos) **nunca** paginava e o 51º em diante não era lido. E 12 novos
exatos pediam `from=12`, uma página sobreposta.

**O que mudou.**
- `Extractor.report_list_icons()` devolve, por id, a miniatura e os ícones de
  comando da linha. Linha que o regex não reconhece não entra no dict.
- `ReportManager.LIST_ONLY_THUMBS = {"report_trade": "trade"}`. Linha com essa
  miniatura **e sem ícone de comando** é gravada sem GET, com
  `type: "trade"` e `extra: {"source": "report_list", "list_icon":
  "report_trade"}`. O tipo é `trade`, e não `ReportTrade`, porque a lista não
  separa as duas coisas e gravar o nome do jogo seria inventar a distinção.
  Qualquer outra linha (miniatura desconhecida, sem ícone, ou combinação nunca
  vista) é aberta como antes.
- Relatório não-ataque que **é** aberto passa a guardar `list_icon` no
  `extra`. É o dado para a tabela crescer a partir de medição: `ReportSupport`
  (53 em 3 dias), `ReportAutoMintingSessionEnd` (34) e `ReportFoundMaterial`
  (24) são os próximos candidatos, e nenhum tem a miniatura capturada ainda.
- Paginação: página seguinte quando a página **inteira** era nova, a partir do
  tamanho real dela (`offset + len(ids)`), com teto `MAX_PAGES = 4` (200
  relatórios). Sem teto, um cache vazio paginaria o histórico inteiro (18
  páginas no recorte) abrindo cada ataque.
- `/reports` rotula o tipo novo como "Comércio (pela lista)". Os
  `ReportTrade`/`ReportAccept` antigos continuam no cache com o nome antigo até
  a poda levar.

**Ganho esperado:** ~187 GETs por dia (560 em 3 dias), ou ~48 min de ciclo por
dia a 15,3 s cada; nos ciclos diurnos, cerca de 60 a 100 requisições a menos.

**Testes.** `tests/test_report_list.py`, com fixture verbatim
(`tests/fixtures/report_list_br143.html`, 5 das 50 linhas, nomes de terceiros
anonimizados): o parser nas cinco formas de linha (exploração, ataque,
comércio, oferta aceita, fila do gerente sem ícone), o `read()` abrindo só
ataque, exploração e o desconhecido, o registro gravado pela lista, a
combinação miniatura + ícone de comando sendo aberta, a paginação a partir de
5 numa página de 5, o teto de páginas e a lista `None`. Provado por mutação:
tabela vazia, paginação antiga, ignorar os ícones de comando e um regex de
miniatura quebrado derrubam cada um o teste correspondente. Suíte: 85/85.

**⏳ Falta campo.** Reiniciar o bot. No log, `Reports: N relatorio(s) de
comercio gravado(s) pela lista, sem abrir`. No `/cycles`, `report/all/view`
cai de ~90–140 para ~30–45 por ciclo diurno. Conferir também que a fase
`farm` não muda: os relatórios de ataque continuam sendo abertos.

✅ **Visto em campo em 2026-10-04 às 01:28:09**, no primeiro ciclo depois do
reinício: `Reports: 4 relatorio(s) de comercio gravado(s) pela lista, sem
abrir` na BBM 015, e a única página aberta no ciclo foi uma exploração
(`report/all/view (1)`). Os quatro arquivos têm `type: "trade"` e o `extra`
previsto. Falta o ciclo diurno para o número do `/cycles`.

## 8.47 ✅ `P-RELATORIO-UNICO` — um leitor de relatórios por processo (2026-10-04)

**O que o log de 01:28 mostrou.** Três `First run, re-reading cache entries`
em 42 s, um para cada aldeia de origem preparada pela conquista (BBM 015, 001
e 010). Cada um relia os 1.000 arquivos de `cache/reports` e baixava a lista
de relatórios de novo.

**Por quê.** A lista de relatórios é da conta, e o laço de aldeias já usava um
`ReportManager` só (`rm`, em `twb.py`). Só que esse objeto era amarrado
**dentro** do laço, na vez de cada aldeia. Desde a §8.15 o prime da conquista
roda antes do laço, e `Village.update_pre_run()` criava um leitor por aldeia
primada. Cada um tinha o seu `last_reports`, ou seja, três visões do mesmo
cache em memória.

**O que mudou.**
- `TWB._new_village()` cria um `ReportManager` por instância de `TWB` e o
  injeta em toda aldeia na criação. O `rm` do laço saiu. Um retry de `main()`
  cria um `TWB` novo e, com ele, um leitor novo, que é o comportamento de
  antes.
- `ReportManager.read(max_age=...)`: com valor, não relê a lista se a
  primeira página foi lida com sucesso há menos que isso. Lista que falhou
  não conta como leitura. O prime passa `Village.PRIME_REPORT_MAX_AGE` (300
  s). O laço de aldeias e a lealdade do nobre (`_get_real_loyalty`) continuam
  lendo sempre: no laço, a leitura por aldeia é o que mantém o farm da aldeia
  seguinte com relatório fresco (§8.44). Na lealdade, o pouso pode ter
  acontecido segundos antes.

**Ganho.** Uma leitura de 1.000 arquivos por processo em vez de uma por aldeia
primada. E N−1 GETs da lista por ciclo, onde N é o número de aldeias primadas
(3 na noite de 04/10; a PvP prima mais).

**Testes.** `tests/test_report_list.py` ganhou: mesmo objeto nas aldeias de
um `TWB`, objeto próprio num `TWB` novo, `max_age` pulando só quando pedido e
só dentro da janela, e lista `None` sem marcar leitura. Provado por mutação:
sem a injeção, sem o pulo e marcando a leitura antes do GET. Suíte: 85/85.

**⏳ Falta campo.** Reiniciar o bot. No log, uma linha só de `First run,
re-reading cache entries` por processo. No prime, a partir da segunda aldeia
de origem, nenhum GET de `screen=report&mode=all` (a linha
`Reports: lista lida ha Ns` é DEBUG).

---

## 8.48 ✅ `P-NOBRE-LONGE` — origem do trem pela chegada, e aldeia longe dos alvos só cunha (2026-10-04)

**A pergunta do usuário.** "Algumas aldeias ficam fora do alcance de qualquer
alvo de conquista; elas deveriam parar de produzir nobre?"

**O que a medição mostrou, antes de mexer.** Ninguém está fora do alcance.
`conquest.max_radius` é 70, o próprio `<snob><max_dist>` do br143. Pelo
`map/village.txt`, a pior aldeia (BBM 019) tem 172 bárbaras elegíveis a 70
campos. Uma regra "pare quando não houver alvo no alcance" seria código que
nunca dispara (15º padrão). O problema real é **tempo de viagem**. O nobre
anda a 35 min/campo, e a área de interesse fica no norte. Das aldeias com
academia, a BBM 029 está a 18 campos do 3º alvo elegível (~11 h) e a BBM 019
a 42 (~25 h). Pior: **o norte não tem academia** (BBM 030 a 040 com academia
0), então os produtores reais formam um contínuo de 11 a 25 h, sem degrau.

**Parte 1 — o planejador escolhe origens pela chegada.**
`_noble_sources()` ordena por quantidade de nobres livres, e `_build_plan()`
pegava as origens nessa ordem. Como a chegada comum é a da origem mais lenta,
o nobre parado na BBM 015 (o único fora da BBM 001/010 em 04/10) entraria
num trem só por estar ali, atrasando os quatro. Agora
`BarbarianTrainPlanner._order_by_arrival()` ordena por distância até o alvo
(todos andam na velocidade do nobre, então distância = chegada). O empate fica
com quem tem mais nobres, e origem sem coordenada vai para o **fim**: "não
sei onde fica" não ganha de "sei que está perto". Sem coordenada do alvo vale
a ordem antiga. A âncora que **pontua** os alvos continua sendo a aldeia com
mais nobres, e agora ela pode não entrar no trem. Não é defeito: o alvo
continua dentro da área de interesse, e o trem é o mais rápido para ele.

**Parte 2 — `NobleRecruitGate` (`game/noble_recruit_gate.py`).** Uma vez por
ciclo, em `twb.py`, depois do planejador bárbaro (o alvo recém-agendado já
sai da conta) e antes do laço de aldeias:
- Candidatas: aldeias com `snobs > 0`, academia > 0 (do builder, ou de
  `cache/managed` no primeiro ciclo) e `noble_ignore_distance` desligado.
- Métrica: distância até o **3º** alvo elegível mais próximo. Os filtros são
  os de `find_target()` que não dependem de quem manda: dono, faixa de pontos,
  `excluded_targets`, reserva de outro jogador no quadro e conquista ativa.
  Vale a mesma partição da área de interesse (dentro primeiro). O 3º, e não o
  1º, porque a BBM 024 tinha **uma** bárbara a 10 campos e nenhuma outra a
  menos de 35: pelo 1º ela pareceria da linha de frente até o primeiro trem.
- Régua: as `conquest.max_noble_recruiters` mais perto recrutam (0 =
  desligado, o default do template). As outras passam a se comportar como
  `snobs: 0` + `mint_coins: true`. A moeda é da conta e aumenta quantos nobres
  as aldeias perto podem recrutar. É relativa, e não um teto em horas, pelo
  contínuo descrito acima: um teto fixo ou não cortava ninguém ou zerava a
  produção, e envelheceria sozinho (14º padrão). Quando uma aldeia do norte
  ganhar academia, ela entra no ranking e empurra a mais distante para fora.
- Ao passar a cunhar, a aldeia solta `resman.requested["snob"]` e
  `is_incomplete`. O pedido sobrevive entre ciclos e vai para
  `required_resources` em `cache/managed`, então sem isso o compartilhamento
  seguiria mandando recurso para um nobre que não vai ser feito.
- Falha aberta: sem lista do mundo, sem alvo, aldeia sem coordenada ou erro
  no portão, todo mundo recruta como a config manda.

**Em campo.** `max_noble_recruiters: 8` no `config.json`. Smoke offline com
a config, a lista do mundo e `cache/managed` reais: recrutam BBM 029, 022, 012,
011, 003, 001, 007 e 010 (12,5 a 18 h). As 15 restantes só cunham (19 a
24,6 h). Nobre já recrutado longe continua existindo e entra em trem quando
estiver entre os mais perto do alvo. Para PvP no sul, ligar
`noble_ignore_distance` na aldeia.

**Testes.** `tests/test_noble_recruit_gate.py` (20), com as coordenadas reais
de 04/10: as 23 aldeias com academia e as 53 bárbaras elegíveis da área. Em
`tests/test_conquest_planner.py`, mais 3 para a ordem por chegada. Provado
por mutação: sem a ordem, sem soltar o pedido "snob", sem o filtro de
academia, com o 1º alvo no lugar do 3º e sem o portão na `Village`. O dublê
de `tests/test_snob_mint_only.py` ganhou o método novo. Suíte: 86/86.

**⏳ Falta campo.** Reiniciar o bot. O bump 4.8 → 4.9 dispara o merge, que
foi simulado antes e não descarta nada. No log: uma linha `Conquest: recrutam
nobre as 8 aldeias…` por ciclo, e `Nobre: so cunha moeda` uma vez por aldeia
cortada. Nas cortadas, `required_resources` em `cache/managed` sem a chave
`snob` a partir do ciclo seguinte.

✅ **Visto em campo em 2026-10-04, sessão das 10:29.** Merge 4.8 → 4.9 sem
perda de chave; `Conquest: recrutam nobre as 8 aldeias mais perto do 3o alvo`
uma vez; `Nobre: so cunha moeda ... posicao 9 de 23` na BBM 001. O trem
contra a 61990 saiu das duas origens mais perto (41123 ×3, 74689 ×1, ~28
campos), e o Hunter disparou a 74689 no segundo marcado.

## 8.49 ✅ `P-RELATORIO-OURO` — fim de cunhagem automática gravado pela lista (2026-10-04)

**O que o log mostrou.** A primeira leitura de relatórios da sessão das 10:29
levou 4 min (10:29:54 → 10:33:56), e a maior parte foram ~33
`ReportAutoMintingSessionEnd` abertos um a um, a ~5 s cada. Nenhum consumidor
lê esse tipo. O §8.46 já previa isso: relatório não-ataque aberto guarda a
miniatura em `extra.list_icon`, para a tabela crescer por medição.

**Medição.** No `cache/reports`, os 26 relatórios abertos depois do §8.46 com
`list_icon: report_gold` são todos `ReportAutoMintingSessionEnd`, e nenhum
outro tipo veio com essa miniatura (`ReportAMStockpileDistribution`,
`ReportRelic*`, `ReportSupportBack` e `ReportSupportAttackMerged` vieram sem
miniatura). Um GET da página `from=50` com a sessão do bot confirmou do outro
lado: as 26 linhas `report_gold` da página casam, por id, com 26
`ReportAutoMintingSessionEnd` do cache, todas sem ícone de comando.

**O que mudou.** `LIST_ONLY_THUMBS` ganhou `"report_gold": "gold"`. O tipo
gravado é o nome da miniatura, não o do jogo, pelo mesmo motivo do `trade`:
26 de 26 não prova que o jogo não use o ícone em outro tipo. O `/reports`
rotula "Cunhagem automática (pela lista)". A linha de log passou a ser
`Reports: N relatorio(s) gravado(s) pela lista, sem abrir (gold X, trade Y)`.

**Testes.** `tests/test_report_list.py` com uma linha verbatim nova
(`tests/fixtures/report_list_gold_br143.html`): a miniatura lida, o relatório
não aberto e gravado como `gold`. Provado por mutação: sem a entrada na
tabela, o teste cai. Suíte: 86/86.

**Ganho esperado.** ~30 GETs (~2,5 min) na primeira leitura de cada processo,
e um GET por sessão de cunhagem concluída depois disso (8 h por aldeia).

**Próximo candidato:** `report_notes_sharing` (`ReportVillageNotesSharing`),
com 1 amostra só. `ReportSupport` (53 em 3 dias) ainda não foi aberto desde o
§8.46, então a miniatura dele segue desconhecida.

**⏳ Falta campo.** Reiniciar o bot. No log, `gold N` dentro da linha
`gravado(s) pela lista`, e nenhum `Processed ReportAutoMintingSessionEnd`.


## 8.50 ✅ `P-FERREIRO-GATE` — a tela do ferreiro só é lida quando há pesquisa por fazer (2026-10-04)

§9 item 20 (Camada 1, grátis). Depois do §8.46/§8.49, o maior GET repetido por
aldeia que ninguém tinha olhado era `smith`.

**A medição.** O ciclo diurno de 03/10 (15:23, `cache/cycles/1791051798.json`)
leu o ferreiro **44 vezes** na fase `recrutamento`, praticamente uma por
aldeia. `TroopManager.attempt_upgrade()` fazia o GET em toda aldeia que tivesse
qualquer `upgrades` no estágio do template, todo ciclo. Do outro lado,
`cache/logs/twb_*.log` tem **56** `TWB_UPGRADE` em toda a história, cerca de
duas pesquisas por dia no império inteiro, quase todas em aldeia recém-conquistada.

**Por que um gate por nível não bastaria.** Os templates pedem `light: 3`,
`axe: 3`, `spear: 3` e outros níveis acima de 1, e o br143 tem pesquisa
simplificada (`<tech>2</tech>`), de nível único. "Nível ≥ pedido" nunca
fecharia e o gate não pularia nada (15º padrão ao contrário). O dado que
resolve está na própria resposta: o `BuildingSmith.techs` marca com
`"error_level": true` a unidade que já está no nível máximo. Isso vale em
qualquer mundo, e o bot não precisa deduzir o máximo pelo tipo de pesquisa.
O código antigo já tratava esses pedidos como resolvidos, só que por acaso:
`can_research` vem ausente na unidade pesquisada.

**O que mudou** (`game/troopmanager.py`):
- `TroopManager.smith_settled_levels(smith_data, wanted)` devolve, das
  unidades pedidas, as resolvidas: nível ≥ pedido, ou `error_level: true`
  (entra como `inf`). Unidade pesquisável, sem edifício (`error_buildings`),
  com falta de recurso ou ausente da tela fica de fora.
- `smith_read_needed()`: sem GET quando **todo** pedido atual já foi visto
  resolvido numa leitura com menos de `SMITH_RECHECK_SECONDS` (24 h). Pedido
  novo (estágio novo do template) reabre a leitura na hora. Com qualquer
  pendência, a aldeia continua lendo todo ciclo, como antes, porque o builder
  pode ter subido o edifício que faltava.
- Leitura falha não arma o gate. O estado mora na instância (1º padrão) e só
  em memória, então um reinício custa um GET por aldeia.
- Uma linha INFO por aldeia, quando ela fecha: `Smith: todas as pesquisas
  pedidas resolvidas (...)`. A pulada é DEBUG.

**Smoke contra o servidor** (`cache/_probe_smith_gate.py`, um GET pelo
`get_action` do wrapper): a BBM 001 veio hoje com as 8 unidades em nível 1 e
`error_level: true`, ou seja, o markup de 20/08 continua valendo e essa aldeia
fecha o gate na primeira leitura.

**Ganho esperado:** perto de 40 GETs por ciclo diurno nas aldeias sem
pendência (~10 min a 15 s cada), e um GET por aldeia por dia depois disso. A
fração exata depende de quantas aldeias têm pedido travado por edifício, o que
não dá para medir sem ler o ferreiro de todas. O `/cycles` vai dizer.

**Testes.** `tests/test_smith_gate.py`, fixture verbatim
(`tests/fixtures/smith_techs_br143.html`, o `<script>` de
`cache/_smith_br143.html`): o parser com os campos que o gate usa, as
resolvidas (incluindo `light: 3` num mundo de nível único), quando ler, o
`attempt_upgrade()` pulando, relendo depois de 24 h, relendo e tentando
pesquisar com pedido novo, leitura falha e estado por aldeia. Provado por
mutação: sem `error_level`, gate desligado, sem reset na pendência, sem
reconferência e unidade nova ignorada. Cada uma derruba o teste. Suíte: 87/87.

**⏳ Falta campo.** Reiniciar o bot. No log, uma linha `Smith: todas as
pesquisas pedidas resolvidas` por aldeia sem pendência. No `/cycles`,
`recrutamento smith` cai de ~40 para o número de aldeias com pendência.

## 8.51 ✅ `P-COLETA-UNIDADES` — a coleta deixa de pedir `place/units` (2026-10-04)

§9 item 20 (Camada 1, grátis). Escolhido ao reler os dois documentos: o resto
da Camada 1 é configuração do usuário (21), já está feito (22 à mão, 23 pela
§8.15) ou pede envio real autorizado (24), e os itens abertos da §8.32
(A26-09, A26-11) pedem sondagem de erro ou estão atrás de gate desligado.

**A medição.** No último ciclo diurno gravado (03/10, `1791069538.json`, 21
aldeias, 593 requisições), `place/units` aparece **duas vezes por aldeia**:
20 na fase `recrutamento` (`update_totals`) e 20 na `coleta`. A segunda é
`TroopManager.gather()`, que baixa `screen=place&mode=scavenge` e, logo em
seguida, `place&mode=units` só para saber quem está em casa. A tela de coleta
já traz isso no `var village`: `unit_counts_home`. A do recrutamento fica,
porque dela também saem `units_owned_total` (apoio enviado, §8.26).

**A sondagem, montada para poder falhar.** Numa aldeia sem apoio recebido, a
tropa "em casa" e a tropa "na aldeia" coincidem, e o teste não distinguiria
nada. Um GET de `overview_villages&mode=units` achou a BBM 035 (52876) com
apoio da BBM 010 estacionado. As duas telas dela, lidas com 40 s de
intervalo pelo `WebWrapper` do bot (`cache/_probe_scavenge_units.py`, 3 GETs
no total, sem `priority_mode`), deram:
- `unit_counts_home`: lança 75, espada 244, machado 0, espião 28, leve 113;
- `units_home`, linha "Desta aldeia": 75 / 244 / 0 / 28 / 113;
- `units_home`, linha "Total": 87 / 244 / **743** / 28 / 484.

Ou seja, `unit_counts_home` é a tropa **própria** em casa, sem o apoio
recebido, que é exatamente o que `Extractor.units_in_village()` lia.

**O que mudou.** `TroopManager.units_home_from_scavenge(village_data)` converte
o campo para o formato de antes (str, só > 0). Devolve `None` quando o campo
falta ou tem valor ilegível, e aí o GET antigo volta. Devolve `{}` quando o
jogo diz que não há ninguém em casa: as duas coisas não se confundem (6º
padrão). Nada mais muda. `_deduct_gathered` continua descontando o envio de
`self.troops`, que vai para o `cache/managed`.

**Efeito indireto conferido.** Antes, a última tela HTML antes do mercado era
`place/units`, e agora é a de coleta. O reaproveitamento de `game_data` do
mercado (§9 item 20a, ≤ 60 s) continua valendo: é HTML de jogo com
`updateGameData`, e um `send_squads` (JSON) segue invalidando o guardado.

**Testes.** `tests/test_gather_units_home.py`, com fixture verbatim
(`tests/fixtures/scavenge_units_home_br143.html`: a linha `var village` e a
tabela `units_home` da BBM 035). Cobre a equivalência no caso com apoio, os
`None` e o `{}`, a coleta sem GET de `place/units` com o esquadrão saindo com
a tropa da tela, e a volta ao GET sem o campo. Provado por mutação: ignorar o
campo e devolver sempre `None` derrubam o teste. Suíte: 88/88.

**Ganho esperado.** Um GET por aldeia que coleta, por ciclo: 20 a 32 por
ciclo diurno, ~5 a 8 min a ~15 s cada.

**⏳ Falta campo.** Reiniciar o bot. No `/cycles`, `coleta place/units` cai
para zero (ou para o número de aldeias em que a tela veio sem o campo).

## 8.52 ✅ `P-NOBRE-TREINO` — o bot mandava formar nobre sem conferir o custo (2026-10-04)

Achado ao procurar o próximo GET repetido do §9 item 20, e é pior que um GET
repetido.

**A medição.** Na fase `nobre` dos ciclos gravados, `snob action=train`
aparece em 17, 17, 21 e 16 de 17 a 23 leituras da academia, em ciclos com
zero moeda cunhada. Na sessão de 04/10 (bot das 10:29), o mesmo GET saiu da
BBM 003, 007, 011 e 012, e as quatro seguem com `snob: 0` no
`cache/managed`. A BBM 007 tinha 109.357 / 28.071 / 6.641 às 11:28.

**A captura** (`cache/_probe_snob.py`, um GET pelo `get_action` do wrapper,
sem POST e sem `priority_mode`; BBM 007, às 13:50). A academia diz, ao mesmo
tempo:
- "Ainda podem ser produzidos: **1**" (limite 49, 8 existentes, 40 aldeias);
- `BuildingSnob.Modes.train.next_snob = {"wood":40000,"stone":50000,"iron":50000}`;
- `<td id="train_snob_cell" class="inactive">Recursos disponíveis amanhã às 03:04</td>`,
  com a aldeia em 125.501 / 58.805 / 11.546.

**O defeito.** `SnobManager.attempt_recruit` só lia a primeira linha. Ela é o
limite da **conta** (moedas e aldeias), não diz se a aldeia paga o nobre.
Sendo > 0, o código pulava `need_reserve()` e mandava `action=train` às
cegas, sem olhar a resposta, e devolvia `True`. Três efeitos, desde o bot
base:
1. Um GET recusado por aldeia recrutadora, todo ciclo (hoje até 8, com o
   `NobleRecruitGate`; antes dele, até 21).
2. **A aldeia nunca pedia o recurso do nobre.** Os pedidos `snob` só nasciam
   no caminho da moeda (vaga = 0). Com vaga aberta, nem o compartilhamento nem
   o mercado sabiam que ela juntava para um nobre, e a vaga ficava esperando o
   acaso de uma aldeia acumular 40k/50k/50k sozinha.
3. `is_incomplete` ficava `False`, então `prioritize_snob` (hoje desligado em
   todas) também não funcionaria nesse caso.

**O que mudou** (`game/snobber.py`):
- `SnobManager.next_snob_cost(text)` lê o custo do script da academia
  (`None` se faltar ou não parsear). Com custo lido e recurso curto, não há
  GET. O que falta vai para `requested["snob"]` (fonte de déficit, igual à
  moeda; `SHORTFALL_SOURCES` do compartilhamento) e `is_incomplete` fica
  `True`. O pedido antigo é limpo antes, porque moeda e nobre gravam na mesma
  chave e `request()` só sobrescreve recurso a recurso: sem isso, a madeira
  pedida para uma moeda ficaria pendurada no pedido do nobre.
- `SnobManager.train_blocked_reason(text)`: com a célula "Formar" inativa
  (população, por exemplo), não há GET e o motivo do jogo vai para o log. Não
  é falta de recurso, então não trava o recrutamento.
- Falha aberta: sem o script de custo e sem a forma inativa da célula, o
  caminho antigo segue igual.
- Log: `Nobre: sem recurso para formar (custo …, tem …), pedido registrado`,
  e `Nobre: academia nao deixa formar agora: <texto do jogo>`.

**Efeito de comportamento, de propósito.** As até 8 aldeias recrutadoras
passam a pedir o recurso do nobre quando a conta tem vaga. O compartilhamento
(regra de necessidade) e o mercado passam a abastecê-las. Nada se perde
quando uma delas ocupa a vaga: as outras voltam a ver vaga 0 e o pedido vira
pedido de moeda, que é da conta inteira.

**Não verificado.** A forma **ativa** da célula, e se o
`GET …&action=train&h=` realmente forma o nobre quando o recurso basta. Nada
nos dados de hoje mostra um nobre formado por esse GET, e o usuário recruta à
mão na mesma conta (9º padrão). O teste do caso ativo usa uma célula suposta.
Como o código só reconhece a forma inativa, ele não depende disso. A primeira
aldeia que juntar 40k/50k/50k com vaga aberta responde: `snob` subindo no
`cache/managed` sem ação manual.

**Testes.** `tests/test_snob_train_gate.py` (9), com fixture verbatim
(`tests/fixtures/snob_train_short_br143.html`, o recorte da tabela de
formação até o `storage_item`, sem o formulário que carrega o `h`). Provado
por mutação: sem o gate de custo, sem limpar o pedido antigo e sem a célula
inativa, cada um derruba o teste. Suíte: 89/89.

**⏳ Falta campo.** Reiniciar o bot. No `/cycles`, `nobre snob action=train`
cai para o número de nobres de fato formados. No log, `Nobre: sem recurso
para formar` nas recrutadoras, e `required_resources.snob` no
`cache/managed` delas.

## 8.53 `P-MAPA-PREMIUM` — o que é pago, medido nas duas situações (2026-10-04)

**Pedido do usuário:** mapear o jogo como está hoje (premium + gerente de
conta + assistente de saque), usar o bot uma semana sem nada pago depois que
vencerem, e repetir o mapeamento. A diferença diz, com certeza, o que é pago.
É a base da camada 2 da §9 ("ativável por detecção") e fecha os "premium? (a
confirmar)" da §8.25.

**Prazo, lido do jogo** (`premium&mode=feature_log`, 2026-10-04 20:58): os
três foram comprados em 08/09 01:16 por 30 dias e **vencem em 08/10 01:16**.
Antes disso a conta já tinha usado pacotes de 3 e 7 dias em agosto.

**Por que não basta a KB nem a §8.25.** A KB (artigo 1296) só lista as
vantagens por alto ("fila de construção maior", "várias visões gerais",
"mapa até 30x30"…) e manda ver a lista completa em *Premium > Vantagens*, no
jogo. A §8.25 foi feita **só com premium**, então não tinha como ver o que
some. O mapeamento compara a conta consigo mesma.

**Instrumento: `tools/feature_map.py`.** Mesma lista fixa de telas, mesmo
cliente (o `WebWrapper` do bot, 7º padrão), nas duas situações:
- 75 telas fixas (72 na captura 1, mais as 3 de "Vantagens" acrescentadas
  depois dela), nesta ordem: as que o bot consome (as que podem quebrar em
  08/10), as "a confirmar" da §8.25, gerente e assistente (`am_*`), premium
  (`premium`, `use`, `feature_log`) e o resto da interface. Aldeia de
  referência BBM 003 (44683, 16 de 17 edifícios); a torre é lida na BBM 002.
- Segunda passada (`--discover`, até 40): as telas que as páginas lidas
  linkam e que não estão na lista. Nunca compra, transferência, conta ou
  correio.
- Para cada tela, um **resumo estrutural**: links e endpoints de ação
  normalizados (sem id, página ou `h`), formulários, nomes de campo, módulos
  JS iniciados, tabelas, títulos, caixas de aviso, links de compra e classes
  `premium`/`locked`/`disabled`. Nada de número de jogo, para dois dias
  diferentes darem o mesmo resumo. HTML bruto em
  `cache/feature_map/<rótulo>_<data>/pages/` (fora do git: tem token de sessão
  e nome de jogador).
- Segurança imposta no código: só GET, URL com `action`, `ajaxaction` ou `h`
  é recusada antes de pedir, nenhum `group=` (não mexe no grupo que o jogador
  deixou), uma requisição por minuto, e **parada** no primeiro
  `data-bot-protect` com valor (o `pending` vem antes do captcha). Recusa
  rodar dentro de `active_hours` sem `--force`. Testes em
  `tests/test_feature_map.py` (14), provados por mutação: sem o `h` na lista
  proibida, sem negar a transferência na descoberta e parando só no
  `forced`, cada um derruba um teste.

**Calendário:**

| # | Quando | Situação | Para quê |
|---|---|---|---|
| 1 | 04/10, 23:05 | premium | a foto de hoje |
| 2 | 06/10 à noite (antes de 08/10 01:16) | premium | **piso de ruído**: o que muda entre dois dias sem mudar a conta (ordens do gerente, comandos no ar, relatórios novos) |
| 3 | a partir da noite de 08/10 | sem nada pago | a foto sem premium |
| 4 | fim da semana sem premium | sem nada pago | ruído do lado grátis, e o bot já adaptado |

`compare <1> <3> --noise <1> <2>` desconta do resultado o que mudou entre 1 e
2. Sem a captura 2, uma diferença premium × grátis poderia ser só o dia
seguinte (11º padrão: saber se o conjunto é um conjunto).

**O que o bot consome e precisa ser vigiado no primeiro ciclo de 08/10:**
- `overview_villages&mode=prod` (lista de aldeias, pontos): o código diz
  que "conta sem premium só tem Produção" e trata a coluna a mais do premium
  (`pages/overview.py:256`, Feature 22). É afirmação, não medição.
- `overview_villages&mode=commands` (`InFlightTracker`, card "Em voo"):
  candidata forte a premium. Se for, o card some, mas a conquista não depende
  dele (§8.41).
- Fila de construção: a KB diz que o premium aumenta. O `BuildingManager`
  precisa saber o teto novo, senão pede a terceira ordem e leva recusa.
- Gerente de construção e de tropa ativos em 27 aldeias (§8.25, achado 2) e
  `am_warehouse` balanceando recurso: tudo isso **para** em 08/10. O
  `resource_sharing` do bot passa a ser o único transporte.

### Captura 1 (premium) — 04/10 23:05 → 05/10 00:57

`cache/feature_map/premium_20261004_2305/`: 72 telas fixas + 40 da descoberta
+ 2 de "Vantagens" lidas às 00:56 e juntadas (a descoberta agrupa por
tela/modo e só tinha pego a do gerente) = **114 telas, todas 200, nenhum
`data-bot-protect`**, uma por minuto com o bot no ciclo noturno. Uma tela da
descoberta (`extforum`) redirecionava para o fórum externo; saiu da descoberta
para as próximas capturas.

**O que o jogo diz que é pago — lista oficial, dentro do jogo**
(`premium&mode=help&feature=…`, que a KB manda consultar):

| Produto | Vantagens declaradas |
|---|---|
| Conta premium | **+3 ordens na fila de construção**; melhorias no mapa (para onde vão as tropas, pop-up estendido, mapa maior, cores); visão geral da aldeia melhorada (produção de todos os edifícios e ataques na tela da aldeia); tela de informação da aldeia melhorada (ataques, últimos relatórios, notas); **funções de múltiplas aldeias: visões gerais, alternar aldeias, recrutamento em massa** "e muito mais"; brasão, barra de acesso rápido, sem anúncios, pastas de relatório/mensagem, renomear comandos, catálogo de endereços |
| Gerente de conta | gerente de construção, de tropa e de pesquisa; distribuidor de recursos (`am_warehouse`); gerente de entregas (`am_market`); e-mail quando sob ataque (`am_notify`); **inclui o assistente de saque** |
| Assistente de saque | saque em aldeias bárbaras (`am_farm`) |

"E muito mais" e "funções de múltiplas aldeias" não dizem quais telas: é a
captura 3 que fecha isso.

**O jogo esconde parte do premium no cliente.** O `<body>` da conta paga tem
a classe `has-pa`, e o CSS do jogo usa isso para esconder o aviso
`premium_account_hint` e liberar o bloco `premium-required`. O aviso vem no
HTML **mesmo com premium ativo**, e na captura 1 só existe em um lugar,
verbatim: *"Evolua para um Conta premium para poder enviar comandos de coleta
de várias aldeias ao mesmo tempo."* (`place&mode=scavenge_mass`). Ou seja:
**ver a coleta em massa não basta; enviar de várias aldeias num comando é
premium.** Isso responde metade do §9 item 24, e pela leitura do jogo, não por
teste. O resumo de tela passou a registrar `body_classes`, `premium_hints` e
`data_features` (com teste, `tests/test_feature_map.py`, agora com 15), e o
comando `refingerprint` recalcula uma captura antiga a partir do HTML salvo:
a captura 1 já foi recalculada, então as próximas comparam com a mesma
versão do resumo.

**Estado do que para em 08/10** (lido das telas `am_*`):
- Gerente de construção: **27 de 41 aldeias ativas** (19 `ADC - DEFENSIVA`,
  5 `ADC - OFENSIVA BOT`, 3 `ADC - TORRE`); 14 sem gerência. É o mesmo duplo
  comando da §8.25: depois de 08/10, o `BuildingManager` passa a ser o único a
  construir nessas 27.
- Gerente de pesquisa: 13 ativas (modelo `ALL`), 28 sem gerência.
- Gerente de tropa: modelos `ADC - OFENSIVA`, `ADC - DEFENSIVA` e
  `ADC - TORRE` (a atribuição por aldeia não foi reconferida aqui; ver §8.25).
- `am_warehouse` **ativo** ("algumas vezes por dia" move recurso entre aldeias);
  o `resource_sharing` do bot passa a ser o único transporte.
- Assistente de saque: dois modelos (capacidade 4.000 e 8.000) e a lista de
  saques da aldeia, incluindo `?` para os alvos sem relatório.

**Achados sobre o próprio bot, sem precisar da captura 3:**
- **A detecção de premium que já existe está errada.** `config.json` tem
  `world.premium_account: false` com os três ativos. A Feature 22 deduz o
  premium de uma coluna vazia a mais na visão geral e só detecta **uma vez**
  (enquanto o valor é `null`), e ninguém lê `game_data.features`, que diz o
  estado certo em toda tela, de graça (§8.25, achado 1). Hoje isso não faz
  estrago só porque `building.auto_queue_len` está `false`. A camada 2 tem que
  ler `features.*.active` a cada ciclo, nunca guardar uma detecção (6º padrão:
  o premium vence e volta).
- Fila de construção: `BuildingMain.order_count` vem na tela `main` (2 na
  BBM 003 às 23:09), mas o teto não. A página de Vantagens dá "+3", o que é
  coerente com `max_queued_items: 2` / `premium_max_queued_items: 5`. Fica
  para confirmar na captura 3.
- **Renovação automática:** as três linhas da tela de assinaturas têm
  "Prolongar automaticamente", e a conta tem 200 pontos premium. As caixas
  vêm no HTML sem `checked`, mas o estado pode ser aplicado por JS. Se alguma
  estiver ligada, a assinatura não vence e a semana sem premium não acontece:
  **conferir na tela antes de 08/10.**

### Captura 2 (premium, piso de ruído) — 06/10 23:05 → 23:26, **interrompida**

`cache/feature_map/premium_20261006_2305/`: **21 telas**. A 22ª
(`market/exchange`, 23:26) voltou com `<body … data-bot-protect="pending">`,
e a captura parou sozinha, como foi desenhada. A mesma tela na captura 1 não
tinha o atributo.

**O ritmo que passou limpo na captura 1 não passou aqui.** O bot dormia das
23:01:26 às 23:28 (`Dead for 27.02 minutes`), então as 21 requisições foram
praticamente só da captura, a 1 por minuto. Não sei o que mais pesou na conta
(o volume do dia inteiro, o navegador do usuário mais cedo, ou a cunhagem da
§8.55, que entrou em 05/10). O fato é que **1 req/min não é um piso seguro
por si só**. Para não deixar o bot transformar o `pending` em captcha no
ciclo noturno, encerrei o processo do bot às 23:27:25, ainda dormindo, um
minuto antes de ele acordar, a pedido do usuário ("fecha tudo e desliga o
computador").

**O que as 21 telas disseram sobre o ruído:** 13 idênticas à captura 1.
As outras 8 diferem só por estado do jogo:
- relíquias equipadas (títulos em `overview` e `overview_villages/prod`);
- comandos no ar (`info_command`, `Command.init`, "Movimento de tropas" na
  praça, tabela `units_transit`);
- ofertas existentes no mercado (o formulário `accept_multi` aparece quando há
  oferta para aceitar, e o `delete_offers` quando há oferta própria);
- ordem cancelável na fila do quartel.

Nenhuma dessas é premium, e o `--noise` desconta todas. Dois defeitos do
**próprio resumo** apareceram e foram corrigidos (com teste; agora são 16):
o hash de versão do CDN vazava para títulos que vêm escapados dentro de JS, e
a praça tem um campo oculto com **nome aleatório a cada carga**. As duas
capturas foram recalculadas com `refingerprint` depois da correção.

**✅ Completada em 07/10 23:05 → 08/10 00:26:** as 54 telas fixas que
faltavam, a 90 s, todas 200 e sem `data-bot-protect`, com o bot rodando o
ciclo noturno e o Hunter mandando um nobre às 23:55 (`36294 -> 61535 — OK`)
no meio da captura. As duas partes foram juntadas em
`premium_20261006_2305/`, que agora tem as **75 telas fixas**. Uma tentativa
às 05:51 de 07/10 caiu no portal (sessão vencida depois do desligamento) e
parou em 1 requisição; daí a guarda `SessionLost`.

**Piso de ruído, captura 1 × captura 2 (75 telas): 19 idênticas.** Nada que
mudou é premium; tudo é estado da conta, e `compare --noise` desconta:

| Fonte do ruído | Onde aparece |
|---|---|
| Banner **"Oferta!"** com contagem regressiva no cabeçalho (`icon header premium`, `Premium.buy`), que surgiu nas últimas horas antes do vencimento | todas as telas da segunda parte (07/10 23:05 em diante) |
| Relíquias equipadas | títulos da visão geral e das visões gerais por modo |
| Comandos no ar | `info_command`, `Command.init`, "Movimento de tropas", `units_transit` |
| Ofertas e transportes no mercado | `accept_multi`, `delete_offers`, "Transportes em chegada" |
| Fila do quartel com ordem cancelável | `barracks&action=cancel` |
| Aldeias listadas no assistente de saque | ícones `farm_village_<id>` em `am_farm` |
| Bloco de notas no perfil (`notebook`, `BBCodes`) | `info_player` |

⚠️ O banner "Oferta!" usa a **mesma classe** (`icon header premium`) que
marca o cabeçalho das telas de premium. Na comparação com a captura 3, essa
classe sozinha não indica nada; tem que vir junto com outra diferença.

### Captura 3 (sem nada pago) — 08/10 23:15 → 09/10 01:58

`cache/feature_map/free_20261008_2315/`: **110 telas** (as 75 fixas + 35 da
descoberta), todas 200 e sem `data-bot-protect`, a 90 s, com o bot no ciclo
noturno e nenhum envio do Hunter na madrugada. `game_data.features`:
`Premium.active false`, `AccountManager` **`possible: false`** (sem premium o
jogo nem oferece o gerente), `FarmAssistent.active false`; o `<body>` perdeu o
`has-pa`.

**Parada na 36ª da descoberta, e foi defeito meu.** A descoberta lia links
também de `action="…"` de formulário e pediu por GET
`report&mode=process_reports`, que é o **POST** da lista de relatórios (apagar
ou mover). O GET foi sem corpo e sem nenhum relatório selecionado, voltou sem
`game_data`, e a guarda `SessionLost` parou a captura antes de gravar. A
sessão estava boa (o bot fez GETs normais até 01:56). Corrigido: destino de
formulário nunca entra na descoberta (teste com recorte verbatim do form,
provado por mutação; 19 testes).

**Método da leitura.** `compare 1 × 3 --noise 1 2`, mais uma separação feita
à mão entre o que muda em **todas** as telas (cabeçalho e menu) e o que muda
só em uma. O banner "Oferta!" (`icon header premium`) aparece como `+` em
telas que a captura 2 não leu, e foi descartado como ruído.

**O que muda em todas as telas (menu):** sem premium somem os links de
`overview_villages` por modo (`combined`, `trader`, `units`, `buildings`,
`tech`, `groups`, `commands`, `incomings` e os subtipos), `mail&mode=address`
e `mail&mode=groups` (catálogo de endereços), `report&mode=groups` (pastas de
relatório), e a classe `has-pa`.

**Tela por tela — o que é premium com certeza** (some, ou o jogo mostra o
aviso de compra no lugar):

| Tela | Com premium | Sem nada pago |
|---|---|---|
| `overview_villages` em **qualquer** modo além de produção | tabela própria do modo (`commands_table`, `units_table`, `buildings_table`, `techs_table`, `combined_table`, `trades_table`, `group_assign_table`) | serve a `production_table` com o aviso *"Adquira uma Conta premium para usufruir de visões gerais aperfeiçoadas"* |
| `overview` (tela da aldeia) | widgets de fila de construção (`overview_buildqueue`), bloco de notas, grupos, gerente | sem esses widgets |
| `train&mode=mass` | recrutamento em massa (`mass_train_table`, `train_mass_all`) | cai no recrutamento de uma aldeia (`TrainOverview.initSingleVillageMode`) |
| `place&mode=call` (apoio em massa) | lista de tropas de todas as aldeias, envio único | página vazia (303 KB → 41 KB) |
| `place&mode=neighbor` | aldeias vizinhas | some do menu, página vazia |
| `market&mode=call` (Pedido) e `mass_create_offers` | puxar recurso de várias aldeias, criar ofertas em massa | somem |
| `place&mode=scavenge_mass` | envio de várias aldeias num comando | a tela abre, mas o envio múltiplo é premium (aviso da captura 1) |
| `snob&mode=coin` | `coin_overview_table`: cunhagem de várias aldeias | uma aldeia: `snob&action=coin` e **`start_auto_minting_session`** |
| `report&mode=all` | filtros (`set_filter_*`) e tamanho de página configurável | **12 relatórios por página**, sem filtro |
| `report&mode=groups` | pastas de relatório | some |
| `map` | marcar por cor (`ColorGroups`), comandos rápidos, notas, mapa maior | aviso *"…para usufruir de um mapa maior"* |
| `memo` / notas | bloco de notas (`memo&action=toggle`) | some |
| `ally&mode=reservations` | campo **`comment[]`** no formulário de reserva | o formulário existe, **sem** comentário |
| `settings&mode=settings` | `map_size`, `minimap_size`, `show_toolbar`, `confirm_queue`, `disable_call_all_warning` | somem |
| `barracks`/`stable`/`garage` | modo `decommission` (dispensar tropa) no menu | some |
| `place&mode=templates` | salvar modelo de tropas (`templates_save`) | a tela abre sem salvar |
| `market&mode=other_offer` | tamanho de página das ofertas | some |
| todas as `am_*`, `accountmanager` | gerente e assistente de saque | **redirecionam** para `premium&mode=help&feature=…` |

**Grátis, confirmado pela medição:** `place&mode=scavenge` (coleta por
aldeia), a cunhagem por aldeia e a **cunhagem automática** (§9 item 22),
`report&mode=filter` (o filtro que impede o jogo de gerar relatórios, §9 item
21; sem premium perde só as opções ligadas ao gerente), o mercado (enviar,
ofertas, bolsa), praça, simulador, bandeiras, inventário, estátua, torre,
tribo, reservas (sem comentário) e a lista de aldeias em produção (as 44
numa página só, `page_size` 50).

**Efeito no bot, já visto no log da sessão das 19:30 de 08/10 (sem
premium):**
- **`InFlight` quebrou.** Cinco WARNING `a tela respondeu 200 mas sem tabela
  de comandos -- login/bot-protection, ou o markup mudou`. O motivo real é o
  terceiro, nenhum dos que a mensagem sugere: sem premium,
  `overview_villages&mode=commands` serve a tabela de produção. O card
  "Em voo" do painel ficou sem dado.
- **A reserva da tribo perdeu o carimbo.** `reserva 100814 de 66317 criada SEM
  comentario -- … o bot nao vai conseguir remove-la depois e ela vai expirar
  sozinha em 3 dias`. A Fase 2 do `P-CONQ-RESERVA` (§8.7) usa o comentário
  como prova de que a reserva é do bot. Sem premium, o campo não existe.
- **Lista de relatórios:** 12 por página contra 50. A §8.46 já pagina pelo
  tamanho real, então o bot segue funcionando, mas ler N relatórios custa
  ~4× mais GETs.
- **Lista de aldeias:** intacta (44 de 44, uma página). Com mais de 50 aldeias
  ela pagina; isso já valia com premium.
- **Fila de construção:** o teto não aparece na tela (só `order_count`); não
  houve recusa nem WARNING de fila no log. Fica sem medição direta.
- Dois captchas no fim da tarde (20:11, 309 s; 22:29, 854 s), com o bot
  sozinho na conta. Registro, não conclusão: pode ou não ter relação com a
  conta gratuita.

**O que isto dá para a camada 2 (§9, "ativável por detecção"):**
1. A detecção é `game_data.features.*.active`, lida a cada ciclo, que vem em
   toda tela de graça. Nada de detectar uma vez e guardar (o
   `world.premium_account` da Feature 22 está errado desde sempre).
2. **Premium ligado** libera para o bot: visão geral de comandos (`InFlight`),
   de tropas (`overview_villages&mode=units`, que substitui o `place/units`
   por aldeia), de edifícios e de pesquisa (substituem `main` e `smith` por
   aldeia), recrutamento em massa, apoio em massa, Pedido no mercado, coleta
   multi-aldeia num comando, filtro e página de 50 na lista de relatórios,
   comentário na reserva da tribo e +3 ordens de construção.
3. **Sem premium**, o bot precisa: desligar o `InFlight` (ou trocá-lo por
   outra fonte) em vez de acusar login; marcar a reserva da tribo por outro
   meio que não o comentário; e contar com 12 relatórios por página.
4. Gerente de conta exige premium (`possible: false` sem ele). O duplo
   comando da §8.25 some sozinho quando o gerente vence; com ele ativo, o bot
   pode ceder construção, recrutamento, pesquisa e transporte.

**⏳ Próximo:** a captura 4, no fim da semana sem premium, para medir o ruído
do lado grátis. Nada do bot foi alterado por esta seção: as correções da
lista acima são trabalho à parte, a decidir.

---

## 8.54 ✅ `P-BANDEIRA-UPGRADE` — o upgrade de bandeira nunca subia nada (2026-10-05)

**Sintoma.** Em 05/10 o bot postou `upgrade_flag` em laço, um a cada ~30 s:
9 vezes na BBM 030 (tipo 3, nível 3, 14:56–15:01) e 43 na BBM 037 (tipo 3,
nível 2, 16:14–16:38), logando `Upgraded flag 3` em todas. Os laços só
acabaram porque **o usuário subiu as bandeiras na mão**. Durante o segundo, o
ciclo ficou preso em `manage_flags()` e o ataque do Hunter 74689 → 68082
(saída ~16:28:52) foi recusado às 16:39 por atraso de 632 s. O usuário
mandou na mão.

**Prova de que nenhum upgrade subiu, sem depender do relato.** Em 43
"sucessos" do nível 2, o bot nunca tentou o nível 3. Se um único upgrade
tivesse funcionado, o nível 3 teria chegado a 3 bandeiras em no máximo três
sucessos, e o mesmo passe teria tentado subi-lo.

**Causa (três defeitos juntos).**
1. **Faltava `confirm`.** Lido no `Flags.2dbd8d.js` do br143 (CDN público,
   cópia em `cache/debug/`): o upgrade tem duas etapas.
   `showUpgradeFlagDialog` posta `confirm:!1` e recebe só a prévia do popup
   (`current_flag`, `upgraded_flag`). `upgradeFlag` posta `confirm:!0` e
   recebe as contagens novas, que vão direto para `setFlagCounts`. O bot não
   mandava o campo. Que a resposta **sem** o campo seja a prévia é inferência
   (o JS nunca o omite), mas o laço de campo é consistente com ela.
2. **Sucesso era "veio JSON".** A prévia é JSON sem erro.
3. **A guarda do Bug 2 não podia disparar.** `_upgrade_attempts` zerava a
   cada "sucesso", e a releitura era uma chamada recursiva de
   `manage_flags(force=True)`, sem fundo.

De brinde: `setFlagCounts` publica **string** por nível (`"2"`), e o laço
fazia `for amount in raw[t][l]`, dígito a dígito. 12 bandeiras liam como "1"
e "2": nunca subiam, e a oferta saía 3. O comentário dizia "o jogo publica
uma LISTA"; a captura de 20/09 já mostrava string.

**Correção.** `flag_upgrade` manda `confirm=true`. O sucesso agora é
**a contagem daquele (tipo, nível) cair na releitura**, não o formato da
resposta. A releitura virou um laço dentro de `manage_flags`, e cada
(tipo, nível) tem 2 tentativas por sessão que não zeram em falso sucesso. O
laço termina porque cada sucesso tira bandeiras do inventário e cada falha
gasta uma tentativa. Nível 9 (`max_level` do JS) não sobe, e a quantidade
por upgrade é lida de `FlagsScreen.required_for_upgrade` (3). Antes de cada
POST de upgrade roda o checkpoint do Hunter (`Village._service_hunter`): uma
cascata legítima custa ~30 s por upgrade e a janela do Hunter é de 120 s.
Testes em `tests/test_flag_upgrade.py`. Rodados contra o código antigo, os
mesmos testes estouram com `RecursionError` e leem 12 como 3.

**Revisão da §8.44.** Lá os 53 `upgrade_flag` da 52876 em 01/10 foram
registrados como "cascata única" real. Com o que se sabe agora, o mais
provável é que fosse **este mesmo laço**, encerrado do mesmo jeito (alguém
mexendo no inventário). O argumento usado na época, "hoje nenhum nível tem 3
ou mais e `upgrade_attempts` está vazio", é exatamente o estado que o laço
deixa: o contador zerava em todo falso sucesso. Não há log de 01/10 para
fechar a questão.

**⏳ Validar em campo:** na próxima vez que um nível chegar a 3 bandeiras,
`grep -a "Upgraded flag\|Upgrade de bandeira"` no `session_latest.log`. O
esperado é `Upgraded flag T nível N -> N+1 (a -> b ...)` com `b < a`. Se vier
`Upgrade de bandeira ... contagem ficou em`, o `confirm=true` não é o que o
servidor quer, e a linha traz a resposta para diagnóstico. Nos dois casos o
laço não volta.

**✅ Validado em campo em 07/10**, no primeiro ciclo depois de subir o bot às
05:56. Na BBM 001 (41123): `Managing flags` às 06:04:52, POST com `confirm=true`
às 06:05:22, e `Upgraded flag 5 nível 4 -> 5 (3 -> 0 no nível 4)` na releitura.
Daí a cascata: o nível 5 tinha 2 bandeiras na leitura de 06/10 23:00, foi para 3 e
subiu também (`5 nível 5 -> 6 (3 -> 0 no nível 5)`, 06:06:12). O nível 6 ficou
com 2 e o laço parou ali, sem nenhum WARNING. Foram dois POSTs para dois upgrades,
cerca de 30 s cada, como estimado. O `confirm=true` é o que o servidor quer, e a
releitura distingue sucesso de prévia.

---

## 8.55 `P-CUNHAGEM` — aba Cunhagem: hub, roteamento, campanha de itens e cunhagem diária (2026-10-05)

**Pedido.** Usar juntos o Bônus de bandeira (dobra a bandeira atual, 48 h, uma
aldeia) e o Decreto Real (−10 % no custo da moeda, 24 h, todas as aldeias) na
melhor aldeia, cunhar o máximo, e ter isso num botão do painel. Junto: iniciar a
cunhagem automática em todas as academias num horário fixo antes do horário
inativo, e poder rotear o recurso para a aldeia de moeda mais barata mesmo sem
itens.

**Números do mundo, lidos antes de escrever.**

- Custo base da moeda no br143: 28.000 / 30.000 / 25.000 (tela `snob&mode=coin`,
  captura de 04/10).
- A bandeira tipo 7 no nível n dá −(8 + 2n) %. Medido pela coluna de custo de seis
  aldeias: níveis 1, 2, 3, 4, 5 e 7 dão 25.200, 24.640, 24.080, 23.520, 22.960 e
  21.840 de madeira. Os níveis 6, 8 e 9 são extrapolação.
- `train.storage_item` da academia é o custo com **todos** os bônus aplicados
  (`{"wood":23520,…,"id":"coin"}` na BBM 003). É a única fonte que enxerga
  Bônus de bandeira e Decreto. O bot mede o custo antes e depois de cada item e
  grava em `cache/mint/state.json`. O planejador usa a medição por até 6 h e,
  depois disso, volta à bandeira.
- `coin_mint_fill_max` é o "(N)" ao lado do campo de cunhar. O usuário lembrou que
  um clique ali preenche o máximo, e o bot passa a cunhar esse N de uma vez
  (`action=coin`, `count=N`).

**Endpoints, conferidos sem gastar item.**

- Item: `POST screen=inventory&ajaxaction=consume` com `item_key` e `amount`. Lido
  em `Inventory.dff6db.js_` na CDN, sem tocar na conta.
- O diálogo `ajax=item_dialog&dialog=activate_reward` do Bônus de bandeira (GET,
  só leitura) diz *"serão aplicados em sua aldeia atual"* e não tem seletor: a
  aldeia é a da URL. O do Decreto diz *"em todas as suas aldeias"*.
- Cunhagem automática: `POST screen=snob&action=start_auto_minting_session`, sem
  corpo (formulário "Ativar"). Dura 8 h, cunha sozinha cada moeda que o recurso
  permitir e é grátis com ≥ 5 aldeias (KB).
- O usuário confirmou dois fatos de jogo: a cunhagem automática aplica o desconto
  da bandeira, e o 2º Decreto ativado com o 1º ativo **estende** a duração. O que
  ainda não se sabe — se Decreto e bandeira somam ou multiplicam — fica medido no
  diário da própria campanha.

**O que foi feito.**

- `game/mint_planner.py` (puro): custo por aldeia, ranking do hub e
  `plan_route`. O ranking ordena por custo, depois armazém, depois aldeia que não
  recruta nobre, depois proximidade do estoque das outras. O `plan_route` manda
  por blocos de comerciante o recurso que o hub tem menos em relação ao custo da
  moeda, respeitando o piso da doadora e o espaço do hub. Com os dados de 05/10 o
  hub é a **BBM 002**: bandeira nível 7, empatada com a BBM 010 e desempatada pelo
  armazém (500 mil contra 400 mil).
- `core/mint_store.py`: campanha `approved → activating → active → done`, com
  `failed`/`cancelled`, em `cache/mint/campaign.json`. Tem dois escritores (painel
  e bot), então passa por `file_lock` e relê antes de gravar.
- `game/mint_manager.py`, uma instância por processo:
  - Ativa a campanha só depois da aprovação no painel.
  - Antes de gastar qualquer item, confere na tela de bandeiras que o hub ainda
    está com a tipo 7.
  - Cada item conta como gasto só quando a quantidade **cai na releitura** do
    inventário, o mesmo desenho da §8.54. Uma releitura sem `inventory` não vale
    como queda.
  - `activating` grava o inventário de antes. Se o processo cair no meio, a
    retomada gasta só a diferença e nunca reenvia às cegas.
  - Mantém a sessão de 8 h do hub, cunha o máximo a cada renovação e roda a
    cunhagem diária (POSTs espaçados por `daily_auto_mint_spacing_sec` para não
    disparar captcha).
  - Relê o inventário a cada `inventory_refresh_hours`.
  - Roda no início do ciclo, no checkpoint do Hunter e antes do sono, e encurta o
    sono para os seus horários (28º padrão).
- Na aldeia (`Village`): o hub não doa; as outras rodam `run_mint_route` no lugar
  das regras normais. Durante a campanha, o hub tem a bandeira travada
  (`DefenceManager.flag_lock_reason`, que vale também para a troca de defesa, já
  que trocar a bandeira cancela o bônus) e para de construir, pesquisar, formar
  nobre, recrutar e usar o mercado (`campaign_pause_hub_spending`).
- Painel `/minting`: ranking, projeção de moedas em cada cenário, campanha
  (aprovar/cancelar/encerrar, diário e medições), roteamento (liga/desliga, hub,
  piso) e cunhagem diária (horário e aldeias).
- Config `minting` em `config.example.json` (`build.version` 4.9 → 5.0 só no
  exemplo). O merge foi conferido com `cache/_check_merge_loss.py`: nada se perde.
- Testes: `tests/test_mint.py`. A guarda da releitura foi provada desligando-a: sem
  ela, o teste vê a campanha virar "ativa" sem os Decretos.

**Primeira campanha, 05/10 18:30 (BBM 002).** Ativou tudo e o custo medido
respondeu a dúvida: 21.840 antes, **15.680 com o Bônus** (−44 %) e **12.880 com o
Decreto** (−54 %), ou seja, **Decreto e bandeira somam**. O 2º Decreto não mudou o
custo, o que bate com estender a duração. Foram 5 moedas cunhadas de uma vez no
primeiro tick e a sessão automática de 8 h começou.

**Ajuste no mesmo dia: quem recruta nobre não envia ao hub.** O roteamento
ignorava a reserva da própria aldeia. Com piso de 20.000, ele levava tudo o que
uma recrutadora juntava para o nobre (40.000/50.000/50.000), e ela nunca formava o
nobre. Pedido do usuário: sincronizar as duas configurações. A aldeia que recruta
(`snobs` > 0, academia construída e escolhida pelo NobleRecruitGate da §8.48, no
máximo `max_noble_recruiters`) não envia. A que só cunha por estar longe dos alvos
envia (`Village._recruits_nobles`, `test_quem_recruta_nobre_nao_envia_ao_hub`).

**Ainda não capturado.** A tela da academia **com** a cunhagem automática em
andamento. O bot só afirma o que viu: o botão "Ativar" sumiu. A primeira resposta
de cada tipo vai para `cache/mint/samples/` (token `h` redigido) para virar
fixture.

## 8.56 Releitura do `TWBOT_LazyTurtle` e `P-SNIPE-TREM` (2026-10-06)

Segunda leitura do fork principal da §7.9, de `a2b13a8` (19/set, último commit
auditado) até `97ded44` (06/out): 55 commits, ~5.100 linhas, quase tudo em
`game/snipe.py`, `snipe_wave.py`, `dodge.py`, `csnipe.py`, `massgather.py` e
`events.py`. **Auditoria estática (`T`)**, como a §7.9. Os números abaixo são do
nl116 e foram medidos por eles, não aqui; vale o décimo sétimo padrão. A exceção
são os dois parâmetros do br143 marcados como "lido em 06/out", que vieram de
`interface.php?func=get_config`. **Nenhum código foi transplantado.**

### O que serve

1. **Evento da Bigorna (`83b9b32`).** Lê estoque e livro de receitas, segura os
   metais raros para o melhor alvo que precisa deles e forja seguindo um perfil
   (nobre, defesa, construção, ids livres). Usa o livro de receitas do próprio
   jogador, então é compatível com "as receitas são por jogador". Não foi
   portado porque o evento do br143 fecha em 13/out (forja até 14/out), e são
   ~600 linhas com painel. Se o evento voltar, o ponto de partida é
   `anvil_plan()` em `game/events.py` deles.
2. **Precisão de horário.** São as medições que alimentam o `ServerClock` da
   §7.9 e o `P-SNIPE-TREM` abaixo:
   - Conexão já aberta mede ~70–115 ms de ida e volta; conexão nova, ~160–215 ms.
     Sincronizar numa e disparar na outra errou +55..+81 ms (`d0ac37a`) e
     −81 ms (`eb8b2a7`). A correção foi fechar as conexões ociosas antes da
     sincronização **e** antes do disparo, para os dois pegarem o mesmo caminho
     frio.
   - Antecedência fixa não segura nem uma hora: o mesmo envio pousou −31 ms às
     13:12 e +28 ms às 16:47, com a carga da noite (`adc82d9`). A saída foi
     calibrar pelo pouso relido do envio anterior, guardado como "delta sem
     antecedência". Com a mediana dos 5 últimos, a calibração correu atrás do
     ruído (desvio 13,7 ms contra 11,9 ms cru). Com os 15 últimos, 12,7 ms
     (`e2ccba9`). Leituras acima de 80 ms são descartadas como leitura quebrada.
   - Uma "melhoria" (várias amostras de relógio em conexão quente) fez o
     primeiro envio real pousar +90 ms atrasado, e foi revertida (`941e73b`).
     É o décimo terceiro padrão do lado deles: a amostra extra media uma
     latência que o disparo não ia ter.
   - Erro residual de **±15–20 ms** por envio, que a sincronização não remove
     (`snipe_wave.py`, cabeçalho).
3. **Onda de espiões não é ataque cheio (`f54797c`).** Baixar o limiar de
   unidades para pegar meio-full também pegou ondas de ~2.900 espiões mortos,
   que seriam lidas como "full morto". Eles passaram a exigir ≥ 25% de unidades
   ofensivas (bárbaro, leve, arqueiro a cavalo). Em 301 ataques acima de 2.000
   unidades essa fração foi 0% ou ≥ 75,6%, então o corte cai num vazio.
   **Conferido aqui:** `ReportManager.safe_to_engage()` julga só as perdas do
   **nosso** ataque contra o alvo, e não infere o exército inimigo pelo tamanho.
   O defeito deles não tem equivalente hoje. Fica a lição para quando o
   `DEF-01` classificar ataques recebidos: separar por composição, não por peso.
4. **Nome do comando × tempo de voo (`5c7fff9`).** Um ataque visto 134 min
   antes do pouso, a 4 campos, não pode ser aríete (que levaria 120 min). Só
   pode ser nobre. Eles avisam quando o nome contradiz o voo e usam a distância
   exata, porque a arredondada fazia aríetes verdadeiros parecerem lentos demais
   acima de 60 campos. A metade que vale para nós é a do **limite inferior de
   viagem**, ver `P-SNIPE-TREM` abaixo.

### O que não serve, e por quê

- **Coleta em massa (`massgather.py`):** enviar de várias aldeias num comando é
  premium. Quem diz é o próprio jogo, na §8.53 (*"Evolua para um Conta premium
  para poder enviar comandos de coleta de várias aldeias…"*). O alvo do bot é
  conta grátis. Mesmo assim ficam duas observações deles:
  - **O jogo troca o token CSRF a cada ação aceita.** O segundo POST seguido com
    o token velho é recusado (`1a4ae14`). Aqui o `post_process`
    (`core/request.py:134`) relê o `h` de toda resposta, então o risco só
    existe num lote de POSTs sem leitura no meio. Quem escrever um envio em
    lote tem que reler entre os POSTs.
  - Eles afirmam que o saque de uma coleta de duração fixa é igual em qualquer
    opção (`d9c5a0a`). Nossa coleta avançada já distribui entre as opções
    mirando durações iguais. A afirmação não foi medida no br143.
- **Dodge (`dodge.py`):** a filosofia é tirar a aldeia inteira da frente. A
  nossa evacuação esconde só `snob` e `axe` (`defence_manager.py:47`) e deixa a
  defesa em casa. Por isso o risco que motivou o item 4 acima (nobre com nome de
  aríete pegando a aldeia vazia) não nos atinge do mesmo jeito.
- **Relatórios uma vez por ciclo (`d0f89b1`):** já feito aqui na §8.47, de
  forma independente.

### `P-SNIPE-TREM` — cortar um trem de nobres inimigo (registrado, não priorizado)

**Pedido do usuário (2026-10-06):** ter uma estratégia para parar um trem de
nobres inimigo matando um ou dois nobres do meio do ataque.

**A mecânica.** Um trem são N nobres pousando com milissegundos de intervalo. O
primeiro costuma vir colado num full que limpa a aldeia. Os seguintes vêm com
escolta leve. Apoio que pousa **entre o nobre k e o nobre k+1** luta contra
k+1…N. Se aguentar as escoltas, esses nobres morrem e a lealdade só cai pelos k
primeiros. No br143 cada nobre tira **20 a 35** de lealdade (`<mood>`,
`loss_min`/`loss_max` no `get_config`; lealdade é `mood` em inglês). Daí:

- 3 nobres derrubam 100 com no máximo 105, no limite. Por isso o padrão é 4.
- Cortar **atrás do 1º nobre** deixa a lealdade em 65–80, e é o melhor ponto: um
  apoio ali cobre o trem inteiro (`snipe_wave.py`: *"a support standing behind
  the train's first noble meets every noble after it"*).
- Cortar **na frente do 1º** é perder a tropa, porque o full limpa tudo.
- Cortar só o último de um trem de 4 deixa 3 nobres, que ainda podem somar
  ≥ 100. Matar "um do meio" só resolve se for cedo no trem.
- Pousar **no mesmo ms** de um nobre é cara ou coroa, e depois dele é inútil.
  Eles tratam os dois casos como falha, não como acerto de +1 ms
  (`keep_verdict`, `coin_flip_on_hit`).

**O que o br143 permite (lido em 06/out, `get_config`):** `millis_arrival = 1`
(o jogo mostra e processa chegada em ms) e `command_cancel_time = 600` (comando
cancelável por 10 min). O ms da chegada **já está no markup** que o bot lê, só
que é jogado fora: a linha de comando recebido traz
`hoje às 13:13:09:<span class="grey small">598</span>`, e
`Extractor.incoming_commands()` só guarda `data-endtime`, em segundos. Nossos
próprios trens pousam 100 ms separados (§9, item 0). É essa a ordem de grandeza
de janela que se espera contra um inimigo que manda do mesmo jeito. Com erro de
±15–20 ms por envio, uma janela de 100 ms é alcançável, e uma de 20 ms é
sorteio.

**Dois jeitos de pousar no buraco:**

- **Snipe de apoio:** outra aldeia manda defesa para pousar em
  `hit_1 + offset`. Exige uma aldeia com tropa defensiva a uma distância cujo
  tempo de viagem caiba antes do pouso. Atenção ao paladino: ele dita a
  velocidade do comando inteiro, e um apoio com paladino saiu a 10 min/campo em
  vez dos 18 da lança.
- **C-snipe (cancelamento):** a própria aldeia atacada manda a defesa para fora
  e cancela no meio do caminho, para ela voltar dentro do buraco. Tropa
  cancelada volta em tempo igual ao que andou: enviada em S e cancelada em C,
  volta em 2C − S. Não precisa de outra aldeia, mas é amarrado pela janela de
  10 min. Eles mediram no nl que o servidor credita o tempo andado em
  **segundos inteiros** (a volta é S + 2k s, mantendo o ms do envio), e que o
  "2C − S" em ms que a página de cancelamento mostra é artefato de renderização.
  Isso não foi medido no br143. É exatamente o tipo de regra que o décimo
  nono padrão manda medir antes de usar.

**Como reconhecer o nobre numa conta grátis.** Eles reconhecem pelo rótulo que o
etiquetador escreve, e renomear comando é premium (lista do jogo na §8.53).
Aqui só restam dois sinais:

1. **Limite inferior de viagem:** se o ataque foi visto pela primeira vez em t₀,
   pousa em A e vem de d campos, então a viagem é ≥ A − t₀. Se isso passa de
   d × 30 min (o aríete), só pode ser nobre (35 min/campo). Só funciona se o bot
   vir o ataque cedo, o que pede o leitor de `game_data.player.incomings` do §9
   item 23 rodando no início do ciclo, e não por aldeia.
2. **Forma de trem:** ≥ 2 comandos da mesma origem na mesma aldeia, pousando
   dentro de ~1 s. Com o ms guardado, isso é um `groupby`.

**Restrição que muda o desenho em relação ao fork: orçamento de requisição.** A
"onda" deles arma *toda* opção alcançável e cancela as que erraram. No br143 o
captcha vem por taxa da **conta**: já dispararam ~75 GETs em 15 min, e o teto
seguro somando todos os clientes é ~2 req/min. Cada tentativa custa pelo menos
o preparo e a confirmação da praça, mais a releitura do pouso e o cancelamento
se errou. Por isso aqui é **1 a 3 tentativas por trem**, escolhidas pela margem,
e nunca a onda inteira. O captcha no meio de um snipe perde o snipe **e** o
ciclo.

**Faseamento proposto.** Cada fase só começa com a anterior medida:

| Fase | O que | Envia tropa? | Aceite |
|---|---|---|---|
| F0 | `incoming_commands()` passa a devolver `arrival_ms`, com teste contra o recorte verbatim que já existe em `tests/test_incoming_commands.py` | não | teste |
| F1 | `ServerClock`: sincronização por rtt/2 em conexão nova, duração da tela de confirmação como fonte da viagem, disparo dormido até o ms | não | offset e rtt logados por 2–3 dias, com distribuição |
| F2 | Medir o erro de pouso no br143 com **apoio entre aldeias próprias**, mirando um ms arbitrário e relendo a chegada na lista de comandos. Não precisa de inimigo nem arrisca tropa | sim, inofensivo | ~15 amostras em horários diferentes; desvio comparado aos ±15–20 ms do nl |
| F3 | Detector de trem (os dois sinais acima), só avisando no painel e no Telegram, com o buraco calculado e as aldeias que alcançam | não | trens reais detectados, conferidos pelo usuário na tela do jogo |
| F4 | Snipe **semi-manual:** o usuário escolhe o trem no painel e o bot calcula a opção, reserva a tropa e dispara | sim | primeiro corte real |
| F5 | (Opcional) C-snipe, depois de medir no br143 a regra do segundo inteiro | sim | idem |

**O que tem que conversar com o que já existe:**

- A tropa do snipe é uma **reserva nova** no mesmo sistema da §8.20. Sem isso, o
  apoio da §8.39, a escolta do trem bárbaro ou o farm podem gastar a tropa
  entre o armar e o disparar. O fork resolve com uma política de falta na hora
  do envio (`scale`/`all`/`strict`), o que é o sexto padrão: reconferir a
  premissa no momento de agir.
- O disparo precisa de prioridade sobre o laço de aldeias, como o Hunter. O
  vigésimo oitavo padrão vale de novo: todo `time.sleep` do laço principal tem
  que conhecer o prazo do snipe.
- `DefenceManager.evacuate()` esconde `snob`/`axe` e não mexe na defesa, então
  não briga com o snipe. Já um c-snipe **mexe** na defesa da própria aldeia e
  precisa travar a evacuação e o apoio dela durante a janela.
- Envio real de tropa, então vale a regra do `CLAUDE.md` para
  `AttackManager`/`DefenceManager`: F2 em diante só com autorização explícita.

## 8.57 Evento da Bigorna: o que foi capturado para o próximo (2026-10-07)

O evento "Bigorna do Rei Mercenário" do br143 vai de 29/09 14:00 a 13/10 14:00 (a
forja e o passe vão até 14/10 14:00, `end_crafting`/`end_event_pass`). Ele deve
voltar em outros mundos. Esta seção junta o que só dá para medir **com o evento no
ar**, para que o módulo possa ser escrito depois sem começar do zero. **Nenhum
código de bot foi escrito.** O ponto de partida externo continua sendo o
`anvil_plan()` do LazyTurtle (§8.56, item 1).

**Capturas** (só GET, 90 s entre elas, com o bot rodando; script
`cache/_probe_event_crafting_state.py`; token `h`/`csrf` redigido), em
`cache/debug/event_crafting_20261007/`:

| Arquivo | Pedido | O que traz |
|---|---|---|
| `main.html` | `screen=event_crafting` | `CraftingEvent.init(...)` (11 args, ver `cache/_probe_event_crafting.py`) e o formulário de forja |
| `get_state.json` | `screen=event_crafting&ajax=get_state` (cliente `get_api_data`, embrulhado em `response`) | estoque, receitas conhecidas, rankings, prazos, widget do passe |
| `event_pass_popup.json` | `screen=event_pass&ajax=popup` | `EventPass.init({...})`: progresso, checkpoints, os 15 prêmios grátis e os 15 do passe pago |

O JS do jogo também ficou guardado em `cache/debug/event_crafting_js/`
(`CraftingEvent.a14db7.js_`, `EventPass.29b649.js_`, baixados da CDN, sem tocar a
conta). Ele dá o protocolo inteiro, **que não foi exercitado por nós**:

- **Forjar um trio:** POST `screen=event_crafting&ajaxaction=craft&h=…` com três
  `material[]` (ids 1–7). A resposta traz `item` (nome e descrições) e
  `event_pass`.
- **Forjar uma receita conhecida pelo livro:** POST `ajaxaction=craft_recipe` com
  `recipe_id`.
- **Coletar o passe:** POST `screen=event_pass&ajaxaction=collect_all` sem corpo,
  ou `collect_grand_prize` com `checkpoint`.
- **Pagos (fora do escopo, porque o alvo é conta grátis):** `buy_material`
  (`material_id`, 30 PP o comum e 80 PP o raro, e o preço sobe a cada compra no
  dia), `buy_recipe` (70 PP), `buy_event_pass` (600 PP) e `collect_noble_prize`.
- `seen_recipes` só marca a receita como vista na interface.

**A previsão das receitas foi confirmada em todos os grupos.** Em 29/09 só o grupo
de 3 comuns tinha sido testado. Agora são **25 de 25** trios feitos batendo com a
regra "ids contíguos a partir de 16129, ordem pelo número de raros e depois
lexicográfica", inclusive com 2 raros (`3-5-7`=16193) e 3 raros (`5-5-5`,
`5-6-7`, `6-6-7`). Os 84 resultados vêm do livro de receitas da própria conta. A KB
diz que as receitas variam por jogador, e o módulo deve continuar lendo o livro em
vez de chumbar a tabela.

**Números da conta em 07/10 ~15:00:**

- Passe: `progress` 32 itens forjados, `checkpoint_progress_max` 3, ou seja, **um
  prêmio a cada 3 forjas**. São 15 prêmios grátis, logo 45 forjas completam a
  trilha grátis. Os checkpoints 1–9 foram coletados e o 10 (Pacote de recurso
  10%) está **desbloqueado e não coletado**. O último grátis é "Privilégio".
- Ranking geral: score 32 = forjas, posição ~10.040, prêmio −2% em custo de
  recrutamento. Ranking diário: 3 forjas hoje, 3º lugar.
- Estoque: Chumbo 1, Estanho 5, Cobre 3, Ferro 1, Bronze 4, Prata 1, Ouro 0.
- PP: 200 em 29/09 e 200 hoje.
- **Inventário:** `cache/inventory/status.json` (lido pelo bot às 13:58) tem
  **61 itens de nomes de receita do evento parados**, em 29 linhas, de 73 itens no
  total. O nome não separa o que veio da forja do que veio do passe.

**Origem dos materiais** (KB InnoGames 2921, em inglês): recrutar, construir,
cunhar, aceitar oferta de comércio, atacar e defender têm cada um uma **chance**
de dar 1 material aleatório, **até 8 por dia**. Não há leitura do lado do jogo
(`player_material_grants` = 0 e `player_materials` = `{}` no `get_state`).

**A conta dos materiais, e a segunda fonte.** 32 forjas × 3 + 15 em estoque são
111 materiais, e nove ciclos diários × 8 dão no máximo 72. O usuário confirmou que
**não comprou nada**: os 200 PP são os que sobraram da ativação do premium. A
segunda fonte provável é o **ranking diário de forja**. A tabela "Classificação
diária" de `main.html` tem a coluna "Recompensa" com o ícone
`events/crafting/DailyIcon_01.webp`, que é um desenho de lingotes. Hoje pagava 4
ao 1º, 3 ao 2º e 2 do 3º ao 7º. Ler isso como "N materiais" vem do ícone, não de
um texto. Com só 7 jogadores na tabela e 6 forjas bastando para o 1º lugar, a
conta estava em 3º hoje com 3 forjas. Os dias anteriores não foram vistos. Em 9 dias, 2 a 4 materiais
diários dão +18 a +36, o que aproxima 72 de 111. **Não está provado:** falta
capturar um crédito de material depois do fechamento do ciclo (14:00, `cycle_end`).
Não se sabe se a tabela para em 7 por ser o total de quem forjou ou por ser o
corte do prêmio.

As conquistas do evento existem no perfil (`awards.html`, `info_player&mode=awards`):
"Antiga Forja: Mestre Ferreiro" (32/40 itens) e "Colecionador de fórmulas" (24/30
fórmulas, contra 25 trios em `known_recipes`; diferença não explicada). A página
**não mostra recompensa** para nenhuma conquista. As missões também não explicam:
o bot já resgata recompensas de missão sozinho (`Village.get_quest_rewards`), e a
única linha `Got quest reward` do `session_latest.log` de hoje é de recurso por
nível de edifício.

**Consequência para a estratégia de forja:** forjar um pouco **todo dia**, antes
das 14:00, rende mais que acumular, porque cada ciclo diário paga o ranking.
Forja barata com 3 comuns serve, já que conta para o passe e para o ranking do
mesmo jeito.

**O que isto muda no desenho.** O gargalo da conta não é forjar: 61 itens parados
mostram que é **usar**. O módulo que vale a pena tem duas metades:

1. **Usar itens** (vale fora do evento, sobre qualquer item do inventário): a
   Feature 25 fase 2, que nunca teve desenho. Bônus do Nobre antes do pouso do
   trem (Hunter), Édito da Academia e Recrutador quando o NobleRecruitGate
   recruta, Sinal da Aflição antes do `support()`, Boas ligações no hub de
   cunhagem. Já existe precedente de ativação, nos itens de campanha da §8.55.
2. **Forjar** (só com evento): coletar o passe (`collect_all`), forjar até a
   próxima marca de 3, e guardar os raros para os trios-alvo. As duas primeiras
   partes são baratas e sem ambiguidade. A terceira depende da política da
   metade 1.

## 8.58 `P-HUNTER-GATE` — o Hunter decide antes de cada tarefa, não depois (2026-10-08)

**Incidente.** Trem de 4 nobres contra a Bárbara #57033 (chegada comum
09/10 05:41:28). O nobre da BBM 027 (46676) devia sair às 14:22:46. O último
checkpoint antes disso foi às 14:19:58, com **168 s** de folga; a janela do
Hunter era 120 s, então ele seguiu. O trecho seguinte da BBM 029
(recrutamento → nobre → mercado → compartilhamento, que mandou ferro para a
42134) levou **174 s**, e o Hunter só voltou a olhar às 14:22:52: 6,2 s
atrasado, recusado (`send_time_missed`). O usuário mandou o nobre na mão às
~15:07 (chega 06:25:38); o registro da conquista foi acertado à mão com
`manual_extra` e a chegada real em `noble_arrivals`, senão o caminho do nobre
extra (§8.41) mandaria um segundo nobre com o dele no ar.

**Causa.** Checkpoint que só pergunta "está na hora?" falha sempre que o
trecho até o próximo checkpoint dura mais que a janela. As fases medidas em
80 ciclos chegam a 1.300 s (farm), 1.831 s (defesa) e 7.570 s
(compartilhamento — esse com 7.512 s de captcha).

**O que mudou** (escolha do usuário: opção C + E como reserva):

- `Hunter.window` 120 → **300 s**: a menos de 5 min de uma saída, todo
  checkpoint entrega o controle ao Hunter, que espera o segundo exato.
- `Hunter.gate()` **antes de cada fase**, com a duração prevista dela
  (`core/phase_forecast.py`: maior valor das 10 últimas amostras da mesma
  fase na mesma aldeia em `cache/cycles`, captcha descontado; sem histórico,
  p90 da fase; nunca vista, 120 s). Se `previsão + PREP_SECONDS (90)` não
  cabe até a saída: fase adiável é **adiada** nesta passada; não adiável
  (`init`, `defesa`, `mapa`) **segura** o bot até a saída. Farm e defesa têm
  checkpoint por iteração, então a previsão delas tem teto de 180 s
  (`INTERRUPTIBLE_CAP`). Adiado o bloco de recrutamento (que relê as tropas),
  PvP, apoio, farm e coleta também ficam para a próxima passada.
- Fases da conta em `twb.py` passam pelo mesmo gate (conquista bárbara,
  reservas, estatísticas, em voo, cunhagem, estátua, inventário,
  perfis_farm). A espera do gate conta no balde `hunter` do medidor, não no
  da fase, para a previsão não inflar sozinha.
- **Detector de furo**: `WebWrapper` loga `Hunter: FURO` (uma vez por saída)
  se uma requisição comum sai dentro dos 300 s de uma saída sem o Hunter estar
  rodando. Só observa — é o que faz um furo novo aparecer em vez de sumir.

Testes: `tests/test_hunter_gate.py` (o caso real 168 s × 174 s, silêncio,
adiar × segurar, `PREP`, teto de fase interrompível, detector). Provado que o
teste do caso real **falha** com o comportamento antigo (janela 120 s,
checkpoint sem previsão).

**Em aberto, na ordem combinada:** (1) sondar quanto tempo a tela de
confirmação da praça continua válida, para preparar o envio antes e disparar
só o POST final no segundo (precisão); (2) opção E — tolerância de atraso só
para trem bárbaro. ⚠️ O incidente de 12/08 (§6.1) já responde metade da
sondagem do E: nobre que pousa **depois** da conquista autoconquista a aldeia,
queima moeda e mata a guarnição. Logo, mandar atrasado só é seguro se os
nobres anteriores não puderem fechar a conquista sozinhos.

## 8.59 ✅ Alvo de conquista sem coordenada: o `village.txt` não chegava ao envio (2026-10-10)

**Sintoma** (`session_latest.log`, 12:08:10), uma vez por ciclo:

```
[Attack] BBM 022 (40618) -> 40808: sem coordenada no scan desta aldeia nem em cache/villages/40808.json
Hunter: sem coordenada para o alvo 40808 a partir da aldeia BBM 022 (40618)
Conquest: nao consegui a duracao de BBM 022 (40618) -> 40808 pelo servidor -- ... adiando
```

**Causa.** Seleção e envio liam a coordenada de fontes diferentes (décimo
segundo padrão: o irmão não foi relido). Desde a §8.6, `_candidate_pool()`
descobre alvo no mundo inteiro pelo `map/village.txt` (Feature 36, camada 1).
Já `AttackManager._resolve_position()` — usado pela sonda de duração do
Hunter/planejador **e** pelo envio — só conhecia o scan de mapa da própria
aldeia e `cache/villages`. A 40808 (bárbara, 1012 pts, 531|289 no
`village.txt`) nunca tinha sido escaneada por aldeia nossa nem tinha arquivo
em `cache/villages`. Então o planejador a elegia, a sonda recusava, e a
conquista ficava adiada ciclo após ciclo sem sair do lugar.

**Correção.** `_resolve_position()` ganhou uma terceira fonte, o
`village.txt`, consultada só na falta das outras duas (scan > `cache/villages`
> mundo). Coordenada não apodrece como posse (§8.6), então a idade do arquivo
não importa aqui. Se o arquivo não puder ser lido, a função recusa o alvo sem
derrubar o bot. Fiação: o `ConquestManager` repassa a lista ao `AttackManager`
interno, e `twb.py` instala `world_villages` em cada `Village` (e no
`village.attack`) a cada ciclo, junto com o `hunter_service_callback`. Assim
a sonda e o disparo posterior usam a mesma fonte. Com a conquista desligada a
lista não é criada e nada muda.

Medido com o dado real: sem a lista, `None` para a 40808; com ela,
`(531, 289)`. Testes em `tests/test_conquest_manual_target.py` (alvo só do
mundo, precedência do cache sobre o mundo, `village.txt` ilegível). **Em
campo:** depois do restart, procurar `veio do village.txt` (DEBUG) no lugar
do aviso de "sem coordenada".

## 9. Próximos passos

**Auditoria de 2026-09-26 (§8.32):** 21 achados. Os Lotes A (A26-01, 02, 10;
§8.33) e B (A26-03, 04, 14; §8.35) foram fechados em 2026-09-27, e **nenhum P1
segue aberto**. O Lote C (A26-05, 06, 07, 08, 12) foi fechado no mesmo dia
(§8.36). Sobram A26-09 e A26-11, que pedem sondagem do servidor antes, e os
P3 (A26-13, 15 a 21). A ordem está no fim da §8.32.

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
   ✅ **Fechado em 2026-09-23:** `12:57:18 Unlock: iniciada coleta 4 (Extrema
   Coleta) na aldeia 40374 por {'wood': 10000, 'stone': 12000, 'iron': 10000}`
   (BBM 024) e `13:58:03 ... coleta 1 (Pequena Coleta) na aldeia 44167`
   (BBM 031). Falta só a confirmação independente do plano: `unlock_time` na
   tela no ciclo seguinte.

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
   ✅ **Exercitado em campo em 2026-09-23 às 09:09:54:** `alvo 50833 (575|291)
   reservado no quadro da alianca (reserva 82601) -- 1 de 1 vagas proprias em
   uso`. É a primeira reserva criada pelo bot. No mesmo passo, o gate da Fase 1
   decidiu pela primeira vez: 11 alvos descartados por `tribe_reservation`
   (Aiko, GeBarreto, birkner, Buginha). **Resta ver** a vaga ser devolvida por
   `_release_finished_target_claims()` depois que a 50833 resolver.
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
   ✅ **Metade da sessão validada em 2026-09-23:** o bot subiu às 09:01:53 com
   a sessão vencida, logou `O cookie em cache/cookies.txt nao autenticou` e
   `Esperando uma sessao`. O usuário salvou o cookie às 09:02, e às 09:02:33
   veio `Sessao aceita`, sem reinício. **Falta o captcha.**
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
   Ciclo de 2026-09-23 (bot subiu às 09:01): às 10:57, 10 leituras e zero
   `Setting flag`. As BBM 028–031 ainda não tinham rodado.
   **Ciclo completo (09:01–14:04): 31 leituras e 2 `Setting flag`.** As duas
   seguem a política, e nenhuma é o vaivém do Bug 1. **BBM 029 (49709):**
   tinha recrutamento nível 1 (+6%) e foi para produção nível 1 (tipo 1 à
   frente do 2 na preferência sem academia). Apareceu no inventário uma tipo 1
   nível 1 sobrando, e o recrutamento voltou para o inventário. **BBM 032
   (51540, recém-conquistada):** estava sem bandeira e recebeu recrutamento
   nível 1, o melhor disponível depois que a BBM 029 levou a de produção. A
   previsão de "zero" partia de um inventário sem tipo 1. **A prova do Bug 1
   agora é nenhuma das duas trocar de volta no ciclo seguinte.**

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
   ✅ **Visto em campo em 2026-09-23 às 09:47:43:** `Pacote {'light': 15} tem
   60 de populacao, abaixo do minimo 62 desta aldeia (6274 pontos); crescido
   para {'light': 16}`. Os pontos chegam e a correção do pacote age.
   Até as 11:40, nenhuma recusa por ataque falso. A única recusa do ciclo foi
   `Não existem unidades suficientes` (74689 → 66113, às 10:56:57, o 8º farm
   seguido da aldeia), e ela foi tratada como devia: pacote abandonado no
   resto do ciclo. **Fecha** quando o ciclo inteiro terminar sem recusa por
   ataque falso.
   ✅ **Fechado:** o ciclo terminou às 14:04 com 35 pacotes aumentados e
   nenhuma recusa por ataque falso.

19. ~~**`P-FARM-CONQUISTA`**~~ — ✅ **feito em 2026-09-22** (§8.24). A primeira
   conquista multi-origem (51540, 21:23:50) foi seguida de fogo amigo: um farm
   mandado com o trem já no ar chegou 25 min depois e bateu na guarnição. O
   farm agora nunca ataca aldeia da lista de conquista, bárbara ou PvP, desde
   o agendamento. **⏳ Falta campo:** o próximo trem, com o bot reiniciado.
   ✅ **Visto em campo em 2026-09-23:** o trem contra a 50833 foi agendado às
   09:09:54, e às 09:17:16, com os nobres ainda na praça esperando o
   `send_time`, o farm logou `50833 fora do farm -- alvo de conquista
   (conquista barbara, status train_scheduled)`. Os 4 nobres saíram às 09:19:43
   (74689) e às 09:25:28 (41123), cada par num POST só, com chegada às
   18:15:06. **Fecha** com o pouso sem nenhum farm nosso contra a 50833.

**Acrescentado em 2026-09-23, pedido do usuário (§8.28):**

19a. ~~**`P-CONQ-PARALELO`**~~ — ✅ **feito em 2026-10-03** (§8.43):
    `conquest.max_parallel_trains` (padrão 1), um trem novo por ciclo, a
    reserva `barb_train:*` reconstruída do Hunter a cada ciclo, e o
    acompanhamento de todas as conquistas da âncora. Medido antes: 4 nobres
    livres parados com o trem da 53691 agendado. **⏳ Falta:** o usuário subir
    o teto, e o campo. Texto original do pedido:
    **`P-CONQ-PARALELO` — mais de um trem bárbaro ao mesmo tempo.** O
    usuário vai ter 3 trens de nobres disponíveis na maior parte do tempo e
    precisa expandir rápido dentro do alcance de 70 campos. Hoje
    `BarbarianTrainPlanner.run()` sai quando existe **qualquer** conquista em
    `active_conquests()` ("um trem por vez no império inteiro"), e o trem de
    cada alvo leva cerca de 9h entre agendar e pousar. A invariante existe para
    que dois trens não disputem os mesmos nobres e escoltas. Tirá-la exige
    reserva de nobre e escolta **por trem**, que a §8.20 já faz para o PvP, e
    exige olhar os consumidores que assumem um trem só: `_release_orphan_reserves`,
    `_promote_scheduled_trains`, a Hunter por alvo e o farm. Antes de
    implementar, medir quantos nobres o império tem por dia e quanto tempo eles
    ficam parados esperando a invariante. `reserve_max_slots` já está em 3.

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

    **20-medida — ✅ medidor por tela (2026-09-23).** O único ciclo diurno
    medido (22/09, 3h51, 860 req) dá por fase: coleta 143, farm 130,
    recrutamento 126, **mercado 98**, init 101, **compartilhamento 84**. Só
    que fase diz *onde no código*, não *o que foi pedido*: "mercado 98" mistura
    a releitura da visão geral (já na sombra, 20a), as ofertas e a bolsa, e
    "compartilhamento 84" mistura a leitura de mercadores (`market/send`) com
    envios reais. A lista de relatórios fica dentro de `init`, junto com a
    visão geral, então o "30 por ciclo" também não sai separado. Cortar a
    partir disso seria chute.
    Por isso o `CycleMeter` agora conta requisição por **(aldeia, fase, tela)**
    — `screens` em cada balde de `cache/cycles/*.json`, rótulo de
    `cycle_meter.screen_key()` (`market/send`, `report/all` × `report/all/view`,
    `scavenge_api ajaxaction=send_squads`, `POST ...`), sem id nenhum. Fica fora
    de `buckets` numéricos para não quebrar as somas de `by_phase` e do
    `CycleReader`. O fechamento do ciclo loga `Ciclo por tela:` com as 10
    maiores, e `by_screen()` agrega. Teste em `tests/test_cycle_meter.py`
    (provado quebrando o repasse da URL no wrapper).
    **⏳ Falta campo:** o mesmo ciclo diurno que fecha o 20a responde com
    números quais telas do mercado, do compartilhamento e do `init` se repetem.
    Ciclos gravados antes disto não têm `screens` e simplesmente não somam.

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
    Parcial de 2026-09-23 (bot de 09:01, 11 aldeias até as 11:40):
    `update_totals` deu 18 × `producao`, `market` deu 14 × `producao`, e
    nenhum dos dois teve `diverge`. `init` deu 3 × `producao` e 1 × `diverge`.
    O `diverge` foi na 74690, às 11:01:24, com o dado anterior vindo do `map`
    **1h52 antes** (+15k de madeira recebidos no intervalo). É o caso que o
    plano mandava filtrar por `age_sec`, e não conta contra o corte. Ainda não
    é decisão: faltam as aldeias restantes e o ciclo fechar.
    ✅ **Ciclo diurno completo (09:01–14:04, 32 aldeias):** `update_totals`
    deu 35 × `producao` e `market` deu 32 × `producao`, sem nenhum `diverge`
    nos dois. `init` deu 3 × `producao` e 2 × `diverge`, ambos com dado
    anterior velho (1h52 do `map` e 3h05 de `ally/reservations`, este com
    `trader_away 4->0`). **Pelo critério de aceite, as releituras 2 e 3
    (`update_totals` e `market`) podem sair.** São cerca de 67 requisições por
    ciclo. A decisão de cortar é do usuário.
    ✅ **Cortado em 2026-09-23, por decisão do usuário.** As duas releituras
    agora reaproveitam o `game_data` **completo** da última resposta HTML
    daquela aldeia (`WebWrapper.game_data_full`, guardado em `post_process`),
    desde que ele tenha no máximo `bot.reuse_game_data_max_age` segundos
    (padrão 60; a idade máxima medida nesses dois pontos foi 34 s, com
    mediana de 12,5 s em `update_totals` e 17 s em `market`). Sem dado, dado
    velho ou dado vindo de resposta JSON: o GET volta, e a comparação da
    sombra continua rodando nesse caminho. Só HTML de propósito, porque é a
    mesma origem do `Extractor.game_state()` que os consumidores sempre
    receberam, e ninguém conferiu se o `game_data` do envelope AJAX tem todas
    as chaves que `ResourceManager.update()` lê. Uma resposta JSON posterior
    também invalida o HTML guardado, porque ele deixa de ser o dado mais novo.
    O GET da visão geral não tinha outro efeito colateral: o `x-csrf-token`
    não é renovado por essa tela durante o ciclo, e o que vem em seguida são
    GETs comuns. A leitura inicial (`init`) **não** foi cortada: nela o dado
    anterior chega a ter horas. Testes em `tests/test_overview_shadow.py`
    (reaproveitamento, idade, JSON, gate 0, cópia, e `update_totals` sem GET),
    provados por mutação. **⏳ Falta campo:** a fase `init`/`recrutamento`/
    `mercado` do `/cycles` cair cerca de 67 requisições no primeiro ciclo
    depois do reinício.
    O mesmo ciclo respondeu o item 20-medida (`Ciclo por tela`, 1.171
    requisições em 5h02). Os maiores gastos: `scavenge_api send_squads` 105;
    `report/all/view` 85 em `init` + 52 em `conquista_barbara` (**137 páginas
    de relatório**, o maior candidato depois das releituras); `market/send` 60
    + a confirmação dela 35; `place` 52 + 52 + 51 no farm; `main` 40;
    `market/other_offer` 38.
    ✅ **2026-10-03 (§8.44):** o popup de missões (`new_quests
    ajax=quest_popup`, ~39 por ciclo, 946 GETs para 5 resgates) só sai quando
    a tela diz que há recompensa pronta. No mesmo passo, duas hipóteses de
    corte foram medidas e **descartadas**: a lista de relatórios não é
    rebaixada entre aldeias (o `ReportManager` já é um só e nenhum relatório
    foi reescrito), e os 53 `upgrade_flag` da 52876 foram uma cascata única,
    não laço.
    ✅ **2026-10-04 (§8.50):** a tela do ferreiro (`smith`, ~40 por ciclo
    diurno) só é lida quando há pesquisa pedida e ainda não resolvida, com
    reconferência diária.
    ✅ **2026-10-04 (§8.46):** a página de cada relatório de comércio (72%
    dos relatórios abertos, ~187 GETs por dia) deixou de ser aberta: a
    miniatura da linha da lista já basta. No caminho, a paginação da lista
    passou a usar o tamanho real da página (50, não 12).
    ✅ **2026-10-04 (§8.51):** a coleta deixou de pedir `place/units` (~20 a
    32 por ciclo diurno). A tropa em casa sai do `unit_counts_home` da tela de
    coleta, que ela já baixava, e isso foi conferido numa aldeia com apoio
    recebido.
    ✅ **2026-10-04 (§8.52):** o `snob action=train` (até 8 por ciclo, até
    21 antes da §8.48) era mandado às cegas a toda aldeia recrutadora, com
    o jogo recusando. Ele só sai quando a academia diz que o recurso basta.
    No mesmo passo, a aldeia passou a pedir o recurso do nobre.
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
    *(Nota de 2026-10-04: a primeira metade já está feita desde a §8.15. O
    acompanhamento da `reserved_by` roda no início de todo ciclo, também no
    noturno, em `TWB.run_barbarian_conquest()`, e não espera mais a vez da
    aldeia.)*
24. **Hipótese a testar, possivelmente grátis:** o endpoint `scavenge_api`
    `send_squads` que o bot **já usa** aceitar N esquadrões num POST. A tela
    de coleta em massa talvez seja premium (KB não diz), mas o endpoint não
    necessariamente. Um envio real resolve; exige autorização.
25. ~~**Painel**: os cinco itens de gravidade alta da `frontend.md` §2.8~~ —
    ✅ **feito em 2026-09-30** (§8.42). De brinde, a metade "ler
    `game_data.player.incomings`" do item 23 (só para o painel; a defesa
    continua por aldeia).
29. **`P-SNIPE-TREM`** (§8.56, pedido do usuário em 2026-10-06): cortar trem
    de nobres inimigo pousando defesa atrás do 1º nobre. **Grátis:** só usa
    praça de reunião e cancelamento. F0 (guardar o ms da chegada, que o
    `incoming_commands()` hoje joga fora) e F1 (`ServerClock`) não enviam
    tropa e podem começar sem autorização. Registrado, sem prioridade definida.

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
