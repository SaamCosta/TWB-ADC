# TWB-ADC — Frontend

> Documento único da interface: estado da migração, auditoria do que existia,
> arquitetura de informação, direção visual, catálogo de componentes, contratos
> que faltam no backend e o processo por fatia.
>
> **Consolidado em 2026-09-14.** Substitui `interface/auditoria_interface_atual.md`,
> `interface/arquitetura_informacao.md`, `interface/direcao_visual.md`,
> `interface/plano_migracao.md` e `interface/handoff_interface.md`.
>
> ⚠️ **Esses cinco arquivos nunca foram commitados e foram perdidos na
> consolidação** (ver o vigésimo terceiro padrão no `CLAUDE.md`). Este documento é
> o que sobreviveu: estado, decisões e regras. O que se perdeu é o **histórico
> fatia a fatia** do handoff — a narrativa de cada rodada, os arquivos tocados e a
> verificação de cada uma. As 36 capturas em `docs/screenshots/` continuam lá e
> são a evidência visual dessas fatias.
>
> O par deste documento é [`backend.md`](backend.md). A fronteira entre os dois é
> dura e vale como regra de trabalho: **o frontend não inventa estado que o
> backend não publica.**

---

## 1. Fronteira e princípio de trabalho

A migração atua **somente** em Jinja, CSS, JS de apresentação e nesta
documentação. Não altera `webmanager/server.py`, `webmanager/utils.py`, managers,
cache, contratos de domínio ou endpoints.

O princípio que organiza tudo o que segue:

> Quando a fonte, a idade, a razão, a próxima ação ou a confirmação não existem,
> o componente diz **"não disponível"** e aponta o diagnóstico possível. Não
> deriva o estado de string de log, não colore por substring e não chama de
> sucesso o que foi apenas aceito.

O maior risco da interface anterior não era estético: **processo ativo, cache
presente e sucesso confirmado pareciam a mesma coisa.**

Rollback por fatia: restaurar o template específico e manter o CSS novo (que
preserva as classes Bootstrap). Não há migração de dados.

---

## 2. Estado da migração

**Sete fatias auditáveis concluídas até 2026-09-14** — etapas 1 a 11 da sequência
abaixo. A sétima fechou exclusivamente `config.html`.

| # | Template | Objetivo | Estado |
|---:|---|---|---|
| 1 | `main.html` | shell, tokens, navegação por intenção | ✅ |
| 2 | `bot.html` | verdade operacional e exceções | ✅ |
| 3 | `villages.html` | tabela comparável e filtros | ✅ |
| 4 | `logs.html` | diagnóstico e filtros acessíveis | ✅ |
| 5 | `reports.html` | evidência, fonte e veredito | ✅ |
| 6 | `resource_sharing.html` | tentativa / aceitação / falha / unknown | ✅ |
| 7 | `hunter.html` | deadlines, confirmação e risco | ✅ |
| 8 | `pvp_conquest.html` | evidência separada, pipeline, override | ✅ |
| 9 | `conquest.html` | posse confirmada versus estimada | ✅ |
| 10 | `village.html` | detalhe, estado observado, configuração | ✅ |
| 11 | `config.html` | configuração global | ✅ |
| 12 | `map.html` | camadas e alternativa acessível ao canvas | ⬅️ **próxima, condicionada a alternativa tabular** |
| 13 | `zones.html` | risco regional e raio | ⬜ |
| 14 | `empire.html` | agregados coerentes | ⬜ |
| 15 | `farmscores.html` | explicar score e segurança | ⬜ |
| 16 | `flags.html` | último ciclo e frescor | ⬜ |
| 17 | `statue.html` | leitura, slots e stale | ⬜ |
| 18 | `inventory.html` | leitura e degradação de labels | ⬜ |
| 19 | `unit_templates.html` | editor seguro e confirmação | ⬜ |
| 20 | `templates.html` | corrigir markup e completar CRUD | ⬜ |

**A sétima fatia (`config.html`)** completou o par do editor por aldeia: o mesmo
HTML concatenado é reorganizado em seções acessíveis, mas o alcance global,
defaults locais, fallback/autodetecção e efeito em ciclo posterior permanecem
separados da persistência.

**Riscos de canvas ficam para depois** (`map`, `zones`, `empire`): são de alto
valor mas exigem alternativa tabular antes de poderem ser considerados
acessíveis.

### 2.1 Artefatos

| Arquivo | Papel |
|---|---|
| `webmanager/static/css/twb-interface.v1.css` | tokens + todos os componentes (~39 KB) |
| `webmanager/static/js/twb-shell.v1.js` | só o shell: drawer, Escape, foco (~2 KB) |
| `docs/screenshots/` | 36 capturas por fatia, viewport e estado |

O JS de apresentação faz **formatação**, nunca **criação de valor**: ele formata
`last_run` em idade, mas não inventa `last_run`.

---

## 3. Auditoria do que existia (2026-09-13)

Estado anterior à primeira fatia. **Maturidade visual: 38/100** — havia identidade
cromática e componentes Bootstrap reutilizados, mas nenhum token, documentação de
componente, arquitetura por intenção, escala responsiva consistente ou vocabulário
uniforme de estado.

### 3.1 Achados estruturais

| Severidade | Achado |
|---|---|
| **Crítica** | **Processo ativo não prova saúde.** Badge verde "Ativo" quando `BotManager.is_running()` retornava verdadeiro — isso confirma apenas detecção de processo. |
| **Crítica** | **Solicitação e confirmação se confundiam.** Nenhuma página representava "requisição enviada", "resultado desconhecido" e "efeito confirmado" separadamente. |
| Alta | **Estado inferido por texto.** `bot.html` colorindo output por `ERROR`/`Traceback`/`WARNING`; `logs.html` por substring de `event_type`; `farmscores.html` derivando faixa do score; conquista mapeando strings de status em CSS local. Mudar o texto mudava o significado visual. |
| Alta | **Ausência virava traço ou zero.** `0`/`—` onde "sem dado", "zero real" e "não aplicável" são coisas distintas. |
| Alta | **Frescor não era sistemático.** `last_run` existia, `fetched_at` existia, mas sem SLA/cadência comum e quase nunca exibidos. |
| Alta | **Barra horizontal com 18 destinos** numa linha, com risco de overflow já em 1280 px e sem colapso utilizável. O operador precisava conhecer a taxonomia interna. |
| Média | **Nomenclatura mista** (inglês/português) e **Bootstrap 4 e 5 misturados** (`ml-*` com `me-*`, `badge-*` com `bg-*`) sobre um Bootstrap 4.3.1 — classes que simplesmente não faziam nada. |
| Média | Tudo competia pelo primeiro plano; bloqueio, ausência de dado e volume normal tinham o mesmo peso visual. |

Dívida repetida: borda `#c8a96e` em quase toda página sem significado consistente;
`style="color:#2c1810"` em todo cabeçalho; estados vazios reimplementados em sete
templates; badges servindo ao mesmo tempo de estado, perfil, contagem, tag e ação;
filtros feitos caso a caso; confirmação destrutiva por `confirm()` nativo com
cobertura inconsistente.

### 3.2 Acessibilidade (WCAG 2.1 AA)

| Severidade | Achado | Critério |
|---|---|---|
| crítica | canvas comunica quase só por cor/hover, sem equivalente tabular | 1.1.1, 1.3.1, 2.1.1 |
| alta | navegação sem landmark/grupos e sem indicação programática de página ativa | 1.3.1, 4.1.2 |
| alta | foco dependia do padrão do browser; sem foco global visível | 2.4.7 |
| alta | controles com label visual sem `for`/`id` | 1.3.1, 3.3.2 |
| alta | emojis em botões anunciados de forma inconsistente | 1.1.1, 4.1.2 |
| alta | estados dependendo de vermelho/verde | 1.4.1 |
| média | alvos `btn-sm` abaixo de 44 px | 2.5.5 |
| média | tabelas sem `scope`/`caption` | 1.3.1 |
| média | atualização AJAX não anunciada por região viva | 4.1.3 |
| média | tooltips somente por mouse | 2.1.1 |

⚠️ **Nenhuma rodada executou leitor de tela.** As fatias cobriram estrutura,
teclado, foco, contraste medido por token e reflow — validação manual com
NVDA/VoiceOver continua pendente.

### 3.3 Dependências externas

Bootstrap 4.3.1, jQuery 3.3.1, Popper 1.14.7 e Bootstrap JS, **todos por CDN**.
47 imagens locais herdadas do jogo em `webmanager/static/images/`. Falha de CDN
degrada fortemente layout e modais. A vendorização é trabalho separado e ainda
não feito; Bootstrap permanece como **camada de compatibilidade** para que cada
template continue utilizável durante a transição.

---

## 4. Arquitetura de informação

O mapa anterior era a barra plana de 18 nomes de módulo. O modelo mental era o
nome interno; não havia distinção entre diagnóstico, operação de risco, economia,
território e configuração.

| Grupo | Itens |
|---|---|
| **Operação** | Visão geral `/` · Aldeias `/villages` + `/village` · Atividade e relatórios `/reports` |
| **Defesa** | Ameaças · Apoios · Mapa defensivo — **futuros, `aria-disabled`, não são links** |
| **Operações** | Hunter `/hunter` · Conquistas `/conquest` · Conquista PvP `/pvp_conquest` · Zonas `/zones` |
| **Economia** | Recursos `/resource_sharing` · Construção `/building_templates` · Tropas `/unit_templates` · Bandeiras `/flags` · Paladino `/statue` · Inventário `/inventory` |
| **Território** | Mapa `/map` · Império `/empire` · Farm Score `/farmscores` |
| **Sistema** | Configuração `/config` · Logs `/logs` · Estado do bot (alias de `/`) |

**Nenhuma rota foi criada ou removida.** Os três itens de Defesa existem como
texto desabilitado porque o backend ainda não publica o contrato que os
sustentaria (§6) — é melhor mostrar a lacuna do que fingir que ela não existe.

### 4.1 Fluxos prioritários

**Diagnóstico** — visão geral mostra processo, última observação e exceções → a
exceção aponta a aldeia ou os Logs → Logs filtra por arquivo, tipo e aldeia →
Relatórios dá a evidência e o veredito agregado. Se o contrato não existe, a UI
registra "não disponível" e **não propõe ação automática**.

**Localizar uma aldeia** — Aldeias → filtrar por nome, ID ou coordenada →
comparar estado, perfil, recursos, tropas, fila e idade → abrir detalhe ou
centralizar no mapa → copiar coordenada por controle dedicado.

**Verificar uma operação crítica** — a visão geral **informa que não possui
agenda consolidada** (não finge ter) → Operações → confirmar status, deadline,
fonte e falha na página específica → consultar Logs antes de repetir ação cujo
resultado é desconhecido.

**Pausar ou intervir** — visão geral → controle do processo → "solicitação
enviada" durante a requisição → a resposta confirma **apenas processo
detectado/não detectado** → saúde das automações continua não confirmada até
existir heartbeat.

### 4.2 Telas pequenas

Navegação vira drawer com botão, backdrop e Escape · saúde vira lista vertical ·
cabeçalhos e ações empilham · **tabelas preservam todas as colunas críticas em
scroll horizontal e nunca escondem estado ou idade** · canvas permanece legado
nesta fase. Densidade plena é para 1280–1920 px; abaixo disso a prioridade é
decisão segura, não paridade visual.

---

## 5. Direção visual e design system

### 5.1 Tese e princípios

**Mesa de comando cartográfica com precisão operacional moderna.** Papel técnico
aquecido, estrutura marrom profunda, latão como assinatura, cor semântica apenas
onde existe estado. A referência cartográfica aparece na grade de fundo e no
alinhamento de coordenadas — não em textura medieval.

1. Exceções ocupam o primeiro plano; inventário saudável recua.
2. **Um estado só recebe linguagem positiva quando há evidência positiva.**
3. Números usam alinhamento tabular; coordenadas e horários usam monoespaçada.
4. Bordas delimitam estrutura; sombra só diferencia planos.
5. Cards representam unidades semânticas, não uma grade automática.
6. Movimento orienta abertura, foco e atualização; respeita `prefers-reduced-motion`.
7. **Ícone acompanha texto e nunca carrega significado sozinho.**

### 5.2 Tokens v1

Em `webmanager/static/css/twb-interface.v1.css`.

| Categoria | Tokens | Uso |
|---|---|---|
| marca | `--twb-brand-950/900/800` | navegação, títulos, ação primária |
| assinatura | `--twb-brass-700/500/300` | seleção, divisor, detalhe |
| superfícies | `--twb-paper-50/100/200`, `--twb-surface` | fundo, agrupamento, painéis |
| texto | `--twb-ink`, `-secondary`, `-muted` | hierarquia textual |
| semântica | `--twb-info`, `-success`, `-warning`, `-danger`, `-unknown` e variantes `-soft` | estado, sempre com texto |
| espaço | `--twb-space-1..6` | 4, 8, 12, 16, 24, 32 px |
| forma | `--twb-radius-sm/md/lg`, `--twb-border*` | controles e painéis |
| elevação | `--twb-shadow-1/2` | superfície e overlay |
| movimento | `--twb-motion-fast/normal`, `--twb-ease` | resposta e navegação móvel |
| shell | `--twb-nav-width`, `--twb-content-max` | geometria principal |

Tipografia: Segoe UI / Inter / system para texto; Cascadia Mono / Consolas para
coordenadas, horários e IDs. Escala parte do tamanho base do navegador; `clamp()`
só no título de página.

**Contraste medido** dos tokens semânticos: info 5,98:1 · muted 5,68:1 ·
unknown 5,56:1 · danger 5,47:1 · warning 5,07:1 · texto secundário 6,42:1.

### 5.3 Catálogo de componentes

Todos com variantes, estados, tokens e regra de acessibilidade documentados no
CSS. O que cada um **proíbe** é a parte que importa.

| Grupo | Componente | Proibição central |
|---|---|---|
| Shell | Shell da aplicação | navegação horizontal paralela; link para rota inexistente |
| Shell | Navegação principal e grupos | placeholder clicável; ícone sem rótulo |
| Shell | Cabeçalho de página | contador como substituto do propósito |
| Estado | Faixa de saúde operacional | chamar de "saudável" quando só há PID ou cache |
| Estado | Indicador de frescor | classificar stale com limiar inventado |
| Estado | Status badge | `success` para "requisição enviada"; badge como botão |
| Estado | Painel de exceção | ocultar o painel para produzir aparência verde |
| Estado | Timestamp técnico | exibir hora sem dizer de onde veio |
| Dados | Tabela operacional | card repetido onde linhas devem ser comparadas |
| Dados | Filtro compacto | placeholder como único label |
| Dados | Seletor de visão e paginação | mudar semântica do conjunto sem avisar |
| Dados | Bloco de metadados operacionais | misturar dado observado com dado configurado |
| Dados | Cartão de aldeia | grade de cards iguais quando a tarefa é comparar |
| Ação | Ações (primária/secundária/destrutiva) | trocar rótulo para "sucesso" antes da confirmação |
| Ação | Confirmação de ação | confirmação genérica sem alvo |
| Ação | Exclusão de operação | rotular limpeza de cache como cancelamento de ataque |
| Ação | Limpeza forte de acompanhamento | esconder risco de duplicação |
| Conteúdo | Alertas e estados de conteúdo | tratar "vazio" e "sem dados" como sinônimos |
| Conteúdo | Mensagem técnica expansível | truncar erro sem dar acesso ao texto integral |
| Operação | Cartão de deadline | mostrar prazo sem dizer se já venceu |
| Operação | Sequência de status da operação | pular o estado desconhecido |
| Operação | Composição de tropas, real versus fake | apresentar fake como ataque |
| Operação | Editor repetível de ataques | submeter linha incompleta |
| Operação | Pipeline PvP · cartão de operação e fontes | somar fontes já comprometidas |
| Evidência | Evidência, divergência e confirmação em camadas | fundir scout, simulação e resultado |
| Evidência | Evidência separada de scout e simulação | usar scout vencido como atual |
| Evidência | Autorização explícita sem scout | agir sem registro da autorização |
| Conquista | Cartão de Conquista Bárbara | apresentar `assumed_done` como conquistado |
| Conquista | Leitura de lealdade com proveniência | exibir estimativa como leitura |
| Conquista | Evidência de posse e encerramento | encerrar sem prova de posse |
| Aldeia | Detalhe operacional da aldeia | confundir valor configurado com automação executada |
| Aldeia | Matriz global versus aldeia | esconder a precedência |
| Aldeia | Editor progressivamente aprimorado de configuração | prometer edição para o que o gerador não gera |

**Composição recomendada:** cabeçalho → faixa de saúde → exceções → próxima ação
→ comparação → histórico. No móvel: cabeçalho → saúde empilhada → exceções →
tabela com scroll.

### 5.4 Preservar e abandonar

**Preservar:** família marrom/dourado/creme, assets reconhecíveis do jogo,
Flask/Jinja, Bootstrap como compatibilidade, densidade útil e as explicações de
domínio já registradas.

**Abandonar:** nav plana, "card para tudo", borda dourada universal, emoji
ornamental, gradiente ostensivo, badge verde para booleano, hex por página,
mistura acidental de Bootstrap 4/5.

| Faça | Não faça |
|---|---|
| "Processo detectado — saúde das automações não confirmada" | "Ativo" em verde |
| "Sem timestamp; frescor desconhecido" | assumir recente porque existe cache |
| tabela comparável com exceção marcada por texto **e** borda | grade de cards iguais |
| link futuro visivelmente desabilitado | link quebrado |
| latão como assinatura e divisor | dourado em toda borda |

---

## 6. Contratos que faltam no backend

O frontend aceita a ausência destes contratos e apresenta *unknown* / *sem
dados*. **Não deve derivá-los de string de log.** Cada um tem contraparte direta
no roteiro de `backend.md` §7.4.

### 6.1 Contratos desejados

```text
Snapshot operacional comum
  observed_at, source, source_version, freshness_sla_seconds,
  state, state_reason, partial, errors[], next_action, intervention_url

Ação e confirmação
  operation_id, intent, requested_at, dispatched_at, confirmed_at,
  state(requested|dispatched|confirmed|failed|unknown), reason,
  idempotency_key, reconciled_at

Aldeia
  village_id, name, coordinates, profile, operational_state,
  risk[], blockers[], queues[], resources, troops_home, reserves,
  observed_at, next_action, next_deadline

Centro de eventos
  event_id, severity, category, village_id, operation_id, occurred_at,
  observed_at, source, title, explanation, recommended_action,
  acknowledged_at, resolved_at
```

| Contrato | Depende de | Destrava |
|---|---|---|
| Snapshot operacional | `FND-01` + `FND-04` | frescor real, fim do "verde por cache" |
| Ação e confirmação | `FND-02` + `TIM-02` | linguagem de efeito em toda ação |
| Aldeia (com `reserves`/`blockers`) | `FND-03` | matriz de precedência honesta |
| Centro de eventos | `FND-01` + `OBS-01` | os três itens de Defesa hoje desabilitados |

### 6.2 Limitações concretas achadas na sexta fatia

Diagnóstico do contrato real de `/village`, que é representativo do resto:

1. **A configuração é HTML concatenado no servidor.** `pre_process_village_config()`
   gera `<button data-type=toggle>`, `<select data-type=select>`, number, texto e
   `data-type=list`; **dicionários são pulados**, por isso `keep_resources` é
   visível como reserva declarada mas honestamente não editável. Precisa virar um
   schema de campos (chave, tipo, label, ajuda, enum, valor herdado/efetivo,
   validação, risco) — hoje a acessibilidade depende de progressive enhancement.
2. **A escrita não retorna estado.** `POST /app/config/set` grava e devolve
   `jsonify(sync())`; a UI reconcilia comparando o valor devolvido. Falta
   `persisted`, erro tipado, versão/revisão e status HTTP adequado — **um ID de
   aldeia inválido respondia 200** enquanto o POST era silenciosamente ignorado.
   A página migrada bloqueia edição nesse caso e não aplica o fallback da primeira
   aldeia.
3. **Reservas e bloqueios não são agregados.** Hunter, Conquista Bárbara e PvP
   mantêm reservas em managers e caches separados que a rota não agrega
   (`backend.md` §8.2). `required_resources` registra faltas momentâneas e
   **não é reserva** — some quando a meta é atingida.
4. **`cache/managed` não expõe** reserva militar consolidada, bloqueio por
   operação, próxima ação, aceite/efeito, versão de schema, fonte nomeada além do
   diretório, nem SLA.
5. **`scout_first` existe nas 27 aldeias do config vivo**, não pertence ao
   `village_template` e nenhum código o lê. Apresentado como legado, com efeito
   conhecido nenhum. Remover exige mudança de contrato própria.
6. **`profile_templates` só é aplicado na herança inicial** — trocar apenas
   `profile` numa aldeia existente não reaplica os campos. A UI registra o limite.

### 6.3 Precedências que a UI precisa dizer em voz alta

Descobertas ao migrar e hoje documentadas na matriz global-versus-aldeia:

- `active_hours=null` e `delay_factor=null` herdam do `bot`;
- `building=null` herda `building.default`; `building=false` desabilita o builder
  local; `building.manage_buildings=false` fecha a ação globalmente;
- conquista bárbara exige `conquest.enabled` **e** `conquest_enabled` local;
- **Conquista PvP processa primeiro e pode bloquear suas origens** antes da
  conquista bárbara, do farm e da coleta;
- farm depende de `farms.farm` e não roda sob ataque; coleta idem;
- apoio automático depende de `units.manage_defence` **e** dos toggles locais;
- troca premium exige `world.trade_for_premium` **e** `village.trade_for_premium`;
- resource sharing tem **só gate global**; `keep_resources` protege apenas a regra
  de necessidade, não o transbordo.

### 6.4 Contrato real da configuração global — sétima fatia

`GET /config` continua chamando `pre_process_config()`, que devolve um dicionário
de **HTML concatenado**, não um schema. No config vivo observado, o gerador expôs
20 seções e 147 controles: booleanos, números, strings, `null`, listas, selects e
chaves com dois componentes. Uma subseção aninhada não vazia também produz chaves
com três componentes. `render_value()` não produz controle para dicionários.

As seções `build`, `villages`, `profile_templates` e `hunter` são ocultadas pelo
backend. Dicionários fora das seções marcadas como aninhadas também são pulados;
folhas objeto relevantes, como `village_template.keep_resources`, não entram no
editor. `conquest.min_escort` só gera controles quando seus filhos existem. A UI
expõe essas limitações e não cria aproximação editável.

O editor agora mantém três representações distintas: valor persistido, proposta
local e estado da solicitação. Toggle, select, texto, número, lista e `null` são
staged; o diálogo lista chave, valor anterior, proposta e alcance. O POST permanece
exatamente `POST /app/config/set?parameter=<chave>&value=<valor>`, sem body e sem
endpoint novo. Escritas múltiplas são sequenciais. Um HTTP 200 só vira
"persistência confirmada" quando o valor reaparece no caminho correspondente de
`data.config`; ausência, divergência, erro e timeout viram resultado desconhecido
ou divergente, sem retry automático. Mesmo após reconciliação, a interface diz
"efeito operacional ainda não observado".

Semântica comprovada no código consumidor: `building` e `units` têm gates/defaults
globais com overrides locais; `village_template` é default para novas aldeias e
não reconfigura registros existentes; conquista bárbara exige gate global e
local; resource sharing não tem gate por aldeia; premium exchange exige o gate
do mundo e o local; campos de capacidade do mundo podem ser gates, fallback ou
autodetectados; alterações são percebidas apenas quando o respectivo consumidor
volta a ler a configuração. Campos sem consumidor localizado ficam apresentados
sem alegação de efeito.

QA usou servidor temporário isolado, sem importar `webmanager.server` e com toda
escrita interceptada em memória pelo cabeçalho
`X-TWB-Fixture-Write: intercepted-memory-only`. Cobriu config cheia/vazia,
seção/campo ausente, `null`, zero, `false`, string/lista vazia, lista preenchida,
subseção, legado, reconciliação positiva, divergência e timeout. Em navegador real
foram verificados 1440×900, 1024×900, 720×900 e 390×844: sem overflow no body, um
`h1`, IDs únicos, labels associados, navegação por âncora/teclado, foco, Escape,
cancelamento sem POST, bloqueio de duplo clique e ordem sequencial. Capturas:
`config-desktop-1440.png`, `config-mobile-390.png`,
`config-pending-changes.png`, `config-global-confirmation.png`,
`config-persistence-confirmed.png`, `config-divergent-result.png` e
`config-unknown-timeout.png`.

Limites dependentes do backend: falta schema tipado de campo/validação/risco;
recibo com versão e erro tipado; confirmação do efeito no consumidor; contrato de
frescor; e suporte formal a dicionários. Correspondem a `backend.md` §7.4
(`FND-01`, `FND-02`, `FND-04`, `FND-05`) e §8. Não foram simulados no frontend.

Backlog visual preservado para `bot.html`: (1) a faixa superior nasce do render
inicial e não acompanha o polling; (2) parar processo detectado/adotado fora do
painel merece confirmação forte; (3) polling de estado deve preferir
`/bot/status`, deixando `/bot/output` para atualização explícita ou menos
frequente. Nenhum desses itens foi implementado nesta fatia.

---

## 7. Processo por fatia

### 7.1 Critérios de aceite

- rotas, nomes de campo, métodos e actions preservados;
- renderização com conjunto **cheio, vazio e com campos ausentes**;
- foco visível e operação completa por teclado;
- status com texto, não apenas cor;
- sem hex ou espaçamento novo no template, salvo valor dinâmico de canvas;
- viewports 1440, 1024 e 390 px sem conteúdo crítico inacessível;
- POST testado **sem efetuar ação real** quando não houver ambiente seguro;
- `git diff --check`, compilação Jinja de todos os templates e verificação de
  links locais;
- screenshot e limitações anexados.

### 7.2 Como um POST é testado sem causar efeito

Padrão usado na sexta fatia e reutilizável: servidor de fixture temporário com a
rota de escrita **interceptada em memória**, devolvendo
`X-TWB-Fixture-Write: intercepted-memory-only`. A UI confirma o valor refletido e
mantém "efeito operacional ainda não observado". `config.json`, caches e operações
reais permanecem intocados; o servidor de fixture é removido antes da entrega.

### 7.3 Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Trabalho concorrente no worktree | registrar hashes dos caminhos compartilhados antes/depois; não tocar arquivo de domínio; parar se houver sobreposição |
| Bootstrap 4/5 misto | manter o 4 e neutralizar classes inválidas template a template |
| Dados reais heterogêneos | `or {}`, `default` e condições Jinja pequenas; **não alterar o produtor** |
| Falso frescor | calcular idade só de timestamp existente; não classificar stale sem SLA |
| Ação real disparada por teste | preferir renderização/GET; POST só com fixture ou autorização explícita |
| CDN offline | registrado como dependência; vendorização é trabalho separado |

### 7.4 Auditoria cruzada

1. Antes de cada fatia, comparar o que o agente de domínio mudou em campos,
   estados e timestamps.
2. Auditoria de compatibilidade Jinja, formulários, rotas, ausência e suposições
   de domínio.
3. Auditoria de novas semânticas de status, fila, reserva, confirmação, erro e
   stale.
4. Repetir a renderização com fixtures contratuais **quando o backend introduzir
   snapshot e eventos unificados** — é a reauditoria que fecha o ciclo com §6.

---

## 8. Próximos passos

1. **`map.html`** (fatia 8), somente depois de oferecer alternativa tabular
   acessível ao canvas.
2. **Validação com leitor de tela real** (NVDA/VoiceOver) — é a única categoria de
   acessibilidade que nenhuma fatia cobriu.
3. **Alternativa tabular ao canvas** antes de migrar `map`, `zones` e `empire`;
   sem ela, essas três páginas não podem ser declaradas acessíveis.
4. **Vendorizar as dependências de CDN**, como trabalho próprio.
5. Quando `FND-01`/`FND-04` existirem: substituir os indicadores de frescor
   "sem SLA" por classificação real e ligar os três itens de **Defesa** hoje
   desabilitados.
