# Estudo dos cinco forks irmãos — versão Claude (2026-09-20)

> ⚠️ **ARQUIVO TEMPORÁRIO, PARA CONSOLIDAR E APAGAR.**
> O `CLAUDE.md` diz que trabalho novo se registra em `docs/backend.md` ou
> `docs/frontend.md`, e que não se cria documento por feature. Este arquivo é a
> exceção combinada com o usuário em 2026-09-20: o Codex rodou o **mesmo** estudo
> em paralelo e já escreveu a `§7.9` do `backend.md` (além de ter mexido em
> `CLAUDE.md` e `frontend.md`), então gravar a minha versão no mesmo arquivo
> arriscava uma das duas sumir em silêncio. Fica aqui para comparação lado a
> lado; depois que o usuário decidir o que vale, o conteúdo aproveitado migra
> para `backend.md`/`frontend.md` e **este arquivo é removido**.
>
> Enquanto existir, ele é `??` no `git status`. Vale o vigésimo terceiro padrão:
> **commitar antes de qualquer limpeza de diretório.**

**Autor da leitura:** Claude (sessão de 2026-09-20, 01:50–02:30).
**Método:** clonagem dos 5 repositórios + do upstream `stefan2200/TWB` como base
de diff, em `%TEMP%\twb_study\`. Leitura estática. **Nada foi executado contra
servidor nenhum.**

---

## 0. Cobertura e o que este documento não prova

Repositórios estudados, com o diff estrutural contra o upstream
(`stefan2200/TWB`, HEAD `09c8c87`, 2024-04-02):

| Repo | HEAD | Data | `.py` | LOC | Δ vs upstream |
|---|---|---|---|---|---|
| `LazyTurtleStyle/TWBOT_LazyTurtle` | `a2b13a8` | 2026-09-19 | 50 | 26.617 | +21 módulos novos |
| `Themegaindex/TWB` | `aa48004` | 2025-12-04 | 34 | 9.107 | +1 módulo, +4 testes |
| `felipewariat/kuzyn-plemiona` | `78ea499` | 2026-06-23 | 29 | 6.877 | tradução PL + Farm Assistant |
| `Trojanekkk/TWB` (`develop`) | `8665362` | 2026-05-29 | 24+ | 5.257+ | painel (auth, stats) |
| `KrzysztofKalisiak/TWB_plus` (`master`) | `09c8c87` | 2024-04-02 | 29 | 6.709 | **zero** |

> **Achado que muda a leitura do lote:** `TWB_plus` no `master` é **byte-a-byte
> igual ao upstream** — `diff -rq --exclude=.git` não acusa um arquivo sequer.
> Não é um fork desatualizado, é um espelho sem alterações. Todo o trabalho dele
> está no branch `NoDriverLogging` (`cebd75c`, fev/2026), que precisa ser buscado
> à mão (`git fetch origin NoDriverLogging:<local>`).

Nosso repo, para calibrar: **18.187 LOC**. Não estamos atrás em volume; estamos
atrás em **superfície de features** e à frente em **verificação** — temos 15+
arquivos de teste, e o LazyTurtle tem **zero** (não existe diretório `tests/`).

**Limites desta auditoria:**

1. É **estática**. Nenhum número abaixo foi medido por mim no br143.
2. O LazyTurtle é jogado quase só em mundos **`.nl`** (o README diz isso). Vale o
   **décimo sétimo padrão**: constantes e fórmulas deles podem estar certas num
   mundo `speed=2.0` e erradas num `speed=1` — e o mundo onde mediram não
   consegue contar isso.
3. O LazyTurtle é, ele mesmo, vibe-coded com Claude (commits trazem
   `Co-Authored-By: Claude Opus 5`). **Prosa boa de docstring não é evidência de
   validação em campo.** Quando o docstring nomeia a medição (valor, data,
   mundo), anotei como medição; quando não nomeia, tratei como hipótese.
4. **Licença:** os cinco são GPLv3, igual ao nosso. Copiar código adaptado é
   legal mantendo a licença. Não há impedimento jurídico em nada abaixo.

---

## 1. Veredito por repositório

| Repo | Veredito | Uma linha |
|---|---|---|
| **LazyTurtle** | Mina de ouro | 21 módulos que não temos; ~8 adaptáveis quase direto, e 3 corrigem defeitos que sabemos ter. |
| **Themegaindex** | Duas ideias + o hábito de testar | "smart farming" e o **limite de saque do mundo**, mecânica que talvez nem exista no br143. |
| **kuzyn-plemiona** | Uma ideia | Tradução PL da base de 2024 + `am_farm` com paginação. O resto é ruído. |
| **Trojanekkk** (`develop`) | Duas ideias de painel | Autenticação por senha e agregação estatística 24h/7d. |
| **TWB_plus** | Uma ideia, alto risco | Login automatizado por navegador (`nodriver`) com rotação de sessão. Código inaproveitável; a ideia, sim. |

---

## 2. LazyTurtle — inventário módulo a módulo

Caminhos são relativos ao repo deles.

### 2.1 TIER A — pegar (alto valor, risco baixo, dor conhecida nossa)

#### A1. `core/request.py` — retomada automática de captcha e sessão via arquivo

`:242` `_await_captcha_clear` · `:333` `start` · `:388` `_wait_for_session` · `:442` `reauth`

É **o vigésimo segundo padrão do nosso `CLAUDE.md`, resolvido**. Confirmado em
2026-09-20 que o nosso `core/request.py` ainda tem:

- linha **79**: `input("Press any key...")` no caminho de captcha
- linha **115**: `input("Enter browser cookie string> ")` no start

O que eles fazem no lugar:

- **Captcha:** em vez de bloquear em `input()`, gravam `cache/captcha_block.json`
  (alimenta o banner do painel), notificam por Telegram e **re-buscam a mesma URL
  em loop** até `data-bot-protect="forced"` sumir. Ao limpar, apagam o marcador,
  **refrescam o heartbeat** (senão o painel pula de "captcha" para "travado" no
  instante do desbloqueio) e devolvem a resposta boa.
- **Backoff por horário:** 20 s em horário ativo, **300 s fora dele**, com
  justificativa medida — *"um captcha às 22:40 de 2026-08-27 bloqueou o loop até
  06:59 e custou ~1500 re-checagens"*. Reavaliado a cada volta, acelera sozinho
  ao amanhecer.
- **Cookie nunca pelo console:** `start()` não pergunta nada. Lê
  `cache/session.json`, tenta `cache/cookies.txt`, e senão entra em
  `_wait_for_session()` (poll de 10 s, lembrete a cada 5 min). Motivo escrito:
  *"o console corta a linha longa, então o cookie parece aceito e volta deslogado
  em todo ciclo"* — e com stdin fechado (bot iniciado pelo painel) `input()`
  levanta `EOFError` e derruba o run.
- **POST também checa captcha.** Sem isso, um captcha que bate num POST de
  construção/recrutamento é **invisível**: nenhum banner, só um no-op silencioso.
- `REQUEST_TIMEOUT = (10, 30)` em todo request. (Nós já temos.)

**Valor:** alto e imediato. Fecha o buraco que o `BotManager` contornou com
`CREATE_NEW_CONSOLE` — se o bot não pergunta mais nada, o console visível deixa
de ser obrigatório.

#### A2. `core/instance_lock.py` — trava de instância por **conta**

163 linhas; usado em `twb.py:1080`.

- Chave = **host do endpoint** (`nl99.tribalwars.nl`), não o nome do mundo nem o
  diretório. Raciocínio escrito, e é o nosso caso: *"um bot iniciado sem
  `--world` e um com `--world nl99` são dois mundos para o painel e a mesma conta
  para o TribalWars — que é como uma segunda instância é lançada por acidente"*.
- Guarda `pid` **+ `create_time`**. PID sozinho não prova nada (são reusados); se
  o `create_time` gravado não bate, o lock é lixo e some. Se o `create_time` não
  puder ser lido (permissão), **assume vivo** — nunca rouba lock de bot vivo.
- Lock morto se limpa sozinho; re-aquisição pelo mesmo PID passa (o loop de retry
  de crash depende disso).
- `describe()` → *"pid 1234 (world: nl99, rodando há 87 min)"*.

**Valor:** é a mitigação de risco de ban mais barata do lote. Depende de `psutil`,
que já é dependência nossa. Melhor que a nossa varredura por cwd.

#### A3. `game/worldvillages.py` — a lista pública de aldeias do mundo inteiro

`:41` `parse` · `:64` `fetch` · `:85` `fetch_players` · `:107` `cached`

**Resolve o nosso vigésimo quarto padrão pela raiz.** O `P-CONQ-RAIO` (§8.6)
documentou dois funis em série, e o de cima é "a aldeia só enxerga o que o
prefetch de mapa dela baixou". O TribalWars publica, **sem sessão e sem
autenticação**:

- `<mundo>/map/village.txt` → `id,name,x,y,player_id,points,rank`, uma linha por
  aldeia do mundo (~600 KB num mundo cheio; `owner == "0"` = bárbara)
- `<mundo>/map/player.txt` → `id,name,tribe,villages,points,rank`
- (o `markings.py` deles também usa `map/ally.txt`)

Uma requisição responde "quem é o dono disto e onde fica" para o mundo inteiro.
Cache de 6 h, com justificativa certa: *"posse muda na escala de conquistas, não
de minutos"*. O motivo declarado de terem escrito isto é igual ao nosso: *"de 53
aldeias inimigas que valia nomear, 37 eram desconhecidas para o cache de mapa"*.

Guardas que valem copiar junto: recusam corpo > 40 MB (não ler página de erro
como dado) e **recusam parse com ≤ 100 aldeias** — um mundo sempre tem milhares,
então um punhado significa redirect, não o arquivo. Na falha, devolvem o cache
velho.

**Valor: o maior do lote para o roadmap de conquista.** `find_target()` deixa de
depender de `map_sector_radius` para *descobrir* alvos; o raio volta a ser só
decisão de alcance, não peneira cega. Também alimenta o painel (nome de jogador e
de aldeia fora do cache).

**Medir antes:** que `br143.tribalwars.com.br/map/village.txt` responde 200 e tem
> 100 linhas. Dois minutos de `Invoke-WebRequest` — quinto padrão manda não
adiar por falta de dado buscável.

#### A4. `core/server_clock.py` — duas classes, duas perguntas

`ServerClock:54` · `GameClock:137`

A separação é a parte boa, e está escrita no topo do arquivo:

- **`ServerClock`** responde *"que horas o relógio do jogo marca"*. Lê
  `<span id="serverTime">`/`serverDate` do rodapé de qualquer página (que o bot já
  baixa) e guarda o offset contra o host. Cobre drift **e fuso**. O fuso é o
  perigoso: os timestamps epoch dos dois lados são idênticos, *nada parece
  errado*, enquanto toda hora de parede escrita por humano (paz forçada, hora de
  chegada) significa um instante diferente para o bot e para o jogador. Tentam 6
  formatos de data e **escolhem o que produz offset plausível** (≤ 14 h) — é assim
  que desempatam `dd/mm` de `mm/dd` sem saber o mercado. Reamostram a cada
  overview, então horário de verão entra no mesmo dia.
- **`GameClock`** responde *"quando disparar"*. Amostra `game_state.time_generated`
  (epoch **ms** do servidor) contra o ponto médio local do request → erro ~metade
  do RTT. Guarda o `rtt` para o disparo liderar pela latência de ida e ser
  **processado** no ms escolhido. Observação de fundo: *o jogo calcula viagem em
  segundos inteiros, então a chegada carrega os ms do envio* — disparar em `.250`
  chega em `.250`.
- `observe(res, t0, t1)` aprende de graça de uma página que o chamador ia abrir.

**Valor:** destrava coisa nossa — o `Hunter` (Feature 10) e as janelas de apoio da
§4.6/§6 estão ancorados em `datetime.now()` do host. Casa com o **décimo oitavo
padrão** (limiar que exige *chegar* antes do prazo).

#### A5. Coleta (scavenging) — o que estava sendo mexido na mesma noite

`troopmanager.py:13-46` (fórmulas) · `:486` `unlock_scavenge` · `:547` `gather`
`village.py:800` `_gather_night_consolidate` · `:844` `_scavenge_target_option` ·
`:860` `do_scavenge_unlock` · `:900` `scavenging_enabled` · `:922` `_gather_group_policy`

Comparado com o nosso `troopmanager.gather()`: temos o split avançado (mesma
origem), `effective_gather_selection` e `gather_option_keys` — eles **não** têm
esses dois; nisso estamos à frente. Sete coisas que não temos:

1. **Fórmula de duração invertida.** `scavenge_max_carry(option, max_seconds,
   world_speed)` = *"maior esquadrão cuja corrida volta dentro de X"*. Direta:
   `((carry² × 100 × fator²)^0,45 + 1800) × world_speed^-0,55`. Nota do arquivo:
   *"verificada contra corrida real de opção IV num mundo NL speed 2.0: 39.160 de
   capacidade previu 16h10, observado 16h09"*. É medição **nomeada**.
2. **`SCAVENGE_LOOT_FACTOR = {1:0.10, 2:0.25, 3:0.50, 4:0.75}`** — saque esperado
   = capacidade × fator. Permite **logar o saque previsto no despacho**
   (`log_scavenge_run`), que é a **única** fonte possível de "quanto a coleta
   rendeu em 24 h": *os relatórios de coleta concluída não carregam saque nenhum*.
3. **Auto-desbloqueio por nível de Edifício Principal** (`scavenge_unlock_hq_1..4`,
   defaults 1/5/8/15), respeitando a regra do jogo: só **uma** opção desbloqueia
   por vez → tentam no máximo uma por ciclo, sempre a mais baixa. Se é querida mas
   impagável e `prioritize_scavenge_unlock` está ligado, setam
   `builder.hold_for_scavenge` e **seguram a construção**.
4. **Pulam a requisição extra** quando o snapshot do ciclo anterior já mostra tudo
   desbloqueado.
5. **Consolidação noturna:** dentro da janela, **uma** corrida longa na maior
   opção, dimensionada para voltar quando a janela fecha, com
   `gather_night_min_hours` (default 5) impedindo corrida curta inútil de
   madrugada. **Nunca consolidam sob ataque** — "uma corrida longa com toda a
   tropa é o oposto do que você quer com um ataque a caminho".
6. **Política por grupo do jogo** (alpha): `never` / `pause_attacked` / `always`,
   **mais restritiva vence** quando a aldeia está em vários grupos. Usa o
   vocabulário que o jogador já criou no jogo.
7. **O conserto do interruptor global — e a lição vale por si.** A chave de coleta
   do painel *escrevia-se em cada aldeia*: isso desliga tudo, mas **sobrescrevendo
   cada escolha por aldeia no caminho**, então religar ligava em aldeias
   deliberadamente desligadas. A frase deles: *"um interruptor que você não
   consegue voltar sem perder o que ele escondia é um interruptor que custa caro
   usar"*. Correção: `farms.scavenge` (global, default **on**) **E**
   `gather_enabled` (por aldeia) — **gate, não broadcast**.

**O item 7 é revisão obrigatória** do que estiver sendo escrito no webmanager: o
`P-COL-01` da §8.5 é literalmente "botão de ativar coleta em todas as aldeias", ou
seja, este bug esperando acontecer.

#### A6. `twb.py` — o `deepcopy` que clona a sessão inteira por aldeia

Commit `7d4668d` (2026-08-31); `twb.py:1143`.

O upstream faz `self.villages.append(copy.deepcopy(Village(...)))`. Como cada
`Village` referencia o `WebWrapper` compartilhado, o deepcopy clona **o grafo
inteiro**: `requests.Session`, cookie jar, connection pool e `last_response` com o
corpo de uma página anexado — uma vez por aldeia.

Medição deles: **numa conta de 41 aldeias o processo passava de 767 MB** e travava
em sleep ininterrompível antes de logar qualquer linha depois de "Game Endpoint";
`py-spy` punha todas as pilhas amostradas dentro do mesmo `deepcopy`, ~130 quadros
de profundidade. Pico após a correção: **85 MB**.

O argumento estrutural vale mais que o número: **a cópia nunca comprou nada** (a
linha acima já constrói um `Village` novo por iteração) e é errada por si só — as
aldeias devem compartilhar uma sessão viva; um snapshot privado por aldeia
**impede rotação de cookie e atualização de token CSRF de propagar**. Escala com o
número de aldeias, que é por que um mundo de uma aldeia nunca mostra.

> O Codex já aplicou este no nosso `twb.py`. Diagnóstico confere. **O que a
> correção dele não menciona:** o commit irmão do mesmo dia, `map: stop keeping a
> parsed copy of the map alive per village`, ataca a segunda metade do mesmo
> problema — vale conferir se o nosso `Map` mantém cópia parseada viva por aldeia.

#### A7. `core/notification.py` — Telegram com categorias, e que não derruba o bot

`:22` `CATEGORIES` · `:74` `send` · `:100` `test`

Nosso `core/notification.py` tem 45 linhas e três defeitos que o deles corrigiu:

1. **Lê o config no `__init__`** (no import). O deles lê **lazy**, na primeira
   `send()`. Para nós o ganho é outro: `enabled` e toggles pegam efeito **sem
   reiniciar**.
2. **`send()` não tem try/except.** O deles tem, com data do incidente: *"o
   handler de crash do `main()` chama isto enquanto já trata uma exceção, então um
   timeout do Telegram escapa do loop de retry e o bot sai em vez de reiniciar —
   foi o que aconteceu em 2026-08-03"*. É o nosso **segundo padrão** com outra
   máscara: o caminho de erro tem o próprio erro.
3. **Categorias** (`startup`, `crash`, `session`, `captcha`, `village`, `farm`,
   `attack`) via `notifications.notify_<categoria>`, default `True`.
   + `test()` devolvendo `(ok, erro)` para o botão "enviar mensagem de teste".

### 2.2 TIER B — pegar depois de medir no br143

#### B1. `game/flags.py` — bandeiras são **inventário de conta**

docstring `:1-33` · `resolve_desired:302` · `allocate:356`

Tese: *"uma bandeira dada à aldeia B é uma bandeira tirada da aldeia A; não existe
jeito de ter vinte aldeias em bandeira de recurso possuindo três delas"*.

O diagnóstico do arranjo antigo deles é **literalmente o Bug 1 da nossa §6.3**:
cada `DefenceManager` lia a tela sozinho, via "a melhor de recurso que possuo é
nível 3" e atribuía — *"vinte aldeias configuradas igual passavam o dia passando
as mesmas três bandeiras de mão em mão, cada uma desfazendo a anterior"*.

Arquitetura:

- **Um passe account-wide**, não por aldeia.
- Plano ordenado `(grupo → tipo)`, aplicado de cima para baixo, **linha posterior
  vence**; `priority` = índice da linha que decidiu.
- **Conta oferta contra demanda.** Oferta = o que possui **menos o que já está em
  pé numa aldeia** — bandeira que está fazendo o serviço nunca conta como sobra e
  nunca é tirada.
- Aldeia que já carrega o tipo certo **não é tocada** — e a nota diz: *"isso, não
  a contagem, é o que para o embaralhamento"*.
- Quem sobra vira **`unmet` reportado**, não é servido com bandeira roubada.
- Respeita o **cooldown** do jogo (`<span class="timer cooldown">`): vira um
  resultado "on cooldown" em vez de uma fileira de falhas idênticas.
- Cache de leitura por aldeia (TTL 12 h) + teto de leituras por passe (15):
  *"uma bandeira só se move quando este passe a move; a releitura existe para
  pegar uma movida à mão"*.
- `auto_upgrade` opcional: funde 3 iguais em 1 do nível seguinte, **só do pool
  livre**, opt-in porque *"não tem volta"*.

**Pergunta que isso levanta para nós, e que a §6.3 não responde: a nossa política
conta a oferta?** Se ela só compara "bandeira atual × desejada", funciona enquanto
houver bandeira sobrando e volta a embaralhar quando faltar. Vale checar **antes**
de fechar a validação 1-de-18, senão a validação mede o caso fácil.

> ⚠️ **Alpha declarado.** O arquivo avisa: *"a leitura da tela de bandeiras nunca
> rodou numa conta viva aqui (`flags.manage` está off desde o fork)"*, e o parser
> de `setFlagCounts` foi escrito para sobreviver a um formato que não conhece.
> **Arquitetura vale; parser precisa de fixture verbatim do br143.**

#### B2. `game/balancer.py` — perguntar ao **servidor** o que já está a caminho

`read_receiver:355` · `_headroom:464` · `parse_travel_seconds:683` ·
`_plan_even:763` · `send:827` · `run:901`

Nosso `resource_sharing.py` (828 linhas) foi validado em campo em 2026-08-11 com 4
transferências reais. O deles tem três invenções que não temos:

1. **O `headroom` sai da página do receptor, não de um ledger.**
   `game.php?village=X&screen=market&mode=call` renderiza *"Recursos chegando"* —
   os totais exatos de **todo comboio viajando, contados pelo servidor**. Nota:
   *"não é estimativa: sem modelo de viagem, sem ledger, e sem jeito de dois
   remetentes discordarem"*. Chegaram nisso **depois** de um ledger que errava:
   *"22k de armazém com 23k de argila reservada por dois remetentes que mediram o
   mesmo espaço vazio"*.
   - **Fatiam a célula antes de ler os dígitos**, porque o jogo escreve o separador
     de milhar como `<span>` próprio: `23<span>.</span>000` lê como **23** em
     qualquer regex que pare na primeira tag. **Armadilha real de pt-BR.**
   - Distinguem "sem mercado" (nível 0, lido do blob de estado do jogo —
     `"market":"0"` — não do texto, para não depender de idioma) de "falha de
     leitura", com TTL de 4 h e aviso **uma vez por aldeia**, não uma vez por
     remetente por passe (*"com 50 remetentes isso eram 200+ avisos idênticos por
     dia sobre uma aldeia só, que é como um aviso de verdade se perde"* — nosso
     **décimo quinto padrão**).
2. **Velocidade de mercador medida pelo próprio jogo.** A confirmação informa a
   duração; dividem pela distância e guardam a **taxa min/campo** para todos os
   pares futuros. O palpite clássico (`30 / world_speed`) é desconfiado por
   escrito: *"num mundo speed 1.5 isso prevê 20 min/campo e a confirmação do jogo
   diz 1"*. Guarda assimétrica: taxa **rápida demais** é a perigosa (faz comboio
   parecer entregue enquanto viaja). Bandas 2–120 min/campo; segunda medição que
   discorde da assentada por mais de 2× é descartada como parse errado.
   - **`parse_travel_seconds` merece leitura isolada:** acham duração/chegada/
     retorno **pela relação entre eles** (retorno − chegada == duração, mod 86400),
     não por posição nem por rótulo traduzido. A tentativa anterior pegava "os três
     últimos relógios da página" e media o rodapé (o relógio do servidor vem depois
     de todos) — então **toda** confirmação real era rejeitada e a velocidade nunca
     era aprendida. Falha silenciosa clássica.
3. **`_plan_even`: nivelar o receptor, não encher um recurso.** Busca binária pela
   "linha d'água" mais baixa que o orçamento paga. Comentário que explica:
   derramar tudo no recurso mais vazio *"transforma 1334 madeira ao lado de 16274
   ferro em 18334 madeira ao lado de 3949 argila"*. Acertam as contas em
   **mercadores inteiros** no fim (1000 por mercador; 3056 ocupa quatro, não
   3,056).
4. **Coordenação sem comunicação:** todo remetente ranqueia um alvo de forma
   **idêntica** (empate por id), e um de rank menor só assume depois que o
   preferido **teve a vez e passou** (`_mark_turn` / `may_serve`). Substitui a
   corrida "quem o bot visitar primeiro fica com o alvo".

**O item 1 é aproveitável sem tocar no resto.** Medir antes: fixture verbatim de
`screen=market&mode=call` no br143.

#### B3. `game/minter.py` — abastecer a aldeia de cunhagem

`read_academy:136` · `read_call:164` · `plan_request:198`

Tese econômica: escolher **uma** aldeia, pôr a bandeira de custo de moeda nela, e
despejar a produção da conta inteira naquele armazém — a parte que repete é o
**despejo**, e é só `mode=call` com um número por linha.

- **Pedem na proporção que a moeda realmente custa**, lida da academia
  (`id="coin_cost_wood"` etc.), com o desconto da bandeira **já embutido** — não
  calculada. *"Um armazém cheio de ferro não cunha nada."*
- **Espaço por barra, não por pool.** Um armazém são três barras de `storage`
  cada; tratar como pool único foi o que deixou a aldeia *"sentada em 429k de ferro
  enquanto a madeira secava e a cunhagem parava por falta da metade barata de uma
  moeda"*.
- **Nunca cunha, nunca liga a cunhagem automática, nunca mexe em bandeira.**
  Decisão de escopo deliberada e bem argumentada.

Mesma armadilha do separador de milhar.

#### B4. `game/attack.py:152` + `Extractor.farm_assistant_icons`

`fetch_farm_icons:152` · `send_farm:164`

A página `am_farm` **já traz o julgamento do jogo** por alvo: os ícones A/B/C vêm
cinza (`farm_icon_disabled`) quando não há tropa suficiente *ou* quando o muro
torna o ataque perda garantida; e o ícone C ("do relatório") carrega
`data-units-forecast`, **a previsão exata de tropa que o jogo calculou**. Lido uma
vez por `run()`, em vez de simular.

**Por que importa:** o **décimo primeiro padrão** descreve o problema de medir
saque com um instrumento censurado pela capacidade do próprio pacote. O forecast do
jogo é uma **segunda fonte independente** para a mesma pergunta — e "comparar duas
partes do sistema que respondem a mesma pergunta é diagnóstico de graça"
(corolário do vigésimo quarto padrão).

Medir antes: se o br143 renderiza `data-units-forecast` e a mesma classe
`farm_icon_disabled`. Fixture verbatim obrigatória.

#### B5. `game/incomings.py` — rastreio de comandos recebidos, comando a comando

`slowest_floor:108` · `update_incomings:418` · `_capture_label_endpoint:535` ·
`rename_command_ingame:747`

Temos `Extractor.incoming_commands` (com teste de regressão contra o regex antigo).
O que eles têm além:

- **Poller em thread própria**, com `WebWrapper` separado e
  `block_on_captcha=False` (poller de fundo não tem console para responder) —
  intervalo randomizado entre `incoming_check_min/max` (300–570 s).
- **`slowest_floor()`**: estima a unidade mais lenta possível pelo tempo de voo
  restante — é o "tagging" que o jogo faz. Voo mais lento que aríete implica nobre;
  voo muito rápido é provavelmente fake.
- **Renomear o comando no próprio jogo** com a etiqueta deduzida, então a
  informação fica onde você já vai olhar.
- **Cache de grupos in-game** (`cache/world/groups.json`), que alimenta as
  políticas por grupo da coleta e das bandeiras.
- ⚠️ **Higiene para auditar no nosso código hoje:** dois commits deles existem só
  para devolver a tela do jogador ao estado anterior — `incomings: put the villages
  overview back on Gecombineerd when done` e `reports: put the report screen back
  on Alle when done`. O bot muda filtro/modo da tela **do jogador** para ler e
  precisa restaurar; senão o usuário abre o jogo e acha a tela mexida — e pior,
  relatórios podem cair em grupos que o bot nunca lê (é item do troubleshooting
  deles).

#### B6. `attack_scheduler.py` + `csnipe.py` — precisão de ms e a lição de física

Não proponho trazer snipe/c-snipe agora (alpha, complexo). Proponho **ler a nota de
`csnipe.py:1-60`**, porque é a melhor medição do lote e o raciocínio é
transplantável:

> O servidor credita o tempo de voo de um comando cancelado em **segundos
> inteiros**, e `k` **não** é `(C − S)/1000` — é o número de **fronteiras de
> segundo de parede cruzadas** entre envio e cancelamento. Provado com dois snipes
> reais: envio `.611` / cancel `.861` no mesmo segundo → retorno no plano; envio
> `.950` / cancel `.100` no segundo seguinte → retorno **2,163 s atrasado**, que só
> o cruzamento de um `:000` extra compra. Mirar em `S + k*1000 + margem` comprava a
> fronteira extra silenciosamente para **15% dos envios** (todos cujo ms caísse em
> `.850` ou depois).

É o nosso **décimo nono padrão** (fórmula que comporta duas leituras e só a medição
decide) e o **sexto** (separar "quando mandei" de "quando acontece").

Do `attack_scheduler`, duas ideias já aproveitáveis:

- **Pré-estágio**: abrir e confirmar a praça durante a janela anterior, deixando só
  o lançamento para o instante exato. E sob `priority_mode` (que tira a pausa de
  3–7 s), inserem **0,4–1,8 s aleatórios entre abrir e confirmar**, para que só o
  lançamento seja instantâneo.
- **Claim com expiração**: comando em `sending` com `claimed_at` velho volta a ser
  reivindicável. Sem isso, um crash na janela de pré-estágio deixa o comando preso
  para sempre (é o B7 da auditoria deles).

### 2.3 TIER C — ideias boas, implementação cara ou alpha

| Módulo | O que é | Por que é C |
|---|---|---|
| `events.py` (704) | Joga o evento semanal. Insight: a energia recarrega sozinha até um teto, então **toda hora com a barra cheia é uma ação jogada fora** — "jogar bem é quase todo 'não estar dormindo'". Não fixa favorito: lê os **jackpots progressivos ao vivo** e gasta na opção de maior EV *naquele momento* (viram a opção 4 subir de 575 para 1400 em uma hora, movendo-a de pior, EV 53,75, para muito melhor, EV 95). | Cada evento precisa de driver próprio; o do br143 será outro. **A arquitetura** vale (detectar pelo link do menu que o bot já baixa; parar quando o link some; guardar evento terminado como histórico). |
| `reportanalysis.py` (588) + `villagenotes.py` (196) | Acha os **nukes mortos** — quem perdeu tudo na sua muralha não ataca de novo por semanas — e escreve na **nota privada da aldeia do atacante**, que é a tela que você já abre ao clicar num incoming. Só **acrescenta** (lê a nota atual e põe a linha acima); aldeia que já tem a linha é deixada em paz. Roda **quando você aperta o botão**. Números deles: 53 clears desde 1º/set; de todos os ataques acima de 2000 unidades, **41 perderam tudo e 52 perderam menos da metade**, com um único 70% no meio — por isso o limiar binário funciona. | Só rende em guerra de tribo. Mas `villagenotes.py` isolado (ler/escrever nota via `ajaxaction=village_note_edit`) é **pequeno e reaproveitável** para qualquer anotação nossa, inclusive marcar alvo de conquista. |
| `noblebarb.py` (913) | Conquista de bárbara andando com a lealdade para baixo. **Guarda de sobreposição idêntica em espírito à nossa**: assume que todo nobre bate o **máximo** (35), então com lealdade estimada L no máximo `ceil(L/35)` nobres podem estar no ar. Bárbara fresca de 100 leva trem de 3; os 1–2 restantes só depois dos relatórios. Auto-parada: dono deixou de ser bárbaro, relatório vermelho, praça recusa duas vezes seguidas. Jobs nascem **desarmados**. | Nosso `ConquestManager` + `conquest_planner` já é mais evoluído (multi-origem, área de interesse). Vale comparar a **regeneração** (eles: +1/h × world speed; nós medimos 1/h no br143 em `/page/settings`) e a auto-parada por recusa repetida. |
| `barbshaper.py` (268) | Derruba muralha de bárbara com aríete+machado antes de farmar. Mecânica citada: aríete dá dano pré-batalha (nunca abaixo de metade do nível, arredondado para cima); vitória rebaixa em ~`rams / (2 × 1,09^muro)` níveis, logo arrasar nível W pede ~`2 × W × 1,09^W` aríetes (muro 10 → ~48; muro 20 → ~225); aldeia vazia ainda revida pela defesa básica da muralha (`20 × 1,25^nível`). Escolta dimensionada para que **até o pior rolo (−25%)** mantenha a perda sob tolerância. | Alpha. Mas as **fórmulas de muralha** valem para o nosso `simulator.py` mesmo sem o módulo. |
| `playerfarm.py` (450) | "Hit list" curada de aldeias de jogador, com origem, pacote e cadência próprios. **Para sozinho e nunca retoma**: relatório vermelho, tipo de unidade zerado, defensor visível, ou amarelo cujo saque não supera `2×` o custo em recurso da tropa morta. **Jitter de ±10%** na cadência, porque *"cadência fixa é assinatura de bot"*. | É o `farms.find_player_owned` do nosso quarto padrão. No formato obrigatório: **`find_player_owned` não existe e não funciona — mas `additional_farms` funciona e serve para isso**; o que o `playerfarm.py` acrescenta é a **parada automática por relatório**, que o `additional_farms` não tem. |
| `accountmanager.py` (577) | Entrega construção/recrutamento/pesquisa ao Gerente de Conta premium e **para de fazer** essas coisas (e de ler as telas que só serviam para elas). Mantém plano `grupo → template` e **reaplica toda manhã**, porque a fila do gerente seca em poucos dias. Nenhum endpoint adivinhado: todo POST reusa a action que o jogo acabou de renderizar, CSRF e tudo. | Só vale com premium ativo. O padrão "reusar a action renderizada" vale para tudo. |
| `browser-extension/` + `/app/tw-open` | Extensão Chrome/Edge/Firefox que **injeta os cookies do bot no navegador** e abre o mundo, para jogar sem matar a sessão. Diagnóstico preciso: o login vive em **dois domínios** (mundo e portal), o bot só tem o do mundo, então entrar pelo portal **cunha sessão nova e mata a do bot**. | Dor real de quem joga junto com o bot. É frontend + rota nova → `frontend.md`. |

### 2.4 TIER D — não pegar

- **Dashboard sem autenticação exposto em `0.0.0.0`.** A auditoria interna deles
  (B11) registra que `DEBUG=True` + bind em todas as interfaces = **RCE remota**
  pelo debugger do Werkzeug. Nosso Lote 5 já fechou; não reabrir.
- **`game/hunter.py` deles** — protótipo morto (`self.village_id` indefinido,
  `self.map` vs `self.game_map`, unidades de sleep erradas). O nosso `Hunter` (523
  linhas) é outra coisa e é melhor.
- **Multi-mundo** — muda o `FileManager` inteiro para `worlds/<nome>/`. Só se for
  jogar dois mundos.
- **Snipe / c-snipe completos** — alpha, e o valor depende de guerra ativa.

---

## 3. Os outros quatro

### 3.1 `Themegaindex/TWB`

**(a) "Smart farming"** (`game/attack.py`): quando o template não tem tropa
suficiente, em vez de **pular o alvo**, monta pacote de **capacidade equivalente**
com o que estiver em casa — fase 1 usa o template, fase 2 preenche a lacuna por
lista de prioridade (`light, marcher, heavy, spear, axe, sword, archer`), com
divisão-teto correta. Já corrigiram um bug real: template de capacidade zero (só
espião/aríete) precisa devolver `None`.
→ Relevante ao **décimo primeiro padrão**. Hoje, quando o pacote não cabe, perdemos
o envio inteiro. **Cuidado:** interage com o **limite de ataque falso**
(`min_attack_population`), que já nos mordeu — um pacote montado por capacidade
pode nascer ilegal por população.

**(b) Limite de saque do mundo** (`Extractor.get_farm_bag_state`): algumas
configurações impõem **teto de recurso saqueável** por aldeia/período, mostrado na
praça como *"Erbeutete Rohstoffe X / Y"*. Param de farmar (e opcionalmente de
espionar) ao chegar perto, com margem configurável, e re-checam depois.
→ **Ação: descobrir se o br143 tem isso** (`interface.php?func=get_config` +
`/page/settings`, públicos). Se tiver e não tratarmos, farmamos contra um teto
invisível.
→ ⚠️ **Não copiar o parser deles.** O fallback é `(\d[\d.,]*)\s*/\s*(\d[\d.,]*)`
sobre a página inteira despida de tags — casa com qualquer "N/M" da tela
(mercadores, população, fila). **Décimo quinto padrão em pessoa.**

**(c) O hábito:** único fork além do nosso **com testes** (`test_extractors`,
`test_overview`, `test_smart_farming`, `test_village`) e com `AGENTS.md` de
convenções. O `warehouse_balancer.py` é uma terceira implementação de
balanceamento, mais pobre que a do LazyTurtle (sem leitura do servidor de "recursos
chegando") — não recomendo.

### 3.2 `felipewariat/kuzyn-plemiona`

95% é tradução polonesa sobre a base de 2024 (inclusive o
`input("Naciśnij dowolny klawisz...")` — o mesmo bug de captcha, traduzido). Código
novo:

- `Extractor.farm_assistant_targets` + `farm_assistant_pagination`: varre `am_farm`
  **seguindo a paginação** (`class="paged-nav-item"`) e monta
  `{id: {wall, links: {A, B, C}}}`.
- `AttackManager.attack_with_assistant`: filtra por `farm_min_wall` /
  `farm_max_wall`; no modo `AUTO` usa **A quando o muro passa de um limiar e B
  quando não**, caindo para o primeiro disponível.

→ Versão mais pobre do B4 (que usa `disabled` + `forecast` do próprio jogo).
**A paginação é a peça útil:** se o nosso leitor de `am_farm` não segue páginas,
ele só enxerga a primeira leva de alvos — outro funil silencioso, da família do
vigésimo quarto padrão.

### 3.3 `Trojanekkk/TWB` (branch `develop`)

- **Autenticação por senha** no dashboard: hook `before_request` com rotas isentas,
  `hmac.compare_digest` contra senha de `.env`, sessão Flask, e — detalhe bem
  feito — **503 + tela explicativa quando não há senha configurada**, em vez de
  abrir sozinho. Com `is_safe_redirect` para o `next`. ~40 linhas.
- **`webmanager/stats.py` (500 linhas)**: agrega relatórios em **taxa de
  preenchimento, % de perda, capacidade enviada × saque obtido, mediana**, com
  buckets de 24 h para gráfico. Tem a tabela `unit_loads` (spear 25, sword 15, axe
  10, light 80, heavy 50, knight 100…). É a versão persistida da análise que
  fizemos à mão no décimo primeiro padrão. **Mas** `_report_kind` deduz o tipo por
  presença de campo (`has_loot and not is_scout`) e o nosso `ReportReader` já faz
  filtro dinâmico — comparar antes de trocar.
- `/bot/status` explícito e `/bot/session` por POST (cookie entra pelo painel,
  nunca pelo console).
- ⚠️ Descartar: `DEBUG=True`, cache/runtime versionado, e **rotas GET que mutam
  estado** (`/bot/start`, `/bot/stop` são GET).

### 3.4 `KrzysztofKalisiak/TWB_plus` (branch `NoDriverLogging`)

Usa **`nodriver`** (sucessora do undetected-chromedriver) para abrir navegador
real, logar com usuário/senha, entrar no mundo, **extrair o cookie via CDP**
(`uc.cdp.network.get_cookies()`) e passar ao `WebWrapper` — eliminando a colagem
manual. Por cima, um **rotacionador**: roda ~70 ciclos (≈6 h, com `random.gauss` em
volta), encerra, refaz login, **rotaciona o cookie**, e segue para o próximo mundo.
Telegram no começo, no captcha e no fim de sessão.

**A ideia tem mérito** e conversa com um conselho do LazyTurtle: *"uma sessão
rodando 24 h seguidas é forte sinal de bot"*.

**Por que o código não entra:**

- Depende de `personal_config.py` com `SECRETS` (usuário, **senha**, tokens) — e o
  `test.py` do repo carrega credencial no fonte. Credencial de conta de jogo em
  texto plano num módulo importado no boot é risco que não compensa.
- `bypass_captcha()` procura literalmente `self.no_driver_page.find('???')`. É um
  stub.
- No `run()` passam `no_driver_page=None` para o `WebWrapper` — o caminho de bypass
  está **morto** no próprio branch.
- Mantém `input("Press any key...")` no captcha: continua precisando de humano, só
  avisa melhor.
- Preserva atributos de classe mutáveis e paths frágeis do upstream de 2024.

**Aproveitar:** o **conceito** de rotação de sessão com intervalo aleatorizado, e o
alerta "vá resolver o captcha" com instrução de acesso remoto. A implementação,
não.

---

## 4. Armadilhas no código deles — o que **não** copiar junto

1. 🚩 **`_Lock` é no-op no Windows.** `attack_scheduler.py::_Lock` faz
   `if fcntl is None: return self` — e `fcntl` **não existe no Windows**. Todo
   módulo deles construído sobre essa trava (`attack_scheduler`, `flags`,
   `accountmanager`, `noblebarb`, `playerfarm`, `snipe`) tem **zero exclusão mútua
   entre processos na nossa plataforma**. Rodamos Windows 10 e temos dois processos
   (bot + webmanager) escrevendo os mesmos arquivos. Qualquer transplante precisa
   reescrever a trava (`msvcrt.locking`, ou rename atômico com retry). O
   `os.replace()` atômico salva o leitor de ver meio arquivo, mas **não** salva do
   read-modify-write perdido.
2. 🚩 **`worldvillages.fetch()` usa `requests.get` cru**, sem os headers do
   `WebWrapper`. Para `map/village.txt` (público) é aceitável e proposital — mas é
   o **sétimo padrão**, e se o padrão for reaproveitado para tela autenticada a
   resposta muda de forma. Usar `cached(wrapper)` sempre que houver wrapper.
3. 🚩 **`flags.py` nunca rodou em conta viva.** O parser de `setFlagCounts` é
   palpite de formato, assumido no próprio arquivo (`_count()` admite que a forma
   "não está documentada em lugar nenhum e nunca foi vista nesta conta").
   Arquitetura sim, parser não.
4. 🚩 **Separador de milhar como elemento.** `23<span>.</span>000` → lê **23**.
   Caíram nisso três vezes (`minter._totals`, `minter._coin_costs`,
   `balancer.read_receiver`). Em pt-BR é o nosso formato padrão: qualquer parser de
   número nas telas de mercado/academia precisa **fatiar a célula antes de ler os
   dígitos**.
5. 🚩 **Valor de falha disfarçado de resposta válida.** Já temos o caso do
   `Extractor.attack_duration()` devolvendo 0; reencontrei a mesma classe no
   `parse_travel_seconds` (a versão anterior rejeitava toda página real e ninguém
   notou, porque o fallback "funcionava"). Ao consumir parser: perguntar **qual
   valor ele devolve ao falhar** e se é distinguível de um resultado legítimo.
6. 🚩 **Restaurar a tela do jogador** depois de mudar filtro/modo para ler (ver
   B5). Auditar o nosso.
7. 🚩 **Fallback de regex frouxo** (megaindex `get_farm_bag_state`) — §3.1(b).

---

## 5. Os bugs deles como checklist do nosso código

O `CODE_REVIEW.md` do LazyTurtle (283 linhas, 11 bugs com status re-checado) é, na
prática, **uma segunda auditoria da mesma base que a nossa §5 auditou**.

| Bug deles | Nosso estado (verificado 2026-09-20) |
|---|---|
| **B1** `get_api_data`/`post_api_data`/`get_api_action` fazem `res.status_code` com `res` podendo ser `None` | ✅ nosso segundo padrão / Lote 4-5 |
| **B2** `can_recruit` deleta de dict durante iteração | ✅ provavelmente coberto |
| **B3** paz forçada escreve variável local em vez de atributo | ✅ nosso terceiro padrão (P1-17) |
| **B4** crash antes de `self.wrapper` existir mata os 3 retries | ⚠️ **conferir** — família do "logger que ainda não existe no caminho de erro" |
| **B5** `is_active_hours` com `range()` exclusivo e sem wrap | ✅ **estamos à frente**: `_hour_in_window` + `is_village_active_hours` por aldeia |
| **B6** fuso do host × fuso do servidor | ⚠️ **aberto para nós** — é o A4 |
| **B7** comando preso em `sending` após crash no pré-estágio | n/a |
| **B8** `report["extra"]["units_sent"]` sem `.get()` | ⚠️ **conferir** no nosso `manager.py`/`farm_manager` |
| **B9** overview parseia zero aldeias → **todas** marcadas "não disponível" e puladas, *parecendo saudável* | ⚠️ **conferir**: temos `tests/test_village_purge_guard.py` e `purge_refusal_reason`, mas distinguimos "logado, parseou zero" de "genuinamente zero"? |
| **B10** user-agent lido de `server.user_agent` em vez de `bot.user_agent` | ⚠️ conferir no webmanager |
| **B11** Flask DEBUG + bind 0.0.0.0 = RCE | ✅ Lote 5 |

**Quatro itens viram tarefa de verificação nossa** (B4, B8, B9, B10), e custam um
`grep` cada.

---

## 6. Backlog priorizado proposto

Ordenado por (valor × certeza) ÷ risco. Nenhum está provado no br143.

| # | Item | De onde | Esforço | Medir antes |
|---|---|---|---|---|
| 1 | Captcha auto-resume + sessão por arquivo (tirar os dois `input()`) | LT `core/request.py` | S | nada, é lógica local |
| 2 | `InstanceLock` por endpoint | LT `core/instance_lock.py` | S | nada |
| 3 | Notification: lazy config + try/except + categorias | LT `core/notification.py` | S | nada |
| 4 | `map/village.txt` + `player.txt` do mundo | LT `worldvillages.py` | S | `GET br143…/map/village.txt` 200 e > 100 linhas |
| 5 | Revisar o gate global de coleta (não virar broadcast) | LT `village.py:900` | S | revisão do que está sendo escrito agora |
| 6 | Verificar os 4 bugs da §5 (B4, B8, B9, B10) | LT `CODE_REVIEW.md` | S | leitura |
| 7 | `ServerClock` + `GameClock` | LT `core/server_clock.py` | M | ler `serverTime`/`serverDate` do br143, conferir formato de data |
| 8 | Auto-desbloqueio de coleta por nível de EP + saque previsto logado | LT `troopmanager.py:486`, `:13` | M | validar a fórmula de duração contra **uma** corrida real (o mundo deles é speed 2.0 — 17º padrão) |
| 9 | Consolidação noturna da coleta | LT `village.py:800` | M | depende de 8 |
| 10 | Bandeiras: conferir se a nossa política conta **oferta** | LT `flags.py` | M | reler a nossa política antes de fechar a validação da §6.3 |
| 11 | `mode=call`: ler do servidor o que já está a caminho | LT `balancer.py:355` | M | fixture verbatim do br143 |
| 12 | Velocidade de mercador medida na confirmação | LT `balancer.py:683` | M | mesma fixture |
| 13 | Ícones A/B/C do `am_farm` + `data-units-forecast` | LT `attack.py:152` | M | br143 renderiza o atributo? |
| 14 | Paginação do `am_farm` | kuzyn | S | o nosso leitor já segue páginas? |
| 15 | Existe limite de saque no br143? | megaindex | S | `get_config` + `/page/settings` |
| 16 | Smart farming (pacote por capacidade equivalente) | megaindex | M | interação com `min_attack_population` |
| 17 | Notas privadas de aldeia (`village_note_edit`) | LT `villagenotes.py` | S | fixture do `info_village` |
| 18 | Métricas 24h/7d de farm no painel | trojanek `stats.py` | M | comparar com o nosso `ReportReader` |
| 19 | Senha no painel | trojanek | S | só se sair do localhost |
| 20 | Extensão de restauração de sessão | LT `browser-extension/` | L | frontend |

---

## 7. Onde isso entra nos nossos documentos

- **`backend.md` §7.4** (backlog `FND`/`TIM`/`DEF`/`ECO`): 1–3 são `FND`; 7 é
  `TIM`; 4, 11 e 12 são `ECO`/conquista.
- **§8.5 (coleta)**: 5, 8, 9 e 14 — e o **5 é pré-requisito do `P-COL-01`**.
- **§8.6 (`P-CONQ-RAIO`)**: o item 4 é a resposta ao segundo funil. Vale nota lá
  dizendo que a fonte existe e é pública.
- **§6.3 (bandeiras)**: item 10, **antes** de continuar a validação 1-de-18.
- **§4.2 (mecânicas do br143)**: item 15 e a fórmula de duração de coleta do 8.
- **`frontend.md`**: 18, 19, 20 + o design-system deles (também usam Claude Design,
  com `/design-sync` e marcadores `@dsCard`; paleta forge/iron/parchment e tokens em
  `design-system/styles.css`, espelhando `shell.html`).

---

## 8. Diferenças em relação à §7.9 (escrita pelo Codex)

Li a §7.9 do `backend.md` ao procurar onde encaixar as recomendações — registro
isso por transparência, já que influenciou o que eu sabia ao escrever.

**Concordo:** o diagnóstico do `deepcopy` está certo e bem fundamentado; "o número
de módulos do fork não é evidência de qualidade" está certo; rejeitar o `TWB_plus`
por segurança está certo.

**Acrescento ou divirjo:**

1. **`TWB_plus` no `master` é idêntico ao upstream.** A §7.9 diz que "o `master`
   default para em 2024", o que é verdade mas subestima: não é fork desatualizado,
   é espelho sem alterações.
2. **O `map/village.txt` não está na §7.9.** Na minha leitura é o item de maior
   valor estratégico do lote, porque responde direto ao funil que nós mesmos
   documentamos na §8.6, e custa um arquivo de 130 linhas.
3. **A `_Lock` no-op no Windows não está registrada** — e a §7.9 lista "passe
   account-wide de bandeiras" e "scheduler" como próximos candidatos, que são
   justamente os dois que dependem dela.
4. **"A nossa política de bandeira conta a oferta?"** merece ser a próxima pergunta
   da §6.3 e não aparece nos próximos candidatos.
5. **A armadilha do separador de milhar em pt-BR** vale registro próprio: os três
   lugares onde eles tropeçaram (academia, totais de mercado, custo de moeda) são
   telas que nós também lemos.
6. Sobre **"0 testes"** no LazyTurtle: confirmo (não existe `tests/`). Mas a
   leitura que eu faria é mais fina — vários módulos carregam, no docstring, a
   **medição que originou a correção**, com data, mundo e número (a corrida de
   coleta de 16h09, os dois snipes do `k`, os 767 MB do `py-spy`, o 4,01 min/campo
   contra o 1,0 banqueado). Não substitui teste, mas é evidência **de campo**, que
   nenhum teste unitário nosso produz.

---

## 9. Onde estão os clones

`%TEMP%\twb_study\` — `lazyturtle`, `kalisiak` (+ branch local `nodriver`),
`trojanek` (+ branch local `dev`), `kuzyn`, `megaindex`, `base` (upstream).
São descartáveis; recriar é `git clone --depth 50` de cada um.
