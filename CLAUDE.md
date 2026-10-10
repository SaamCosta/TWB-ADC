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
  `BuildingManager` → `TroopManager` → `SnobManager` → `AttackManager` →
  `DefenceManager` → `ResourceManager` / `ResourceSharingManager`. Também guarda
  cache de estado em `cache/managed/*.json`.
  ⚠️ **As duas conquistas NÃO decidem de dentro do laço de aldeias.** Desde
  2026-09-21 (PvP, `docs/backend.md` §8.14) e 2026-09-22 (bárbara, §8.15) elas
  rodam uma vez, no **início** do ciclo — bloco do `pvp_manager` e
  `TWB.run_barbarian_conquest()` em `twb.py` —, precedidas de um prime
  somente-leitura das aldeias de origem (`Village.prime_for_conquest()`).
  Motivo: `units`/`area` só existiam depois que a aldeia rodava, e um ciclo
  completo mede ~4h com 30 aldeias. `Village.run_pvp_conquest()` ainda roda
  por aldeia (prioridade sobre o farm daquela aldeia); `Village.run_conquest()`
  não — ele é chamado só para a aldeia `reserved_by` da conquista ativa, que
  só **acompanha**: o nobre extra sai de qualquer aldeia gerenciada, a que
  pousa primeiro (§8.41), sob o mesmo portão do trem
  (`conquest_origin_block_reason`).
- **Managers de jogo (`game/`) e infraestrutura (`core/`)**: um módulo por
  sistema, cada um abrindo com docstring (`ls game/ core/`). O que o código
  não conta:
  - `hunter.py` — além de disparar, o `Hunter.gate()` roda **antes de cada
    fase** e adia (ou segura) o que não termina antes da próxima saída, com a
    duração prevista por `core/phase_forecast.py` a partir de `cache/cycles`.
    Fase nova em `Village.run()`/`twb.py` precisa de `_gate(...)` antes dela,
    senão vira o furo de 2026-10-08 (§8.58). `Hunter: FURO` no log = alguma
    tarefa escapou do gate.
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
  Cobertura: cada `tests/test_*.py` diz na docstring o que cobre e de qual
  seção da `docs/backend.md` vem (`ls tests/` lista tudo).
  ⚠️ **O repositório é público**: fixture
  de fórum de tribo, lista de amigos ou token de sessão (`h`, `ch`) entra
  anonimizada/redigida. ⚠️ `Notification.send`
  só age depois de `Notification.arm()`, que só `twb.main()` chama: a suíte lê
  o `config.json` real, e sem essa trava rodar os testes com o Telegram ligado
  mandaria mensagem ao canal. Teste que precisa do `send()` de verdade arma
  uma instância própria, nunca o singleton.
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
- **Aldeia própria nunca aparece só pelo id** (pedido do usuário, 2026-10-08).
  Em log e aviso de Telegram, `village_label(vid)` de `core/village_label.py`
  → `BBM 022 (40618)`; no painel, o filtro Jinja `{{ vid | vlabel }}`. Pode
  embrulhar qualquer id de aldeia, inclusive alvo: aldeia alheia não tem
  arquivo em `cache/managed` e sai só com o id. Teste em
  `tests/test_village_label.py`.
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

⚠️ **Segunda auditoria, de 2026-09-26: 21 achados (`A26-01` a `A26-21`), em
`docs/backend.md` §8.32.** O Lote A (A26-01, A26-02, A26-10) foi fechado em
2026-09-27 (§8.33), depois de uma queda de rede derrubar o bot e custar o 4º
nobre de um trem. O Lote B (A26-03 autoconquista, A26-04 trem
preso, A26-14 sonda dobrada) foi fechado no mesmo dia (§8.35): **nenhum P1
aberto**. O Lote C (A26-05 fila do Hunter, A26-06 `trade_max_per_hour`, A26-07
proporção da oferta, A26-08 `supported`, A26-12 trava do `schedules.json`) também
foi fechado no mesmo dia (§8.36). Sobram A26-09 e A26-11, que pedem sondagem
do servidor antes, e os P3.
⚠️ **`cache/hunter/schedules.json` tem vários escritores** (Hunter, planejador,
painel). Quem grava nele passa por `core.file_lock` e **relê antes de gravar**.
Nunca gravar a cópia lida antes de uma espera: é esse o bug do A26-12, e é o
mesmo da §8.29 em outro arquivo.

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

- ⚠️ **Os 28 padrões de erro deste projeto.** Abaixo, a regra curta de cada
  um. A narrativa completa (incidente, números, por quê) está na skill
  **`twb-padroes`** (`.claude/skills/twb-padroes/SKILL.md`): carregue-a ao
  investigar bug, sondar o servidor, medir dados, mexer em efeito diferido ou
  apagar algo — é ela que mostra como a regra se aplica ao caso que não está
  escrito.
  1. **Atributo de classe mutável:** `list`/`dict` no corpo da classe é
     compartilhado por todas as instâncias (= entre aldeias). Mutável vai em
     `__init__`.
  2. **`None` de rede/parse:** `get_url`/`get_action`/`get_api_action`
     devolvem `None` em qualquer exceção, e vários `Extractor.*` devolvem
     `None` quando o regex não casa (login, captcha, markup novo). Guardar
     antes de `.text`/`in`/`[]`; num caminho de erro, conferir que o logger já
     existe.
  3. **Função órfã:** ao corrigir o corpo de uma função, `grep` os chamadores.
     Ao alargar o que ela pode devolver, reler cada consumidor ("e se vier
     este valor agora?").
  4. **Remover config "morta":** `grep` diz se é seguro, não o que o usuário
     perde. Relatar sempre como *"`X` não existe e não funciona — mas `Y`
     funciona e serve para isso"*.
  5. **Número do servidor:** dizer de qual tag/campo veio, não só que veio do
     servidor. `get_config` e `/page/settings` não expõem os mesmos campos;
     enum de jogo se mapeia contra o servidor, nunca contra a wiki. "Não
     achei" só vale dizendo onde procurou — e se você mesmo nomeou a fonte
     plausível, abra-a.
  6. **Efeito diferido** (nobre voa horas): separar "quando mandei" de
     "quando acontece" e reconferir a premissa na hora de agir. Travar por
     tempo de chegada, não por `status`. `attack_duration()` devolve **0** na
     falha. O bloqueio nasce com a intenção (lista de operações agendadas),
     não com o efeito.
  7. **Sondar com o cliente do bot:** a resposta depende dos cabeçalhos
     (`TribalWars-Ajax: 1` embrulha em `response`/`game_data`). Sondar pelo
     próprio método do `WebWrapper`, e fazer smoke contra o servidor depois
     dos testes.
  8. **Jinja2:** chave de dict com nome de método (`items`, `keys`, `get`,
     `pop`, `values`, `update`, `copy`) perde para o método — renomear a
     chave. Lição de classe de erro mora neste arquivo, não em doc de feature.
  9. **Log é ação do bot, não estado do mundo:** o usuário joga na mesma
     conta. Dizer "o bot não mexeu", nunca "não mudou".
  10. **Limite lido de dado é fato sobre o arquivo:** antes de desenhar em
      volta de um teto, perguntar o que o pôs lá. Sem "porque", é dívida.
  11. **Média de conjunto heterogêneo:** perguntar se o conjunto é um
      conjunto (`groupby`). Valor no teto de um instrumento nosso é
      censurado, não observação.
  12. **Mais um de algo** (template, parser, manager): ler os irmãos antes.
      Ao corrigir, varrer a classe inteira.
  13. **Experimento que só pode confirmar não é evidência:** instrumentar a
      falha real e esperar. Dizer de qual ocorrência a mensagem foi lida.
  14. **Constante relativa a estado que cresce** (pontos, níveis) expira
      sozinha: vira função em runtime ou degraus.
  15. **Detector que dispara sempre não detecta:** ancorar a guarda no mesmo
      padrão do parser. Silêncio de um filtro não prova que está tudo bem.
  16. **Este arquivo é memória, não especificação:** instrução que descreve
      comportamento de código se confirma no código; se estiver errada,
      corrigir a instrução no mesmo passo.
  17. **Valor de API pode vir transformado** (velocidades de `get_unit_info`
      já são efetivas): conferir num mundo onde o fator não é neutro.
  18. **Mesmo gatilho, prazo diferente:** esconder é instantâneo, apoio
      precisa *chegar*. Limiar de tempo se compara ao período do ciclo.
  19. **"+N%" do jogo não define a conta:** montar as leituras possíveis e
      medir uma instância real. Armadilha plausível também se mede.
  20. **Corpo de módulo roda em todo `import`:** efeito destrutivo só sob
      `__main__` ou preguiçoso. `twb_*.log` não substitui `session_latest.log`.
  21. **Teste não escreve no artefato de produção que verifica** (o bot o tem
      aberto): preferir observação passiva e provar que a guarda ainda falha.
  22. **Programa interativo num botão:** procurar `input()`/prompts antes.
      Pid vivo não é atividade; unicidade de recurso externo se detecta
      varrendo o SO, não por registro próprio.
  23. **`??` no `git status` = sem cópia em lugar nenhum:**
      `git ls-files --error-unmatch` antes de apagar. Recuperabilidade só se
      promete depois de tentar recuperar.
  24. **Medir na mesma fonte que o código lê**, e contar quantas peneiras há
      antes do filtro medido.
  25. **Nada de `deepcopy` em objeto que aponta para serviço vivo** (sessão,
      lock, logger): injetar e compartilhar; testar identidade (`is`).
  26. **Lista do jogo:** a primeira pergunta é "quantas linhas existem no
      total, e este é o total?" (`page=all`/`page=-1`). Não mudar config
      compartilhada da tribo só para conseguir ler.
  27. **"Fonte mais velha" é propriedade do campo:** decidir a precedência
      por campo, medindo a assimetria entre as fontes.
  28. **Todo `time.sleep` do laço principal consulta os prazos do Hunter**, com
      margem para o custo de voltar; um retorno "inofensivo" pode estar sendo
      contado por quem chama.
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
  código morto, mas **nenhum envio real jamais aconteceu**.
  ⚠️ **2026-09-29 (§8.39): o `support()` montava ATAQUE.** Mandava os dois
  botões da praça (`attack` e `support`) no POST, e o jogo trata o par como
  ataque. Sondado: só `support` → "Confirmar apoio"; os dois → a mesma recusa
  de ataque que só `attack`. Corrigido com duas travas (POST só com
  `support`, e `Extractor.command_confirm_kind` exigindo a confirmação de
  apoio antes de criar o comando). **Validado em campo no mesmo dia**: o
  primeiro apoio real (BBM 001 → La Rochelle, 80 exploradores) apareceu na
  lista de comandos do jogo como "Apoio para…". ⚠️ Todas as aldeias coletam:
  apoio com lança/espada/pesada usa a fatia `gather_share` do total e espera
  a tropa voltar da coleta (§8.39).
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
