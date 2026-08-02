# Comparação: mecânicas reais do Tribal Wars vs. cobertura do bot

Pesquisa feita em 2026-08-02 comparando mecânicas documentadas do jogo (wiki oficial,
suporte Innogames, fórum) com o que o código do bot atualmente automatiza ou modela.
Objetivo: identificar lacunas concretas, não just achados genéricos. Cada item abaixo
cita o arquivo/linha do bot que foi checado.

**Fontes consultadas:**
- [Battles - Tribalwars Wiki EN](https://help.tribalwars.net/wiki/Battles)
- [World settings - Tribalwars Wiki EN](https://help.tribalwars.net/wiki/World_settings)
- [FAQ - Game Mechanics & Features (Innogames Support)](https://support.innogames.com/kb/TribalWars/en_DK/5970)
- [New Building Watchtower guide (fórum TW-US)](https://forum.tribalwars.us/index.php?threads/new-building-watchtower-guide.8042/)
- [What is a Paladin? (Innogames Support)](https://support.innogames.com/kb/TribalWars/en_DK/1192)

## 1. Moral, night bonus e sorte no simulador de PvP conquest

**Mecânica real:** combate em Tribal Wars aplica três modificadores multiplicativos
sobre a força de ataque: moral (penalidade quando o atacante tem muito mais pontos
que o defensor — quanto maior a diferença, maior a penalidade, incentivando não bater
em contas muito menores), night bonus (bônus de defesa em horário noturno configurado
por mundo, tipicamente +30-100% dependendo do world setting) e sorte (variação
aleatória, tipicamente ±25%). Esses três fatores stackam.

**O que o bot já modela:** `game/simulator.py:312-318` já implementa `moral`,
`nightbonus` e `luck` como parâmetros do simulador — a lógica matemática existe e
está correta (`moral /= 100`, `nightbonus = 2 if nightbonus else 1`).

**Gap encontrado:** `game/pvp_conquest.py:202-208` (`PvpConquestManager`, a única
função que atualmente chama `simulate()`) passa esses valores **hardcoded**:
`moral=100` (sem penalidade, sempre), `nightbonus=False` (sempre ignorado), `luck=0`
(sempre neutro). Ou seja, a simulação de batalha usada para decidir se vale a pena
conquistar um alvo PvP nunca reflete a realidade quando o alvo tem muito menos pontos
(deveria ter moral penalizada) ou quando o ataque chega em horário noturno do mundo.
Isso pode fazer o bot recomendar conquistas que na prática falhariam por moral baixa,
ou vice-versa.

**Sugestão:** calcular `moral` real a partir da razão de pontos atacante/defensor
(dados já disponíveis via `game_state`/reports) e `nightbonus` a partir do horário
do servidor + world setting de night bonus (checar se o mundo tem essa opção ativa
via `game.php?screen=info_player` ou settings do mundo). `luck` pode continuar 0
(neutro) como aproximação conservadora, já que é aleatório por natureza.

## 2. Igreja (Church) — influência de moral por raio geográfico

**Mecânica real:** em mundos com igreja ativa, tropas atacando/defendendo dentro do
raio de influência de uma igreja lutam com moral cheia; fora do raio (tanto origem
quanto destino), há penalidade adicional de moral. Isso é independente da penalidade
de pontos do item 1 — são dois modificadores de moral que se combinam.

**O que o bot faz hoje:** `church` aparece apenas como nome de building em
`webmanager/helpfile.py:117` (lista de construções para UI de config). Não há
nenhuma lógica em `game/`, `core/simulator.py` ou `game/zone_manager.py` que leia o
raio de influência de igrejas (próprias ou de outros jogadores) ou que ajuste
decisões de farm/ataque/conquista com base nisso.

**Sugestão:** baixa prioridade a menos que o servidor br143 tenha mundo com igreja
ativa — confirmar isso primeiro (world settings). Se ativo, é um refinamento do
`ZoneManager` (Feature 11, já existe clustering geográfico) e do simulador de PvP
conquest (Feature 13): cruzar coordenadas de aldeias-alvo com posições de igrejas
conhecidas antes de decidir atacar.

## 3. Watchtower — detecção antecipada de ataques

**Mecânica real:** a torre de vigia revela ataques chegando dentro de um raio (até
nível 20) antes que apareçam como "comando chegando" normal na visão geral,
oferecendo alerta mais cedo do que o padrão.

**O que o bot faz hoje:** `DefenceManager.update()` (`game/defence_manager.py`)
reage a `'no_ignored_command' in main`, que é o marcador padrão de "há um comando
não ignorado chegando" na tela de visão geral — não usa dados específicos de
watchtower (tempo de chegada, nome do atacante, `data-command-id`).

**Observação:** isso já está coberto pelo backlog — ver Feature 16 em
`docs/backlog.md` ("DefenceManager avançado"), que propõe exatamente usar
`data-endtime`/atacante/`data-command-id` para priorizar evacuação por urgência.
Nenhuma ação nova necessária aqui além de manter a prioridade dessa feature.

## 4. Paladin — unidade especial com experiência e equipamento

**Mecânica real (revisada em 2026-08-02 com detalhe do usuário, servidor br143):**
o Paladino é gerenciado pela tela `screen=statue` e é mais complexo do que a
avaliação inicial supunha:
- **Treino por XP:** botão dedicado ("Treinar por XP") converte recursos
  diretamente em XP do Paladino, como via alternativa ao ganho por combate e
  construção de edifícios. Decidir *quando* vale a pena gastar recursos nisso
  exige comparar contra a taxa normal de ganho de XP — não é um cálculo trivial.
- **3 árvores de skill:** Ofensiva, Aldeia (economia) e Defesa, com pontos de
  habilidade investidos por tier e **re-especialização disponível** (botão
  "Re-especialização") — ou seja, dá pra realinhar a build do Paladino ao
  perfil da aldeia onde ele mora (`village.profile`: `offensive`/`defensive`,
  já existente na config do bot).
- **Slots progressivos:** só existe 1 Paladino por conta inicialmente; slots
  adicionais desbloqueiam por número de aldeias conquistadas — 3, 5, 10, 20, 35
  aldeias no print do usuário, indo **até 100 aldeias** para os slots mais altos
  (confirmado pelo usuário, que joga no servidor). É um sistema de progressão de
  late-game, alinhado com o foco declarado do projeto (`CLAUDE.md`: "mid/late
  game").

**O que o bot faz hoje:** Paladino é reconhecido como tipo de unidade (excluído do
gather noturno em `game/troopmanager.py:413`, filtrado em `core/extractors.py:152`),
mas não há nenhuma leitura ou gerenciamento ativo de `screen=statue` — nem para
recrutar o Paladino inicial, nem treino por XP, nem skills, nem múltiplos slots.

**Sugestão:** revisada para prioridade média (era baixa) dado o potencial de
otimização de skills por perfil de aldeia e a progressão de slots em late-game —
mas ainda precisa de mais desenho antes de virar tarefa de implementação,
principalmente a economia de decisão do treino por XP (combate vs. construção vs.
recursos). Ver Feature 24 em `docs/backlog.md`.

## 5. Farm Assistant nativo (Plunder List) vs. lógica própria do bot

**Mecânica real:** o jogo oferece uma tela nativa (`screen=am_farm`) com lista de
alvos de farm pré-calculada pelo servidor, atualizada automaticamente com relatórios
recentes.

**O que o bot faz hoje:** `AttackManager` (`game/attack.py`) mantém sua própria
lógica de scoring de farm (`core/twstats.py`, `game/reports.py`), independente da
tela nativa `am_farm`. Não há uso da API nativa `screen=am_farm` em nenhum grep do
código (`get_url`/`get_api_*` para essa screen não aparece).

**Avaliação:** isso é uma escolha de design válida, não um bug — a lógica própria dá
mais controle (zonas, hunter, farm score customizado). Não é uma lacuna a corrigir,
só um ponto de comparação registrado para contexto.

## 6. Fila de construção e conta premium

**Mecânica real:** contas premium ativas aumentam o limite de fila de construção
simultânea (de 2 para mais).

**O que o bot faz hoje:** `game/buildingmanager.py:34` define
`max_queue_len = 2` como constante fixa, com o comentário "Can be increased with a
premium account" — mas não há leitura do status premium real da conta para ajustar
esse valor dinamicamente.

**Sugestão:** baixa prioridade. Se o servidor br143 tiver a conta com premium ativo,
detectar isso (a tela de visão geral geralmente expõe esse dado) e ajustar
`max_queue_len` dinamicamente evitaria deixar fila de construção subutilizada.

---

## Resumo priorizado (ver também docs/backlog.md Features 18+)

| # | Item | Prioridade | Esforço estimado |
|---|------|-----------|-------------------|
| 1 | Moral/night bonus dinâmicos no PvP conquest simulator | Alta — afeta decisão real de conquista PvP (Feature 13 já em campo) | Médio |
| 6 | Detecção de conta premium para `max_queue_len` dinâmico | Baixa | Pequeno |
| 2 | Suporte a igreja no ZoneManager/PvP conquest | Baixa (depende do mundo) | Médio-alto |
| 4 | Gerenciamento de Paladin (XP, arma) | Baixa | Médio |
| 3, 5 | Watchtower e Farm Assistant nativo | Sem ação — já cobertos (Feature 16) ou decisão de design válida | — |
