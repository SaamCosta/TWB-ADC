# Backlog — Features pendentes

Ordem de implementação até agora: `4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 18 → 19 → 20 → 21 → 22 → 23 → 24 (fase 1) → 14 → 15 → 16` (✅ todas)

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
