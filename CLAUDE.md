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

## Backlog de features pendentes

Ver `docs/backlog.md` para a lista priorizada (Features 14–22 e seguintes).
Features 18–22 vieram de uma comparação entre as mecânicas reais do jogo e o
que o bot cobre hoje — ver `docs/game_comparison.md` para o raciocínio
completo por trás delas.

## Features já implementadas (referência rápida)

Features 4 a 13 implementadas e (majoritariamente) validadas em campo — ver
histórico completo em `docs/features_log.md` se precisar do detalhe de cada uma
(arquivos tocados, config associada, notas de validação).
