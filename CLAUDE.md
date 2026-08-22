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
- **Cache (`cache/`)** — todo estado runtime persiste em JSON por diretório
  (`cache/attacks`, `cache/conquest`, `cache/managed`, `cache/zones.json`,
  `cache/hunter/schedules.json`, `cache/pvp_conquest`, etc). `.gitignore` cobre
  `cache/**`, `config.json`, `config.bak`.

## Convenções

- **Existe `tests/`** desde 2026-08-13 (antes não existia; se alguma nota falar
  em "sem test suite", está velha). São testes pontuais de lógica pura, sem
  rede e sem estado de jogo. Rodar:
  `foreach ($t in (Get-ChildItem tests/test_*.py)) { python $t.FullName }`
  — cada arquivo roda sozinho, sem depender de `pytest` instalado.
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
  que `get_unit_info` já publica min/campo **efetivo**).
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

**Auditoria completa em `docs/auditoria_codigo_2026-08-08.md`** — leitura integral
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
  completas no Lote 7 de `docs/auditoria_codigo_2026-08-08.md`.
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
  `docs/backlog.md`, que não entra em contexto. Repeti o mesmo erro em
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
- `core/twstats.py::buildings_to_farm_pop()` — `self.max_levels[b][buildings[str(b)]]`
  tenta indexar um `int` como dict; parece código não exercitado/quebrado.
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
- Sistema de bandeiras (`DefenceManager`): dois bugs corrigidos no código (troca
  constante de bandeira, loop de upgrade), aguardando validação em campo — ver
  `docs/bugs_flags.md` para o diagnóstico original e o estado atual.
- `game/defence_manager.py::DefenceManager.supported` (Bug 3 de
  `docs/bugs_flags.md`) — ✅ **corrigido no Lote 1**, movido para `__init__`.
  A condição invertida do laço em `DefenceManager.update()`, que impedia
  `support_other()` de ser chamado, foi corrigida no Lote 3 (P1-6) — junto com
  a leitura de `support_others_max_villages` do config. O suporte deixou de ser
  código morto, mas **`support_others` segue `false` em campo**: nenhum envio
  real jamais aconteceu e o payload `"support": "Ondersteunen"` nunca foi
  validado em pt-BR. Ligar em uma aldeia só, observando.
- **Feature 9 (resource sharing) desligada no `config.json` local** desde
  2026-08-08, e **reformulada em 2026-08-11** (ver `docs/features_log.md`).
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
  ⚠️ **Não existe gate por aldeia** — `resource_sharing.enabled` é global e
  vale para todas as aldeias gerenciadas de uma vez. Notas antigas que falavam
  em "ligar em uma aldeia só" descreviam algo que o código nunca ofereceu.
  ⚠️ **Quem poupa para nobre precisa declarar `village.keep_resources`.** A
  reserva automática (`required_resources`) registra o que *falta* e some
  quando a aldeia já juntou o suficiente — ou seja, some exatamente quando
  proteger importa.

## Backlog de features pendentes

Ver `docs/backlog.md` para a lista priorizada (Features 14–22 e seguintes).
Features 18–22 vieram de uma comparação entre as mecânicas reais do jogo e o
que o bot cobre hoje — ver `docs/game_comparison.md` para o raciocínio
completo por trás delas.

**Feature 34 (Troca Premium) tem documento próprio: `docs/troca_premium.md`** —
mecânica medida no servidor, economia da bolsa por continente, a estratégia de
fazer PP no início de mundo e o gap do `do_premium_stuff()`. Parada de propósito
até abrir mundo novo (no K35 a bolsa está cheia e a venda está bloqueada).

## Features já implementadas (referência rápida)

Features 4 a 13 implementadas e (majoritariamente) validadas em campo — ver
histórico completo em `docs/features_log.md` se precisar do detalhe de cada uma
(arquivos tocados, config associada, notas de validação).
