# Backlog — Features pendentes

Ordem de implementação até agora: `4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 18 → 19 → 20 → 21` (✅ todas)

## Feature 14 — Templates de tropas editáveis no webmanager

Nova página `/unit_templates`. Listar, criar, deletar e editar templates de
tropas (JSON em `templates/troops/*.txt`) inline no webmanager. Elimina a
necessidade de editar os arquivos `.txt` manualmente.

## Feature 15 — Seleção manual de alvo de conquista bárbara no webmanager

Botão "Definir alvo manual" na aba `/conquest`. Input de coordenadas ou ID.
Cria `cache/conquest/{id}.json` com status `manual`, sobrepondo a seleção
automática da Feature 8 (`ConquestManager.find_target()`).

## Feature 16 — DefenceManager avançado

Usar `data-endtime`, nome do atacante e `data-command-id` do HTML de overview
para priorizar evacuação por urgência (ataques chegando em minutos têm
prioridade sobre ataques em horas). Estende `DefenceManager.evacuate()` /
`update()`.

## Feature 17 — Relatório de império no webmanager

Dashboard em `/empire` com: total de tropas por tipo agregado (todas as
aldeias), gráfico de recursos por aldeia, mapa de calor de atividade de farm,
histórico de conquistas com timeline. Consome `cache/managed/*.json`,
`cache/attacks/*.json`, `cache/conquest/*.json`.

## Feature 18 — Moral e night bonus dinâmicos no simulador de PvP conquest ✅ Implementado (2026-08-02)

`PvpConquestManager` (`game/pvp_conquest.py:202-208`) chama `Simulator.simulate()`
com `moral=100`, `nightbonus=False`, `luck=0` fixos, mesmo o simulador já
suportando os três parâmetros corretamente (`game/simulator.py:312-318`). Isso
faz a decisão de conquista PvP (Feature 13, já em campo) ignorar a penalidade
real de moral por diferença de pontos e o bônus noturno de defesa do mundo,
podendo recomendar conquistas que falhariam na prática. Calcular moral real a
partir da razão de pontos atacante/defensor e nightbonus a partir do horário
do servidor + world setting. Ver `docs/game_comparison.md` item 1 para detalhe.

**Status:** implementado atrás de flag opt-in (`pvp_conquest.dynamic_moral_night_bonus`,
default `false`) — novo `core/world_config.py` lê `interface.php?func=get_config`
(endpoint público do mundo) para night bonus e moral (`mood.loss_max`), e
`Village.points` passou a ser persistido em `cache/managed/*.json` a cada ciclo
para dar o dado de pontos do atacante. **Fórmula de moral é aproximação
best-effort** (sem fórmula oficial pública) — aguardando validação de campo do
usuário antes de virar default `true`. Build version bumpada 2.3 → 2.4.

## Feature 19 — Página de status de bandeiras no webmanager ✅ Implementado (2026-08-02)

Não existe rota nem template no webmanager para visualizar o estado de
bandeiras por aldeia (`current_flag`, cooldown via `_can_change_flag`,
histórico de tentativas de upgrade). Especialmente relevante após o fix dos
Bugs 1 e 2 de bandeiras (ver `docs/bugs_flags.md`) — ter visibilidade no
dashboard ajudaria a validar em campo que os fixes funcionam sem precisar ler
logs brutos. Consumiria estado hoje só mantido em memória em `DefenceManager`
(considerar persistir em `cache/` se for exposto via webmanager, que roda
como processo separado).

**Status:** `Village.set_cache_vars()` (`game/village.py`) agora persiste um
bloco `"flags"` em `cache/managed/{village_id}.json` a cada ciclo — snapshot
de `current_flag`, `_flag_state_confirmed`, `_can_change_flag`,
`manage_flags_enabled`, bandeiras disponíveis no inventário (`self.flags`) e
`_upgrade_attempts` (achatado de tupla para string `"tipo:nível"`, já que
chaves de dict em JSON precisam ser string). Novo `FlagReader` em
`webmanager/utils.py` lê e formata esse bloco (nomes dos 8 tipos de bandeira
via `FLAG_TYPE_NAMES`, espelhando `game/defence_manager.py::FLAG_TYPES`).
Nova rota `/flags` e template `webmanager/templates/flags.html` — um card por
aldeia com bandeira atual, estado de cooldown, inventário de bandeiras e
tentativas de upgrade em curso, com aviso de que o dado reflete o último
ciclo concluído (não é live). Link adicionado na nav de `main.html`. Nenhuma
config nova — não foi necessário bumpar `build.version`.
**Limitação conhecida:** só mostra dados depois do primeiro ciclo completo de
cada aldeia; aldeias novas ou com `manage_flags_enabled: false` desde sempre
não aparecem/aparecem vazias até rodar.

## Feature 20 — Página de resource sharing no webmanager ✅ Implementado (2026-08-02)

`ResourceSharingManager` (`game/resource_sharing.py`, Feature 9) não tem
rota/template correspondente no webmanager — sem visibilidade de quanto
recurso foi transferido entre aldeias, quando, ou se houve falha por falta
de mercadores.

**Status:** `ResourceSharingManager` ganhou `_log_event()`, chamado em três
pontos de `run()` — envio bem-sucedido, envio que falhou no mercado
(`send_resources()` retornou `False`) e skip por falta de mercadores. Cada
evento é acrescentado a `cache/resource_sharing/history.json` (lista, capada
em 300 entradas). `cache/resource_sharing` foi adicionado à lista de
diretórios criados em `Twb.start()` (`twb.py`), e o próprio `_log_event()`
recria o diretório defensivamente antes de escrever. Novo `ResourceSharingReader`
em `webmanager/utils.py` lê e formata o histórico (nomes de aldeia via
`cache/managed/*.json`, timestamps formatados, motivo de falha traduzido) e
agrega o total enviado por recurso. Nova rota `/resource_sharing` e template
`resource_sharing.html` — mostra status/config atual (enabled, threshold_pct,
priority), totais agregados e uma tabela com o histórico recente (mais
recente primeiro). Link adicionado na nav. Nenhuma config nova.

## Feature 21 — Página de reports no webmanager ✅ Implementado (2026-08-02)

`ReportManager` (`game/reports.py`) lê e cacheia relatórios de ataque/defesa
em `cache/reports/*.json`, mas o webmanager não expõe essa informação em
nenhuma rota — só `/logs` (log de texto bruto) e `/farmscores`. Uma view
resumida de relatórios recentes (perdas, ganhos, `safe_to_engage`) ajudaria a
diagnosticar decisões do `AttackManager` sem abrir os JSONs manualmente.

**Status:** novo `ReportReader` em `webmanager/utils.py` lê `cache/reports/*.json`
e calcula, por relatório, um veredito ("Sem perdas" / "Perdas parciais" /
"Perda total" para ataques, "Seguro" / "Alvo com defesa" para scouts) com a
mesma lógica de `ReportManager.safe_to_engage`, mas aplicada por relatório
individual em vez de agregada por aldeia-alvo. Nova rota `/reports` (filtros
por aldeia-destino e tipo via query string) e template `reports.html` — cards
de estatísticas agregadas (total, ataques/scouts, sem perdas/com perdas, loot
total) mais uma tabela com os relatórios mais recentes primeiro. Link
adicionado na nav. Nenhuma config nova.
**Nota de segurança:** `cache/reports/` acumula estado real do jogo (não é
regenerável 1:1 — o jogo pode auto-deletar relatórios antigos da lista antes
que o bot os releia). Só leitura nesta feature, nenhuma escrita/limpeza nesse
diretório pelo webmanager.

## Feature 22 — Detecção de conta premium para fila de construção dinâmica

`BuildingManager.max_queue_len` (`game/buildingmanager.py:34`) é fixo em 2,
mas contas premium liberam mais slots de fila simultânea. Detectar o status
premium real (geralmente exposto na visão geral) e ajustar o limite
dinamicamente evita deixar fila de construção subutilizada. Baixa
prioridade — ver `docs/game_comparison.md` item 6.

## Feature 23 — Variância comportamental para automação mais "orgânica"

**Objetivo:** reduzir a assinatura de automação do bot variando o *quando* e
a *ordem* das ações — não o *o quê* (decisões de jogo continuam as mesmas).
Discutido em 2026-08-02: scraping adicional ou trocar para navegador headless
não têm ganho real aqui (o bot já manda as mesmas requisições HTTP/headers/
CSRF que um navegador real mandaria, e o Tribal Wars não tem fingerprinting
de JS/TLS pesado além do gate de captcha já tratado em `core/request.py`
via `data-bot-protect="forced"`). A alavanca real é comportamental.

**Base parcial já existente:**
- `delay_factor` + sleep aleatório 3–7s por requisição (`core/request.py`,
  `get_url`/`post_url`).
- `active_hours`/`active_delay`/`inactive_delay` com jitter de +20–120s por
  ciclo (`twb.py`), inclusive por aldeia (`village.active_hours` override).
- Pausa de 2s antes de recursão de upgrade de bandeira (fix do Bug 2, ver
  `docs/bugs_flags.md`).

**Lacunas:**
- Ordem de iteração das aldeias gerenciadas em `twb.py` é sempre a mesma
  sequência fixa a cada ciclo.
- Janela de delay é sempre a mesma faixa previsível — sem variação de
  "atenção" (ex: dias em que a reação demora mais, como aconteceria com um
  jogador humano ocupado).

**Proposta:**
1. Embaralhar a ordem de processamento das aldeias a cada ciclo em `twb.py`.
2. Jitter maior e configurável por aldeia (não só global) no delay entre
   ações.
3. Probabilidade baixa e configurável de "atraso de atenção" — um ciclo
   ocasional com reação bem mais lenta que o normal, simulando um jogador
   distraído.

**Cuidado importante:** NÃO aplicar esse jitter/atraso extra em
`DefenceManager` (reação a ataque recebido) nem em qualquer lógica de
segurança — humanização não pode comprometer a efetividade defensiva real.
Isolar essa variância nas ações não-críticas (farm, build, recruit, market).

**Prioridade:** depois das Features 18–22 (ordem confirmada pelo usuário em
2026-08-02).

## Feature 24 — Paladino (estátua): treino por XP, skills por perfil de aldeia e slots progressivos

Detalhe completo em `docs/game_comparison.md` item 4 (revisado em 2026-08-02
com prints do usuário). Resumo:
- `screen=statue` não é lido nem gerenciado pelo bot hoje — só existe como
  prédio na fila de construção (`buildingmanager`).
- **Treino por XP:** converte recursos em XP diretamente. Decidir quando vale
  a pena exige modelar a taxa de XP normal (combate + construção) contra o
  custo em recursos — não é trivial, precisa de mais desenho.
- **3 árvores de skill** (Ofensiva/Aldeia/Defesa) com re-especialização
  disponível — dá pra alinhar a build à `village.profile` (offensive/defensive)
  já existente na config.
- **Slots progressivos** por número de aldeias conquistadas (3, 5, 10, 20, 35,
  ..., até 100 aldeias confirmado pelo usuário) — sistema de late-game.

**Escopo proposto (fase 1, menor):** só leitura — expor estado do(s)
Paladino(s) (nível, XP, skills investidos, slots desbloqueados/bloqueados) no
webmanager, sem automação ativa.
**Escopo futuro (fase 2):** automatizar re-especialização por perfil de
aldeia e decidir treino por XP via threshold configurável.
**Prioridade:** depois da Feature 23. Fase 1 é pequena e escopada; fase 2
precisa de mais design antes de virar tarefa de implementação.

## Feature 25 — Catálogo e otimização de itens de inventário (boosts)

`Perfil > Inventário` (não coberto hoje, nem lido) tem itens obtidos via
missões/eventos: boosts percentuais de recursos por tipo (madeira/pedra/
ferro), possivelmente bandeiras, baús, medalhas. Segundo o usuário (2026-08-02),
os boosts variam bastante — percentual, recurso-alvo, tipo de bônus (ataque,
defesa, produção) — e precisam ser catalogados individualmente antes de dar
pra desenhar uma lógica de uso eficiente (ex: qual boost ativar e quando).

**Nota a confirmar:** os ícones de bandeira que aparecem no inventário podem
ser instâncias consumíveis do mesmo sistema já gerenciado por
`DefenceManager` (ver `docs/bugs_flags.md`) — ou um sistema totalmente
separado. Confirmar antes de desenhar a automação, pra não duplicar lógica.

**Prioridade:** depois da Feature 23/24. Precisa de levantamento mais
detalhado (usuário tem mais contexto de jogo aqui) antes de virar plano de
implementação — ainda não é uma tarefa pronta para começar.

---

## Pendências transversais (não são features novas, mas trabalho aberto)

- **Bugs do sistema de bandeiras** (`DefenceManager`) — corrigidos no código
  em 2026-08-02 (troca constante de bandeira e loop de upgrade), aguardando
  validação em campo. Bot ainda só reconhece tipos de bandeira 1 e 4 dos 8
  existentes no jogo — ver `docs/bugs_flags.md` para o mapeamento completo
  dos 8 tipos, ainda não implementado (`FLAG_TYPES`).
- Feature 12 (evacuação preventiva regional) — implementada, aguardando
  validação em campo.
- Feature 13 (PvP conquest) — implementada, aguardando validação em campo
  (requer nobles disponíveis no mundo atual). Ver Feature 18 acima para o
  refinamento de moral/night bonus no simulador usado por essa feature.
- Comparação de mecânicas reais do jogo vs. cobertura do bot — ver
  `docs/game_comparison.md` (pesquisa feita em 2026-08-02) para o raciocínio
  completo por trás das Features 18-22 acima, incluindo itens avaliados e
  descartados (watchtower e farm assistant nativo, já cobertos ou decisão de
  design válida).
- Levantamento de telas do jogo (`screen=`) já cobertas pelo bot vs. não
  cobertas, feito em 2026-08-02 a pedido do usuário (contexto: decidir se
  scraping adicional é necessário para a Feature 23). Cobertas: `overview`,
  `overview_villages`, `main`, `place` (+ `scavenge`/`scavenge_api`),
  `smith`, `train`, `snob`, `flags`, `market`, `report`, `map`, sistema de
  quests. Não cobertas em nenhum lugar do código: `info_player`, `am_farm`,
  `ally`, `forum`, `ranking`, `statue` (só como prédio na fila, sem lógica de
  Paladin — ver item 4 de `docs/game_comparison.md`), `inventory` (só
  checado como flag de world settings, nunca navegado).
  **Validado pelo usuário em 2026-08-02:** `statue` e `inventory` importam de
  fato — viraram Features 24 e 25. `info_player`, `am_farm`, `ally`, `forum`,
  `ranking` seguem sem uso confirmado por enquanto.
- **Sub-abas de `screen=place`** — o usuário notou que o bot pode não cobrir
  todas as sub-abas da Praça de Reunião. Conferido no código: `Comandos`
  (envio de ataque/suporte) e `Tropas` (`mode=units`) e `Coletando`
  (`mode=scavenge`/`scavenge_api`) estão cobertas. `Simulador` e `Modelos de
  tropas` não precisam de cobertura — o bot tem simulador próprio
  (`game/simulator.py`) e sistema de templates próprio (`templates/troops/*.txt`,
  ver Feature 14). `Coleta em Massa` — **confirmado pelo usuário em 2026-08-02:
  exclusivo de conta premium**, não vira feature (o bot já processa cada
  aldeia individualmente em loop, que é o efeito equivalente sem depender de
  premium).
- **Outras abas do Perfil** apontadas pelo usuário: `Tesouraria` — feature
  muito recente do jogo, adiada a pedido do usuário, sem feature registrada
  ainda. `Estatísticas` — não vira feature própria por ora, mas é candidata a
  fonte de dados para Feature 18 (cálculo de moral real) ou Feature 17
  (relatório de império) quando essas forem implementadas.
