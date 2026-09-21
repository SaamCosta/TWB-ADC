# TWB-ADC — Contexto para Claude Code

**Projeto:** Automação avançada para mid/late game em Tribal Wars
**Bot base:** [stefan2200/TWB](https://github.com/stefan2200/TWB)
**Fork:** [SaamCosta/TWB-ADC](https://github.com/SaamCosta/TWB-ADC) (branch `master`)
**Servidor ativo:** br143.tribalwars.com.br

## Fonte da verdade

Este repositório clonado localmente **é** a fonte da verdade. Não é necessário
buscar o conteúdo no GitHub antes de editar — trabalhe direto nos arquivos locais.
Antes de qualquer edição, rode `git status` e `git diff` para confirmar que não há
mudanças locais não commitadas/sincronizadas que possam ser sobrescritas.

Fluxo de push: `git add . → git commit -m "msg" → git push origin master`

## Arquitetura (visão geral)

- **`twb.py`** — loop principal. Carrega config, itera aldeias gerenciadas,
  chama `Village.run()` por ciclo, depois dispara sistemas globais
  (`Hunter`, `ZoneManager`, `PvpConquestManager`, `VillageManager.farm_manager`).
- **`game/village.py`** — orquestrador por aldeia. Chama, em ordem, os managers:
  `BuildingManager` → `TroopManager` → `SnobManager` → `AttackManager` /
  `ConquestManager` → `DefenceManager` → `ResourceManager` /
  `ResourceSharingManager`. Também guarda cache de estado em `cache/managed/*.json`.
- **Managers de jogo (`game/`)**:
  - `attack.py` — `AttackManager` (farm) e `ConquestManager` (noble trains contra bárbaros)
  - `defence_manager.py` — `DefenceManager` (bandeiras, evacuação, suporte entre aldeias)
  - `troopmanager.py` — recrutamento, pesquisa, gather
  - `buildingmanager.py` — fila de construção
  - `resources.py` / `resource_sharing.py` — mercado e transferência direta entre aldeias
  - `hunter.py` — agendamento de ataques coordenados (Feature 10)
  - `zone_manager.py` — clustering geográfico de aldeias (Feature 11)
  - `pvp_conquest.py` — conquista PvP semi-manual (Feature 13)
  - `simulator.py` — simulador de batalha (usado pelo PvP conquest)
- **`core/`** — infraestrutura: `request.py` (HTTP/sessão), `extractors.py` (regex sobre
  HTML do jogo), `filemanager.py`, `templates.py`, `reporter.py`, `notification.py`.
- **`webmanager/`** — dashboard Flask separado, lê os mesmos arquivos de `cache/` e
  `config.json`. Rotas em `server.py`, lógica de leitura em `utils.py`.
  `BotManager` (reescrito em 2026-09-14) sobe o bot num **console visível
  próprio** (`CREATE_NEW_CONSOLE`, sem redirecionar stdout) e **adota**
  qualquer `twb.py` vivo neste diretório, tenha sido iniciado pelo painel ou
  pelo `cmd` — ver o vigésimo segundo padrão abaixo. O output do painel vem do
  `cache/logs/session_latest.log` (o tee do próprio `twb.py`), não mais do
  `bot_output.log`. Testes em `tests/test_bot_manager.py`, mais um smoke com
  processo real em `tests/smoke_bot_manager.py` (fora do glob da suíte de
  propósito: abre console de verdade; rodar na mão ao mexer em `BotManager`).
- **Cache (`cache/`)** — todo estado runtime persiste em JSON por diretório
  (`cache/attacks`, `cache/conquest`, `cache/managed`, `cache/zones.json`,
  `cache/hunter/schedules.json`, `cache/pvp_conquest`, etc). `.gitignore` cobre
  `cache/**`, `config.json`, `config.bak`.

## Convenções

- **Existe `tests/`** desde 2026-08-13 (antes não existia; se alguma nota falar
  em "sem test suite", está velha). São testes pontuais de lógica pura, sem
  rede e sem estado de jogo. Rodar:
  `foreach ($t in (Get-ChildItem tests/test_*.py)) { python $t.FullName }`
  — cada arquivo roda sozinho, sem depender de `pytest` instalado. Os
  `tests/smoke_*.py` ficam **fora** desse glob de propósito: vão à rede ou
  abrem processo de verdade, e se rodam na mão (`smoke_bot_manager.py`,
  `smoke_conquest_reach.py`, `smoke_instance_lock_twb.py`).
  ⚠️ **Ao rodar a suíte no PowerShell, checar `$LASTEXITCODE`, não `$?`.**
  Vários testes escrevem WARNING em stderr, e no PowerShell 5.1 qualquer saída
  em stderr de executável nativo torna `$?` falso mesmo com código 0 — um laço
  com `if (-not $?)` reportou 15 falhas inexistentes numa suíte 100% verde em
  2026-09-20.
  Cobertura atual: conquista bárbara (nobre em voo, lealdade do relatório,
  alvo perdido, semântica de status, faixa de queda), encoding do
  `FileManager`, alocação de torre de vigia, limiares de slot de Paladino
  (`StatuePage`, recorte verbatim de `screen=statue`), escolha de pacote de
  farm por saque esperado (`AttackManager._ordered_templates`), mecânicas do
  mundo lidas de `get_config` (`WorldConfig._parse_features`, com recortes
  verbatim de br143 sem arqueiro e br142 com), o motivo da recusa do jogo
  (`Extractor.error_box_text`, fixture verbatim de um `error_box` real) e o
  limite de ataque falso (`_legalize`, `min_attack_population`), a venda na
  bolsa premium (`do_premium_stuff`, com os números da bolsa lidos do br143 em
  2026-08-20), a integridade dos templates de builder
  (`tests/test_builder_templates.py`) e a leitura dos comandos recebidos na
  visão geral (`Extractor.incoming_commands`, recorte verbatim de um trem de
  nobres real em 2026-08-22 — inclui um teste que roda o regex **antigo**
  contra o markup real e exige zero casamentos, para o bug não voltar calado)
  e o gate de urgência do apoio (`DefenceManager.support_timing`,
  `WorldConfig.travel_seconds`, com as velocidades de quatro mundos que provam
  que `get_unit_info` já publica min/campo **efetivo**) e o bônus do "Sinal da
  Aflição" (`Extractor.incoming_support_speed_bonus`, com a fórmula
  `duração / 1,3` medida contra um envio real em vez de deduzida do texto),
  o alcance do mapa (`Map.sector_grid`/`merge_sectors`/`fetch_sectors`, com
  recorte verbatim de `map.php?v=2`), a classificação de perfil de farm por
  lotação e aproveitamento (`tests/test_farm_profiles.py`), a guarda de que
  importar `twb.py` não trunca o log de sessão
  (`tests/test_session_log_guard.py`) e a integridade da config
  (`tests/test_config_integrity.py` — varre por AST toda chamada a
  `get_config`/`get_village_config` e exige que a chave exista em
  `config.example.json` / `village_template` e esteja documentada em
  `webmanager/helpfile.py`; é a verificação automática das três regras de
  config deste arquivo) e a política de bandeira por academia
  (`tests/test_flag_policy.py`, que roda a política contra o snapshot real das
  18 aldeias) e o `ReportReader` do webmanager
  (`tests/test_report_reader.py` — veredito agregado por alvo espelhando
  `ReportManager.safe_to_engage`, rótulo de aldeia com o `name=0` de bárbara,
  filtro de tipo dinâmico e paginação; substitui as duas funções que tocam
  disco por fixtures, então não depende do `cache/` real) e a elegibilidade de
  alvo do trem multi-origem (`tests/test_conquest_target_reach.py` — pool de
  candidatos e alcance por origem, com as coordenadas reais do bolsão oeste do
  K25; ver o vigésimo quarto padrão) e a trava de instância única
  (`tests/test_instance_lock.py` — recusa cross-process com subprocessos de
  verdade, porque trava de arquivo é **reentrante no mesmo processo** e um teste
  in-process não distinguiria trava real de no-op; `docs/backend.md` §8.10).
  **A maior parte do bot continua
  sem cobertura** — em especial tudo que faz requisição — então revisar diffs
  manualmente segue valendo. Ao introduzir lógica pura e isolável, escrever
  teste pontual.
- **Fixture de markup do jogo se copia do servidor, não se inventa.** Os
  testes de `Extractor` usam recortes verbatim de HTML real; a versão anterior
  de `loyalty_from_report()` falhava justamente por ter sido escrita contra um
  markup suposto. Para buscar: cookies em `cache/session.json`, user-agent em
  `config.json` → `bot`, e um `requests.session()` acessa
  `game.php?village=NNN&screen=report&mode=all&view=<id>` sem atrapalhar o bot
  rodando.
- **Nunca commitar `config.json`** (contém credenciais/sessão) — só `config.example.json`.
- **Ao adicionar bloco de configuração novo, bumpar `build.version` SÓ em
  `config.example.json`.** A redação anterior desta linha mandava bumpar "em
  `config.example.json` e `config.json`", e está errada: seguindo-a ao pé da
  letra em 2026-08-20 eu deixei as duas versões iguais e **desliguei** a
  propagação que queria causar. O mecanismo real (`twb.py:231`) é
  `if config["build"]["version"] != template["build"]["version"]: merge` — o
  merge roda quando as versões **divergem**, e é ele que injeta a seção nova no
  `config.json` do usuário (salvando `config.bak` antes). Versões iguais = nada
  acontece e a seção nunca chega na config real.
  Antes de disparar o merge num `config.json` vivo, conferir o que
  `merge_configs()` descarta: ele usa o template como base e só preserva chave
  que exista **nos dois**, então chave que só existe no `config.json` some.
  (Aldeias são a exceção: lá ele acrescenta do `village_template` sem remover —
  foi assim que `scout_first`, chave morta que nenhum código lê, sobreviveu.)
- Ao adicionar config nova, atualizar **`config.example.json`** e
  **`webmanager/helpfile.py`** (`help_file` + `nested_sections` se for dict aninhado)
  no mesmo commit.
- **Toda chave lida por aldeia tem que existir em `village_template`.** Se o
  código faz `config["villages"][vid].get("x")`, então `x` precisa aparecer em
  `village_template` no `config.example.json`, nem que seja com o valor
  neutro/vazio. O template é o que documenta o que é configurável por aldeia e
  é a fonte de `add_village()` e do merge por `build.version` — uma chave fora
  dele é invisível para quem lê a config e some nas aldeias novas.
- Mudanças em `AttackManager` / `ConquestManager` / `DefenceManager` afetam tropas
  reais em jogo — revisar com cautela extra antes de considerar "pronto".
- Preferir tarefas pequenas e escopadas (um manager/feature por vez) em vez de
  mudanças amplas simultâneas.

## Bugs conhecidos / débito técnico

**Auditoria completa na seção 5 de `docs/backend.md`** — leitura integral
dos 34 `.py`, com 5 achados P0, 14 P1, 20 P2 e dívida técnica, cada um com nível
de confiança e correção sugerida. **Lotes 1 a 7 corrigidos** (estado compartilhado,
integridade de dados, features ressuscitadas, crashes de caminho quente, no
Lote 5: segurança do webmanager, `farm_score`, mercado em pt-BR, paz forçada,
no Lote 6: a reserva de escolta que travava o farm e o I/O do PvP conquest, e no
Lote 7: o piso de moral). Seções já corrigidas levam um banner ✅ no topo; a ordem
priorizada e as notas de implementação de cada lote estão no fim do documento.

**Nenhum item da auditoria segue aberto.** O último (P2-29) foi fechado em
2026-08-12 — ver o Lote 7 e o quinto padrão abaixo.

⚠️ **Aberto, fora da auditoria: rastreio de conquista sumiu sem explicação.**
Em 2026-08-12 às 19:46 o `ConquestManager._get_my_conquest()` devolveu `None`
para a Bárbara #40314 com o arquivo `cache/conquest/40314.json` em
`status: "train_sent"` e mtime de 11:56 — nada tinha reescrito o arquivo no
intervalo. Como `existing` veio falsy, o `run()` seguiu para `find_target()`,
que reelegeu **o mesmo alvo** como se fosse novo e disparou um segundo trem
inteiro de 4 nobres. A assinatura no log é o `_build_escort()` aparecendo
**duas vezes** seguido de `sending noble train` (o caminho de alvo novo chama
`_build_escort` no `run()` e de novo no `_send_train`; o caminho de conquista
existente chama uma vez só). Não reproduzi e não sei a causa — nenhum outro
caminho no código escreve nesse arquivo sem logar, não houve restart do
processo e o webmanager não estava rodando. A trava de nobre em voo
(`4c4229b`) impede o estrago por não depender de `status`, mas isso é
robustez, não diagnóstico: **se um trem duplicado reaparecer, é aqui que se
puxa o fio.**

- ⚠️ **Padrão de bug recorrente neste projeto: atributo de classe mutável.**
  Quase toda classe aqui declara seus campos no corpo da classe, não em
  `__init__`. Para `int`/`str`/`bool`/`None` é inofensivo (a atribuição cria
  um atributo de instância), mas para `list`/`dict` mutados in-place
  (`.append()`, `[k] = v`) o objeto é **compartilhado por todas as instâncias**.
  Como existe uma instância de quase todo manager por aldeia, isso vira
  vazamento de estado entre aldeias. Corrigidos no Lote 1: `TWB.villages`,
  `ResourceManager.actual`/`requested`, `Map.villages`/`map_pos`/`map_data`,
  `DefenceManager.supported`/`attacks`/`flags`/`current_flag`. No Lote 5:
  `BuildingManager.waits`/`queue`/… (P2-23), `AttackManager.ignored`/
  `_unknown_ignored` (P3) e `ReportManager.last_reports`. **Nenhum aberto que
  eu conheça** — mas ao criar classe nova ou campo novo, declarar mutáveis em
  `__init__`.
- ⚠️ **Segundo padrão recorrente: `None` não guardado vindo de rede/parse.**
  `WebWrapper.get_url()` retorna `None` em **qualquer** exceção
  (`core/request.py`), e por tabela `get_action`/`get_api_action` também.
  Vários `Extractor.*` (`game_state`, `recruit_data`, …) têm `return None`
  implícito quando o regex não casa — o que acontece numa resposta 200 que não
  é a tela esperada: sessão expirada virando login, página de bot protection,
  ou markup novo do jogo. O consumidor típico faz `res.text`, `x in res` ou
  `res["chave"]` direto e derruba o processo. O Lote 4 corrigiu cinco desses
  só no caminho de recrutamento, dos quais **quatro não estavam no diagnóstico
  original** — ao mexer num caminho que faz requisição, assumir que há mais.
  `buildingmanager` (P2-24), `reports` (P2-25), `manager.py` (P2-26),
  `resources` (P2-30) e `overview` (P2-31) foram fechados no Lote 5.
  Corolário achado no Lote 4: `ResourceManager.logger` era criado só no fim
  de um `update()` bem-sucedido, então a própria guarda nova crashava. Ao logar
  num caminho de erro, conferir se o logger já existe naquele ponto — o mesmo
  vale para `BuildingManager.start_update()`, corrigido no Lote 5.
- ⚠️ **Terceiro padrão, achado no Lote 5: função definida mas nunca chamada.**
  `Village.check_forced_peace()` estava correto e órfão — `farms.forced_peace_times`
  era config inerte e o bot atacaria durante a paz forçada. O Lote 3 já tinha
  "corrigido" um bug *dentro* dele sem notar. **Ao corrigir o corpo de uma
  função, conferir os chamadores no mesmo passo** (`grep` pelo nome; se a única
  ocorrência for a `def`, é código morto). Corolário: ao ressuscitar um caminho
  morto, reler os consumidores assumindo que nunca foram exercitados — foi assim
  que apareceu o bug do `score or default` no P1-8, e a necessidade de tornar
  explícito o bloqueio de paz forçada no P1-17. **Segundo corolário, do Lote 6
  (P2-22):** vale também quando o corpo continua chamado, mas o *domínio de
  retorno* muda. `_calculate_needed_escort()` só devolvia `{}` num caso que
  quase nunca ocorria, então o `if needed:` do chamador não tinha `else` e isso
  era inofensivo; ao tornar `{}` um retorno comum, o `else` ausente virou uma
  reserva presa para sempre — exatamente o bug que a correção existia para
  matar. Ao alargar o conjunto de valores que uma função pode devolver, reler
  cada consumidor perguntando "e se vier este valor agora?".
- ⚠️ **Quarto padrão, achado em 2026-08-12: remover config "morta" sem
  perguntar o que ela nomeia.** Ao limpar as três chaves do P3 ("declarado mas
  nunca lido"), verifiquei que nenhuma tinha leitura no código e removi. Para
  `farms.find_player_owned` isso era verdade e mesmo assim insuficiente: a
  chave dizia "atacar aldeias de jogador", e **essa capacidade existe** —
  `AttackManager` farma aldeia de jogador desde que ela esteja em
  `village.additional_farms` (`attack.py:201`, com trava adicional de 23h–8h em
  `attack.py:238`). O que não existia era o modo *automático sem lista* que a
  chave prometia. Nada quebrou porque a chave era de fato inerte, mas eu não
  sabia disso quando removi — só tinha checado "alguém lê?", não "o que isso
  significa e existe em outro lugar?". Grep por leitura responde se é seguro
  remover; não responde o que o usuário perde de vista ao remover.
  **Formato obrigatório ao relatar remoção de config** (formulação do usuário,
  2026-08-12): *"`X` não existe e não funciona — mas `Y` funciona e serve para
  isso"*. Se não der para preencher o `Y`, é sinal de que a funcionalidade não
  foi mapeada e a remoção ainda não está pronta para ser relatada. Dizer só
  "chave morta, removida" está certo no mérito e ainda assim leva quem lê a
  concluir que a capacidade sumiu — foi o que aconteceu aqui, e só não virou
  problema porque o usuário desconfiou.
- ⚠️ **Quinto padrão, achado em 2026-08-12 (P2-29): valor real lido do campo
  errado, e "bloqueado por falta de dado" que ninguém tentou destravar.** O
  `estimate_moral()` derivava o piso de moral de `mood.loss_max`, e o docstring
  se defendia dizendo que o número veio "confirmado ao vivo" do servidor — o que
  era verdade sobre a *origem* e falso sobre o *significado*: `<mood>` não é a
  config de moral do TW; quem manda é a tag de topo `<moral>` (0/1/2/3). Um
  número real, lido do servidor, do campo errado — **é mais convincente que um
  palpite e por isso passa mais fácil.** Ao escrever "confirmado ao vivo", dizer
  *qual tag*, não só que veio do servidor.
  Segunda metade da lição: o item ficou aberto por duas semanas com a nota
  "precisa de uma amostra do servidor antes de mexer", e a amostra custava um
  `Invoke-WebRequest` — `interface.php?func=get_config` é **público e sem
  autenticação**, e o cache local já existia com outro nome
  (`cache/world/config_br143.json`, não `cache/world_config*` como a nota dizia).
  Antes de adiar por falta de dado, conferir se o dado é buscável agora e se o
  arquivo procurado só tem outro nome.
  **Terceira metade, cometida na própria correção acima, menos de uma hora
  depois:** ao mapear os valores de `<moral>` (0/1/2/3) usei a wiki da
  comunidade e escrevi "2 = só por tempo", fazendo esse modo devolver
  `moral=100` — a mesma superestimativa que o P2-29 existia para matar, válida
  em 6 dos 8 mundos br ativos. O certo é que **não existe modo "só por tempo"**:
  2 é "pontos e tempo" e 3 é "pontos e tempo ilimitado". **Enum de jogo se mapeia
  contra o servidor, não contra a wiki** — e o servidor publica os dois lados de
  graça: o valor bruto em `interface.php?func=get_config` e a redação
  correspondente em `/page/settings`, por mundo. A lista de mundos sai de
  `backend/get_servers.php` por mercado. Cruzar ~30 mundos custa dois
  `Invoke-WebRequest` cada e transforma palpite em tabela; foi assim que
  `night.active` (0 = off, 1 = janela fixa do mundo, 2 = janela escolhida por
  cada jogador) e o `<duration>` constante saíram do "desconhecido". Tabelas
  completas na seção 4.3 de `docs/backend.md`.
  **Quarta metade, cometida em 2026-08-13 — a nota acima já existia e mesmo
  assim não me salvou.** Procurei a regeneração de lealdade
  (`conquest.loyalty_regen_per_hour`, que valia 1.5), não achei campo
  correspondente em `get_config`, e concluí em voz alta que "não tem fonte
  verificável no servidor", propondo ao usuário medir na mão dentro do jogo. O
  valor estava publicado em português, numa tabela, em `/page/settings`:
  *"Aumento de lealdade por hora: 1"* — 50% abaixo do que o config assumia. O
  usuário teve que mandar o print.
  A lição anterior dizia "cruze os dois lados"; eu li isso como *"use
  `/page/settings` para traduzir um enum que já achei em `get_config`"*, e não
  como o que ela também diz: **`get_config` e `/page/settings` não expõem o
  mesmo conjunto de campos.** Ausência em `get_config` não é ausência no
  servidor. `/page/settings` é a página que fala a língua do jogador, então um
  parâmetro de regra tende a aparecer lá com nome legível mesmo quando não há
  tag XML para ele. Regra prática: **"não achei" só vale como conclusão depois
  de dizer onde procurou** — e para número de mundo isso significa citar as
  duas fontes, não uma.
  **Quinta metade, 2026-08-16, e a mais desconfortável: o código já nomeava a
  fonte certa e argumentou contra ela.** `StatuePage._parse_locked_slots()`
  regexava um texto renderizado que nunca chega na resposta HTTP (só existe
  depois que o JS monta o template no navegador), então devolvia `[]` em todo
  ciclo. O docstring dessa função **citava** o 3º argumento de
  `BuildingStatue.initImmutables(...)` como alternativa — e a descartava por
  ser "uma constante fixa do JS que teoricamente poderia variar". Era ali que
  o dado estava, server-side, na mesma resposta que o bot já baixava; um
  `requests.get` com a sessão do bot mostrou `[1,3,5,10,20,35,50,65,80,100]`
  em dez segundos. A nota de campo que diagnosticou o bug repetiu o erro por
  outro caminho: procurou os limiares no 3º argumento de `receiveKnightsData`
  (que é `0`), não achou, e concluiu "provavelmente hardcoded num bundle JS
  estático" — quase levando a chumbar a lista no bot.
  As metades anteriores diziam "procure nas duas fontes antes de dizer que não
  existe". Esta acrescenta: **quando você mesmo escreveu qual é a fonte
  plausível, olhar custa menos que o parágrafo justificando não olhar.** Um
  descarte fundamentado ("poderia variar") soa como análise e não passa de
  palpite enquanto ninguém abriu a resposta — e um parser que devolve lista
  vazia falha em silêncio, então ninguém percebe por meses.
- ⚠️ **Sexto padrão, achado em 2026-08-13: decidir sobre um estado do mundo
  que mudou desde a última vez que se olhou.** Este bot age num mundo remoto
  com latência de **horas** — um trem de nobres voa ~4h. Entre decidir e o
  efeito acontecer, o mundo anda. Os três bugs que custaram 527 tropas e uma
  moeda na Bárbara #40314 são o mesmo erro em três roupas:
  1. O bot mandou nobre sem saber que **já havia nobre dele no ar** para o
     mesmo alvo. Não existia o conceito de "em voo" no modelo.
  2. Marcou a conquista como resolvida **no instante do envio**, 3h41 antes do
     impacto — e `last_hit_timestamp` contava regeneração a partir da saída do
     trem, não da chegada.
  3. Nunca reconferia se a bárbara ainda era bárbara. `find_target()` e
     `_get_manual_target()` revalidavam o dono; a conquista **já em andamento**
     não — então o bot seguiria nobrando a aldeia de um jogador que se
     adiantou.
  Regra prática ao mexer em qualquer coisa com efeito diferido: **separar
  "quando eu mandei" de "quando isso acontece", e reconferir a premissa no
  momento de agir, não no momento de decidir.** Corolário de desenho, que é o
  que faz a trava atual segurar: a guarda foi construída sobre **tempo de
  chegada**, não sobre o campo `status` — porque era justamente o `status` que
  estava errado (dizia `"complete"` com quatro nobres voando). Ao proteger
  contra um estado inconsistente, não se apoie no campo que pode estar
  inconsistente.
  Corolário do corolário: `Extractor.attack_duration()` devolve **0**, não
  `None`, quando o regex não casa. Somar 0 à hora de envio faz o nobre nascer
  "já pousado" — o valor de falha se disfarça de resposta válida. É o segundo
  padrão desta lista com outra máscara: ao consumir um parser, conferir *qual*
  valor ele devolve quando falha, e se esse valor é distinguível de um
  resultado legítimo.
- ⚠️ **Sétimo padrão, achado em 2026-08-16: sondar a API com um cliente
  diferente do que o bot usa.** Explorando o inventário com um
  `requests.Session()` montado à mão, mandei só `X-Requested-With` e vi
  `game.php?screen=inventory&ajax=get_inventory` devolver
  `{"inventory":…,"data":…,"expire":…}` no topo. Escrevi o parser contra isso,
  com fixture verbatim, e os testes passaram. Mas `WebWrapper.get_api_data`
  manda **também** `TribalWars-Ajax: 1`, e com esse cabeçalho **o mesmo
  endpoint embrulha tudo em `{"response": {...}, "game_data": {...}}`** — o
  parser teria falhado no primeiro ciclo real. Só apareceu porque rodei um
  smoke com os cabeçalhos do próprio wrapper antes de dar por pronto.
  A quinta metade do padrão acima diz "vá olhar a resposta do servidor". Esta
  acrescenta o que ela não diz: **a resposta depende de como você pergunta.**
  Ao sondar uma tela nova, reproduzir os cabeçalhos que o bot manda de fato
  (`core/request.py`: `get_url`, `get_api_data`, `get_api_action` — cada um
  monta um conjunto diferente), ou melhor, sondar chamando o próprio método do
  wrapper. Fixture capturada com o cliente errado é fixture de uma resposta
  que o bot nunca vai receber. Corolário: um smoke contra o servidor **depois**
  de os testes passarem não é redundância — foi o único passo que pegou isto.
- ⚠️ **Oitavo padrão, achado em 2026-08-16: chave de dict que colide com
  método de dict, em template Jinja2.** `{{ x.items }}`, `{{ x.pop }}`,
  `{{ x.get }}`, `{{ x.keys }}`, `{{ x.values }}`, `{{ x.update }}`,
  `{{ x.copy }}` — o Jinja2 tenta `getattr` **antes** de `x["chave"]`, então
  num dict Python puro o método nativo vence: a página renderiza
  `<built-in method …>` ou o `{% for %}` estoura com
  `'builtin_function_or_method' object is not iterable`. Preferir **renomear a
  chave** (foi o que `InventoryReader` fez: `entries`, não `items`) a
  contornar com `x['items']` — o contorno funciona e a colisão volta na
  próxima edição do template, porque nada no nome avisa que ela existe.
  **A metade que importa desta entrada é onde ela está escrita.** O bug já
  tinha acontecido na Feature 17 (coluna "Pop") e estava documentado — em
  `docs/backlog.md` (hoje consolidado em `docs/backend.md`), que não entra em
  contexto. Repeti o mesmo erro em
  2026-08-16 com a lição a um `grep` de distância e nunca lida. **Lição que
  vale para uma classe de erro, e não só para o arquivo onde ela apareceu,
  mora aqui**; o registro por feature guarda o caso, não a regra.
- ⚠️ **Nono padrão, achado em 2026-08-17: reconstruir estado passado a partir de
  logs que só registram o que o *bot* fez.** Para saber como a `BBM 002` estava
  quando foi conquistada, cruzei todas as linhas `TWB_BUILD` dela com os níveis
  atuais e li "nenhuma linha para armazém/mercado" como "esses edifícios não
  mudaram desde a conquista". Reportei com "confiança alta". Estava errado: o
  usuário tinha **demolido o mercado manualmente** de 21 para 14, e demolição
  manual não gera log nenhum — o valor que apresentei como herdado era um ponto
  intermediário do trabalho dele. A conclusão de fundo sobreviveu (mercado 21 é
  ainda mais extremo que 14), mas por sorte.
  A regra: **o log é registro das ações do bot, não do estado do mundo.** Ausência
  de linha prova que o bot não fez, não que ninguém fez — o usuário joga na mesma
  conta, e as ações dele são invisíveis aqui. Ao reconstruir passado por log,
  dizer explicitamente "o bot não mexeu nisso" em vez de "isso não mudou", e
  perguntar antes de calibrar confiança. Corolário que salvou a análise: o
  argumento independente (o template `watchtower_support` tem teto de mercado 10,
  logo 14 não pode ter vindo do bot **sob este template**) não dependia de log
  nenhum. Quando existir um argumento estrutural, ele vale mais que o rastro.
- ⚠️ **Décimo padrão, achado em 2026-08-18: relatar um limite observado como se
  fosse uma decisão de projeto.** Ao dimensionar templates de tropa, li nos
  builders que a fazenda parava no nível 25, e apresentei isso ao usuário como
  restrição — duas vezes, montando um plano inteiro em cima dela ("ou os builders
  sobem a fazenda, ou os templates cabem em 8.400"). O usuário perguntou: *"você
  chegou a investigar por que a fazenda aparece em 25?"*. Não tinha. O motivo é
  que **o arquivo simplesmente acaba ali** — as últimas linhas de
  `purple_predator_into_off` são `wood:30 stone:30 iron:30 storage:30 barracks:25`
  e o `farm:25` anterior nunca teve continuação. Não era teto pensado; era o fim
  de uma lista herdada do bot base. O `watchtower_support`, escrito neste projeto,
  já ia até 30 — a prova de que 30 era alcançável estava no diretório ao lado.
  A regra: **um limite lido de dados é um fato sobre o arquivo, não uma decisão
  de alguém.** Antes de desenhar em volta de um teto, perguntar o que o colocou
  lá; se a resposta for "ninguém, é onde acabou", ele não é restrição, é dívida.
  O sinal de alerta é escrever "X está limitado a N" sem conseguir completar
  "porque". Corolário barato: quando outro artefato do mesmo tipo ultrapassa o
  limite (aqui, outro template de builder chegando a 30), isso sozinho já refuta
  a leitura de que o limite é intrínseco.
- ⚠️ **Décimo primeiro padrão, mesma sessão: estatística agregada sobre amostras
  heterogêneas, que inverteu o sinal da conclusão.** Medi 336 ataques de farm e
  reportei "34% voltaram lotados, e nos demais o aproveitamento mediano foi 15%",
  concluindo que os pacotes eram **grandes demais** e propondo encolhê-los. Os
  envios, porém, vinham de duas configurações distintas — capacidade 8.000 (175
  ataques) e 1.600 (209). Separando: o de 8.000 lotou **46%** das vezes com 62%
  de aproveitamento, e o de 1.600 lotou 33% com 53%. **Nenhum dos dois era grande
  demais; os dois estouravam o teto.** A conclusão correta era o oposto da minha
  — e pior, como 46% dos envios voltaram exatamente com 8.000, o valor real
  daqueles alvos era e continuava **desconhecido acima disso**: a própria medição
  estava censurada pelo instrumento.
  A regra: **antes de tirar média de um conjunto, perguntar se ele é um conjunto.**
  Aqui o agrupamento óbvio (tamanho do pacote enviado) estava no próprio dado e
  custava um `groupby`. E quando a métrica é limitada por uma escolha nossa
  (capacidade do pacote, `max_farms`, teto de qualquer fila), tratar os valores
  no teto como **censurados**, não como observações — "voltou com 8.000" não
  significa "o alvo tinha 8.000", significa "o alvo tinha 8.000 ou mais". Foi
  exatamente por isso que a correção final aumentou o pacote maior: para medir
  onde fica o teto de verdade.
- ⚠️ **Décimo segundo padrão, achado em 2026-08-19: escrever um artefato novo de
  um tipo que já existe sem ler os irmãos dele.** Ao escrever `def_no_archer.txt`
  pus cavalaria pesada no estágio gated em `stable:10`. Rodando, as aldeias
  logaram `heavy failed because it is not researched` todo ciclo: pesada exige
  **Ferreiro 15** (lido de "Requisitos em falta" na tela do ferreiro), e elas
  estavam com ferreiro 6. O `watchtower_support.txt` — escrito neste projeto,
  no mesmo diretório, e que **eu tinha aberto e impresso na primeira ferramenta
  dessa mesma sessão** — já gateava o heavy em `smith:15`. A regra do jogo
  estava codificada corretamente a um arquivo de distância e eu não olhei.
  A regra: **ao adicionar mais um de algo (template, parser, manager, migração),
  ler os existentes antes — eles carregam restrições do domínio que ninguém
  escreveu em documento nenhum.** Um template não é só dados; é o lugar onde as
  regras do jogo foram descobertas na marra por quem veio antes. O sinal de
  alerta é escrever o primeiro arquivo de uma leva nova sem ter aberto nenhum
  irmão no mesmo passo.
  Corolário que salvou o resto: ao corrigir, **auditei os 8 templates contra a
  tabela de requisitos em vez de consertar só o que falhou**, e apareceu o mesmo
  erro pré-existente em `basic_into_off` (heavy e catapulta no estágio
  `barracks:15`, com ferreiro em 10), herdado do bot base e nunca exercitado.
  Bug achado em campo raramente é o único da sua classe — a correção barata é
  varrer a classe inteira enquanto a regra está fresca.
- ⚠️ **Décimo terceiro padrão, achado em 2026-08-19, e o mais traiçoeiro até
  agora: provocar um erro para ler a mensagem dele, e tratar isso como
  evidência sobre falhas que eu não tinha observado.** O bot vinha tendo
  ataques recusados e o código descartava o motivo. Levantei a hipótese "falta
  de tropa", e para confirmar **provoquei** uma recusa no servidor mandando
  9999 lanceiros de uma aldeia que tem zero. Veio *"Não existem unidades
  suficientes"*, e eu escrevi ao usuário: *"a hipótese estava certa, mas era
  inferência; agora é leitura"*. Não era. Eu li a mensagem do erro que **eu
  mesmo fabriquei** — um experimento que só podia produzir a resposta que eu já
  esperava. A causa real das recusas do bot era outra: o **limite de ataque
  falso** do mundo (todo ataque precisa carregar ≥ `fake_limit%` dos pontos da
  aldeia atacante em população), que só apareceu quando o log passou a mostrar o
  motivo verdadeiro, um ciclo depois.
  A regra: **experimento que só pode confirmar a hipótese não é evidência.**
  Antes de provocar um erro, perguntar "que resultado deste teste me faria mudar
  de ideia?" — se não houver, o teste não informa nada. Para descobrir por que
  algo falha, instrumentar a falha real e esperar; reproduzir uma falha de
  desenho próprio e chamá-la de a mesma coisa é fabricar confirmação. O caminho
  que funcionou custou uma linha de log e um ciclo de espera.
  Corolário sobre linguagem: escrever "agora é leitura, não inferência" é uma
  afirmação sobre a *procedência* do dado, e por isso soa mais forte que um
  palpite. Só vale quando o dado veio do caso em questão — dizer *de qual
  ocorrência* a mensagem foi lida é o que distingue as duas coisas.
- ⚠️ **Décimo quarto padrão, mesma sessão: número em arquivo é foto de uma
  relação, e expira sozinho quando o outro lado da relação se move.** O menor
  pacote de farm dos templates era `{"light": 15}` = 60 de população. A regra do
  jogo é "≥ 1% dos pontos da aldeia", então esse pacote era legal até a aldeia
  chegar a 6.000 pontos e ilegal depois — **sem nenhuma mudança no bot**. O
  sintoma foi 100% dos ataques de uma aldeia recusados, num código que não
  tinha sido tocado.
  A regra: ao escrever uma constante que existe em relação a um estado do jogo
  (pontos, nível de edifício, número de aldeias), perguntar se esse estado
  cresce. Se cresce, ou o valor vira função dele em runtime, ou o arquivo
  precisa de degraus que acompanhem — e aí os degraus são a coisa importante,
  não um detalhe de granularidade. Foi o usuário quem apontou que os templates
  originais do bot base **já escalavam os pacotes por estágio**, e que era
  justamente por isso; eu tinha achatado os quatro estágios finais num valor só
  e lido isso como simplificação inofensiva. Quando um artefato herdado varia
  onde eu simplificaria, a variação costuma estar codificando uma restrição que
  eu ainda não entendi (ver também o décimo segundo padrão).
- ⚠️ **Décimo quinto padrão, achado em 2026-08-20: detector que dispara sempre
  não detecta nada, e o custo é mascarar o caso que ele existia para pegar.**
  `_parse_incoming_resources()` tinha uma guarda boa no desenho — separava
  "nada a caminho" (normal, DEBUG) de "o rótulo está lá mas a estrutura mudou"
  (WARNING + dump da página). Só que ela procurava o rótulo **solto** no HTML,
  e `Chegando` também é item do menu de navegação, presente em toda tela de
  mercado. O WARNING disparava em todo ciclo, com um dump de 58 KB junto.
  A regra: ao escrever uma guarda que distingue A de B, perguntar **em que
  outro lugar da página aquele sinal aparece** — quase sempre há um C. O
  sintoma é um alerta que nunca fica quieto; a partir daí ele é indistinguível
  de um alerta quebrado, e ninguém vai investigar quando A finalmente
  acontecer. Correção barata e geral: ancorar a guarda no **mesmo** padrão que
  o parser real usa (aqui, exigir `:\s` como o `INCOMING_RE` já exigia), em vez
  de numa versão frouxa dele.
  Corolário sobre monitoramento, da mesma sessão: silêncio de um filtro não é
  prova de que está tudo bem, porque o filtro só vê o que eu escolhi. Ao
  responder "está tudo certo?", medir de novo em vez de inferir da ausência de
  eventos — foi assim que este alerta apareceu, num `grep` de todos os WARNING
  que o monitor não cobria.
- ⚠️ **Décimo sexto padrão, achado em 2026-08-20: seguir uma instrução deste
  arquivo sem conferir o código que ela descreve.** A regra de bumpar
  `build.version` mandava bumpar nos **dois** arquivos; obedeci literalmente e
  com isso deixei as versões iguais, o que **desliga** o merge — exatamente o
  contrário do efeito pretendido, porque `twb.py` só faz merge quando elas
  divergem. A seção de config nova nunca teria chegado ao `config.json`, e o
  sintoma seria mudo: `get_config()` cai no default e o bot roda "normal".
  A regra: **este arquivo é memória, não especificação.** Ele registra o que
  alguém entendeu na época, e envelhece ou nasce errado como qualquer nota. Ao
  agir sobre uma instrução daqui que descreve *comportamento de código*
  (merge, ordem de chamada, formato de arquivo), abrir o código e confirmar —
  são dois minutos, e o custo de não fazer é uma mudança que parece aplicada e
  não está. Corolário: quando a instrução estiver errada, **corrigir a
  instrução no mesmo passo**, senão o próximo a ler cai igual. O mesmo vale
  para o oitavo padrão desta lista, que existe porque uma lição verdadeira
  estava escrita num arquivo que ninguém lê.
- ⚠️ **Décimo sétimo padrão, achado em 2026-08-22: valor lido do servidor que
  já vem transformado — e o mundo onde você mediu não consegue te contar.** As
  velocidades de `interface.php?func=get_unit_info` **já são** os min/campo
  efetivos, com `speed` e `unit_speed` do mundo embutidos. Eu ia dividir por
  eles de novo. No br143 o erro seria **invisível para sempre**, porque lá os
  dois fatores valem 1 e as duas hipóteses dão o mesmo número; num mundo de
  velocidade 4 o tempo de viagem sairia 4× menor. O que separou as hipóteses
  foi comparar mundos: o br139 (`speed=1.4`, `unit_speed=0.75`) publica
  `17,142857` para o lanceiro, que é exatamente `18/(1,4×0,75)`.
  A quinta metade do padrão acima manda ir ler o servidor; esta acrescenta que
  **ler o valor não é o mesmo que saber o que ele significa**. Ao consumir um
  número de API, perguntar "isto já inclui o fator X?" — e reparar que a
  pergunta é *inrespondível* se o seu ambiente tem X=1. Regra prática: quando
  um valor deveria escalar com um parâmetro do mundo, buscar uma instância onde
  esse parâmetro **não** seja neutro. São dois `Invoke-WebRequest` e a lista de
  mundos sai de `backend/get_servers.php`, como já registrado acima.
- ⚠️ **Décimo oitavo padrão, mesma sessão: reaproveitar um limiar existente
  para uma reação que parece igual e tem física diferente.** O gate de urgência
  da defesa tinha `evacuate_urgency_threshold_sec = 1800`, e o caminho óbvio era
  aplicar os mesmos 30 min ao envio de apoio. Estaria errado, e na direção que
  não aparece em teste: **esconder tropa é instantâneo e quanto mais tarde
  melhor; apoio precisa *chegar* antes do impacto e ele mesmo leva horas
  viajando.** Apoio despachado 30 min antes de um ataque a 3h40 de viagem pousa
  3h depois da batalha — tropa gasta, zero defesa, e nenhum erro no log.
  A regra: dois efeitos disparados pelo **mesmo gatilho** não compartilham
  necessariamente o mesmo prazo. Antes de reusar um limiar, perguntar "o que
  precisa acontecer até o prazo vencer?" — se a resposta envolve algo *chegar*,
  o número tem que incluir o tempo de trânsito e vira função da distância, não
  constante. Corolário achado ao escrever o gate: fechar só o lado "cedo
  demais" teria deixado passar o lado "tarde demais", que já existia e ninguém
  tinha notado, porque apoio que chega atrasado não gera erro nenhum — só some.
  Segundo corolário, sobre o *default*: a janela de envio mede `lead` segundos
  de largura, e se ela for menor que o intervalo entre dois ciclos da mesma
  aldeia, o bot passa por cima e nunca envia. O default (2h) foi escolhido
  contra o intervalo real medido nos logs (1h39 entre dois ciclos da mesma
  aldeia em 2026-08-21), não por parecer razoável. **Limiar de tempo em sistema
  que roda em ciclos precisa ser comparado com o período do ciclo** — senão a
  condição é logicamente correta e nunca observada.
- ⚠️ **Décimo nono padrão, achado em 2026-08-22: percentual escrito em
  português não define uma conta.** O item "Sinal da Aflição" diz *"apoio irá
  percorrer 30% mais rápido"*. Isso comporta duas leituras — `duração / 1,3` e
  `duração × 0,7` — que diferem em **5 minutos numa viagem de uma hora**, e a
  ingênua erra sempre para menos (o bot acharia que ainda dá tempo quando não
  dá). Só a medição decide: o jogo mostrou `0:53:31` para um envio real, e
  `4.174/1,3 = 3.211 s` bate em 1 segundo enquanto `×0,7` dá `0:48:41`.
  A regra: **texto de item/bônus descreve o efeito, não a fórmula.** Ao
  consumir qualquer "+N%" do jogo, montar as duas ou três leituras plausíveis,
  ver de quanto elas divergem, e medir uma instância real antes de escolher —
  a tela de confirmação da praça de reunião entrega o número de graça, sem
  enviar nada. Se as leituras divergem pouco no seu caso de teste, procurar um
  caso onde divirjam muito (mesmo raciocínio do décimo sétimo padrão).
  Corolário sobre asserção inventada, cometido na mesma sessão: escrevi um
  teste afirmando que um regex ingênuo "não casaria" o markup, por causa de um
  `>` dentro do atributo. Rodei: ele casa. O `[^>]*` de fato trunca a tag de
  abertura, mas a forma em bloco `(.*?)</td>` se recupera. **Armadilha
  plausível também precisa ser medida antes de virar comentário no código** —
  eu já tinha escrito a justificativa errada em `extractors.py`, e foi o teste
  que me pegou.
- ⚠️ **Vigésimo padrão, achado em 2026-08-31: efeito colateral destrutivo no
  corpo do módulo, que dispara no `import`.** O topo do `twb.py` abria
  `cache/logs/session_latest.log` com `open(..., "w")` fora de qualquer guard.
  Como `tests/test_village_purge_guard.py` importa `purge_refusal_reason` de
  lá, **rodar a suíte de testes truncava o log da última sessão real do bot** —
  467 KB de histórico de produção. E a análise que eu ia fazer em seguida era
  justamente ler esse log para validar os fixes de bandeira; encontrei nele a
  saída de um teste.
  A regra: **código no corpo do módulo roda em todo `import`, inclusive nos que
  ninguém previu** — teste, ferramenta auxiliar, REPL, webmanager. Se ele
  escreve, apaga, abre conexão ou muda estado global, precisa estar sob
  `if __name__ == "__main__":` ou ser preguiçoso. O sintoma é cruel porque
  truncar arquivo **não levanta nada**: some em silêncio e só aparece quando
  alguém vai ler o que não existe mais. Neste repo isso é mais caro do que
  parece, porque `cache/` é estado real e não regenerável 1:1 — antes de rodar
  qualquer coisa que importe `twb.py`, perguntar o que aquele import faz *antes*
  de definir a primeira função. Corolário de método: é o terceiro padrão virado
  do avesso — lá o perigo era código que nunca roda, aqui é código que roda
  onde não devia. Guarda em `tests/test_session_log_guard.py`.
  **Corolário sobre o que sobrou:** os `cache/logs/twb_*.log` NÃO substituem o
  `session_latest.log`. Eles são do *reporter* (eventos `TWB_*`: farm, build,
  recruit, market) e não carregam uma linha sequer dos loggers — nada de
  `DefenceManager`, `Attacks` ou `Village`. Ao planejar uma análise sobre log,
  conferir qual das duas fontes tem o dado antes de contar com ela.
- ⚠️ **Vigésimo primeiro padrão, achado em 2026-08-31: a guarda que protege um
  recurso escrevia nesse recurso — e virou a coisa contra a qual ela existe.**
  `tests/test_session_log_guard.py` (escrito no dia anterior para impedir que
  um `import` truncasse `session_latest.log`) validava assim: salvava o log em
  memória, **truncava o arquivo real** para gravar uma sentinela, importava
  `twb`, conferia a sentinela e restaurava no `finally`. Com o bot **rodando**,
  isso é destrutivo e racy: o processo do bot tem um handle aberto e continua
  escrevendo no offset dele, então o truncate abre um buraco de bytes NUL no
  meio do log (133 bytes, medidos) e tudo que o bot logou durante a janela do
  teste morre no restore. De quebra o teste **falhou com diagnóstico errado** —
  "o import alterou o arquivo" — quando quem tinha alterado era o bot,
  escrevendo normalmente; a mensagem acusava a regressão que o teste vigia,
  então quase me fez procurar um bug em `twb.py` que não existia.
  A regra: **um teste que verifica uma propriedade sobre um artefato de
  produção não pode obter essa verificação escrevendo no artefato.** Antes de
  fazer setup destrutivo, perguntar "quem mais tem esse arquivo aberto agora?"
  — neste repo a resposta é quase sempre "o bot". Quando existir uma
  propriedade **observável** que separe as hipóteses, ela vence o setup: aqui,
  truncar faz o arquivo *encolher* e o bot só faz *crescer*, então comparar
  tamanho + cabeçalho detecta a regressão sem tocar em nada. Corolário que vale
  o passo extra: depois de trocar a guarda por uma observação passiva, **provar
  que ela ainda falha** — reproduzi o `twb.py` bugado num diretório temporário
  e confirmei que os dois sinais disparam. Guarda que não pode falhar é o
  décimo quinto padrão de cabeça para baixo, e passa despercebida para sempre.
- ⚠️ **Vigésimo segundo padrão, achado em 2026-09-14: automatizar o lançamento
  de um programa interativo, tirando dele justamente o canal pelo qual ele
  fala.** O `/bot/start` do painel subia o `twb.py` com `CREATE_NO_WINDOW` e
  stdout num arquivo. Só que o bot **pergunta coisas**: `core/request.py:115`
  faz `input("Enter browser cookie string> ")` quando a sessão expira, e
  `twb.py` pede URL e user-agent no primeiro run. Sem console não há onde
  responder — o processo fica **vivo, com pid válido e parado para sempre**, e
  o painel, que só checava o pid, dizia "rodando". O `bot_output.log` guardava
  a prova desde 30/06/2026: duas tentativas seguidas, ambas terminando na linha
  `Enter browser cookie string> `. Ninguém leu porque o sintoma visível era
  "iniciar pelo painel não é confiável", e não um erro.
  A regra: antes de embrulhar um programa num botão, **procurar todo `input()`,
  `getpass` e prompt no caminho dele** — se existir algum, ou o supervisor sabe
  responder, ou o programa precisa de um console de verdade (aqui,
  `CREATE_NEW_CONSOLE`, que é o que o usuário já usava na mão). Corolário sobre
  o sinal de vida: **pid vivo não é atividade.** Quando o programa mantém um
  log, a idade da última linha é o sinal honesto — com o cuidado de separar
  "parado de propósito" (o bot avisa `Dead for X minutes (next run at: …)`
  antes de dormir `inactive_delay`) de "congelado", senão o indicador vira o
  décimo quinto padrão.
  Segundo corolário, sobre detecção: `is_running()` olhava só o pid escrito
  pelo próprio painel, então um bot iniciado pelo `cmd` — o jeito normal de
  rodar aqui — aparecia como "não detectado", e o botão Iniciar subiria um
  **segundo** bot na mesma conta. É o risco de ban que o P2-32 existia para
  matar, entrando por outra porta: ele cobriu "o webmanager reiniciou" e não
  "o processo não nasceu daqui". Ao guardar unicidade de um recurso externo,
  perguntar quem mais pode criá-lo — se a resposta inclui o usuário, a
  detecção tem que ser por **varredura do estado real do SO** (aqui
  `psutil.process_iter` + cwd do repo, 5 ms), não por registro próprio.
  **Fechamento, 2026-09-20 (`docs/backend.md` §8.9):** os dois `input()` de
  `core/request.py` não existem mais — sessão vencida vem de
  `cache/cookies.txt` (o bot espera o arquivo aparecer e retoma sozinho) e o
  captcha é reconferido em laço. Sobrou **um** prompt no repositório,
  `twb.py::manual_config`, que só roda quando não existe `config.json`. Duas
  coisas que a regra acima não dizia e que apareceram ao consertar: o console
  **não era** o canal certo nem quando existia (o buffer de linha do `cmd.exe`
  é menor que um cookie do jogo, então colar ali trunca em silêncio); e a
  varredura por `input()` precisa ir **além do prompt**, porque a mesma tela
  bloqueada chegava pelo `post_url` sem prompt nenhum e era tratada como ação
  aceita.
- ⚠️ **Vigésimo terceiro padrão, cometido em 2026-09-14, e com dano real: tratar
  "está no repositório" como "está versionado".** Ao consolidar a documentação em
  dois arquivos, apaguei doze documentos confiando em que o git guardaria o
  original — cheguei a escrever `git show 85fbbcb:docs/<arquivo>` dentro dos
  documentos novos como se fosse a rede de proteção. Sete estavam rastreados e de
  fato sobreviveram. **Os outros nove nunca tinham sido commitados** (os quatro
  relatórios de `docs/benchmarks/`, os cinco de `docs/interface/` e o
  `roteiro_benchmark_bots.md`), e `rm` no Windows não passa pela lixeira: ~280 KB
  de pesquisa que o usuário tinha acabado de destacar como importante sumiram de
  vez. A informação que me teria salvado estava no `git status` que eu **li no
  começo da sessão** — `M` e `??` estão lá lado a lado, e eu processei a lista
  inteira como "arquivos do projeto".
  A regra: **antes de apagar, `git ls-files --error-unmatch <arquivo>` ou
  `git status --short` no alvo específico.** `??` significa que não existe cópia
  em lugar nenhum — e aí o passo obrigatório é commitar (ou copiar para fora)
  *antes* de remover, não depois. Corolário sobre linguagem, que é a parte que
  mais incomoda: escrever "nada foi perdido, foi comprimido" é uma afirmação
  sobre um fato que eu não tinha verificado, e ela soa mais forte justamente
  porque cita um mecanismo concreto (o hash do commit). Promessa de
  recuperabilidade só vale depois de tentar recuperar — um `git show` de teste
  custava cinco segundos e teria falhado na hora.
- ⚠️ **Vigésimo quarto padrão, achado em 2026-09-19: medir a hipótese sobre um
  conjunto de dados que o código não consome.** O diagnóstico de `P-CONQ-RAIO`
  (§8.6) dizia que `conquest.max_radius` escondia 11 das 46 bárbaras do K25, e
  provava isso com uma tabela calculada sobre `cache/villages` — o snapshot
  compartilhado, com 851 aldeias. Só que `find_target()` **não varre esse
  snapshot**: ela itera sobre `self.map.villages`, o prefetch de mapa da própria
  aldeia, que com `map_sector_radius: 0` tinha 23 das 39 bárbaras. Ou seja,
  havia **dois funis em série** e o diagnóstico mediu só o de baixo. Subir o
  raio não alcançaria 16 dos alvos, porque eles nunca chegavam a ser filtrados:
  não estavam na lista. A medição não estava errada — estava descrevendo um
  programa diferente do que roda.
  A regra: ao medir o efeito de um filtro, **medir a partir da mesma fonte que o
  código lê**, e perguntar quantas peneiras existem antes dela. O sinal de
  alerta é usar um cache "equivalente" porque ele é mais fácil de abrir offline
  — foi exatamente o atalho aqui. Custou um `Map.get_map()` com o `WebWrapper`
  do bot para descobrir (sétimo padrão de novo: sondar com o cliente certo).
  Corolário barato: quando duas partes do sistema respondem a mesma pergunta,
  compará-las é diagnóstico de graça. O painel já contava pelo snapshot
  (`ConquestReader.area_of_interest`) e o bot pelo scan local; os dois números
  divergiam havia semanas e ninguém tinha posto um ao lado do outro.
- ⚠️ **Vigésimo quinto padrão, achado em 2026-09-20: fazer `deepcopy` de um
  objeto novo que aponta para um serviço vivo compartilhado.** O startup fazia
  `copy.deepcopy(Village(wrapper=self.wrapper, ...))` para cada aldeia. A
  `Village` já era nova; o que a cópia profunda acrescentava era clonar o grafo
  do `WebWrapper`: `requests.Session`, cookies, pool e `last_response`. Isso
  multiplicava memória por aldeia e, pior, criava snapshots de sessão que não
  recebiam uma rotação de cookie/CSRF feita por outra aldeia. O fork
  `TWBOT_LazyTurtle` encontrou o mesmo defeito e mediu aproximadamente 767 MB
  contra 85 MB em 41 aldeias depois de removê-lo. Aqui `TWB._new_village()`
  agora cria objetos de aldeia distintos apontando para **a mesma identidade**
  de wrapper, com regressão em `tests/test_gather_controls.py`. A regra: só
  copiar o estado que precisa ser independente; sessão HTTP, lock, conexão,
  logger e outros recursos vivos devem ser injetados e compartilhados
  explicitamente. Testar identidade (`is`), não apenas igualdade.
- ⚠️ **Vigésimo sexto padrão, achado em 2026-09-20: ler uma lista do jogo sem
  perguntar se ela está paginada.** A tela oficial de reservas da tribo
  (`screen=ally&mode=reservations`) parecia responder tudo num GET. Respondia
  **10 de 489** — havia 49 páginas, e o bloco de navegação estava a 40 KB de
  distância do trecho que eu tinha aberto para escrever o regex da linha. Um
  parser escrito ali teria concluído que 479 alvos estavam livres, e a feature
  inteira (não conquistar aldeia reservada por companheiro de tribo) falharia
  em **98% do quadro sem emitir um único erro** — lista curta é indistinguível
  de lista completa. A saída foi `&page=all`, que traz tudo numa requisição.
  A regra: ao capturar uma tela que é uma **lista**, a primeira pergunta não é
  "qual o regex da linha", é **"quantas linhas existem no total, e este é o
  total?"**. Contar as linhas casadas e procurar navegação (`page=`, `[2]`, um
  `<select>` de páginas) custa um grep na captura que já está em disco.
  Corolário específico deste jogo: o tamanho de página costuma ser
  configurável, mas por POST e às vezes numa configuração **compartilhada com a
  tribo** — mudá-la para conseguir uma leitura mexe na interface de outras
  pessoas (21º padrão); preferir sempre o parâmetro de querystring. Corolário
  geral, que é o 15º padrão de cabeça para baixo: lá o detector disparava
  sempre, aqui ele **nunca** dispararia — e as duas falhas se parecem de fora,
  porque em nenhum dos dois casos alguém vai investigar.
- ⚠️ **Vigésimo sétimo padrão, achado em 2026-09-20: "fonte mais velha" é uma
  propriedade do CAMPO, não da fonte.** O plano do `P-CONQ-MAPA` (§8.6) mandava
  entrar com `map/village.txt` como "piso de descoberta, nunca autoridade sobre
  dono/pontos", porque ele seria "o mais completo e o mais velho ao mesmo
  tempo". Soa óbvio e estava errado na metade que importa. Medindo **antes** de
  implementar: das 851 entradas de `cache/villages`, **38 diziam bárbara para
  aldeias que o village.txt já dava como de jogador, e ZERO no sentido
  inverso** — porque bárbara virar aldeia de jogador é o que conquista faz, e o
  snapshot local (20,6 dias de idade) não fica sabendo. Ou seja, para *posse* o
  arquivo "velho" é a fonte **nova**, e obedecer a precedência escrita teria
  deixado 38 alvos-fantasma elegíveis — nobre de verdade contra aldeia de
  gente, que é o incidente da §8.7 entrando por outra porta.
  A regra: quando duas fontes se sobrepõem, "qual é mais fresca" se pergunta
  **por campo**, e a resposta costuma estar no próprio dado — aqui a assimetria
  38×0 era a impressão digital de qual lado apodrece. Cruzar as duas fontes
  custa minutos e transforma a ordem de precedência de escolha estética em fato
  medido. Sinal de alerta: escrever "X é mais velho que Y" sem dizer *sobre o
  quê*. É o 16º padrão outra vez (a instrução vinha de um documento, e
  documento é memória, não especificação), com o agravante de que aqui o
  documento era o **plano da própria tarefa**.
- ~~`core/twstats.py::buildings_to_farm_pop()`~~ — ✅ **removida em 2026-08-31.**
  Era pior que "quebrada": zero chamadores, indexava um `int` como dict, **e o
  nome/docstring prometiam algo que a fonte de dados não pode dar.** A tabela do
  twstats é `prédio → nível → população consumida por aquele prédio` (`main`
  nível 2 = 1 pop), e `max_levels` **não inclui `farm`** — não há como derivar
  capacidade de fazenda dali. No formato do quarto padrão: *`buildings_to_farm_pop()`
  não existe e não funciona — mas `game_state["village"]["pop"]`/`pop_max`
  funciona, vem ao vivo do jogo todo ciclo, e é o que `BuildingManager`
  (`buildingmanager.py:251`) e `ResourceManager` (`resources.py:183`) já usam.*
  Ficou documentada no docstring da classe uma armadilha de procedência (o
  segundo padrão com outra máscara): a chave de nível é `int` quando vem da rede
  e `str` depois do round-trip pelo cache JSON, então `output["main"][2]`
  funciona no ciclo do sync e levanta `KeyError` em todos os seguintes. Nada
  mais lê `TwStats.output` hoje.
- `game/attack.py` — `AttackManager` e `ConquestManager` duplicam bastante lógica de
  montagem/envio de ataque (`attack_form`, `map_pos`, `post_url` de confirmação).
  Candidato a extrair um helper comum.
- Vários módulos (`Hunter`, `ZoneManager`, `ConquestManager`, `ReportReader` do
  webmanager) leem/escrevem cache via varredura de diretório (`os.listdir` +
  `json.load` por arquivo) a cada ciclo. Pode virar gargalo de I/O conforme o
  número de aldeias/cache cresce — considerar indexação ou cache em memória por
  ciclo. **Padrão a copiar:** `PvpConquestManager._scout_report_index()` (P2-35,
  2026-08-11) fez isso para `cache/reports` invalidando o índice pelo
  `frozenset` de nomes de arquivo, em vez de por tempo. Isso só é exato porque
  `ReportManager.read()` pula ids já cacheados, então um arquivo de relatório
  nunca é reescrito — antes de reusar a técnica em outro diretório, conferir
  que vale a mesma premissa (arquivo só nasce e morre, nunca muda de conteúdo
  sob o mesmo nome); se não valer, o índice serviria dado velho.
  **Segundo caso, 2026-08-31: `ReportReader` (webmanager) ✅ indexado.** A
  varredura custava **8,3 s por request** com 1.056 relatórios (medido a frio;
  a página inteira dependia disso), contra ~3 ms com o índice. Confirmada a
  premissa acima relendo `reports.py:174` — `read()` pula id já cacheado, então
  vale. Mesmo assim a chave é `(frozenset de nomes, maior mtime)` e não só o
  conjunto de nomes: o mtime sai de graça do `os.scandir` e dispensa a premissa
  continuar valendo. **E a premissa NÃO vale para `cache/villages`**, usado no
  mesmo método para resolver nome de aldeia — `Map.build_cache_entry()`
  reescreve esses arquivos in-place quando dono/pontos mudam (`map.py:285`),
  então ali o mtime é obrigatório, não opcional. Dois diretórios, duas
  respostas, no mesmo pedaço de código.
- Sistema de bandeiras (`DefenceManager`): dois bugs corrigidos no código (troca
  constante de bandeira, loop de upgrade), **ainda aguardando validação em
  campo** — ver `docs/backend.md` §4.6 e §6.3 para a política e o estado
  atual. Em 2026-08-31 a escolha de bandeira deixou de ser um id fixo e passou
  a ser uma **preferência ordenada por aldeia** (academia → cunhagem; senão
  produção; preenchimento recrutamento › população › saque; ataque e sorte
  nunca automáticos; defesa sobrepõe tudo). Isso torna o Bug 1 finalmente
  testável: o caminho de `flag_set` voltou a ser exercitado, e o esperado no
  primeiro ciclo são **exatamente 3 trocas** (BBM 003, 016, 017) e silêncio
  depois.
  **Validação iniciada em 2026-08-31 na sessão que começou às 10:17, e está
  1 de 18.** A nota anterior aqui dizia que a validação por log era impossível
  porque o `session_latest.log` tinha sido destruído; isso valia para a sessão
  antiga e deixou de valer assim que o bot subiu de novo — o arquivo é
  reescrito a cada run. Resultado até agora: a **BBM 001** logou
  `Current village flag: -22% nos custos de moedas` (tipo 7, nível 7) e o bot
  **não trocou**, que é exatamente o previsto para as três aldeias de cunhagem
  manuais com as quais a política concorda. As outras 17 não rodaram: o ciclo
  da primeira aldeia levou mais de 30 min só de farm, então a conta fecha em
  horas, não em minutos. **O número que importa continua não medido** — as 3
  trocas e o silêncio depois. Ao retomar, `grep -a` (o log tem bytes NUL, ver
  vigésimo primeiro padrão) por `Current village flag` e `Setting flag`.
  **Atualização 2026-09-20 (`docs/backend.md` §8.11):** a pergunta que estava
  aberta — "a política conta a **oferta**?" — foi respondida com medição:
  **não contava**, e quem segurava o Bug 1 era a guarda de rebaixamento, não o
  inventário. Bandeira equipada **sai** do `setFlagCounts` (tipos 1/2/7 em zero
  com 28 das 30 aldeias usando um deles), logo `flag_set` **move** a bandeira
  de outra aldeia. A causa real era decidir sobre leitura velha:
  `manage_flags()` só lê a cada 3–8 runs e o `DefenceManager` sobrevive entre
  ciclos, então `flag_logic()` decidia com foto de vários ciclos atrás — o
  `cache/managed` da BBM 029 acreditava num tipo 6 nível 7 que já estava na
  BBM 030. Corrigido com gate de frescor em `flag_logic()` e
  `manage_flags(force=True)` nos dois caminhos que não podem esperar. A
  validação das 3 trocas **continua aberta**, e agora `flags_read_this_cycle`
  no `cache/managed` separa "não trocou porque estava certo" de "não trocou
  porque não leu".
- `game/defence_manager.py::DefenceManager.supported` (Bug 3 de
  `docs/backend.md`) — ✅ **corrigido no Lote 1**, movido para `__init__`.
  A condição invertida do laço em `DefenceManager.update()`, que impedia
  `support_other()` de ser chamado, foi corrigida no Lote 3 (P1-6) — junto com
  a leitura de `support_others_max_villages` do config. O suporte deixou de ser
  código morto, mas **nenhum envio real jamais aconteceu** e o payload
  `"support": "Ondersteunen"` nunca foi validado em pt-BR.
  ⚠️ **Redação corrigida em 2026-09-21.** A anterior dizia que `support_others`
  "segue `false` em campo" e mandava "ligar em uma aldeia só, observando".
  Medido no `config.json`: está **`true` em 22 das 30 aldeias** (só o
  `village_template` é `false`). A chave **não** é o bloqueio — o bloqueio é que
  `support_other()` só roda quando outra aldeia **pede**, e pedir exige ataque
  real chegando; o `session_latest.log` não tem uma linha
  `Support X -> Y liberado` sequer. Ligar mais aldeias não exercita nada.
  Para exercitar de propósito: ataque mínimo de uma aldeia própria **distante**
  contra outra com `request_support_on_attack: true` — distante porque o gate
  exige o apoio **chegar** antes do impacto e `support_lead_time_sec` é 7200,
  então um ataque de 10 min é recusado por "tarde demais" e não prova nada
  (18º padrão).
- **Feature 9 (resource sharing)** — **reformulada em 2026-08-11**
  (ver `docs/backend.md` §3.1).
  A versão anterior tinha uma regra só — doadora era quem passasse de
  `threshold_pct` da **própria** capacidade — e contra os dados reais da conta
  ela não movia nada: as duas aldeias de armazém grande precisariam de 8× mais
  recurso do que tinham para se qualificar como doadoras, e a única receptora
  precisava de um recurso que a única outra doadora não tinha sobrando.
  Agora são duas regras (transbordo, por percentual da própria capacidade;
  necessidade, por sobra absoluta acima de `need_donor_floor`), necessidade
  primeiro e o transbordo restante despejado na aldeia com mais **espaço
  livre**. **Validada em campo no mesmo dia**, com quatro transferências reais
  concluídas — as primeiras da história da feature. O caminho de envio inteiro
  estava errado e nunca tinha sido exercitado: `mode=send_res` não existe (o
  jogo respondia "Modo inválido"), o destino é por coordenada em campos `x`/`y`
  e não por `target_village`, e o envio tem uma **segunda etapa** de
  confirmação sem a qual nada sai.
  ✅ **Ligada e movendo recurso** — `resource_sharing.enabled` é `true` no
  `config.json` e o log de 2026-09-20 tem envios reais das duas regras
  (`{'stone': 1240} de 37318 → 49709 (regra: need)` e `{'stone': 8000} ...
  (regra: overflow)`). A redação anterior desta entrada dizia "desligada no
  `config.json` local desde 2026-08-08" e estava velha — 16º padrão: nota é
  memória, o `config.json` é o fato.
  ⚠️ **Não existe gate por aldeia** — `resource_sharing.enabled` é global e
  vale para todas as aldeias gerenciadas de uma vez. Notas antigas que falavam
  em "ligar em uma aldeia só" descreviam algo que o código nunca ofereceu.
  ⚠️ **Quem poupa para nobre precisa declarar `village.keep_resources`.** A
  reserva automática (`required_resources`) registra o que *falta* e some
  quando a aldeia já juntou o suficiente — ou seja, some exatamente quando
  proteger importa.

## Documentação

Desde 2026-09-14 existem **dois** documentos, e só dois:

- **[`docs/backend.md`](docs/backend.md)** — arquitetura, estado das Features
  4 a 34, mecânicas do mundo medidas no servidor (moral, bônus noturno, torre de
  vigia, bolsa premium, bandeiras), o índice da auditoria de código, o que está
  aberto hoje, e o roteiro de evolução derivado do benchmark de Nexus, PS
  Evolution e ACID (backlog `FND`/`TIM`/`DEF`/`ECO`…).
- **[`docs/frontend.md`](docs/frontend.md)** — webmanager: estado da migração
  visual, auditoria da interface, arquitetura de informação, tokens, catálogo de
  componentes e os contratos que o backend ainda não publica.

Os doze documentos anteriores (`backlog.md`, `features_log.md`,
`auditoria_codigo_2026-08-08.md`, `bugs_flags.md`, `watchtower.md`,
`troca_premium.md`, `game_comparison.md`, `roteiro_benchmark_bots.md`, os quatro
relatórios de `benchmarks/` e os cinco de `interface/`) foram consolidados nesses
dois. O conteúdo integral continua em `git show 85fbbcb:docs/<arquivo>` — se
precisar do detalhe de uma sessão específica, é lá.

⚠️ **Ao registrar trabalho novo, escrever num dos dois** — não criar documento
por feature. Foi essa proliferação que fez uma lição verdadeira ficar enterrada
num arquivo que ninguém lia (ver o oitavo padrão acima).

**Feature 34 (Troca Premium)** está parada de propósito até abrir mundo novo: no
K35 a bolsa está cheia e a venda está bloqueada — `docs/backend.md` §4.5.
