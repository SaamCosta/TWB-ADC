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
    "defensive": { "building": "purple_predator_into_def", "units": "defensive_1",
                   "support_others": true }
}
```

**Revisão 2026-08-08 — `profile_templates` passou a ser aplicado sempre.**
Antes, os overrides só entravam quando *não* havia doador com o perfil
necessário (`used_profile_template`). Como o filtro de doador acha um assim que
existe uma aldeia de cada perfil, na prática o template quase nunca era
consultado: a aldeia nova herdava o config do doador verbatim, e uma chave nova
no template só chegaria às futuras se fosse propagada à mão em cada doador.

Agora `profile_templates[perfil]` é a fonte da verdade para o que *define* o
perfil; as demais chaves continuam vindo do doador. Foi o que permitiu
`support_others: true` no perfil defensivo: aldeia conquistada e classificada
como defensiva já nasce enviando suporte, mesmo com o doador em `false`.

⚠️ As aldeias defensivas **já existentes** seguem com `support_others: false`
de propósito — o envio de suporte real nunca aconteceu neste projeto (ver P1-6
no Lote 3 da auditoria) e a estreia fica numa aldeia nova só, sob observação.

Não cobre o caminho "nenhum doador disponível" (`candidates` vazio,
[`village.py`](../game/village.py) — primeira aldeia gerenciada), que usa
`village_template` e ignora `profile_templates`. Inalcançável com aldeias já
em cache; deixado como está.

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

- 2026-08-07 — `PvpConquestManager` rodava tarde demais e devagar demais.
  Até este fix, `twb.py` chamava `PvpConquestManager.run()` uma única vez
  por volta completa do loop, **depois** do farm de todas as aldeias já ter
  sido enviado naquela volta e **depois** do `time.sleep()` entre ciclos —
  ou seja, num bot recém-iniciado, o primeiro cycle inteiro (processamento
  de aldeias + farm + sleep de minutos) passava sem o PvP Conquest sequer
  ser avaliado uma vez. Feedback do usuário: a lógica de dominância do jogo
  é o oposto disso — uma vez que a conquista está em andamento, ela deve ter
  prioridade sobre o farm rotineiro, exatamente como a conquista bárbara
  (`ConquestManager`, Feature 8) já faz (`Village.run_conquest()`, chamado
  antes de `run_farming()` dentro do próprio `Village.run()`). Corrigido em
  duas partes:
  1. **Reordenação** (`game/village.py`, `twb.py`): criado
     `Village.run_pvp_conquest()`, no mesmo lugar de `run_conquest()`, logo
     antes de `run_farming()` — ou seja, dentro do `Village.run()` de cada
     aldeia, não mais como uma chamada solta no fim do loop do `twb.py`.
     Isso garante que roda em **toda** volta, inclusive a primeira depois do
     bot iniciar (nesse ponto do `run()`, `self.units`/`self.area` já foram
     carregados por chamadas anteriores no mesmo método) e sempre antes do
     farm daquela mesma aldeia. `twb.py` agora monta
     `managed_villages_dict` (aldeias gerenciadas) **antes** do loop de
     processamento de aldeias e atribui em `village.pvp_conquest_villages`
     de cada uma, espelhando o padrão já usado para `defense_states` /
     `hunter.villages` — `PvpConquestManager` continua escolhendo aldeia de
     clear/nobres considerando o império inteiro, não só a aldeia que
     disparou a chamada. O bloco antigo no fim do loop (pós-sleep) foi
     removido.
  2. **Encadeamento de passos** (`game/pvp_conquest.py::run()`): antes,
     cada alvo avançava no máximo um passo (`pending_scout` →
     `pending_sim`, por exemplo) por chamada, mesmo que o passo seguinte já
     estivesse pronto para rodar na mesma chamada (ex: relatório de scout
     já disponível em cache no instante em que `_step_scout` roda). Agora
     `run()` encadeia um alvo por quantos passos estiverem prontos dentro
     da mesma chamada (`MAX_STEPS_PER_CALL = 4`, cobre
     `pending_scout → pending_sim → scheduled → check_complete` com folga),
     parando assim que um passo não muda o status (esperando algo externo,
     como o relatório chegar) ou cai num status terminal
     (`complete`/`failed`).
  Testado isoladamente com um `PvpConquestManager` real e os três `_step_*`
  mockados (verificado: encadeia os três passos numa chamada só; para
  quando um passo não avança; ignora status terminal sem erro; o guard
  `MAX_STEPS_PER_CALL` corta um loop patológico simulado). Sintaxe e import
  de `game/village.py`, `twb.py` e `game/pvp_conquest.py` verificados após
  a mudança. **Ainda não validado em campo** — precisa reiniciar o processo
  do bot pra carregar o código novo (processos já rodando continuam com a
  ordem antiga em memória até serem reiniciados).

- 2026-08-07 — trem de nobres do PvP Conquest desperdiçava nobres parados.
  `_select_noble_villages(max_count)` escolhia até `nobles_per_target`
  **aldeias** distintas com pelo menos 1 nobre e mandava exatamente 1 nobre
  de cada — uma aldeia só podia contribuir com 1 ataque, não importa quantos
  nobres tivesse sobrando. Com um único alvo real testado (38409), a aldeia
  41123 tinha 6 nobres disponíveis e só 1 foi comprometido no agendamento.
  Diagnosticado com a correção do usuário: em Tribal Wars a lealdade só cai
  uma vez por batalha, não importa quantos nobres estejam no mesmo ataque —
  então empilhar nobres num ataque só é desperdício. O jeito certo de usar
  vários nobres é mandar vários **ataques separados**, cada um com
  exatamente 1 nobre, convergindo pro mesmo horário de chegada — podem vir
  de aldeias diferentes ou da mesma aldeia disparando comandos de ataque
  distintos. Corrigido: `_select_noble_villages` virou
  `_select_noble_attack_plan(max_count)`, que devolve uma lista de até
  `max_count` entradas (uma por nobre disponível, não por aldeia), podendo
  repetir a mesma aldeia várias vezes se ela tiver mais de um nobre. O loop
  que monta `noble_attacks` já dividia a escolta por `noble_count =
  len(noble_villages)` (agora = total de ataques, não de aldeias únicas),
  então repetir a mesma aldeia várias vezes continua sem estourar o total de
  tropas dela — testado isoladamente (7 checks: plano trava no teto mesmo
  com mais nobres disponíveis, drena aldeias com poucos nobres antes de
  passar pra próxima, pula aldeia com 0 nobres, e o total de escolta
  comprometido por uma aldeia que contribui múltiplos ataques não ultrapassa
  `escort_ratio` dela). **Não retroativo**: o alvo 38409 já estava com
  `status: "scheduled"` e `noble_villages: ["41123"]` (1 nobre) gravados
  *antes* desse fix — como `_step_simulate()` só roda quando o status é
  `pending_sim`, essa correção não se aplica automaticamente ao que já foi
  agendado; precisa de intervenção manual pra recalcular esse alvo
  específico com o plano novo antes do Hunter disparar (arrival 10:30, ainda
  sem `send_time` calculado no momento deste registro).

- 2026-08-07 — Paladino (`"knight"`) vazava pro clear e pra escolta de
  nobre do PvP Conquest. `attacker_units` (clear) e `escort_units` (escolta)
  só excluíam `"spy"`/`"snob"` das tropas da aldeia — qualquer Paladino
  parado em casa entrava automaticamente. Com o fix do trem de nobres
  (acima, commit `d2875f0`) isso ficou pior: o piso `max(1, ...)` da
  escolta força pelo menos 1 unidade de cada tipo por ataque, e como o
  Paladino é sempre 1 por aldeia, 4 ataques separados da mesma aldeia
  pediam `knight: 1` **cada um** — 4 no total contra 1 disponível de
  verdade, o que faria pelo menos 3 desses 4 ataques falharem quando o
  Hunter disparasse. Correção pedida pelo usuário: o Paladino nunca deve
  sair da aldeia automaticamente, só em situações específicas de limpeza
  escolhidas manualmente — o bot não tem como julgar isso sozinho, então a
  resposta certa é simplesmente nunca incluí-lo, não tentar acertar a conta
  de quantos "cabem". Corrigido excluindo `"knight"` junto com
  `"spy"`/`"snob"` nos dois pontos (`attacker_units` e `escort_units`).
  Verificado isoladamente (replicando as duas comprehensions com o troop
  dict real: `knight` não aparece em nenhum dos dois dicts resultantes).
  Alvo `38409` resetado de novo (`status: "scheduled"` → `"pending_sim"`,
  `noble_villages` removido) pra recalcular sem o Paladino assim que o bot
  reiniciar com o código novo — mesma mecânica do reset anterior.

- 2026-08-07 — **bug crítico, raiz de tudo**: nenhum ataque agendado pelo
  PvP Conquest jamais conseguiria disparar de verdade, desde a primeira
  versão da integração com o Hunter (Feature 13, commit `41c353a`).
  Descoberto ao ler o log real depois de reiniciar o bot com todos os fixes
  de hoje: `Hunter: target 38409_pvp_clear not in map_pos for village
  41123` (e o mesmo para `38409_pvp_nobles`, repetido pra cada ataque).
  Causa: `PvpConquestManager._hunter_add_schedule()` passava
  `target_id=f"{target_id}_pvp_{label}"` (ex: `"38409_pvp_clear"`) pro
  `HunterReader.add_schedule()`, que grava esse valor **literalmente** no
  campo `"target_id"` do schedule — e é esse mesmo campo que
  `Hunter.run()` (`game/hunter.py`) usa tanto pra sondar a duração da
  viagem (`village.area.map_pos[target_id]`) quanto pra disparar o ataque
  de verdade (`village.attack.attack(target_id, ...)`). Nenhum dos dois
  funciona com uma string tipo `"38409_pvp_clear"` — `map_pos` só tem IDs
  reais de aldeia como chave. Resultado: a sondagem de duração falhava
  pra sempre (o warning acima, repetido todo ciclo), `send_time` nunca era
  calculado, e mesmo que fosse, `AttackManager.attack()` tem o mesmo
  check (`if vid not in self.map.map_pos: return False`) e teria
  rejeitado o ataque de qualquer forma. O sufixo `_pvp_{label}` existia só
  pra `_hunter_add_schedule()` conseguir distinguir os dois schedules
  (limpeza vs. trem de nobres) do mesmo alvo — motivo legítimo, execução
  errada: em vez de afetar só a chave interna do cache
  (`sched_key`), acabou virando o `target_id` real usado pelo Hunter pra
  agir no jogo. Esse mesmo valor quebrado também alimentou o bug do
  `_hunter_schedules_resolved()` corrigido mais cedo hoje (o "achar por
  campo target_id" simplesmente reencontrava a mesma string quebrada).
  Corrigido em duas pontas:
  1. `webmanager/utils.py::HunterReader.add_schedule()` ganhou um parâmetro
     `label=None` opcional. O `target_id` gravado agora é sempre o ID real
     da aldeia; o rótulo (`"clear"`/`"nobles"`) vira um campo `"label"`
     separado, e só afeta `sched_key` (garante que limpeza e trem de
     nobres nunca colidam na mesma chave, mesmo se
     `arrival_buffer_seconds` fosse configurado como 0 — antes disso só
     era garantido pelo sufixo agora removido).
  2. `game/pvp_conquest.py::_hunter_add_schedule()` passa `target_id` real
     + `label=label`. `_hunter_schedules_resolved()` atualizado pra casar
     por `target_id` real **e** `label in ("clear", "nobles")` juntos, em
     vez de reconstruir a string suja antiga.
  Testado isoladamente com um `HunterReader.add_schedule()` real
  apontando pra um arquivo temporário (nunca tocou o cache real): 9
  checks — `target_id` gravado é o real, `label` fica separado, limpeza +
  nobres com o mesmo `arrival_str` não colidem na mesma chave,
  `_hunter_schedules_resolved()` responde certo enquanto pendente e depois
  de resolvido. Limpeza manual necessária no ambiente real: os dois
  schedules quebrados de `38409` (`38409_pvp_clear_...`,
  `38409_pvp_nobles_...`, ambos com `target_id` sujo, nunca poderiam ter
  disparado) removidos de `cache/hunter/schedules.json`; alvo `38409`
  resetado mais uma vez pra `pending_sim` pra recalcular do zero com o
  código corrigido assim que o bot reiniciar.

- 2026-08-07 — **falha real em campo, primeira execução ponta a ponta do
  fluxo completo**: com todos os fixes acima já rodando, o alvo `38409`
  chegou a `scheduled` e o Hunter disparou de verdade pela primeira vez.
  Os 4 ataques de nobre saíram OK (`09:41:15`-`09:43:34`, todos `[REAL] ...
  OK`). O clear falhou (`09:59:17`, `[REAL] ... FAILED`) — a confirmação no
  jogo voltou com `error_box` (tropa insuficiente) e o `Hunter` marcou o
  schedule como `complete` sem reenviar.
  Causa: `attacker_units` (clear, `clear_ratio` padrão 0.8) e `escort_units`
  (escolta somada dos nobres, `escort_ratio` padrão 0.5) eram calculados
  **cada um independente do outro**, como fração do total bruto de tropas
  da aldeia — 0.8 + 0.5 = **130% das tropas que existem**. Como a aldeia de
  clear e a dos 4 nobres eram a mesma (`41123`, único village gerenciado),
  e os nobres (mais lentos, por causa do `snob`) precisavam sair primeiro
  (`09:40:30` vs `09:58:51` do clear), eles consumiram a fatia deles
  primeiro, deixando tropa insuficiente pro clear quando a vez dele chegou
  — confirmado batendo os números reais do log (`spear/sword/axe/light`
  disponíveis em `09:45`/`09:53` vs o que o clear tentou mandar em
  `09:59:17`, diferença batendo quase exata com o que os 4 escoltas
  consumiram). O sistema de reserva de tropas (protege contra farm e
  conquista bárbara) não pega esse caso: ele protege contra *outros*
  sistemas roubarem tropa reservada, não contra o próprio PvP Conquest
  reservar mais do que existe entre suas duas ondas.
  Corrigido em `game/pvp_conquest.py::_step_simulate()`: ao montar o
  `escort_units` de cada aldeia de nobre, se essa aldeia também for a
  `clear_vid`, o `attacker_units` já reservado por ela é subtraído do total
  bruto **antes** de aplicar `escort_ratio` — garantindo que as duas
  reivindicações somadas nunca passem de 100% do que a aldeia realmente
  tem. Não cobre (ainda) o caso de uma mesma aldeia estar comprometida com
  *múltiplos alvos* de PvP Conquest simultâneos — só um alvo estava ativo
  neste ambiente.
  Testado isoladamente reproduzindo os números reais do incidente (troca
  de tropas de 41123 no momento do agendamento): confirma que, com o fix,
  clear + escolta somados nunca ultrapassam o disponível pra
  spear/sword/axe/light, e um teste de sanidade confirma que a lógica
  antiga realmente estourava (axe: 4391 pedido vs 3379 disponível — bate
  com o real).
  **Consequência prática deste incidente específico**: sem impacto — o
  usuário já tinha limpado a aldeia alvo manualmente antes (deve haver
  relatório do ataque manual no jogo), então a ausência do clear automático
  não deveria comprometer os 4 nobres já a caminho (chegada `10:30:00`).

### Bugfix (2026-08-07) — primeira conquista PvP real, validação de ponta a ponta ✅

Após os fixes anteriores (ordenação, multi-nobre, Paladino, target_id/label,
over-commitment — ver entradas acima), o alvo `38409` foi conquistado de
verdade pela primeira vez neste projeto. A validação em campo revelou mais
quatro bugs, todos em código que nunca tinha sido exercitado contra uma
conquista real (só contra simulações/ataques que falharam antes de chegar
até aqui):

**1. `self.villages` nunca sincronizava com aldeias novas (`twb.py`)**
`self.villages` (lista de objetos `Village` processados a cada ciclo) era
montada **uma única vez**, antes do `while self.should_run:`, a partir do
`config["villages"]` que existia no momento em que o processo iniciou.
`get_overview()` → `add_village()` (com `bot.add_new_villages: true`) grava
aldeias novas (achadas ou conquistadas) direto em `config.json` a cada
ciclo, mas nunca criava um `Village` nem dava `self.villages.append(...)`.
Resultado: uma aldeia recém-conquistada ficava só "no papel" — nunca
entrava em `processing_order`, então nunca era gerenciada (sem construção,
sem tropa, sem farm) até reiniciar o processo manualmente. Corrigido
sincronizando `self.villages` com `config["villages"]` a cada ciclo, logo
após `get_overview()`: qualquer `vid` novo ganha um `Village` na hora,
igual ao loop de startup.

**2. `village_template.inherit_on_first_run` divergente do exemplo**
`config.json` local tinha `false` (deveria ser `true`, como já era em
`config.example.json`), então toda aldeia nova nascia com `profile: null`
em vez de rodar `apply_nearest_village_inheritance()` (Feature 6/7) e virar
`offensive`/`defensive` pela proporção configurada. Corrigido no
`village_template` (futuras aldeias) e pontualmente na entrada já existente
de `38409` (que ainda não tinha rodado `Village.run()` por causa do bug 1).
Resultado real: `38409` virou `profile: "defensive"` — bateu com a proporção
`empire.offensive_ratio: 1 / defensive_ratio: 3`.

**3. Detecção de posse sempre falhava silenciosamente (`game/pvp_conquest.py`,
`game/attack.py`)**
`PvpConquestManager._step_check_complete()` e `ConquestManager._target_is_mine()`
liam `self.wrapper.player_id` / `self.wrapper.game_state` para descobrir o
próprio player_id — atributos que **nunca existiram** em `WebWrapper` (só
existem em objetos por-aldeia como `Village.game_data`,
`BuildingManager.game_state`). O `hasattr()` sempre dava `False`, o fallback
sempre levantava `AttributeError`, capturado por um `except` que só fazia
`return`/`return False` **sem logar nada**. Consequência: mesmo com `38409`
100% conquistada (confirmado via `cache/villages/38409.json` com
`owner` batendo com a aldeia própria `41123`), o status em
`cache/pvp_conquest/38409.json` ficava travado em `"scheduled"` pra sempre,
e o painel `/pvp_conquest` do webmanager nunca refletia a conquista.
Corrigido lendo o `owner` de uma aldeia já sabidamente própria em
`cache/villages/{id}.json` em vez de depender do wrapper — em
`PvpConquestManager`, novo helper `_own_player_id()` varre `self.villages`;
em `ConquestManager` (que só conhece a própria `self.village_id`), lê
diretamente `cache/villages/{self.village_id}.json`. `conquest.enabled` é
`false` neste projeto, então o bug em `attack.py` ainda não tinha se
manifestado, mas é o mesmo padrão morto — corrigido junto.
Testado isoladamente contra o cache real (`38409`): `_own_player_id()`
retorna `5955651`, batendo com o owner real do alvo.

**4. Confirmação de leitura de bandeira presa a um regex específico
(`game/defence_manager.py::manage_flags()`)**
`self._flag_state_confirmed = True` só era setado dentro de
`if get_current_flag:` (regex que exige uma bandeira **equipada** com
imagem `/(\d+)_(\d+)\.png`). Uma aldeia sem nenhuma bandeira equipada
(comum logo após conquista) nunca casa esse regex, então a confirmação
nunca acontecia — mesmo com a página `screen=flags` lida e parseada com
sucesso todo ciclo (log mostra `Managing flags` sem warning). O painel
`/flags` do webmanager mostrava "Estado ainda não lido" permanentemente
pras duas aldeias geridas. Corrigido movendo a confirmação pra logo depois
que `get_flag_data` (o parse geral da página) tem sucesso, independente de
haver ou não uma bandeira equipada no momento.

**5. Timeline de conquistas do `/empire` só lia o sistema errado
(`webmanager/utils.py`, `webmanager/server.py`, `webmanager/templates/empire.html`)**
`EmpireReader.conquest_timeline()` só agregava `ConquestReader.load()`
(conquista bárbara, Feature 8) — que fica sempre vazio neste projeto porque
`conquest.enabled: false`. O sistema realmente ativo é o PvP Conquest
(Feature 13), e uma conquista real e confirmada (`38409`) nunca aparecia
ali; o texto de "vazio" ainda apontava pro `/conquest` (sistema não usado).
Adicionado `EmpireReader.pvp_conquest_timeline_entries()`, que normaliza a
saída de `PvpConquestReader.load()` pro mesmo formato de
`ConquestReader.load()` (rótulos prefixados com `"PvP:"`); `conquest_timeline()`
agora mescla as duas fontes por timestamp. `PvpConquestReader.load()` passou
a expor `scheduled_at`/`completed_at` (antes só usados internamente) pra
servir de timestamp de ordenação. Empty-state do template atualizado pra
citar `/pvp_conquest` também.

**6. Tooltip do mapa de calor do `/empire` desalinhado com os marcadores
(`webmanager/templates/empire.html`)**
O canvas fixa seu sistema de coordenadas interno (`W`/`H`, usado por
`toPx()`) uma única vez no carregamento da página, medindo
`parent.clientWidth` naquele instante. O CSS (`width:100%`) deixa o
elemento renderizado esticar/encolher com qualquer mudança de layout depois
disso (resize, zoom, sidebar) — só que o handler de `mousemove` comparava a
posição do mouse (via `getBoundingClientRect()`, tamanho *renderizado*)
direto contra `toPx()` (espaço *interno*, fixo), sem reconciliar os dois.
Resultado visual: passar o mouse perto de um alvo, mas não exatamente em
cima, ainda disparava o tooltip de outro ponto. Corrigido escalando
`mx`/`my` pela razão `canvas.width / rect.width` (e o equivalente em Y)
antes de comparar contra `toPx()` — padrão usual de hit-test em canvas,
robusto a qualquer mudança de layout depois do desenho inicial.

**Consequência prática:** nenhuma das seis correções mexe em envio de tropa
ou lógica de ataque em si — são detecção de posse, sincronização de estado
em memória, um valor de config e leitura/exibição no webmanager. Todos os
arquivos tocados compilam limpo (`python -m py_compile`); a correção do
item 3 foi testada isoladamente contra o cache real do alvo `38409`.

### Bugfix (2026-08-07, continuação) — mais 3 achados na validação em campo ✅

Depois do restart com os seis fixes acima, o usuário seguiu observando o bot
com as duas aldeias (`41123`, `38409`) e o painel `/conquest` (conquista
bárbara, ligada nesta sessão pelo usuário) ao vivo, e mais três problemas
reais apareceram:

**7. Detecção de bandeira equipada sempre falhava (`.png` vs `.webp`)**
Mesmo depois do fix #4 (confirmação de leitura), a `38409` continuava
mostrando "Nenhuma bandeira equipada" — só que ela **tinha** uma bandeira
equipada de verdade (usuário confirmou: atribuída manualmente por ele no
jogo, não pelo bot). Buscando a página `screen=flags` ao vivo (sessão do
bot via `requests`), confirmado: a imagem da bandeira é servida como
`.../graphic/flags/big/1_7.webp`, mas o regex de detecção
(`get_current_flag` em `manage_flags()`) procurava especificamente `.png` —
nunca dava match. A `41123` só parecia certa "por acidente": o bot mesmo
tinha atribuído a bandeira dela nesse ciclo, e `flag_set()` grava
`self.current_flag` direto em memória, sem depender desse regex. Qualquer
aldeia com bandeira **não** atribuída pelo bot (herdada, atribuída
manualmente, ou sobrevivendo de antes de qualquer fix) ficaria com o mesmo
problema. Corrigido trocando `\.png` por `\.\w+` no regex (aceita qualquer
extensão, presente ou futura). Testado contra o HTML real de `38409`
(fetch direto via sessão do bot): regex antigo não casava, o novo casa e
extrai `flag_type=1, level=7` corretamente.

**8. Fórmula de pontuação do `priority: "fill_gaps"` dominada por pontos,
ignorando distância na prática (`game/attack.py::ConquestManager._score_target()`)**
Usuário perguntou por que a conquista bárbara escolheu um alvo a 11.2 tiles
de distância e cancelou o noble train manualmente. Causa: os pesos
60%/30%/10% (comentados no código) eram aplicados direto sobre valores
brutos — distância varia 0–20 (`max_radius`), pontos varia 0–1100
(`max_points`). O termo de pontos (`pts * 0.1`, até 110) dominava
completamente os termos de distância (até ~18 combinados), fazendo a
seleção na prática ignorar proximidade e escolher sempre a bárbara com mais
pontos dentro do raio. Confirmado rodando a pontuação real pra todos os
candidatos: uma aldeia a **1.4 tiles** (`44683`, 364 pts) perdeu pra uma a
**11.2 tiles** (`39158`, 1002 pts, a escolhida/cancelada) por larga margem.
Corrigido normalizando distância (`dist / max_radius`) e pontos
(`pts / max_pts`) pra escalas comparáveis 0–1 antes de aplicar os pesos —
agora os 60/30/10% do comentário valem de verdade. Testado com os dados
reais do ambiente: `44683` (1.4 tiles) passa a vencer com folga
(score 0.052 vs 0.42 da `39158`), e a ordem geral passa a seguir
proximidade primeiro, pontos como desempate.

**9. `/conquest` não tinha como limpar um alvo já em andamento/completo**
Consequência prática do achado 8: o cache `cache/conquest/39158.json`
(status `train_sent`, 4/4 nobles) ficou órfão depois do usuário cancelar o
noble train manualmente no jogo — `ConquestReader.cancel_manual()` (usado
pelo botão "Cancelar" existente) bloqueia de propósito esse caso
(`status not in ("manual", "invalid")` levanta `ValueError`), porque
normalmente apagar o cache de uma conquista em andamento só esconderia o
acompanhamento de nobles genuinamente em rota. Mas não havia nenhuma opção
pra o caso oposto: usuário já tratou a situação fora do bot e só quer
limpar o registro órfão. Adicionado `ConquestReader.force_clear()` (remove
o cache incondicionalmente, qualquer status), rota nova `action=force_clear`
em `/conquest` (`webmanager/server.py`), e botão "Limpar" em
`conquest.html` pra qualquer status que não seja `manual`/`invalid` (esses
continuam usando "Cancelar", que já tinha a validação certa). Alvo `39158`
limpo manualmente nesta sessão como consequência direta.

**Consequência prática:** achado 7 é leitura/parsing, sem risco de tropa.
Achado 8 muda qual alvo bárbaro `ConquestManager` escolhe automaticamente —
revisado com cautela extra por mexer em `game/attack.py` (ver convenção do
projeto), mas o escopo é só seleção de alvo, não envio/quantidade de tropa.
Achado 9 é feature nova de webmanager (limpeza de cache), sem nenhuma ação
de jogo. Todos os arquivos tocados compilam limpo; achados 7 e 8 testados
contra dados reais do ambiente (HTML ao vivo da `38409` e pontuação de
todos os candidatos bárbaros em cache).

### Sessão 2026-08-11 — fecho das lacunas da validação de campo da Feature 13 ✅

Três mudanças, nenhuma validada em campo ainda. As duas últimas fecham o
**Lote 6** da auditoria (`docs/auditoria_codigo_2026-08-08.md`), que passa a ter
19 dos 20 P2 resolvidos — resta só o P2-29, bloqueado por falta de amostra do
`<mood>` real do servidor.

**1. Trem de nobres falhado agora é detectado** (`c45a6e8`,
`game/pvp_conquest.py` + webmanager). Era o último item aberto da lista de
lacunas deixadas pela validação ao vivo da `38409` (seção acima).
`_step_check_complete()` só transicionava `"scheduled"` → `"complete"` na
mudança de dono; se o train chegava e a conquista não acontecia, o alvo ficava
`"scheduled"` para sempre. Como só `_maybe_release_reserve()` tinha fallback
por tempo, a tropa era liberada **enquanto o status mentia** que o ataque
seguia em voo. Novo `_maybe_mark_failed()`: passada a tolerância
(`FAILED_GRACE_SECONDS = 7200`), vira `"failed"` com `failed_at` e um
`fail_reason` que separa "checamos e não é nossa"
(`train_arrived_no_conquest`) de "não deu para checar"
(`train_outcome_unknown`). A tolerância é maior que o fallback de 1h da reserva
de propósito: a posse só fica visível quando um scan de mapa atualiza
`cache/villages/{id}.json`, guiado pelo ciclo do bot e não pela chegada do
ataque — errar para o lado longo só adia, errar para o curto marcaria uma
conquista real como falha. **Sem retry automático de propósito:** reagendar
mandaria nobres reais de novo sem saber por que o primeiro train morreu, que é
exatamente o caso que pede olho humano. O alvo fica terminal e
removível/readicionável em `/pvp_conquest`, onde o motivo virou um alerta
acima das colunas (antes ficaria escondido embaixo de um bloco de simulação
verde "Viável" — a contradição é o dado mais útil ali).

**2. P2-22 — reserva de escolta não trava mais farm/gather** (`74b3346`,
`game/attack.py`). Detalhe completo nas notas do Lote 6 na auditoria. O que
importa aqui: a correção não é "limitar o `min()`", é reconhecer que a reserva
**se sabota**. Ela existe para a escolta acumular, mas quem financia o
recrutamento é o farm que ela paralisa — abaixo de certo ponto tem valor
esperado negativo. Daí dois gates novos, `conquest.escort_reserve_min_progress`
(0.5) e `conquest.escort_reserve_max_pct` (0.8), ambos opt-out.
`build.version` 2.9 → 3.0 só no `config.example.json`, para o bot mesclar.
**O bug mais instrutivo foi o que a própria correção criou:** o `if needed:` do
chamador não tinha `else`, inofensivo enquanto `{}` era raríssimo; com o gate 1
tornando `{}` comum, uma aldeia que perde tropa e cruza de volta para baixo do
gate ficaria com a reserva presa para sempre — o P2-22 exato por outra porta.
Registrado em `CLAUDE.md` como corolário: alargar o *domínio de retorno* de uma
função exige reler os consumidores, não só os chamadores.

**3. P2-35 — `PvpConquestManager` único por ciclo** (`518b07b`, `twb.py`,
`game/village.py`, `game/pvp_conquest.py`). A leitura óbvia do diagnóstico
("4× o I/O") seria rodar a máquina de estados uma vez por ciclo — e é
justamente o que **não** dá para fazer: a execução por aldeia é o fix de
2026-08-07 acima, é o que dá prioridade sobre o farm daquela aldeia, e rodar só
na primeira aldeia escolheria aldeia de limpeza com dados incompletos no
primeiro ciclo após restart. Eliminada a **releitura**, não a execução:
instância única por ciclo (dando aos memos onde viver) e
`_scout_report_index()`, que indexa `cache/reports` por destino invalidando
pelo `frozenset` de nomes de arquivo. Isso é exato, não aproximação, porque
`ReportManager.read()` pula ids já cacheados — arquivo de relatório nunca é
reescrito. **Sutileza preservada de propósito:** o laço antigo descartava
relatório sem `extra.when` (`best_ts` começava em 0); relatórios anteriores ao
fix de data pt-BR realmente não têm o campo, e aceitar um deixaria
`_step_simulate()` comprometer tropa com base num scout de idade desconhecida.

**O que ainda não foi exercitado.** Nenhuma das três rodou contra o jogo — só
testes isolados sem rede (20, 28 e 21 checks). Item 1 só se valida no próximo
train que realmente falhar. Itens 2 e 3 mexem em caminho de tropa real
(`ConquestManager`) e no módulo que envia nobles, então valem a cautela extra
da convenção do projeto. As três só entram em vigor no próximo restart do bot
— processo em execução mantém o código antigo em memória — e o `config.json`
ganha as duas chaves novas do item 2 automaticamente no start (backup em
`config.bak`). Sintomas a procurar em `cache/logs/session_latest.log`:
`marked FAILED`, `too far off to reserve` e `released stale escort reserve`.

## 2026-08-11 (b) — Feature 9 (resource sharing) reformulada

**O diagnóstico veio de um print, não do código.** O usuário mostrou a visão
geral das 6 aldeias e descreveu duas intenções distintas: (1) aldeias de
armazém pequeno com recurso perto do teto deviam despejar em quem tem armazém
gigante, e (2) as aldeias de armazém gigante, já em fase de nobre/tropa, podiam
abastecer as aldeias travadas. Cruzando com `cache/managed/*.json`, a conclusão
foi mais dura que a hipótese: **ligar a feature como estava não moveria nada.**

Sob a regra antiga (doadora = acima de `threshold_pct` da **própria**
capacidade, 80%), com os números reais do dia:

| Aldeia | Capacidade | Piso p/ doar | Maior estoque |
|---|---|---|---|
| BBM 001 | 500.000 | 400.000 | 42.797 ferro |
| BBM 002 | 406.672 | 325.338 | 157.165 ferro |

As duas aldeias que o usuário queria como doadoras precisariam de ~8× mais
recurso do que tinham. As que qualificavam eram as pequenas quase cheias
(BBM 006 com ferro a 98,9%) — e a única receptora da conta inteira (BBM 003,
`required_resources` com pedra) precisava de **pedra**, que a BBM 006 não tinha
sobrando. A interseção `to_send` era vazia. Zero transferências, enquanto a
BBM 002 estava sentada em 122.748 de pedra.

**A lição do desenho:** percentual da capacidade própria é o sinal *certo* para
"vou transbordar" e o sinal *errado* para "tenho sobra". 42.000 de ferro são 8%
para quem tem armazém 30 e são cinco armazéns inteiros para uma aldeia
recém-conquistada. Uma regra só não consegue exprimir as duas intenções, e foi
por isso que a feature nasceu inerte. Agora são duas, avaliadas na mesma
passada, com **necessidade antes de transbordo** — mandar o excedente para quem
precisa resolve os dois problemas de uma vez, e só o resto é despejado no
"banco". O volume de transbordo é isento do piso de reserva (`need_donor_floor`)
porque aquele recurso seria perdido de qualquer forma.

**Três bugs reais corrigidos junto**, todos invisíveis enquanto o sistema não
rodava:
1. **Mercador contado errado.** `sent_count += 1` por *transferência*, quando o
   custo é 1 mercador a cada 1.000 recursos (confirmado no world config público
   do br143: `<MerchantBonus>0</MerchantBonus>`). Um envio de 4.000 consumia 4 e
   o código achava que tinha gasto 1. Como nada limitava o volume pela carga
   disponível, o primeiro envio real provavelmente seria recusado pelo jogo — e
   o `error_box` resultante seria naturalmente diagnosticado como "payload
   `send_res` errado", que é exatamente o que não estaria acontecendo. Agora o
   plano inteiro é montado antes de qualquer requisição, contra um orçamento de
   `mercadores × merchant_capacity`.
2. **Ninguém checava o espaço da receptora.** Dava para mandar madeira para uma
   aldeia com o armazém de madeira quase cheio. Novo `receiver_fill_max_pct`
   (90%), com margem de propósito: o recurso leva tempo de viagem e a produção
   da receptora continua correndo nesse meio tempo.
3. **Mercado só era checado na origem.** O jogo exige mercado nas duas pontas.
   Junto entraram duas exclusões novas de receptora: aldeia sob ataque (recurso
   entregue a quem vai ser saqueado é recurso entregue ao atacante) e aldeia sem
   `storage` conhecido.

**`storage` (capacidade) passou a ser persistido** em `cache/managed/*.json`
(`village.py::set_cache_vars`). Sem ele não há como calcular espaço livre de
uma aldeia que não é a que está rodando. Consequência operacional: **o primeiro
ciclo após a atualização não envia nada**, porque nenhuma aldeia tem a chave
ainda — cada uma a ganha ao rodar. Isso é o degradado certo (pular quem não dá
para medir) e se resolve sozinho depois de um ciclo completo.

Também corrigido: `_deficit()` desconta o estoque que a receptora já tem. A
versão anterior somava os montantes crus de `required_resources` e podia mandar
recurso que a aldeia já possuía — `ResourceManager.request()` grava o montante
**total** da ação, não o que falta.

Config: bloco `resource_sharing` reescrito (10 chaves novas, `threshold_pct`
removido), `build.version` 3.0 → 3.1 no `config.example.json`. O merge de
`twb.py` é baseado no config novo e só preserva chaves que existem nos dois,
então ele adiciona as 10 e **descarta `threshold_pct` sozinho** — nada a fazer
à mão. `webmanager/helpfile.py` e o template `/resource_sharing` atualizados
(badges das duas regras, coluna "Regra" no histórico).

**O que ainda não foi exercitado.** Nada disso rodou contra o jogo. Teste
isolado, sem rede, com os números reais das 6 aldeias: 25 checks. Três deles
falharam na primeira execução e **os três eram expectativa errada minha, não
bug do código** — o mais instrutivo: presumi que o "banco" de ferro seria a
BBM 002 (armazém 406.672) quando é a BBM 001, que tem 407.203 de espaço livre
para ferro contra 208.839 da BBM 002. *Armazém maior não é o critério; espaço
livre é.* Vale como lembrete de que o cache real é melhor fixture do que a
intuição sobre ele. A feature segue **desligada** (`enabled: false`) e o payload
`send_res` continua sem validação de campo em nenhum idioma.

## 2026-08-11 (c) — Feature 9 validada em campo, e o que a validação achou

**Quatro transferências reais**, as primeiras da história da feature. Mas o
caminho de envio inteiro estava errado, e nada disso teria aparecido sem rodar
contra o jogo:

1. **`mode=send_res` nunca existiu.** O jogo respondia `Modo inválido` num
   error_box, tanto no GET quanto no POST. Isso tinha um efeito colateral
   traiçoeiro: o regex do contador de mercadores nunca casava, o que parecia um
   segundo bug independente ("markup mudou") quando era o mesmo — não havia
   página de mercado para casar. **Uma causa raiz, duas falhas aparentes.**
2. **O destino não é `target_village`.** O formulário endereça por coordenada,
   e o campo visível `input` é só a caixa que o usuário digita: o JS a quebra
   nos hidden `x`/`y`, que são os lidos pelo servidor. Mandar só o `input` deu
   `Não há nenhuma aldeia em (0|0)!` — as coordenadas estavam certas o tempo
   todo, o campo é que era outro.
3. **O envio tem duas etapas.** O `action` do form é `try=confirm_send`, que
   valida e devolve uma tela de confirmação; sem submetê-la, nada sai. Mesmo se
   todos os campos estivessem certos na primeira tentativa, o bot teria
   reportado sucesso e a carga não teria saído.

**O que destravou o diagnóstico foi trocar `(error_box)` por `Modo inválido`.**
Registrar só *que* houve erro custou horas mexendo no payload, que era a
hipótese natural — e errada por uma camada. Extrair a mensagem e salvar a
resposta resolveu os três itens acima em três ciclos. Vale como regra: num
caminho que nunca rodou, o custo de logar o motivo é sempre menor que o de
adivinhá-lo.

### O bug que só aparece com várias aldeias

Com o envio funcionando, a conta ficou visível:

```
21:09:24  BBM 001 → BBM 003   stone 2870
21:13:43  BBM 002 → BBM 003   stone 3540      (necessidade real: 3540)
```

Dois doadores, quatro minutos, 81% a mais que o necessário. A causa não é
defasagem de cache — recurso muda devagar. É que **a demanda já atendida não
ficava registrada em lugar nenhum até a carga pousar**: cada doadora lia o mesmo
`cache/managed/{alvo}.json` parado e agia como se fosse a única. Eu tinha
impedido envio duplicado *dentro* do plano de um doador e não percebi que o
caso interessante era entre doadores.

Novo `cache/resource_sharing/pending.json`: cada envio registra alvo, recursos e
hora prevista de chegada; `_deficit()` e `_headroom()` descontam o que está em
voo. A duração vem da própria tela de confirmação, e o discriminador não é o
rótulo (que muda de idioma) e sim o **conteúdo da célula**: das três células no
formato `H:MM:SS`, a duração é a única cujo texto é *só* o horário — chegada e
retorno vêm com "hoje às " na frente. O teste reproduz os números exatos do log
(2.870 + 3.540) e mostra o depois: 2.870 + 670 = 3.540 cravados.

### A reserva do doador ficou explícita de propósito

O usuário perguntou se uma aldeia juntando pedra para um nobre doaria mesmo
assim. Doaria. `in_need_amount()` lê `required_resources`, e esse campo:

- grava o que **falta**, não o custo total (`snob`, `building`, `research`) --
  enquanto `recruitment_*` grava o total, duas convenções no mesmo campo;
- **some quando a aldeia já tem o suficiente** -- o `if custo > actual` nem
  dispara, então a aldeia mais preparada para agir é a que parece mais
  disponível;
- é **intermitente** -- some também nos ciclos em que o snobber vai cunhar
  moeda em vez de conferir custo.

Dava para tentar inferir a intenção da aldeia, mas seria construir em cima de um
sinal que desaparece justamente quando importa. `village.keep_resources`
(`{"stone": 30000}`) é declarado, previsível, e eleva o piso da regra de
necessidade só naquela aldeia. **Não se aplica ao transbordo**: aquele volume
não cabe no armazém de qualquer forma, e segurá-lo não o preserva.

Mesma investigação corrigiu `_deficit()`, que descontava o estoque duas vezes
das fontes que já eram déficit. O caso pior não era mandar menos: uma aldeia
com `snob: 10215` e 19.785 em caixa dava `max(0, 10215-19785) = 0` e era vista
como não precisando de nada. O sistema nunca ajudaria ninguém a fechar um nobre.

### Menores, mas reais

- **Mercador não se divide.** A confirmação pediu 2 comerciantes para 1.080 de
  argila; o orçamento descontava os 1.080 crus e achava que cabiam mais envios
  do que cabem.
- **`last_send_error.html` guardava o *primeiro* erro.** Herdei o "grava só se
  não existir" da amostra de markup, onde faz sentido, para o dump de erro,
  onde faria diagnosticar a falha de amanhã com a resposta de hoje.
- **A mensagem de `INCOMING_LABELS` juntava duas hipóteses num DEBUG só.** Agora
  procura o rótulo sozinho: se ele está na página, a estrutura é que mudou
  (WARNING + amostra); se não está, provavelmente não há nada a caminho.
  **Segue em aberto** se transporte entre aldeias próprias aparece nesse bloco —
  a evidência de campo era compatível com as duas hipóteses e eu não quis
  escolher uma.

`build.version` 3.1 → 3.2 (`village_template.keep_resources`).

## 2026-08-13 — Feature 24: alocação territorial de aldeias de torre de vigia

**Problema.** Uma aldeia de torre de vigia é defensiva por natureza, mas a
necessidade dela é **territorial** (cobrir raio), não numérica. Se ela contasse
na proporção ofensiva/defensiva do `empire` (Feature 7), o bot criaria torres
pela contagem de aldeias em vez de pela geografia, e os raios se sobreporiam —
destruindo o custo-benefício, já que cada torre custa 11.607 pop e 4,85M.

**Arquivos.** `game/village.py`, `config.example.json`, `webmanager/helpfile.py`.

- `Village.NON_RATIO_PROFILES = ("watchtower",)` — perfis fora da proporção.
- `get_needed_profile()` pula esses perfis nos **dois** lados da contagem.
  Perfil ausente ou desconhecido continua contando como defensiva, para não
  mudar o significado de nenhuma config existente.
- `get_watchtower_sites(config)` — coordenadas das torres existentes, lidas de
  `cache/managed/<vid>.json` (o `config.json` só guarda o perfil).
- `needs_watchtower(config, x, y)` — decide pela distância até a torre mais
  próxima, devolvendo `(bool, motivo)` para o chamador logar.
- Gancho em `apply_nearest_village_inheritance`, antes do cálculo de perfil e
  **antes do filtro de zona** (a decisão de torre precisa varrer todas as
  aldeias, não as filtradas por zona). Escopo: só modo `empire_ratio`; os
  outros modos de herança não atribuem perfil nenhum.

**Config nova (`build.version` 3.3 → 3.4).**
`watchtower: {enabled: false, min_spacing: 16, min_villages: 5}` e
`profile_templates.watchtower`. O padrão de `empire` foi **invertido** para
`offensive_ratio: 1 / defensive_ratio: 3` — o default anterior (3:1 ofensivo)
era o inverso do que a conta joga.

**`min_spacing: 16`** vem de simulação contra o mapa real do br143 — ver a
seção 6 de `docs/watchtower.md`. Resumo: o ótimo hexagonal (`R√3 = 25,98`)
maximiza área e **zera o aviso** no ponto pior, que é o produto real da torre.
16 é o maior espaçamento que ainda cobre tudo; 17 é um precipício (o décimo
percentil do aviso cai de 92 para 4 minutos).

**A primeira torre é sempre manual.** A primeira versão devolvia `True` quando
não havia nenhuma torre designada — ou seja, **qualquer** aldeia conquistada
viraria a primeira torre, em qualquer coordenada. Três motivos para não:
1. a primeira torre define o centro da malha inteira (toda seguinte fica a
   ≥ `min_spacing` dela), então errá-la propaga pelo império para sempre;
2. `needs_watchtower()` só roda para aldeia **recém-conquistada**, que por
   definição está na fronteira — a primeira torre nasceria na borda, deixando
   o núcleo descoberto;
3. aldeia recém-conquistada é o pior sítio possível: pela tabela de
   viabilidade, BBM 002 leva 48 dias e a menor aldeia existente 54; uma
   conquista fresca é pior que as duas.
Designar = pôr `"profile": "watchtower"` na aldeia escolhida. O log do
resultado da checagem é **info**, não debug, justamente para que
`watchtower.enabled` ligado sem torre designada não fique inerte em silêncio.

**Validação.** `tests/test_watchtower_allocation.py` — 13 testes: exclusão da
proporção (invariante de que N torres não deslocam o perfil da próxima
conquista), retrocompatibilidade de perfil ausente, guarda de divisão por zero,
primeira torre nunca automática, limiar de espaçamento contra as coordenadas
reais da BBM 002, distância euclidiana nos dois eixos. Nenhum envio ao jogo.

⚠️ **Achado colateral não resolvido: cunhagem de moeda depende de querer nobre.**
`SnobManager.run()` só chega em `coin_item()` através de `attempt_recruit()`,
dentro de `if self.wanted > 0`; e `village.py:455` nem instancia o SnobManager
quando `snobs` é `0`, porque testa o valor por veracidade e `0` é falsy. Ou
seja, **`snobs: 0` desliga a cunhagem junto** — não existe modo "cunhar moeda
sem recrutar nobre". Eu tinha posto `snobs: 0` em
`profile_templates.watchtower` e tirei: decidir isso em silêncio mataria a
única razão de a academia existir nessa aldeia. Fica em aberto.

## Ambiente de referência

Python 3.13, Windows 10. Bot: `python twb.py`. Webmanager: `python server.py`
na pasta `webmanager/`, acesso em `http://127.0.0.1:5000/`.
