# Log de features implementadas (histórico, v11)

Detalhe de arquivo/config por feature, para consulta quando for necessário
entender o "porquê" de uma decisão passada. Não editar retroativamente —
registrar mudanças futuras como entradas novas.

### Feature 4 — Horários ativos por aldeia ✅
**Arquivo:** `twb.py` (`TWB.is_village_active_hours`)
Permite `active_hours` por aldeia em `config["villages"]`; `null` usa o global.

### Feature 5 — Farm score por eficiência loot/distância ✅
**Arquivos:** `game/attack.py`, `manager.py`
Score por farm baseado no loot médio; ordena alvos por `distância ÷ score`.
Cache: `cache/attacks/{id}.json` (`farm_score`, `attack_count`).

### Feature 6 — Herança de config por proximidade geográfica ✅
**Arquivo:** `game/village.py` (`apply_nearest_village_inheritance`)
Modos: `empire_ratio` (padrão), `nearest_village`, `global_template`.

### Feature 7 — Proporção configurável ofensiva/defensiva ✅
**Arquivo:** `game/village.py` (`get_needed_profile`)
```json
"inheritance": { "mode": "empire_ratio" },
"empire": { "offensive_ratio": 3, "defensive_ratio": 3 },
"profile_templates": {
    "offensive": { "building": "purple_predator_into_off", "units": "offensive" },
    "defensive": { "building": "purple_predator_into_def", "units": "defensive_1" }
}
```

### Feature 8 — Seleção automática de alvos de conquista bárbara ✅
**Arquivos:** `game/attack.py` (`ConquestManager`), `game/village.py`,
`game/troopmanager.py` (`conquest_reserve`)
Varre bárbaros, seleciona alvo por score, envia noble train de 4 com escolta
automática. Cache: `cache/conquest/{target_id}.json`
(status `train_sent` / `extra_pending` / `complete`).

### Feature 9 — Transferência automática de recursos entre aldeias ✅
**Arquivos:** `game/resource_sharing.py`, `game/resources.py::send_resources`,
`game/village.py::run_resource_sharing`

### Feature 10 — Agendamento de ataques coordenados (Hunter) ✅
**Arquivos:** `game/hunter.py`, `twb.py`
Webmanager `/hunter` — toggle, tabela de schedules, modal de criação, barra de
progresso.

### Feature 11 — Organização de aldeias em zonas geográficas ✅
**Arquivos:** `game/zone_manager.py`, `twb.py`, `game/village.py`
Cache: `cache/zones.json`. Webmanager `/zones` — mapa Canvas2D, slider de
radius, toggle enabled, badge de zona em `/villages`.
Validado em campo (20/06/2026).

### Feature 12 — Evacuação preventiva regional ✅ (aguardando validação)
**Arquivo:** `game/village.py::_check_zone_evacuation`
Quando N vizinhos na mesma zona são atacados simultaneamente, aciona
evacuação de unidades frágeis (snob, axe) antes que a aldeia atual seja
atacada.
```json
"evacuate_on_zone_attack": true,
"evacuate_fragile_units_on_attack": true,
"zone_attack_threshold": 1
```

### Feature 13 — Conquista PvP semi-manual ✅ (aguardando validação)
**Arquivos:** `game/pvp_conquest.py`, `twb.py`, `webmanager/utils.py`
(`PvpConquestReader`), `webmanager/server.py`, `webmanager/templates/pvp_conquest.html`,
`webmanager/helpfile.py`, `config.example.json`

Fluxo: `pending_scout` → `pending_sim` → `scheduled` → `complete`/`failed`.
Cache: `cache/pvp_conquest/{target_id}.json`.
```json
"pvp_conquest": {
    "enabled": false,
    "clear_ratio": 0.8,
    "min_attack_power": 50000,
    "nobles_per_target": 4,
    "arrival_buffer_seconds": 2,
    "scout_amount": 5
}
```
Nota: `clear_ratio: 0.8` = 80% das tropas disponíveis na aldeia ofensiva usadas
no clear; aumentar para `0.9` em alvos difíceis. `arrival_buffer_seconds: 2` é
o mínimo seguro — em mundos com lag de servidor alto, considerar 3-5s.

**Achado em campo (2026-08-07):** a razão real de "aguardando validação" nunca
progredir era o bug de `extra["when"]` descrito abaixo em "Bug fixes
acumulados" — `PvpConquestManager._find_scout_report()` nunca conseguia achar
o relatório de scout mais recente (mesmo já existindo relatórios válidos em
cache), então o alvo ficava travado para sempre em `pending_scout`. Corrigido
em `game/reports.py`; a partir do próximo scout processado pelo bot depois do
fix, o campo `when` passa a ser preenchido e o fluxo deve progredir
normalmente para `pending_sim` → `scheduled`. Relatórios já em cache (gerados
antes do fix) não são reprocessados retroativamente — o bot reenvia um scout
novo automaticamente quando não acha nenhum relatório utilizável.

### Bug fixes acumulados
- v8 — aldeias perdidas permaneciam na UI (`twb.py::get_overview`)
- v9 — `%d` aplicado em `village_id` string (`game/village.py`)
- v9 — primeira aldeia sem donor para herança (`game/village.py`)
- 2026-08-07 — `extra["when"]` (timestamp do relatório) nunca era preenchido:
  o jogo passou a renderizar a data da batalha localizada em pt-BR
  (`"ago. 07, 2026  05:14:58<span class="small grey">"`) em vez do formato
  antigo `"07.08.26 05:14:58<span class="small grey">"` que o regex de
  `game/reports.py::attack_report()` esperava. Confirmado por varredura: 0 de
  ~190 relatórios em `cache/reports/*.json` tinham o campo. Isso quebrava
  silenciosamente três coisas, sem nenhum erro/exceção visível: (1) a
  conquista PvP semi-manual (Feature 13, acima) — alvo travado para sempre em
  `pending_scout`; (2) a lealdade real extraída de relatório de noble
  (`game/attack.py::_get_real_loyalty`) — sempre caía no fallback matemático,
  nunca usava o valor real; (3) a otimização de "drenar" farms com recursos
  parados (`game/reports.py::has_resources_left`, usada por
  `AttackManager`) — nunca disparava. Corrigido com um novo regex (mais um
  mapa de abreviação de mês pt-BR → número) e fallback para o formato antigo,
  caso o jogo volte a usá-lo em outro idioma/skin. Validado com um fetch ao
  vivo de duas páginas de relatório reais (scout e attack) direto do br143 e
  um teste de integração rodando `ReportManager.attack_report()` de verdade
  contra esse HTML.

## Ambiente de referência

Python 3.13, Windows 10. Bot: `python twb.py`. Webmanager: `python server.py`
na pasta `webmanager/`, acesso em `http://127.0.0.1:5000/`.
