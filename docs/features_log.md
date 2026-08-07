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
- 2026-08-07 — reserva de tropas não cobria todos os sistemas que comprometem
  tropas para conquista. `TroopManager.conquest_reserve` existia desde a
  Feature 8 (conquista bárbara automática) como um dict simples
  `{unit: qty}`, respeitado só pelo farm (`AttackManager.enough_in_village`)
  e pelo gather. Problema: era um valor único — quem escrevesse por último
  (`= {...}` / `= {}`) apagava qualquer reserva de outro dono. E o
  `PvpConquestManager` (Feature 13) nunca escrevia nele: ele decide as tropas
  do clear + escolta dos nobres em `_step_simulate()` mas só manda o ataque
  de verdade via `Hunter`, que pode disparar minutos a horas depois (o
  `send_time` é calculado de trás pra frente a partir do `arrival_time` pra
  sincronizar clear + nobres). Nessa janela inteira, nada impedia o farm
  normal (roda todo ciclo) ou a própria conquista bárbara de gastar essas
  mesmas tropas primeiro — e o `Hunter._send_attack()` não reconfere
  disponibilidade antes de disparar, só reenvia o dict de tropas gravado na
  hora do agendamento; se elas já não estiverem mais lá, o jogo rejeita
  (`error_box`) e o ataque agendado inteiro (clear ou trem de nobres) é
  marcado `failed`, desperdiçando a coordenação. Corrigido transformando
  `conquest_reserve` num dict aditivo por dono
  (`{owner_key: {unit: qty}}`, somado via
  `TroopManager.total_conquest_reserve()`):
  `ConquestManager` (Feature 8) agora usa a chave fixa `"barbarian_conquest"`
  (`.pop()`/atribuição só nessa chave, nunca mais `= {}` genérico);
  `PvpConquestManager` reserva sob `"pvp:{target_id}"` no exato momento em
  que registra os agendamentos no `Hunter` (`_reserve_troops`), e libera
  (`_release_reserve`, via `_maybe_release_reserve` chamado a cada ciclo em
  `_step_check_complete`) assim que os agendamentos `{target_id}_pvp_clear`/
  `{target_id}_pvp_nobles` no `Hunter` deixam de estar `pending` (enviados ou
  falhos) — com um fallback por tempo (`arrival_time + 3600s`) caso essa
  checagem alguma vez falhe em detectar a resolução. Reservas de donos
  diferentes na mesma aldeia agora coexistem sem se apagar. Testado
  isoladamente (aditividade, isolamento entre donos, farm respeitando o
  total agregado, liberação por schedule resolvido, liberação por timeout,
  idempotência do release).

- 2026-08-07 — escolta dos nobres calculada com as tropas da aldeia errada,
  mais dois bugs achados ao validar essa correção. Em
  `PvpConquestManager._step_simulate()`, o dict `escort_units` (tropas de
  escolta dos nobres) era calculado a partir das tropas da **aldeia de
  clear** (`clear_village.units.troops`), mas aplicado igual para o ataque de
  **cada** aldeia de nobre (`troops = dict(escort_units)`), mesmo que essa
  aldeia tivesse um mix de tropas completamente diferente (ou nem tivesse as
  mesmas unidades). Isso fazia o `Hunter` falhar ao disparar a escolta de um
  nobre específico por falta daquela unidade na aldeia dele. Corrigido
  movendo o cálculo de `escort_units` pra dentro do loop
  `for nvid in noble_villages`, usando `nv.units.troops` (tropas da própria
  aldeia do nobre) em vez das do clear.

  **Bug adicional achado ao escrever o teste desta correção:** `attacker_units`
  (tropas do ataque de clear, montadas logo acima de `escort_units` a partir
  de `clear_village.units.troops`) não excluía `"spy"`. Como
  `Simulator.attack_sum()` indexa toda unidade pelo dict `attack_pool`, que
  não tem entrada para `"spy"`, isso derrubava `_step_simulate()` com
  `KeyError: 'spy'` sempre que a aldeia de clear tivesse qualquer espião
  parado em casa — ou seja, praticamente sempre, já que `TroopManager`
  sempre reporta a contagem completa de tropas na aldeia. Esse crash nunca
  tinha aparecido em campo porque, até o bugfix do `extra["when"]` (acima),
  nenhum alvo de PvP conquest jamais saía de `pending_scout` pra chegar
  nesse código. Corrigido excluindo `"spy"` e `"snob"` de `attacker_units`
  (mesmo critério já usado em `escort_units`).

  **Segundo bug adicional, no próprio fix de reserva de tropas do commit
  anterior:** `PvpConquestManager._hunter_schedules_resolved()` procurava o
  schedule por chave exata (`schedules.get(f"{target_id}_pvp_{label}")`),
  mas a chave real gravada por `HunterReader.add_schedule()`
  (`webmanager/utils.py`) é `"{target_id}_{arrival_str}"` — o valor passado
  como `target_id` só fica salvo dentro do campo `"target_id"` de cada
  schedule, não como chave do dict. Isso fazia a busca nunca encontrar nada,
  o que (por design — schedule ausente conta como "já resolvido") liberava a
  reserva de tropas do PvP conquest **no ciclo seguinte ao agendamento**,
  antes mesmo do `Hunter` disparar os ataques — derrubando na prática a
  proteção que aquele fix inteiro deveria oferecer. Corrigido buscando pelo
  campo `"target_id"` de cada schedule em vez da chave do dict. Achado e
  corrigido só ao escrever um teste com o formato de chave realista — o
  teste anterior (do commit da reserva de tropas) usava um formato de chave
  simplificado/errado e por isso não pegou esse problema.

  **Incidente durante os testes (sem impacto real, mas registrado por
  transparência):** o teste isolado do fix de reserva de tropas do commit
  anterior (`_maybe_release_reserve`) usou o `target_id` real "38409" (o
  único alvo de PvP conquest configurado neste ambiente) pra ficar mais
  realista, e esse método persiste em `cache/pvp_conquest/{target_id}.json`
  de verdade — o teste fez backup/restore de `cache/hunter/schedules.json`,
  mas esqueceu de fazer o mesmo pra esse arquivo, deixando
  `cache/pvp_conquest/38409.json` com dados sintéticos do teste (inclusive
  `"noble_villages": []`, que nunca acontece de verdade nesse ponto do
  fluxo). Note que `cache/` é git-ignored, então isso nunca chegou a um
  commit — só existia localmente. Percebido ao revisar o arquivo real
  durante os testes deste fix (o conteúdo não batia com nenhum log real nem
  com a ausência de `cache/hunter/schedules.json`), confirmado como
  artefato de teste (sem processo do bot rodando, sem log de
  `PvpConquest`, sem schedule real no Hunter) e restaurado manualmente pro
  último estado real conhecido (`pending_scout`, sem aldeia de clear
  definida). Lição: testes que chamam métodos que persistem em cache real
  devem sempre usar IDs fictícios quando possível, ou fazer backup/restore
  de **todo** arquivo que o método sob teste possa tocar, não só do mais
  óbvio.

## Ambiente de referência

Python 3.13, Windows 10. Bot: `python twb.py`. Webmanager: `python server.py`
na pasta `webmanager/`, acesso em `http://127.0.0.1:5000/`.
