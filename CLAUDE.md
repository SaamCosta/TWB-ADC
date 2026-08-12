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

- Sem test suite automatizado no projeto. Revisar diffs manualmente com cuidado —
  não assumir que dá para rodar `pytest` e confiar cegamente no resultado.
  Ao introduzir lógica pura e isolável (ex: `Simulator`, `Extractor`, `ZoneManager`),
  considerar escrever testes unitários pontuais.
- **Nunca commitar `config.json`** (contém credenciais/sessão) — só `config.example.json`.
- **Sempre bumpar a versão do build** (`config.example.json` e `config.json`,
  campo `build.version`) ao adicionar novo bloco de configuração estrutural,
  para evitar merge automático indesejado pelo bot (`twb.py` faz merge
  baseado em `build.version` divergente).
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

## Features já implementadas (referência rápida)

Features 4 a 13 implementadas e (majoritariamente) validadas em campo — ver
histórico completo em `docs/features_log.md` se precisar do detalhe de cada uma
(arquivos tocados, config associada, notas de validação).
