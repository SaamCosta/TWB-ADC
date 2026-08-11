# Backlog — Features pendentes

Ordem de implementação até agora: `4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 18 → 19 → 20 → 21 → 22 → 23 → 24 (fase 1) → 14 → 15 → 16 → 17 → 27` (✅ todas)

Pendentes: **25** (inventário/boosts) e **26** (envio em lote `train[N][unit]`)
— ambas precisam de levantamento em campo antes de virar tarefa.

## Fila da auditoria de código

`docs/auditoria_codigo_2026-08-08.md` — **Lotes 1 a 6 concluídos**
(Lote 6 em 2026-08-11). Todos os 19 itens P0/P1 corrigidos e 18 dos 20 P2.
Restam dois:

| Item | O quê | Por que ficou de fora |
|---|---|---|
| **P2-29** | Piso de moral em `estimate_moral()` — código usa `100 - loss_max` = 70, o diagnóstico diz que o piso real do TW é 30 | **Bloqueado por falta de dado.** O docstring afirma que `mood.loss_max` foi confirmado ao vivo; as duas afirmações se contradizem e não há `cache/world_config*` no repo para conferir o `<mood>` real do br143. Trocar 70 por 30 seria trocar um palpite por outro. **Próximo passo:** capturar o bloco `<mood>` do endpoint público do mundo e decidir com o dado na mão. Hoje é inerte (`pvp_conquest.dynamic_moral_night_bonus: false`). |
| **P2-35** | `PvpConquestManager` instanciado 1× por aldeia por ciclo (4× o I/O) | Só performance, é idempotente. Casa com a dívida geral de "varredura de diretório por ciclo" listada no CLAUDE.md — vale atacar junto com ela, não isolado. |

## Feature 14 — Templates de tropas editáveis no webmanager ✅ Implementado (2026-08-03)

Nova página `/unit_templates`. Listar, criar, deletar e editar templates de
tropas (JSON em `templates/troops/*.txt`) inline no webmanager. Elimina a
necessidade de editar os arquivos `.txt` manualmente.

**Status:** diferente de `BuildingTemplateManager` (formato simples
`building:level` por linha, já editável via `/building_templates` com um
formulário por campo), os templates de tropas são JSON aninhado e bem mais
variável entre estágios (`building`, `level`, `build` por prédio de
recrutamento, `upgrades` opcional, `farm` como dict único ou lista de dicts
sequenciais — ver `templates/troops/basic.txt` e `offensive.txt`). Montar um
formulário por campo para essa estrutura seria um esforço bem maior e mais
frágil do que o ganho justifica; a edição foi implementada como um textarea
de JSON bruto, com validação antes de gravar no disco (JSON inválido ou que
não seja uma lista é rejeitado com mensagem de erro, nada é escrito).

Novo `UnitTemplateManager` (`webmanager/utils.py`): `template_cache_list()`
lê `templates/troops/*.txt`, parseia cada um (detecta e sinaliza arquivos
corrompidos sem lançar), `create()`/`save()`/`delete()` para as operações de
CRUD. Nova rota `/unit_templates` (GET/POST) e template
`unit_templates.html` — lista de templates com contagem de estágios à
esquerda, textarea de edição à direita, criação de novo template vazio
(`[]`), delete com confirmação JS. Link adicionado na nav de `main.html`.
Nenhuma config nova.

**Guarda de segurança:** um template ausente/corrompido faz
`game/village.py::units_get_template()` levantar `InvalidUnitTemplateException`,
que não é capturada em nenhum lugar do loop por-aldeia — propaga até
`twb.py`'s `try/except` mais externo e **derruba o bot inteiro** (reporta,
notifica, mas o processo termina). Por isso `UnitTemplateManager.used_by()`
varre `config.json` (`units.default`, `village_template.units`,
`villages.*.units` e, importante, `profile_templates.*.units` — usado pela
lógica de herança de aldeias conquistadas da Feature 23) antes de permitir
delete; se o template estiver em uso em qualquer um desses lugares, o delete
é bloqueado com uma mensagem listando onde. Salvar (`save`) também nunca
escreve no disco se o JSON for inválido ou não for uma lista.

Testado isoladamente (sem servidor real, sem tocar `templates/troops/` real
durante os testes de escrita — usado diretório temporário): parse dos 5
templates reais existentes (`basic`, `basic_into_def`, `basic_into_off`,
`defensive_1`, `offensive` — todos válidos), detecção de JSON corrompido,
`create`/`save`/`delete` end-to-end em diretório isolado, rejeição de JSON
inválido e de JSON que não é lista. `used_by()` validado em modo só-leitura
contra o `config.json` real do usuário — confirmou corretamente `basic.txt`
em uso via `units.default` + `village_template`, `offensive.txt` via aldeia
41123 + `profile_templates.offensive`, `defensive_1.txt` via
`profile_templates.defensive`, e `basic_into_def.txt`/`basic_into_off.txt`
como não referenciados atualmente (logo, deletáveis). Os 3 estados do
template (sem seleção, seleção válida, seleção com erro de validação)
renderizados isoladamente via Jinja2 standalone. **Não validado:** a rota
Flask `/unit_templates` via app real — pendente de validação em campo.

## Feature 15 — Seleção manual de alvo de conquista bárbara no webmanager ✅ Implementado (2026-08-03)

Botão "Definir alvo manual" na aba `/conquest`. Input de coordenadas ou ID.
Cria `cache/conquest/{id}.json` com status `manual`, sobrepondo a seleção
automática da Feature 8 (`ConquestManager.find_target()`).

**Status:** implementado. `find_target()` (`game/attack.py`) agora chama
`_get_manual_target()` antes de rodar o scoring automático — se houver um
`cache/conquest/{id}.json` com `status == "manual"`, ele é devolvido
diretamente (ignorando `max_radius`/`min_points`/`max_points`, já que é uma
escolha deliberada do usuário), processado em ordem de chegada (`queued_at`,
FIFO) quando há mais de um na fila. Antes de devolver o alvo,
`_get_manual_target()` revalida que a aldeia ainda é bárbara consultando o
cache compartilhado `cache/villages/{id}.json` (populado pelo fetch de mapa
de qualquer aldeia gerenciada) — se o dono mudou nesse meio tempo, a entrada
vira `status: "invalid"` com `invalid_reason`, em vez de ser retentada para
sempre. Como o processamento de aldeias no loop principal (`twb.py`) é
sequencial (não há concorrência real), não há risco de duas aldeias
disputarem o mesmo alvo manual no mesmo ciclo — a primeira que envia o train
já sobrescreve o status para `train_sent`/`extra_pending` antes da próxima
aldeia rodar.

No webmanager (`/conquest`): novo formulário "Definir alvo manual" aceita ID
de aldeia (`12345`) ou coordenadas (`512|487`, `512,487`, `512 487`) —
`ConquestReader.add_manual_target()` resolve o identificador contra
`cache/villages/*.json`, valida que é bárbara e que não há conquista já
ativa/pendente para o mesmo alvo, e só então grava o cache; qualquer rejeição
levanta `ValueError` com mensagem amigável exibida inline (nada é escrito em
caso de erro). Alvos com status `manual`/`invalid` ganham botão "Cancelar"
(`ConquestReader.cancel_manual()`), bloqueado por design para qualquer outro
status — cancelar uma conquista já em andamento no webmanager não recuperaria
nobles já enviados, só quebraria o acompanhamento.

**Limitação conhecida (documentada, não corrigida):** o envio do ataque
(`AttackManager.attack()`) só funciona se o `target_id` estiver em
`self.map.map_pos`, que é populado pelo fetch de mapa *daquela aldeia
específica* a cada ciclo (não é compartilhado entre aldeias). Um alvo manual
fora da região de mapa já visitada pela aldeia que eventualmente o reivindica
falhará silenciosamente (log de tentativa, sem crash) até que essa aldeia
finalmente "veja" a região automaticamente. Na prática o fetch de mapa cobre
uma área ampla (bem além do `max_radius` de conquista configurado), então
isso só deve importar para alvos muito distantes/fora do continente.

**Correções feitas durante a auditoria do ecossistema de conquista
automática** (pedido explícito do usuário antes de seguir para a Feature 15,
nenhuma delas exigiu mudança de config nem bump de `build.version`):
- **Bug real de dados**: `ConquestManager._send_train()`/`_handle_existing()`
  gravavam a chave `"hits"` em `cache/conquest/{id}.json`, mas
  `ConquestReader.load()` (webmanager) sempre leu `"hits_done"` — chaves
  nunca bateram, então a página `/conquest` sempre mostrava "0/4" nobles
  independente do progresso real. Também nunca eram gravados
  `target_name`/`target_points`/`target_location`/`hits_needed`, então a
  tabela sempre caía nos defaults do reader (nome genérico "Bárbara #id",
  pontos "?", coordenada "—"). Corrigido: `_send_train()` agora grava
  `hits_done`, `hits_needed` (= `TRAIN_SIZE`), `target_name`, `target_points`,
  `target_location` (via novo helper `_get_village_meta()`) e
  `loyalty_source`; `_handle_existing()` idem, com fallback
  `.get("hits_done", .get("hits", 0))` para não quebrar em cima de qualquer
  cache antigo já gravado com a chave errada.
- `loyalty_source` também nunca era persistido, então o ícone de "lealdade
  confirmada por relatório" 📊 vs. "estimada" ≈ no webmanager sempre caía no
  default (`estimate`) mesmo quando `_handle_existing()` já tinha achado um
  relatório real de noble. Corrigido — a origem (`"report"` vs `"estimate"`)
  agora é rastreada e persistida junto com a lealdade recalculada.
- Restante do fluxo (reserva de escolta via `conquest_reserve`,
  respeitada por `AttackManager._get_farmable_troops()` e
  `TroopManager.do_gather()`; `ConquestCache.all_reserved()`; ordem
  `run_conquest()` → `run_farming()` → `do_gather()` em
  `game/village.py::Village.run()`) foi revisado e está correto — nenhum
  outro problema encontrado nessa auditoria.

## Feature 16 — DefenceManager avançado ✅ Implementado (2026-08-05)

Usar `data-endtime`, nome do atacante e `data-command-id` do HTML de overview
para priorizar evacuação por urgência (ataques chegando em minutos têm
prioridade sobre ataques em horas). Estende `DefenceManager.evacuate()` /
`update()`.

**Status:** antes desta feature, `DefenceManager.update()` reagia de forma
binária a `'no_ignored_command' in main` — qualquer comando recebido (esteja
a 2 minutos ou 5 horas de distância) disparava evacuação imediata das
unidades frágeis (`evacuate()`) sempre que `evacuate_fragile_units_on_attack`
estava ativo, o que podia tirar tropas ofensivas (axe) de produção/farm por
horas para um ataque que ainda ia demorar a chegar.

- Novo `Extractor.incoming_commands(res)` (`core/extractors.py`) varre o HTML
  de overview por `<tr ... data-command-id="N" ...>...</tr>` e extrai, por
  comando, o ETA e o nome do atacante (link `screen=info_player`). O ETA é
  lido em duas variantes de markup já usadas em outras páginas do jogo pelo
  próprio bot: `data-endtime="UNIX_TS"` (timestamp absoluto, ETA = endtime -
  now) e `data-duration="SEGUNDOS"` (já é a duração restante — mesmo padrão
  de `Extractor.attack_duration()`, que usa `data-duration` na página de
  confirmação de ataque). Nunca lança exceção — markup não reconhecido
  resulta em lista vazia, não em crash.
- `DefenceManager._parse_incoming_urgency(main)` pega o comando mais próximo
  (soonest) da lista e guarda `incoming_eta` / `incoming_attacker` /
  `incoming_command_id`. `_is_urgent(eta_seconds)` compara contra o novo
  `urgency_threshold_sec` (config `evacuate_urgency_threshold_sec`, padrão
  1800s = 30 min).
- **Fallback seguro:** se `incoming_commands()` não achar nada usável (ETA
  `None` — markup não reconhecido, ou mudou no jogo), `_is_urgent()` assume
  `True` (urgente) — preserva o comportamento anterior à Feature 16 (evacuar
  sempre que houver comando recebido) em vez de arriscar não evacuar por
  falha de parsing.
- `update()` agora só chama `evacuate()` quando `_is_urgent()` é `True`;
  fora isso, a bandeira de defesa (`flag_logic(set_flag_under_attack)`)
  continua sendo ativada normalmente e o estado (`under_attack=True`) é
  mantido — só a evacuação física das tropas é que espera o ataque ficar
  realmente próximo. Cada detecção gera um log `WARNING` com atacante, ETA e
  `command_id` para visibilidade.
- `Village.set_cache_vars()` (`game/village.py`) passou a persistir um bloco
  `"incoming_attack"` em `cache/managed/{id}.json` (eta_seconds, attacker,
  command_id, urgency_threshold_sec, urgent) — mesma convenção da Feature 19
  (bloco `"flags"`), dado pronto para uma futura página no webmanager sem
  exigir nova infra de leitura.
- Nova config por aldeia `evacuate_urgency_threshold_sec` (default 1800) em
  `village_template` — `config.example.json` e `webmanager/helpfile.py`
  atualizados; `build.version` 2.7 → 2.8.

**Limitação conhecida / não validada em campo:** os nomes exatos dos
atributos (`data-command-id`, `data-endtime`/`data-duration`, link
`screen=info_player` para o atacante) foram inferidos a partir de padrões já
usados em outras páginas do próprio jogo (`attack_duration()` já validado
usa `data-duration`) e da descrição original deste item no backlog, mas
**não foram confirmados contra o HTML real da página de overview do
br143 com um ataque de verdade chegando**. Se o markup real divergir, o
fallback seguro garante que o bot não passa a evacuar *menos* do que antes —
na pior hipótese, `incoming_commands()` retorna lista vazia e o
comportamento fica idêntico ao pré-Feature-16 (evacua sempre). Recomendado
validar em campo (log `WARNING` mostra ETA/atacante quando o parsing
funciona) antes de contar com a priorização por urgência de fato acontecendo.

## Feature 17 — Relatório de império no webmanager ✅ Implementado (2026-08-05)

Dashboard em `/empire` com: total de tropas por tipo agregado (todas as
aldeias), gráfico de recursos por aldeia, mapa de calor de atividade de farm,
histórico de conquistas com timeline. Consome `cache/managed/*.json`,
`cache/attacks/*.json`, `cache/conquest/*.json`.

**Status:** novo `EmpireReader` em `webmanager/utils.py` — puramente
agregador, não cria nenhum diretório de cache novo, só cruza o que `sync()`
já lê (`cache/managed`, `cache/villages`, `cache/attacks`) e a saída de
`ConquestReader.load()` (`cache/conquest`):
- `troop_totals(managed)` — soma `troops` (= `TroopManager.total_troops`,
  persistido por `Village.set_cache_vars()`) de todas as aldeias, ordenado
  por total desc.
- `resources_by_village(managed)` — uma linha por aldeia (recursos, pontos,
  `under_attack`).
- `farm_heatmap(attacks, villages, managed)` — cruza `cache/attacks/*.json`
  (contagem de ataques) com `cache/villages/*.json` (coordenada) para os
  alvos de farm; aldeias próprias entram via `x`/`y` de `cache/managed`
  (sempre presente, não depende do cache de mapa). Alvos sem coordenada
  conhecida são ignorados. Renderizado como scatter plot colorido por
  intensidade em canvas (`empire.html`), não como grid denso tipo
  `MapBuilder`/`/map` — mais leve e mais fiel ao termo "mapa de calor" já
  que os alvos de farm normalmente estão espalhados, não preenchendo uma
  área contígua.
- `conquest_timeline(conquest_targets, limit=30)` — reordena a saída já
  processada de `ConquestReader.load()` por evento mais recente
  (`last_hit_ts` ou `queued_at`), sem reler `cache/conquest` de novo.
- Nova rota `GET /empire` (`webmanager/server.py`) e template
  `empire.html` — cards de tropas totais, recursos por aldeia, heatmap
  (canvas + tooltip, mesmo padrão de `/map`) e timeline de conquistas.
  Link adicionado na nav de `main.html`. Nenhuma config nova.

**Bug real encontrado e corrigido durante a implementação** (mesma classe
do bug de `hits`/`hits_done` achado na auditoria da Feature 15): o campo
`attack_count` em `cache/attacks/{id}.json` nunca era de fato atualizado —
`AttackManager.attacked()` (`game/attack.py`) só preservava o valor
existente (`existing.get("attack_count", 0)`), e nada em todo o código
jamais escrevia um valor novo ali. A contagem real de ataques só existia
calculada na hora, dentro de `VillageManager.farm_manager()`
(`manager.py`), usada apenas para compor a linha de log
("Farm village X attacked N times") — nunca persistida de volta. Isso
deixava tanto a coluna "Ataques" de `/farmscores` quanto o novo heatmap da
Feature 17 permanentemente zerados. Corrigido: `farm_manager()` agora
grava `data["attack_count"] = len(num_attack)` de volta no cache sempre
que o valor mudar. Validado rodando `VillageManager.farm_manager(verbose=True)`
contra o cache real do br143 — os 10 alvos de farm existentes passaram de
`attack_count: 0` para os valores reais (3 a 13, batendo exatamente com o
log de produção já existente), e o heatmap do `/empire` passou a mostrar
intensidade de verdade (`max_count` 0 → 13) em vez de tudo na mesma cor.

**Bug de template encontrado por inspeção visual (usuário) e corrigido antes
do commit:** a coluna "Pop" da tabela "Recursos por aldeia" mostrava o
texto literal `<built-in method pop of dict object at 0x...>` em vez do
valor numérico. Causa: `{{ r.pop }}` no Jinja2 tenta primeiro
`getattr(r, "pop")` antes de cair para `r["pop"]` — como `r` é um `dict`
Python puro e `pop` é também o nome de um método nativo de `dict`, o
`getattr` "vence" e retorna o método em vez de buscar a chave. Corrigido
para `{{ r['pop'] }}` (acesso por chave, sem ambiguidade). Vale lembrar
disso para qualquer chave futura que colida com métodos de `dict`
(`items`, `keys`, `values`, `update`, `get`, `copy`, etc.) — nenhuma outra
ocorrência encontrada em `empire.html` nesta revisão.

**Polimento pendente (funcional, mas com lacunas conhecidas — anotado,
não implementado):**
- **Ícones de tropas pequenos/pouco legíveis.** O card "Tropas totais do
  império" lista ícone+número em uma única linha corrida (`d-flex
  flex-wrap`); com poucos tipos de unidade (caso atual, só 1 aldeia) fica
  compacto demais visualmente. Vale revisar espaçamento/tamanho dos ícones
  (ou usar um layout em grade/cards por unidade) quando houver mais dados
  reais para julgar o resultado.
- **Sem linha de total agregado em "Recursos por aldeia".** Com várias
  aldeias gerenciadas, seria útil uma linha de rodapé somando
  madeira/argila/ferro/pop do império inteiro, além dos totais por aldeia
  já mostrados.
- **Heatmap sem números visíveis nos pontos.** A intensidade (cor/raio do
  círculo) só é lida via hover (tooltip); poderia ganhar uma legenda de
  escala de cor (frio→quente) fixa no card, sem depender do usuário passar
  o mouse em cada ponto.
- Nenhum desses itens bloqueia o uso da página — todos são melhorias de
  UX, não bugs funcionais.

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

**Polimento pendente (funcional, mas com lacunas conhecidas):**
- **Nomes de aldeia inimiga não resolvidos.** A tabela mostra `origin`/`dest`
  como ID cru. `village_options` (dropdown de filtro) só cobre aldeias
  *próprias* (`cache/managed/*.json`); aldeias-alvo de farm/ataque (a maioria
  dos relatórios) não têm nome resolvido porque `ReportReader.load()` não
  cruza com `cache/villages/*.json` (dados de mapa, já usados por
  `MapBuilder`/`ZoneReader`). Devia enriquecer `origin`/`dest` com nome via
  esse cache antes de exibir.
- **Filtro de tipo hardcoded.** O dropdown em `reports.html` só lista
  `attack`/`scout`/`support` fixos. Tipos reais no cache incluem outros
  vistos em `bot.html` (ex: `ReportFoundCrew`) que ficam de fora do filtro
  (ainda aparecem na tabela, só não são selecionáveis). Devia construir as
  opções dinamicamente a partir dos tipos presentes no cache, como `/logs`
  já faz com `event_types`.
- **`safe_to_engage` não é o mesmo valor que o `AttackManager` usa.** O pedido
  original citava `safe_to_engage` — o que foi implementado é um veredito
  *por relatório individual* (`ReportReader._outcome`), não o agregado
  *por aldeia-alvo* que `ReportManager.safe_to_engage()` realmente calcula
  (que olha o relatório mais recente contra aquele alvo para decidir se vale
  atacar de novo). Seria mais fiel adicionar uma view agregada por aldeia
  usando a mesma lógica de `safe_to_engage()`, já que é isso que
  efetivamente influencia as decisões do bot.
- **Sem paginação real.** `ReportReader.load(limit=150)` corta silenciosamente
  nos 150 relatórios mais recentes (ordenados por `extra.when`, quando
  presente) — não há como navegar para relatórios mais antigos pela UI.
- **I/O por request, sem cache.** `ReportReader.load()` varre e abre todo
  arquivo em `cache/reports/*.json` a cada carregamento da página (não só os
  150 exibidos — as estatísticas agregadas somam sobre a pasta inteira).
  Mesma classe de gargalo já registrada em `CLAUDE.md` ("Débito técnico") para
  `Hunter`/`PvpConquestManager`/`ZoneManager`/`ConquestManager` — com a pasta
  crescendo (500+ arquivos já observados em campo), pode ficar perceptível.
  Candidato a um índice incremental ou cache em memória por ciclo, em vez de
  releitura completa a cada acesso.

## Feature 22 — Detecção de conta premium para fila de construção dinâmica ✅ Implementado (2026-08-02)

`BuildingManager.max_queue_len` (`game/buildingmanager.py:34`) é fixo em 2,
mas contas premium liberam mais slots de fila simultânea. Detectar o status
premium real (geralmente exposto na visão geral) e ajustar o limite
dinamicamente evita deixar fila de construção subutilizada. Baixa
prioridade — ver `docs/game_comparison.md` item 6.

**Status:** `pages/overview.py::OverviewPage` já calculava, por linha da
`production_table`, um `idx_offset` para lidar com uma coluna extra (checkbox
de seleção em massa) presente apenas em contas premium — usado desde a
Feature 18 para achar corretamente `village_id`/pontos. Reaproveitei esse
mesmo sinal já validado em campo em vez de inventar um novo: agora
`OverviewPage.is_premium` fica `True` assim que qualquer linha detecta esse
offset.

`twb.py::get_world_options` auto-detecta isso uma única vez (mesmo padrão de
`flags_enabled`/`knight_enabled`/`boosters_enabled`/`quests_enabled`) e grava
em `config["world"]["premium_account"]` — só roda enquanto o valor estiver
`null`, então um override manual no `config.json` sempre prevalece.

O ajuste de fila é **opt-in**, para não mudar comportamento de configs
existentes: `building.auto_queue_len` (default `false`). Quando `true` **e**
`world.premium_account` é `true`, `game/village.py::run_building_manager`
usa `building.premium_max_queued_items` (default `5`) em vez de
`building.max_queued_items` (default `2`) para `self.builder.max_queue_len`.

Config novo em `config.example.json`: `world.premium_account` (null),
`building.auto_queue_len` (false), `building.premium_max_queued_items` (5).
`build.version` bumpado para `2.5` — o bot vai mesclar essas chaves no
`config.json` real automaticamente no próximo start (backup automático em
`config.bak`). `webmanager/helpfile.py` atualizado com as 3 novas chaves.

**Limitação conhecida:** a detecção depende inteiramente do sinal estrutural
do HTML (coluna extra vazia). Não tenho como confirmar 100% contra o HTML
real do br143 nesta sessão — testado isoladamente com HTML sintético
reproduzindo os dois formatos (com/sem coluna extra), e a lógica é a mesma
já usada para extrair `village_id`/pontos desde a Feature 18. Se
`config["world"]["premium_account"]` vier errado após o primeiro ciclo, basta
corrigir manualmente no `config.json` (o auto-detect não sobrescreve valores
não-nulos). Como o ajuste de fila é opt-in (`auto_queue_len=false` por
padrão), nada muda para quem não habilitar essa opção.

## Feature 23 — Variância comportamental para automação mais "orgânica" ✅ Implementado (2026-08-02)

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

**Status:** as 3 propostas foram implementadas, todas com default que preserva
o comportamento atual (opt-in / mesmos valores hardcoded de antes):

1. **Ordem embaralhada:** `twb.py::TWB.run()` agora monta `processing_order`
   (cópia de `self.villages`, embaralhada com `random.shuffle` quando
   `bot.humanize_village_order=true`, default `false`) em vez de sempre
   iterar `self.villages` na mesma ordem. Para não quebrar
   `auto_set_village_names`, a numeração `{num}` do template deixou de vir de
   um contador incremental durante o loop (que dependia da ordem de
   processamento) e passou a vir de `village_numbers`, um dicionário
   `village_id -> número` calculado uma vez a partir da ordem original do
   `config["villages"]`, antes do embaralhamento — assim as aldeias não ficam
   sendo renomeadas de ciclo em ciclo mesmo com a ordem de processamento
   variando.
2. **Jitter configurável (global e por aldeia):** novo helper
   `TWB._jitter(config)` substitui os três `random.randint(20, 120)`
   hardcoded em `twb.py` por `bot.jitter_min`/`bot.jitter_max` (defaults 20/120,
   idênticos ao valor antigo). Para o delay *entre requisições* (não só entre
   ciclos), `game/village.py::Village.run()` agora aceita um override por
   aldeia: `village.delay_factor` (novo campo em `village_template`, default
   `null` = usa `bot.delay_factor` global), mesmo padrão já usado por
   `village.active_hours`.
3. **Atraso de atenção:** `bot.attention_lag_chance` (default `0.0` =
   desligado) é a probabilidade por ciclo de somar um atraso extra de
   `bot.attention_lag_extra_min`–`bot.attention_lag_extra_max` segundos
   (default 600–1800s) ao sleep do ciclo, simulando um jogador distraído.

**Guarda de segurança (cuidado importante acima):** o atraso de atenção só
pode disparar se `not any(defense_states.values())` — ou seja, se nenhuma
aldeia gerenciada estiver com `under_attack=True` conhecido no ciclo que
acabou de rodar. Isso usa o mesmo dict `defense_states` já existente (synced
para `DefenceManager.my_other_villages` logo acima no código). Se qualquer
aldeia estiver sob ataque, o ciclo mantém a cadência normal — a humanização
nunca atrasa uma reação defensiva real. O embaralhamento de ordem e o jitter
configurável não têm esse risco (todas as aldeias ainda são processadas
dentro do mesmo ciclo, só a ordem/o timing dos requests muda).

Testado isoladamente (sem servidor real): `TWB._jitter()` com config default,
custom e min/max invertido; `OverviewPage`/`get_world_options` não afetados
por esta feature. A lógica de `village_numbers` e o guard de
`attention_lag` foram revisados por leitura mas **não foram exercitados
com um ciclo real do bot** — pendente de validação em campo via
`cache/logs/session_latest.log` (usuário confirmou que vai rodar o bot e
revisar o log depois).

Config novo: `bot.humanize_village_order` (false), `bot.jitter_min` (20),
`bot.jitter_max` (120), `bot.attention_lag_chance` (0.0),
`bot.attention_lag_extra_min` (600), `bot.attention_lag_extra_max` (1800),
`village_template.delay_factor` (null). `build.version` bumpado para `2.6`.
`webmanager/helpfile.py` atualizado com as 7 novas chaves.

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

### Fase 1 ✅ Implementado (2026-08-02)

Diferente das Features 18-22 (que trabalharam em cima de sinais HTML já
validados em campo), esta tela nunca tinha sido acessada pelo bot — o usuário
forneceu duas amostras reais de HTML do br143 (`screen=statue&mode=overview`
e `&mode=resident`), usadas para desenhar o parser em vez de adivinhar
seletores às cegas.

**Descoberta chave:** as duas telas embutem um payload JSON limpo no
`<script>` via `BuildingStatue.receiveKnightsData([...], {...}, N);`
(nível, XP, skills por id, `branch_investments`, aldeia principal, regime de
treino atual, lista de regimes de XP disponíveis com custo/payout/duração,
atividade atual) — não foi necessário raspar a árvore de skills renderizada
em HTML/CSS. Os 12 skills (id, nome, descrição, magnitude por nível) e os
limiares de slot (`[1,3,5,10,20,35,50,65,80,100]`) também vêm no mesmo
`<script>`, mas os limiares de slots **bloqueados** são lidos do texto
renderizado ("Obtenha N aldeias para desbloquear este slot") em vez do
argumento posicional do JS, por refletir o que realmente foi exibido.

**Novo `pages/statue.py::StatuePage`:** em vez do regex não-guloso
`\{.+?\}` já usado em `core/extractors.py` (que quebraria com o JSON
profundamente aninhado do Paladino, parando no primeiro `}` interno), usa
uma varredura de colchetes balanceados (`_extract_balanced`, respeitando
aspas/escapes) para extrair os dois argumentos do `receiveKnightsData(...)`
com segurança.

**Novo `game/statue_manager.py::StatueManager`:** roda uma vez por ciclo
completo do bot (não por aldeia — o roster de Paladinos é compartilhado por
toda a conta), pedindo `screen=statue&mode=overview` a partir da primeira
aldeia gerenciada disponível. Persiste em `cache/statue/status.json`.
Opt-in via `statue.enabled` (default `false`) — diferente de Features 19-21
(que só passaram a persistir estado que managers já existentes calculavam),
esta feature faz uma requisição HTTP nova por ciclo a uma tela nunca acessada
antes, então fica desligada por padrão até validação em campo.

**Webmanager:** `StatueReader` (`webmanager/utils.py`) formata o cache —
progresso de XP em %, skills agrupados pelas 3 árvores com pontos investidos,
tabela de regimes de treino por XP (custo/payout/duração), e status de slots
bloqueados vs. número de aldeias atual. Nova rota `/statue` + template
`statue.html` — um card por paladino, seção de slots bloqueados no fim. Link
adicionado na nav.

Config novo: `statue.enabled` (`false`). `build.version` bumpado para `2.7`.
`webmanager/helpfile.py` atualizado com as 2 novas chaves.

**Validado nesta sessão:** parser (`StatuePage`) testado contra as duas
amostras reais de HTML fornecidas pelo usuário — extraiu corretamente nível,
XP (`13.5%`, batendo com o `width: 13.5403%` da barra de progresso renderizada
pelo próprio jogo), skills por árvore (conferido contra os `X/4` renderizados
na árvore de skills do HTML), regimes de treino e limiares de slot. `StatueReader`
e os 3 estados do template (`ativado+dados`, `desativado`, `ativado sem dados
ainda`) testados isoladamente. **Não validado:** o ciclo real de
`StatueManager.run()` dentro do loop do bot (`twb.py`) nem a rota Flask
`/statue` via app real — pendente de validação em campo com `statue.enabled: true`.

**Limitação conhecida:** não distingue um slot já desbloqueado mas ainda sem
paladino recrutado (não há amostra desse estado) — nesse caso ele não aparece
nem na lista de paladinos nem na de bloqueados. Fase 2 (treino por XP
automático, re-especialização por perfil) segue sem desenho, precisa de mais
definição do usuário antes de virar tarefa.

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

## Feature 26 — Envio de ataques múltiplos em lote (train[N][unit])

Descoberto em 2026-08-07 investigando por que o trem de 4 nobres do PvP
Conquest (Feature 13), embora todos enviados com sucesso, chegou **espalhado
ao longo de ~2min19s** em vez de simultâneo: o `Hunter` (`game/hunter.py`)
manda cada ataque agendado sequencialmente — GET da página, POST de
confirmação, POST de envio, e só então passa para o próximo — cada ciclo
levando 40-80s de ida e volta HTTP. Como os 4 nobres tinham o mesmo
`send_time` calculado (mesma composição de tropa, mesma duração de viagem),
o primeiro saiu na hora certa (`09:41:15`) mas o quarto só às `09:43:34`,
porque cada envio bloqueia o próximo até terminar.

**O jogo tem um mecanismo nativo pra isso.** Investigado ao vivo com a sessão
real do bot (JS `game.cb1e4b.js`, objeto `Place.confirmScreen`): o botão
"Adicionar ataque adicional" (`#troop_confirm_train`,
`addAdditionalAttack()`) adiciona linhas de tropa nomeadas
`train[1][unit]`, `train[2][unit]`, etc. **dentro do mesmo
`#command-data-form`** que já tem os campos do ataque principal
(`spear`, `sword`, `axe`...). Como tudo vive no mesmo formulário, o envio
final é um único POST contendo o ataque principal **e** todos os
`train[N][...]` juntos — não é N cliques escondidos, é um envio em lote de
verdade. Isso resolveria o espalhamento de chegada de qualquer trem com mais
de 1 ataque simultâneo (clear + nobres, ou múltiplos nobres).

**Por que não foi implementado ainda:** o formato exato do POST final (tokens
ocultos tipo `ch=`, se cada linha `train[N]` aceita coordenada própria ou
usa sempre a mesma `x`/`y` do form, etc.) não pôde ser confirmado com
segurança só lendo o JS minificado — só o `#command-data-form` "atacar por
mapa" (`comandopelomapa.txt`) e os dois botões "Adicionar ataque adicional"
(`novoataquentmapa.txt`, `novoataquentpraça-place.txt`) foram inspecionados
pelo usuário, sem captura de rede do envio final de verdade. Implementar às
cegas arrisca desperdiçar tropa real ou mandar ataque pro lugar errado.

**Proposta:** antes de implementar, fazer um teste controlado (ex: 2 ataques
pequenos e descartáveis contra um alvo seguro) capturando a requisição de
rede real do envio final, pra confirmar o formato exato dos campos —
só então adaptar `Hunter._send_attack()` (`game/hunter.py`) e
`AttackManager.attack()` (`game/attack.py`) para aceitar múltiplos ataques
por chamada e montar o POST em lote em vez de N chamadas sequenciais.

**Prioridade:** depois da Feature 25. Ganho real só aparece quando há mais
de 1 ataque simultâneo agendado pro mesmo `arrival_time` (hoje, só o trem de
nobres do PvP Conquest se beneficia) — não bloqueia nada em uso hoje.

## Feature 27 — `ConquestManager` (bárbara) respeitar reserva cruzada de tropas ✅ Implementado (2026-08-08)

**Status:** implementado conforme o plano abaixo, mais dois achados que o
plano não previa (detalhados no fim desta seção). Nenhuma mudança de config,
`build.version` não precisou bump. Validado com teste isolado (33 checks,
sem rede) — **pendente de validação em campo**.

**Problema:** `ConquestManager._build_escort()` (`game/attack.py`, função
em torno da linha 862) monta a escolta lendo `self.troopmanager.troops.items()`
**bruto**, sem descontar `TroopManager.total_conquest_reserve()` — diferente
de `AttackManager._get_farmable_troops()` (mesmo arquivo, linhas ~71-87),
que já faz isso corretamente pro farm. Isso significa que a conquista
bárbara pode comprometer tropa que o PvP Conquest já reservou (chave
`"pvp:{target_id}"`, ver `game/pvp_conquest.py::_reserve_troops()`) —
mesma categoria de bug do incidente real do clear em `38409`
(`docs/features_log.md`, 2026-08-07), só que entre dois sistemas
diferentes reivindicando a mesma tropa em vez de dentro de um só.

**Por que é urgente agora:** até esta sessão isso era teórico, porque
`conquest.enabled: false`. O usuário ligou a conquista bárbara enquanto o
PvP Conquest também está ativo nas mesmas 2 aldeias geridas — os dois
sistemas competem pela mesma tropa de verdade a partir de agora.

**⚠️ Armadilha de auto-bloqueio a evitar:** `total_conquest_reserve()`
soma **todas** as chaves de `conquest_reserve`, incluindo a própria
`"barbarian_conquest"` que este mesmo manager usa (setada em `run()`,
linha ~550, quando a escolta ainda está insuficiente, pra impedir
farm/gather de gastar essa tropa enquanto ela se acumula ciclo a ciclo).
Se `_build_escort()` simplesmente subtrair `total_conquest_reserve()` sem
excluir a própria reserva, ele se auto-bloqueia: reserva setada → próximo
ciclo, tropa disponível já sai reduzida por essa mesma reserva → escolta
parece insuficiente de novo → reserva nunca é liberada, mesmo quando a
tropa real já seria suficiente. **A própria chave `"barbarian_conquest"`
precisa ser excluída do cálculo.**

**Plano de implementação:**

1. `game/troopmanager.py::TroopManager.total_conquest_reserve()` (linha
   ~102) — adicionar parâmetro opcional `exclude_owner=None`, mudança
   aditiva/compatível (chamadas existentes sem argumento continuam iguais):
   ```python
   def total_conquest_reserve(self, exclude_owner=None):
       total = {}
       for owner_key, reservation in self.conquest_reserve.items():
           if owner_key == exclude_owner:
               continue
           for unit, qty in reservation.items():
               total[unit] = total.get(unit, 0) + int(qty)
       return total
   ```

2. `game/attack.py::ConquestManager._build_escort()` (bloco `available = {...}`,
   linhas ~879-883) — descontar a reserva de **outros** donos:
   ```python
   reserve = self.troopmanager.total_conquest_reserve(
       exclude_owner="barbarian_conquest"
   ) if hasattr(self.troopmanager, "total_conquest_reserve") else {}
   available = {
       unit: max(0, int(qty) - reserve.get(unit, 0))
       for unit, qty in self.troopmanager.troops.items()
       if unit not in self.EXCLUDED_UNITS and int(qty) > 0
   }
   ```

3. **Bônus, achado ao mapear este plano (mesma função, escopo mínimo pra
   incluir junto):** `EXCLUDED_UNITS = {"spy"}` (linha ~490) não exclui
   `"knight"` — a conquista bárbara pode incluir o Paladino na escolta,
   violando a mesma regra já aplicada ao PvP Conquest em 2026-08-07 ("o
   Paladino nunca deve sair da aldeia sozinho", ver `docs/features_log.md`).
   Trocar para `EXCLUDED_UNITS = {"spy", "knight"}`.

**Teste antes de considerar pronto** (isolado, sem rede — mesmo padrão dos
`_test_*.py` temporários já usados nesta sessão, criar e deletar depois):
- (a) `conquest_reserve` com uma chave `"pvp:X"` populada + tropas no
  village → confirmar que `_build_escort()` desconta corretamente dessa
  chave.
- (b) `conquest_reserve` com a própria `"barbarian_conquest"` já setada
  (simulando um ciclo anterior com escolta insuficiente) → confirmar que
  ela **não** é descontada de si mesma (a fórmula não pode travar).
- (c) confirmar que `knight` nunca aparece em `per_attack` mesmo com
  `knight` disponível no village.

**Arquivos tocados:** `game/troopmanager.py`, `game/attack.py`. Nenhuma
mudança de config necessária (`build.version` não precisa bump).

**Risco:** mexe em `ConquestManager`/tropas reais — CLAUDE.md pede revisão
extra cautelosa nesses módulos. Escopo é pequeno e isolado (uma função),
mas testar isolado (item acima) antes de rodar contra o jogo de verdade, e
reiniciar o bot pra pegar o código novo (mesma mecânica de sempre — processo
já rodando mantém o código antigo em memória).

### O que saiu além do plano

A lógica de reserva foi extraída para um helper (`_available_troops()`) em
vez de ficar inline em `_build_escort()`, porque **`_calculate_needed_escort()`
tinha exatamente o mesmo defeito** — lia `troops` bruto para decidir quanto
reservar. Sem corrigir os dois, a soma das reservas podia exceder a tropa
real da aldeia, deixando farm/gather sem tropa que só existe no papel.

Dois achados a mais, da mesma família de double-booking:

1. **Nobres não eram cobertos.** `PvpConquestManager` reserva `snob: 1` por
   ataque agendado (`game/pvp_conquest.py:430`), e esses nobres ficam parados
   em casa por horas enquanto o `Hunter` sincroniza a chegada. Tanto `run()`
   quanto `_handle_existing()` liam `troops["snob"]` cru, então a conquista
   bárbara podia se achar com train completo e disparar, gastando nobres de um
   train PvP já agendado. Novo `_available_nobles()`. **É a instância mais cara
   do bug** — nobre é a unidade mais custosa do jogo, e o plano original do
   backlog não a cobria.
2. **`snob` entrava no cálculo da escolta.** `_send_train()` faz
   `troops["snob"] = 1` por ataque (`game/attack.py`), sobrescrevendo o que a
   escolta tivesse calculado. Ou seja: nobres inflavam `total_per_attack` na
   checagem de `min_escort_total`, mas nunca eram enviados como escolta — um
   train podia ser julgado "escoltado o suficiente" às custas de tropa que não
   ia junto. `snob` entrou em `EXCLUDED_UNITS` junto com `knight`. Isso torna
   a checagem mais conservadora (direção segura: no máximo deixa de enviar um
   train que antes enviaria com escolta real menor que o configurado).

**Segunda opção, se preferir não fazer esta agora:** "PvP Conquest não
detecta trem de nobres que falhou" (bullet acima, já detalhado) — também
bem escopada, mas menos urgente porque não tem risco de "roubar" tropa de
outro sistema, só falta de retry/sinalização de erro.

---

## Pendências transversais (não são features novas, mas trabalho aberto)

- ~~**PvP Conquest (Feature 13) não detecta trem de nobres que falhou**~~ —
  ✅ **corrigido em 2026-08-11.** `_step_check_complete()` agora, quando a
  aldeia não é nossa, delega para o novo `_maybe_mark_failed()`: passada a
  janela de tolerância (`FAILED_GRACE_SECONDS = 7200`, deliberadamente maior
  que o fallback de 1h de `_maybe_release_reserve` — a posse só fica visível
  quando um scan de mapa atualiza `cache/villages/{id}.json`, o que é
  guiado pelo ciclo do bot, não pela chegada do ataque), o alvo vira
  `status: "failed"` com `failed_at` e um `fail_reason` que distingue
  "checamos e não é nossa" (`train_arrived_no_conquest`) de "não deu pra
  checar" (`train_outcome_unknown`, sem dado de mapa ou sem `player_id`
  resolvível). A confirmação de posse continua vencendo: se a aldeia for
  nossa, `complete` é aplicado mesmo muito depois da janela.
  **Sem retry automático de propósito** — reagendar mandaria nobres reais de
  novo sem saber por que o primeiro train morreu, que é exatamente o caso que
  pede olho humano. O alvo fica terminal e visível em `/pvp_conquest`
  (badge "Falhou" + alerta com o motivo, acima das colunas para não ficar
  escondido embaixo de um bloco de simulação "Viável"), de onde pode ser
  removido e readicionado. `failed_at` também entrou na timeline do
  `/empire`. Nenhuma config nova, `build.version` não precisou bump.
  Validado com teste isolado (20 checks, sem rede) — **pendente de validação
  em campo**, que só acontece no próximo train que realmente falhar.
  Diagnóstico original: `_step_check_complete()` só transicionava
  `status: "scheduled"` → `"complete"` quando a aldeia-alvo mudava de dono.
  Se os nobres chegassem e a conquista **não** acontecesse (lealdade não
  zerou, nobres foram destruídos por falta do clear, etc.), o alvo ficava
  parado em `"scheduled"` pra sempre — nenhum código verificava se o
  `arrival_time` já tinha passado sem sucesso, nem marcava como `"failed"`.
  Só a reserva de
  tropas (`_maybe_release_reserve`) tinha um fallback por tempo
  (`arrival_time + 3600s`) — a reserva era liberada mesmo sem sucesso, mas o
  `status` do alvo em si nunca refletia a falha.
  Descoberto ao vivo em 2026-08-07 quando o clear do alvo 38409 falhou por
  tropa insuficiente (ver `docs/features_log.md`) — os nobres seguiram
  viagem mesmo assim (usuário já tinha limpado manualmente), mas se não
  tivesse, o alvo teria ficado `"scheduled"` indefinidamente sem qualquer
  sinal de que precisa de intervenção manual.
- ~~**`ConquestManager` (conquista bárbara, Feature 8) não respeita
  `TroopManager.total_conquest_reserve()`**~~ — ✅ resolvido pela **Feature 27**
  em 2026-08-08, incluindo o caso dos nobres, que o plano original não cobria.
  Aguardando validação em campo.
- **Sobrecomprometimento de tropa entre clear e escolta de nobre — só
  corrigido para 1 alvo por vez.** O fix de 2026-08-07 em
  `_step_simulate()` (`game/pvp_conquest.py`) subtrai `attacker_units` do
  total bruto da aldeia de clear antes de calcular a escolta, garantindo
  que as duas reivindicações de **um mesmo alvo** nunca somem mais que
  100% da tropa disponível. Não cobre o caso de uma mesma aldeia estar
  comprometida com tropas de **múltiplos alvos de PvP Conquest agendados
  ao mesmo tempo** — cada `_step_simulate()` roda isolado, sem visibilidade
  do que outros alvos já reservaram naquela aldeia via
  `total_conquest_reserve()`. Só um alvo estava ativo no ambiente real
  nesta sessão, então o caso nunca foi exercitado.
- **Piso `max(1, ...)` na escolta de nobre ainda pode sobrecomprometer
  unidades muito escassas.** O bug do Paladino (`knight`) foi resolvido
  excluindo-o completamente da escolta/clear (nunca deveria sair
  automaticamente mesmo). Mas a mesma fórmula (`max(1, int(qty*ratio) //
  noble_count)`) se aplica a qualquer outra unidade — se `ram` ou
  `catapult`, por exemplo, tiverem uma contagem baixa (menor que
  `noble_count`), o piso de "pelo menos 1 por ataque" ainda pode pedir mais
  do que existe no total. Baixa prioridade — essas unidades normalmente não
  ficam tão escassas quanto o Paladino (que é sempre só 1 por aldeia), mas
  é o mesmo padrão de bug, não totalmente eliminado.
- **Bugs do sistema de bandeiras** (`DefenceManager`) — corrigidos no código
  em 2026-08-02 (troca constante de bandeira e loop de upgrade), aguardando
  validação em campo. Bot ainda só reconhece tipos de bandeira 1 e 4 dos 8
  existentes no jogo — ver `docs/bugs_flags.md` para o mapeamento completo
  dos 8 tipos, ainda não implementado (`FLAG_TYPES`).
- Feature 12 (evacuação preventiva regional) — implementada, aguardando
  validação em campo.
- Feature 13 (PvP conquest) — **validada em campo em 2026-08-07, conquista
  confirmada de ponta a ponta**: alvo real (38409) percorreu o fluxo
  completo — scout → simulação → agendamento → Hunter disparando de
  verdade (4 nobres enviados com sucesso, clear falhou por bug de
  sobrecomprometimento de tropa, já corrigido) → **posse confirmada**
  (`cache/villages/38409.json` com `owner` batendo com a aldeia própria),
  village passou a ser gerenciada normalmente (construção, farm, herança de
  config/profile). Essa validação revelou e corrigiu, no total, dez bugs
  que nunca tinham sido exercitados contra um bot rodando de verdade e uma
  conquista real — ver `docs/features_log.md` para o registro completo:
  ordem de execução antes do farm, encadeamento de passos por ciclo,
  múltiplos nobres por aldeia, exclusão do Paladino, bug crítico de
  `target_id` que impedia qualquer disparo real do Hunter, o
  sobrecomprometimento de tropa clear+escolta, `self.villages` nunca
  sincronizando aldeias novas em `twb.py`, `inherit_on_first_run`
  divergente do exemplo, detecção de posse sempre falhando silenciosamente
  em `PvpConquestManager._step_check_complete()`/`ConquestManager._target_is_mine()`
  (atributos inexistentes em `WebWrapper`), confirmação de leitura de
  bandeira presa a um regex específico, timeline do `/empire` só lendo o
  sistema de conquista errado (bárbara, desativado, em vez de PvP), e
  tooltip do mapa de calor do `/empire` desalinhado por mismatch de escala
  do canvas. Lacunas que sobraram dessa validação estão listadas acima
  (detecção de trem falhado, conquista bárbara não respeitando reserva,
  sobrecomprometimento entre múltiplos alvos simultâneos). Ver Feature 18
  acima para o refinamento de moral/night bonus no simulador usado por essa
  feature (ainda não validado separadamente).
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
