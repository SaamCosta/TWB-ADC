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
- Mudanças em `AttackManager` / `ConquestManager` / `DefenceManager` afetam tropas
  reais em jogo — revisar com cautela extra antes de considerar "pronto".
- Preferir tarefas pequenas e escopadas (um manager/feature por vez) em vez de
  mudanças amplas simultâneas.

## Bugs conhecidos / débito técnico

**Auditoria completa em `docs/auditoria_codigo_2026-08-08.md`** — leitura integral
dos 34 `.py`, com 5 achados P0, 14 P1, 20 P2 e dívida técnica, cada um com nível
de confiança e correção sugerida. O Lote 1 (estado mutável compartilhado entre
instâncias) já foi corrigido; o restante segue aberto e está priorizado no fim
do documento.

- ⚠️ **Padrão de bug recorrente neste projeto: atributo de classe mutável.**
  Quase toda classe aqui declara seus campos no corpo da classe, não em
  `__init__`. Para `int`/`str`/`bool`/`None` é inofensivo (a atribuição cria
  um atributo de instância), mas para `list`/`dict` mutados in-place
  (`.append()`, `[k] = v`) o objeto é **compartilhado por todas as instâncias**.
  Como existe uma instância de quase todo manager por aldeia, isso vira
  vazamento de estado entre aldeias. Corrigidos no Lote 1: `TWB.villages`,
  `ResourceManager.actual`/`requested`, `Map.villages`/`map_pos`/`map_data`,
  `DefenceManager.supported`/`attacks`/`flags`/`current_flag`. **Ainda abertos:**
  `BuildingManager.waits` (P2-23) e `AttackManager.ignored` (P3). Ao criar
  classe nova ou campo novo, declarar mutáveis em `__init__`.
- `core/twstats.py::buildings_to_farm_pop()` — `self.max_levels[b][buildings[str(b)]]`
  tenta indexar um `int` como dict; parece código não exercitado/quebrado.
- `game/attack.py` — `AttackManager` e `ConquestManager` duplicam bastante lógica de
  montagem/envio de ataque (`attack_form`, `map_pos`, `post_url` de confirmação).
  Candidato a extrair um helper comum.
- Vários módulos (`Hunter`, `PvpConquestManager`, `ZoneManager`, `ConquestManager`)
  leem/escrevem cache via varredura de diretório (`os.listdir` + `json.load` por
  arquivo) a cada ciclo. Pode virar gargalo de I/O conforme o número de aldeias/cache
  cresce — considerar indexação ou cache em memória por ciclo.
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
  2026-08-08. O fix do P0-2 fez `required_resources` refletir necessidade real
  por aldeia pela primeira vez, o que a ativaria de verdade — mas a escolha de
  destino ordena por `last_run`, que é reescrito a cada ciclo para toda aldeia
  (P2-27), e `send_resources()` sempre retorna `True` sem inspecionar a
  resposta (P1-16). Religar só depois de corrigir os dois.

## Backlog de features pendentes

Ver `docs/backlog.md` para a lista priorizada (Features 14–22 e seguintes).
Features 18–22 vieram de uma comparação entre as mecânicas reais do jogo e o
que o bot cobre hoje — ver `docs/game_comparison.md` para o raciocínio
completo por trás delas.

## Features já implementadas (referência rápida)

Features 4 a 13 implementadas e (majoritariamente) validadas em campo — ver
histórico completo em `docs/features_log.md` se precisar do detalhe de cada uma
(arquivos tocados, config associada, notas de validação).
