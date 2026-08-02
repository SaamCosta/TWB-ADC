# Backlog — Features pendentes

Ordem de implementação até agora: `4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13` (✅ todas)

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

## Feature 18 — Moral e night bonus dinâmicos no simulador de PvP conquest

`PvpConquestManager` (`game/pvp_conquest.py:202-208`) chama `Simulator.simulate()`
com `moral=100`, `nightbonus=False`, `luck=0` fixos, mesmo o simulador já
suportando os três parâmetros corretamente (`game/simulator.py:312-318`). Isso
faz a decisão de conquista PvP (Feature 13, já em campo) ignorar a penalidade
real de moral por diferença de pontos e o bônus noturno de defesa do mundo,
podendo recomendar conquistas que falhariam na prática. Calcular moral real a
partir da razão de pontos atacante/defensor e nightbonus a partir do horário
do servidor + world setting. Ver `docs/game_comparison.md` item 1 para detalhe.

## Feature 19 — Página de status de bandeiras no webmanager

Não existe rota nem template no webmanager para visualizar o estado de
bandeiras por aldeia (`current_flag`, cooldown via `_can_change_flag`,
histórico de tentativas de upgrade). Especialmente relevante após o fix dos
Bugs 1 e 2 de bandeiras (ver `docs/bugs_flags.md`) — ter visibilidade no
dashboard ajudaria a validar em campo que os fixes funcionam sem precisar ler
logs brutos. Consumiria estado hoje só mantido em memória em `DefenceManager`
(considerar persistir em `cache/` se for exposto via webmanager, que roda
como processo separado).

## Feature 20 — Página de resource sharing no webmanager

`ResourceSharingManager` (`game/resource_sharing.py`, Feature 9) não tem
rota/template correspondente no webmanager — sem visibilidade de quanto
recurso foi transferido entre aldeias, quando, ou se houve falha por falta
de mercadores.

## Feature 21 — Página de reports no webmanager

`ReportManager` (`game/reports.py`) lê e cacheia relatórios de ataque/defesa
em `cache/reports/*.json`, mas o webmanager não expõe essa informação em
nenhuma rota — só `/logs` (log de texto bruto) e `/farmscores`. Uma view
resumida de relatórios recentes (perdas, ganhos, `safe_to_engage`) ajudaria a
diagnosticar decisões do `AttackManager` sem abrir os JSONs manualmente.

## Feature 22 — Detecção de conta premium para fila de construção dinâmica

`BuildingManager.max_queue_len` (`game/buildingmanager.py:34`) é fixo em 2,
mas contas premium liberam mais slots de fila simultânea. Detectar o status
premium real (geralmente exposto na visão geral) e ajustar o limite
dinamicamente evita deixar fila de construção subutilizada. Baixa
prioridade — ver `docs/game_comparison.md` item 6.

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
