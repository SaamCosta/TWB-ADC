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

---

## Pendências transversais (não são features novas, mas trabalho aberto)

- **Bugs do sistema de bandeiras** (`DefenceManager`) — ver `docs/bugs_flags.md`.
  Bloqueia uso pleno dos 8 tipos de bandeira do jogo (bot hoje só reconhece
  tipos 1 e 4).
- Feature 12 (evacuação preventiva regional) — implementada, aguardando
  validação em campo.
- Feature 13 (PvP conquest) — implementada, aguardando validação em campo
  (requer nobles disponíveis no mundo atual).
