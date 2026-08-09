# Auditoria completa de código — 2026-08-08

**Escopo:** leitura integral dos 34 arquivos `.py` do repositório (12.403 linhas),
mais `config.json`, `config.example.json`, `requirements.txt`, `installer.bat`,
`start.bat`, `.gitignore`, `CHANGELOG.md` e inspeção do estado real dos caches
runtime (`cache/managed`, `cache/conquest`, `cache/pvp_conquest`,
`cache/hunter`, `cache/zones.json`).

**Estado do bot no momento da auditoria:** parado (processo encerrado pelo
usuário). Nenhuma alteração foi feita no código — este documento é só
diagnóstico.

**Método:**
- Leitura linha a linha de todos os módulos (`twb.py`, `core/`, `game/`,
  `pages/`, `webmanager/`, `manager.py`).
- Análise estática via AST para detectar atributos de classe mutáveis
  compartilhados entre instâncias (o padrão de bug mais recorrente aqui).
- `grep` dirigido para confirmar código morto e chaves de config órfãs.
- Cruzamento com os caches reais para separar "bug teórico" de "bug com
  evidência em campo".

**Não coberto nesta passada:**
- Os 18 arquivos `.html` em `webmanager/templates/` (só foram verificados os
  pontos onde o Python injeta dados nos templates).
- Conteúdo integral de `docs/backlog.md` (886 linhas) e `docs/features_log.md`
  — lidos apenas o suficiente para cruzar com o código.

**Legenda de confiança:**
- 🟢 **Confirmado** — verificado por execução, AST ou evidência em cache.
- 🟡 **Alta confiança** — inferido de leitura de código, caminho claro e
  determinístico, mas não executado.
- ⚪ **A verificar** — depende de comportamento do servidor ou de dados que não
  temos offline.

---

## Índice por prioridade

> **Estado em 2026-08-09:** todos os **19 itens P0/P1 estão corrigidos**
> (Lotes 1 a 5). Dos 20 itens P2, **17 corrigidos** e **3 abertos**: P2-22,
> P2-29 e P2-35. A coluna "Estado" abaixo é a fonte da verdade; o porquê de
> cada pendência está nas notas de implementação do Lote 5, no fim do
> documento.

| ID | Título | Arquivo principal | Confiança | Estado |
|----|--------|-------------------|-----------|--------|
| **P0-1** | `TWB.villages` de classe → aldeias duplicadas após crash | `twb.py` | 🟢 | ✅ Lote 1 |
| **P0-2** | `ResourceManager.actual`/`requested` compartilhados entre aldeias | `game/resources.py` | 🟢 | ✅ Lote 1 |
| **P0-3** | Handler de crash do `main()` pode crashar | `twb.py` | 🟡 | ✅ `ebac9d4` |
| **P0-4** | Webmanager **apaga** cache do bot ao ler JSON parcial | `webmanager/utils.py` | 🟢 | ✅ Lote 2 |
| **P0-5** | `Simulator.simulate()` crasha quando o atacante perde | `game/simulator.py` | 🟢 | ✅ Lote 3 |
| **P1-6** | Suporte entre aldeias é código morto (condição invertida) | `game/defence_manager.py` | 🟢 | ✅ Lote 3 |
| **P1-7** | `forced_peace_today` nunca vira `True` (variável local) | `game/village.py` | 🟢 | ✅ Lote 3 (+ Lote 5: o método era órfão) |
| **P1-8** | `farm_score` nunca é calculado — Feature 5 inerte | `manager.py` / `game/attack.py` | 🟢 | ✅ Lote 5 |
| **P1-9** | Caminho de "noble extra" da conquista é inalcançável | `game/attack.py` | 🟡 | ✅ Lote 5 |
| **P1-10** | `can_attack()`: condição de relatório antigo invertida | `game/attack.py` | 🟡 | ✅ Lote 3 |
| **P1-11** | `recruit()` crasha quando a requisição falha | `game/troopmanager.py` | 🟡 | ✅ Lote 4 |
| **P1-12** | `can_recruit()` muta dict durante iteração | `game/resources.py` | 🟡 | ✅ Lote 4 |
| **P1-13** | `SnobManager.attempt_recruit` crasha com regex sem match | `game/snobber.py` | 🟡 | ✅ Lote 4 |
| **P1-14** | Strings/regex em holandês num servidor pt-BR | `game/resources.py` | 🟢 | ✅ Lote 5 (item confirmado; os ⚪ seguem sem validação) |
| **P1-15** | `Map.villages`/`map_pos` compartilhados + sem guarda de `None` | `game/map.py` | 🟢 | ✅ Lote 1 |
| **P1-16** | `send_resources()` sempre retorna `True` | `game/resources.py` | 🟢 | ✅ Lote 5 |
| **P1-17** | Hunter e PvP dependem de `village.attack`, criado só no farm | `game/village.py` | 🟢 | ✅ Lote 5 |
| **P1-18** | Webmanager Flask com `DEBUG=True` + config via GET sem CSRF | `webmanager/server.py` | 🟢 | ✅ Lote 5 |
| **P1-19** | `check_update()` fora do try → falha de rede impede o boot | `twb.py` | 🟢 | ✅ Lote 5 |
| **P2-20..39** | Robustez / correção lógica (20 itens) | vários | — | 17 ✅ / **3 abertos** (P2-22, P2-29, P2-35) |
| **P3** | Dívida técnica, código morto, documentação | vários | — | mutáveis de classe ✅ Lote 5; resto aberto |

---

# P0 — Crítico

Crash do processo, ação duplicada dentro do jogo, ou perda de dados.

---

## P0-1 — `TWB.villages` é atributo de classe: após qualquer crash, cada aldeia é processada em dobro

> ✅ **CORRIGIDO** no Lote 1 (`78910f5`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado por AST.

**Local:** [`twb.py:120`](../twb.py), [`twb.py:448`](../twb.py), [`twb.py:507`](../twb.py), [`twb.py:714`](../twb.py)

**O que acontece:**

```python
class TWB:
    villages = []          # linha 120 — atributo de CLASSE
    ...
    for vid in config["villages"]:
        v = Village(...)
        self.villages.append(copy.deepcopy(v))   # linha 448 — mutação in-place
```

`self.villages` nunca é reatribuído (`self.villages = []`) em lugar nenhum, só
mutado via `.append()`. Portanto o `[]` da linha 120 é um único objeto
compartilhado por toda instância de `TWB`.

Em `main()`:

```python
for _ in range(3):
    t = TWB()
    try:
        t.start()
    except Exception as e:
        ...
```

A segunda instância de `TWB` **herda a lista já populada da primeira** e
acrescenta as mesmas aldeias de novo.

**Impacto:** com 4 aldeias, após o primeiro crash o loop passa a iterar 8
objetos `Village` — cada aldeia real construindo, recrutando, farmando e
enviando ataques **duas vezes por ciclo**. Após o segundo crash, três vezes.
Esse é exatamente o padrão de atividade anômala que gera detecção/ban.

O laço de sincronização mid-run (`existing_vids`, linha 504) usa um `set` de
`village_id`, então ele *não* duplica — mas também não deduplica o que já foi
duplicado pela retomada.

**Correção sugerida:** mover para `__init__`:
```python
def __init__(self):
    self.villages = []
    self.found_villages = []
```
(`found_villages` já é reatribuído em `get_overview`, mas por consistência.)

**Como validar:** rodar o bot, forçar uma exceção qualquer no primeiro ciclo,
e conferir `len(t.villages)` na segunda tentativa — ou simplesmente observar
logs de "Starting run for village X" duplicados por ciclo após um crash.

---

## P0-2 — `ResourceManager.actual` e `requested` são compartilhados por TODAS as aldeias

> ✅ **CORRIGIDO** no Lote 1 (`78910f5`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado por AST (únicos mutáveis da classe, nenhum
reatribuído via `self.X =` em nenhum ponto do arquivo).

**Local:** [`game/resources.py:95-97`](../game/resources.py)

**O que acontece:**

```python
class ResourceManager:
    actual = {}        # linha 95 — atributo de CLASSE
    requested = {}     # linha 97 — atributo de CLASSE

    def update(self, game_state):
        self.actual["wood"] = ...      # mutação in-place → escreve na classe
    def request(self, source, resource, amount):
        self.requested[source][resource] = amount   # idem
```

`game/village.py` cria um `ResourceManager` por aldeia
([`village.py:154`](../game/village.py)), mas os quatro escrevem no **mesmo
dicionário em memória**.

**Impacto — `actual`:** menos grave, porque `update()` sobrescreve
wood/stone/iron/pop no início do ciclo de cada aldeia e o processamento é
sequencial. Dentro do `run()` de uma aldeia, `actual` reflete aquela aldeia.

**Impacto — `requested`:** é aqui que dói. As chaves não são limpas de forma
uniforme entre aldeias:

- `can_recruit()` ([`resources.py:254`](../game/resources.py)) percorre
  `self.requested` para decidir se pode recrutar. Pedido pendente da aldeia A
  bloqueia o recrutamento da aldeia B (só quando `prioritize_building` está
  ligado, mas a lógica está errada de qualquer forma).
- `get_plenty_off()` ([`resources.py:274`](../game/resources.py)) e
  `manage_market()` decidem trades com base em necessidades que podem ser de
  outra aldeia.
- **`set_cache_vars()` grava `required_resources: self.resman.requested`**
  ([`village.py:1163`](../game/village.py)) — ou seja, os 4 arquivos
  `cache/managed/*.json` recebem o conteúdo do **mesmo objeto**.
- O `ResourceSharingManager` (Feature 9, **ligada** no config atual) lê
  exatamente esse campo em `_find_receivers()` e `_get_needed_resources()`
  ([`resource_sharing.py:192`](../game/resource_sharing.py)) para escolher
  quem recebe recursos. Ele está tomando decisões sobre dados cruzados.

Algumas chaves são zeradas por aldeia (`"building"` em
[`buildingmanager.py:87`](../game/buildingmanager.py), `"research"` em
[`troopmanager.py:130`](../game/troopmanager.py)) — o que na prática significa
que a aldeia B **apaga** o pedido de recursos da aldeia A, outro sintoma do
mesmo problema.

**Evidência em cache:** os 4 arquivos de `cache/managed/` têm
`required_resources: {}` idêntico. Não prova o compartilhamento por si só
(pode ser só "nada pendente"), mas é consistente com a Feature 9 nunca ter
encontrado uma receptora.

**Correção sugerida:**
```python
def __init__(self, wrapper=None, village_id=None):
    self.wrapper = wrapper
    self.village_id = village_id
    self.actual = {}
    self.requested = {}
```

⚠️ **Atenção ao corrigir:** isso vai *ativar* a Feature 9 (resource sharing)
de verdade pela primeira vez, já que `required_resources` passará a refletir
necessidades reais por aldeia. Vale revisar `resource_sharing.py` (ver P2-27)
antes ou junto.

---

## P0-3 — O handler de crash do `main()` pode ele mesmo crashar

> ✅ **CORRIGIDO** no avulso (`ebac9d4`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟡 Alta.

**Local:** [`twb.py:716-722`](../twb.py)

```python
try:
    t.start()
except Exception as e:
    t.wrapper.reporter.report(0, "TWB_EXCEPTION", str(e))   # t.wrapper pode ser None
```

`self.wrapper` só é criado em [`twb.py:429`](../twb.py), depois de
`self.config()` e `self.internet_online()`. Qualquer falha antes disso —
`config.json` corrompido (`InvalidJSONException`), `config.example.json`
ausente, exceção em `manual_config()` — deixa `t.wrapper = None`.

**Impacto:** `AttributeError: 'NoneType' object has no attribute 'reporter'`
levantado **dentro do except**, o que (a) derruba o loop de 3 tentativas
imediatamente e (b) mascara a exceção original, dificultando o diagnóstico.

**Correção sugerida:** guardar com `if t.wrapper and t.wrapper.reporter:` ou
envolver o próprio handler em try/except.

---

## P0-4 — O webmanager **apaga** arquivos de cache do bot ao ler um JSON parcial

> ✅ **CORRIGIDO** no Lote 2 (`36f4f8e`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado por leitura direta; a janela de corrida é real
porque a escrita não é atômica.

**Local:** [`webmanager/utils.py:23-29`](../webmanager/utils.py) +
[`core/filemanager.py:104-109`](../core/filemanager.py)

```python
with open(t_path, 'r') as f:
    try:
        output[...] = json.load(f)
    except Exception as e:
        print("Cache read error for %s: %s. Removing broken entry" % ...)
        f.close()
        os.remove(t_path)        # ← apaga o arquivo
```

E do lado do bot:

```python
@staticmethod
def save_json_file(data, path, **kwargs):
    with FileManager.__open_file(full_path, mode="w") as file:
        json.dump(data, file, indent=2, ...)     # trunca e escreve in-place
```

**Impacto:** `DataReader.cache_grab()` é chamado por `sync()`, que roda em
**toda requisição** do webmanager (`/`, `/config`, `/village`, `/map`,
`/villages`, `/empire`, `/hunter`, `/flags`, `/reports`, ...). Se uma dessas
leituras cair no meio de um `json.dump()` do bot, o webmanager lê JSON
truncado e **deleta o arquivo**. Alvos possíveis: `cache/managed/*.json`
(estado da aldeia), `cache/attacks/*.json` (histórico de farm),
`cache/villages/*.json`, `cache/reports/*.json`.

Perda de `cache/attacks/` significa perder `last_attack` → o bot re-ataca
alvos fora do cooldown. Perda de `cache/managed/` afeta zonas, evacuação
regional (Feature 12) e herança de config (Feature 6).

**Correção sugerida:** duas frentes, ambas simples:
1. No webmanager: trocar `os.remove(t_path)` por um log e `continue`. Deletar
   dado do bot a partir do processo de leitura nunca é seguro.
2. No `FileManager.save_json_file`: escrever em `path + ".tmp"` e fazer
   `os.replace(tmp, path)` — escrita atômica no mesmo filesystem.

---

## P0-5 — `Simulator.simulate()` crasha exatamente quando o ataque falharia

> ✅ **CORRIGIDO** no Lote 3 (`8c3b79b`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado por leitura; o tipo é inequívoco.

**Local:** [`game/simulator.py:375-387`](../game/simulator.py)

```python
if a < 1:                                        # atacante mais fraco
    c = math.sqrt(a) * a
    for unit in defenderUnits:
        defenderUnits[unit] -= defenderUnitsCopy[unit] * c * ratio
    for i in self.attack_units[attackType]:
        unit = self.attack_units[attackType][i]  # ← lista indexada por STRING
        attackerUnits[unit] = 0
else:
    c = math.sqrt(1 / a) / a
    for unit in defenderUnits:
        defenderUnits[unit] -= ratio * defenderUnitsCopy[unit]
    for i in self.attack_units[attackType]:
        unit = i                                 # ← ramo correto
        attackerUnits[unit] -= c * attackerUnits[unit]
```

`self.attack_units[attackType]` é uma **lista** de strings
([`simulator.py:234-238`](../game/simulator.py)). `for i in lista` itera
strings; `lista["spear"]` → `TypeError: list indices must be integers or
slices, not str`.

O ramo `a < 1` só é atingido quando a força de ataque é menor que a defesa —
ou seja, **quando o ataque perderia**.

**Impacto em cadeia:** em
[`pvp_conquest.py:279-290`](../game/pvp_conquest.py) a chamada está dentro de
um `try/except Exception` que apenas loga `"simulator error"` e faz `return`.
Consequência: um alvo PvP inviável **nunca é marcado como `failed`** — fica
preso em `pending_sim` e re-simula (e re-crasha) a cada ciclo, para sempre.
O usuário vê um alvo "Aguardando Simulação" eterno sem nenhuma indicação de
que a simulação está quebrada.

**Correção sugerida:** `unit = i` nos dois ramos (ou
`for unit in self.attack_units[attackType]:` direto).

**Observação adicional no mesmo arquivo:** ver P2-34 (`print()` de debug no
laço) e P3 (`update_with_real_levels` muta o dict de classe `pool`,
permanentemente, para todo o processo).

---

# P1 — Funcionalidade morta ou quebrada em silêncio

---

## P1-6 — Suporte entre aldeias é código morto: a condição está invertida

> ✅ **CORRIGIDO** no Lote 3 (`8c3b79b`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento. O suporte deixou de ser código morto, mas segue `false` em campo.

**Confiança:** 🟢 Confirmado (cruzamento entre dois arquivos).

**Local:** [`game/defence_manager.py:145-163`](../game/defence_manager.py) ×
[`game/village.py:210-222`](../game/village.py)

Em `DefenceManager.update()`:

```python
for vil in self.my_other_villages:
    if vil != self.village_id:
        continue                 # ← pula todas as OUTRAS aldeias
    if len(self.supported) >= self.support_max_villages:
        break
    if (not self.under_attack and self.my_other_villages[vil] and self.allow_support_send):
        ...
        if self.support_other(vil):
            self.supported.append(vil)
```

Mas `my_other_villages` é montado em `village.py::setup_defence_manager()`
**excluindo explicitamente a própria aldeia**:

```python
for cache_file in FileManager.list_directory("cache/managed", ends_with=".json"):
    cached_vid = cache_file.replace(".json", "")
    if cached_vid == self.village_id:
        continue                 # ← self nunca entra no dict
```

Portanto nenhuma chave do dict é igual a `self.village_id` → o `continue` da
primeira linha dispara em **toda** iteração → o corpo do laço nunca executa →
`support_other()` nunca é chamado.

**Nota sobre ordem de execução:** `twb.py:600-603` atribui
`village.def_man.my_other_villages = defense_states` (que *inclui* a própria
aldeia) no fim do ciclo — mas `setup_defence_manager()` sobrescreve esse valor
no início do `run()` da aldeia, antes de `def_man.update()`. Então a atribuição
do `twb.py` nunca chega a influenciar o laço.

**Impacto:** toda a mecânica de suporte mútuo (`support_others`,
`support_others_factor`, `request_support_on_attack`) está inerte desde
sempre. Hoje `support_others: false` nas 4 aldeias, então não há prejuízo
ativo — mas ligar a opção não faria nada.

Para contraste: `evacuate()`
([`defence_manager.py:207`](../game/defence_manager.py)) usa o padrão correto
(`if vid == self.village_id: continue`), e por isso a evacuação funciona.

**Correção sugerida:** inverter para `if vil == self.village_id: continue`.
Ao corrigir, revisar junto: (a) o `index >= 2` hardcoded na linha 158, que
duplica `support_max_villages`; (b) `support_max_villages` nunca é lido do
config (ver P3 — a chave `support_others_max_villages` existe no config e no
helpfile mas nada a consome); (c) o Bug 3 de `docs/bugs_flags.md`
(`supported` compartilhado entre aldeias), que vai passar a importar de fato
assim que o laço voltar a executar.

---

## P1-7 — `forced_peace_today` nunca vira `True` (variáveis locais em vez de `self.`)

> ✅ **CORRIGIDO** no Lote 3 (`8c3b79b`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado.

**Local:** [`game/village.py:471-481`](../game/village.py)

```python
self.forced_peace_today = False
self.forced_peace_today_start = None
for time_pairs in forced_peace_times:
    ...
    if start_dt.date() == datetime.today().date():
        forced_peace_today = True            # ← local, sem self.
        forced_peace_today_start = start_dt  # ← local, sem self.
```

**Impacto:** `self.forced_peace_today` permanece `False` sempre, então o bloco
de [`village.py:728-730`](../game/village.py) nunca roda, `attack.forced_peace_time`
fica `None`, e a proteção de
[`attack.py:407-411`](../game/attack.py) ("não enviar ataque que chegaria
depois do início da paz forçada") está desligada.

Sem impacto hoje (`forced_peace_times: []` no config), mas é uma armadilha
silenciosa para quando o usuário configurar um evento.

**Correção sugerida:** prefixar as duas atribuições com `self.`. Também vale
adicionar `break` ou revisar: hoje o laço continua depois de setar, e o último
par de datas do dia vence.

---

## P1-8 — `farm_score` nunca é calculado: a ordenação por eficiência da Feature 5 é inerte

> ✅ **CORRIGIDO** no Lote 5 (`d9d36e2`). Implementar a escrita revelou um
> segundo bug no lado da leitura (`score or default` tratava score 0 como
> "sem histórico") — ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado por `grep` exaustivo em todo o repositório.

**Ocorrências de `farm_score` no projeto inteiro:**

| Arquivo | Linha | Operação |
|---|---|---|
| `game/attack.py` | 244 | **lê** (`farm_scores.get(vid, {}).get("farm_score") or 9999`) |
| `game/attack.py` | 264 | **preserva** (`existing.get("farm_score", None)`) |
| `webmanager/utils.py` | 1091, 1825, 1835, 1840, 1851 | **lê** (exibição/ordenação) |

**Nenhuma escrita em lugar nenhum.** O comentário de
[`attack.py:254`](../game/attack.py) diz *"preserve score fields calculated by
farm_manager"*, mas [`manager.py`](../manager.py) só grava `attack_count`,
`low_profile`, `high_profile` e `safe` — nunca `farm_score`.

**Impacto:**
- Em `get_targets()`, `score` é sempre `9999` para todo alvo →
  `distance / max(score, 1)` = `distance / 9999` → o `sorted()` final é
  **ordenação por distância pura**. A "ordenação por eficiência de saque" da
  Feature 5 não existe na prática.
- A tela `/farmscores` classifica tudo como `status_key = "new"`
  ([`utils.py:1835`](../webmanager/utils.py)) permanentemente, e a coluna
  "Score" fica vazia.
- No mapa de calor do `/empire`, `farm_score` sempre `None`.

**Correção sugerida:** implementar o cálculo em
`VillageManager.farm_manager()`, onde os dados já estão à mão (o laço já
computa `loot` total e `len(num_attack)` por alvo). Algo como
`farm_score = total_loot / num_attacks`, gravado junto com `attack_count` no
mesmo `AttackCache.set_cache()` que já acontece na linha 76. Cuidado com a
semântica de ordenação: hoje o código assume "score maior = melhor"
(`distance / score`), enquanto `/farmscores` ordena por `-s`.

---

## P1-9 — O caminho de "noble extra" da conquista bárbara é inalcançável

> ✅ **CORRIGIDO** no Lote 5 (`42b2ef9`), exatamente como sugerido: o
> `_get_my_conquest()` foi movido para antes do guard de 4 nobles.

**Confiança:** 🟡 Alta.

**Local:** [`game/attack.py:511-536`](../game/attack.py)

```python
def run(self):
    ...
    available_nobles = int(self.troopmanager.troops.get("snob", 0))
    if available_nobles < self.TRAIN_SIZE:       # TRAIN_SIZE = 4
        self.logger.info("Conquest: %d/%d nobles available, waiting for full train", ...)
        self.troopmanager.conquest_reserve.pop("barbarian_conquest", None)
        return False                             # ← sai antes de checar conquista em andamento

    existing = self._get_my_conquest()
    if existing:
        return self._handle_existing(existing, cfg)
```

`_handle_existing()` existe justamente para o estado `extra_pending`: lealdade
não zerou, precisa de **1** noble adicional
([`attack.py:1053-1064`](../game/attack.py) checa `available_nobles < 1`).
Mas o guard acima exige **4** nobles antes de sequer chegar lá.

**Impacto:** logo depois de disparar um trem, a aldeia tem 0 nobles. A partir
daí toda chamada a `run()` sai no primeiro `return False`. A lógica de regen de
lealdade (`loyalty_regen_per_hour`), leitura de lealdade real via relatório
(`_get_real_loyalty`) e envio de noble extra só voltam a ser avaliadas quando
a aldeia acumular 4 nobles novos — o que pode levar dias. Nesse meio tempo a
lealdade do alvo regenera e o progresso se perde.

Como agravante, a linha 530 (`pop("barbarian_conquest")`) limpa a reserva de
tropas justamente nesse caminho.

**Correção sugerida:** mover o bloco `existing = self._get_my_conquest()` para
**antes** do guard de 4 nobles, já que `_handle_existing` tem seu próprio
requisito (1 noble).

**Evidência de contexto:** `cache/conquest/39292.json` e `44683.json` mostram
`hits_done: 4`, `loyalty_after_train: 0`, `status: "complete"` — os dois
trens completos funcionaram e as aldeias hoje são nossas. O caminho quebrado
é só o de trem incompleto / lealdade não zerada.

---

## P1-10 — `can_attack()`: condição de "relatório de scout antigo" invertida

> ✅ **CORRIGIDO** no Lote 3 (`8c3b79b`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟡 Alta (a mensagem de log contradiz a condição).

**Local:** [`game/attack.py:318-327`](../game/attack.py)

```python
if status == 0:
    if cache_entry["last_attack"] + self.farm_low_prio_wait * 2 > int(time.time()):
        self.logger.info(f"{vid}: Old scout report found (...), re-scouting")
        self.scout(vid)
        return False
    else:
        self.logger.info("%s: scout report noted enemy units, ignoring", vid)
        return False
```

`last_attack + 14400 > now` significa "o último ataque foi há **menos** de 4h"
= relatório **recente**. Mas o ramo diz "Old scout report found, re-scouting".

**Impacto:** o bot re-espia alvos cujo relatório é fresco (desperdiçando
espiões) e desiste permanentemente de alvos cujo relatório é velho — que são
justamente os que deveriam ser reavaliados. Alvos marcados como perigosos há
muito tempo nunca são reconsiderados.

**Correção sugerida:** trocar `>` por `<` (ou reescrever como
`now - last_attack > farm_low_prio_wait * 2`).

---

## P1-11 — `recruit()` crasha quando a requisição de recrutamento falha

> ✅ **CORRIGIDO** no Lote 4 (`ac67cc5`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento. Eram **três** crashes na mesma função, mais dois achados fora do diagnóstico.

**Confiança:** 🟡 Alta.

**Local:** [`game/troopmanager.py:669-700`](../game/troopmanager.py)

```python
result = self.wrapper.get_api_action(...)
if "game_data" in result:      # result pode ser None
```

`WebWrapper.get_api_action()` retorna `None` explicitamente quando a resposta
não é 200 ou quando `post_url` falhou
([`core/request.py:199-204`](../core/request.py)).
`"game_data" in None` → `TypeError: argument of type 'NoneType' is not
iterable`.

**Impacto:** timeout de rede, 502 do servidor ou sessão expirada durante um
recrutamento derruba o processo inteiro (a exceção sobe até o `try` de
`main()`). Como recrutamento roda para toda aldeia todo ciclo, é um dos
caminhos mais expostos.

**Correção sugerida:** `if result and "game_data" in result:` — e retornar
`False` no caso contrário. O restante do arquivo já adota esse padrão
(`update_totals`, `gather` checam `is None`), então é uma inconsistência
pontual.

---

## P1-12 — `can_recruit()` muta o dicionário durante a iteração

> ✅ **CORRIGIDO** no Lote 4 (`ac67cc5`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟡 Alta.

**Local:** [`game/resources.py:254-263`](../game/resources.py)

```python
if self.actual["pop"] == 0:
    self.logger.info("Can't recruit, no room for pops!")
    for x in self.requested:
        if "recruitment" in x:
            del self.requested[x]      # ← RuntimeError
    return False
```

**Impacto:** `RuntimeError: dictionary changed size during iteration` sempre
que a população estiver cheia (`pop == 0`) e houver ao menos um pedido de
recrutamento pendente. Cenário comum em aldeia madura com fazenda no limite.

Note que `village.py` faz a mesma limpeza corretamente em outro lugar, usando
`for x in list(self.resman.requested.keys())`
([`village.py:535`](../game/village.py)) — então o padrão certo já existe no
projeto.

**Correção sugerida:** `for x in list(self.requested.keys()):`

---

## P1-13 — `SnobManager.attempt_recruit` crasha quando o regex não casa

> ✅ **CORRIGIDO** no Lote 4 (`ac67cc5`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟡 Alta.

**Local:** [`game/snobber.py:66-104`](../game/snobber.py)

```python
result = self.wrapper.get_action(action="snob", village_id=self.village_id)
if '"id":"coin"' in result.text:        # ← (a) result pode ser None
    ...
can_recruit = re.search(r"(?s)</th><th>(\d+)</th></tr>\s*</table><br />", result.text)
if not can_recruit or int(can_recruit.group(1)) == 0:
    nres = self.need_reserve(result.text)
    if nres > 0:
        ...
        return False
self.is_incomplete = False
r_num = int(can_recruit.group(1))       # ← (b) can_recruit pode ser None aqui
```

Dois problemas:
- **(a)** `result.text` sem guarda de `None` → `AttributeError` em timeout.
- **(b)** se `can_recruit` for `None` **e** `need_reserve()` retornar `0`, o
  fluxo escapa do `if` e chega na linha 96 → `AttributeError: 'NoneType'
  object has no attribute 'group'`. Isso acontece sempre que o markup da tela
  de academia mudar (o mesmo tipo de quebra que já aconteceu com
  `gold_big.png` → `.webp`, documentado no próprio arquivo).

**Correção sugerida:** guarda de `None` no `result`, e `return False`
explícito quando `can_recruit is None`.

---

## P1-14 — Strings e regex em holandês rodando num servidor pt-BR

> ✅ **CORRIGIDO** no Lote 5 (`42b2ef9`) para o item confirmado (o regex de
> "recursos a caminho"). Os itens ⚪ da tabela abaixo (`"delete"`, `"attack"`,
> `"support"`) seguem sem validação em campo.

**Confiança:** 🟢 Confirmado (o servidor ativo é `br143.tribalwars.com.br`).

**Locais:**

| Local | String | Consequência |
|---|---|---|
| [`resources.py:430`](../game/resources.py) e [`491`](../game/resources.py) | `re.compile(r"Aankomend:\s...")` | **Quebrado.** Em pt-BR o texto é "Chegando:". A detecção de recursos a caminho nunca casa. |
| [`resources.py:381`](../game/resources.py) | `"delete": "Verwijderen"` | ⚪ A verificar — pode funcionar se o servidor só checa presença da chave. |
| [`attack.py:396`](../game/attack.py) | `"attack": "Aanvallen"` | ⚪ Funciona hoje (ataques saem), presença da chave basta. |
| [`defence_manager.py:405`](../game/defence_manager.py) | `"support": "Ondersteunen"` | ⚪ Idem, ainda não validado. O caminho deixou de ser morto no Lote 3 (P1-6), mas `support_others` segue `false` em campo, então nenhum envio real aconteceu até agora. |
| [`hunter.py:336`](../game/hunter.py) | `"attack": "Aanvallen"` | ⚪ Idem. |

**Impacto do item confirmado:** `manage_market()` e `check_other_offers()`
consultam `resource_incoming` para não pedir recurso que já está a caminho.
Como o regex nunca casa, `resource_incoming` fica sempre `{}` → o bot cria
ofertas duplicadas para recurso que já está vindo, gastando mercadores à toa.

**Correção sugerida:** trocar por um regex agnóstico de idioma (ancorar na
classe CSS `icon header (wood|stone|iron)` que já é usada logo em seguida) ou
tornar o termo configurável.

---

## P1-15 — `Map.villages`/`map_pos` compartilhados + `get_map()` sem guarda de `None`

> ✅ **CORRIGIDO** no Lote 1 (`78910f5`). O diagnóstico abaixo descreve o código *antes* da correção; ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado por AST.

**Local:** [`game/map.py:16-23`](../game/map.py), [`map.py:32-41`](../game/map.py)

**(a) Estado compartilhado:** `villages = {}` e `map_pos = {}` são atributos de
classe nunca reatribuídos — só mutados em `build_cache_entry()`
([`map.py:141-147`](../game/map.py)). Cada `Village` cria sua própria instância
de `Map`, mas todas escrevem no mesmo dicionário global.

`my_location` e `last_fetch` **são** reatribuídos (viram atributos de
instância), então a distância é calculada corretamente por aldeia e o filtro de
`farm_radius` mascara o problema na prática. Mas:
- `get_targets()` itera o mapa global acumulado de todas as regiões
  (desperdício de CPU e I/O crescente);
- `ConquestManager.find_target()` e o `map_pos` usado por Hunter/PvP também
  enxergam o conjunto global.

**(b) Sem guarda de `None`:**

```python
self.last_fetch = time.time()                      # ← setado ANTES do fetch
res = self.wrapper.get_action(village_id=..., action="map")
game_state = Extractor.game_state(res)             # res.text → AttributeError se None
```

Um timeout no fetch do mapa levanta `AttributeError` em
`Extractor.game_state()` ([`extractors.py:34`](../core/extractors.py) faz
`res.text` sem checar). E como `last_fetch` já foi atualizado, mesmo que a
exceção fosse tratada o mapa ficaria bloqueado por 8 horas.

**Correção sugerida:** `self.villages = {}` / `self.map_pos = {}` no
`__init__`; guarda `if res is None: return False` antes do `Extractor`; mover
`self.last_fetch = time.time()` para **depois** do fetch bem-sucedido.

---

## P1-16 — `send_resources()` sempre retorna `True`

> ✅ **CORRIGIDO** no Lote 5 (`d9d36e2`).

**Confiança:** 🟢 Confirmado.

**Local:** [`game/resources.py:586-596`](../game/resources.py)

```python
try:
    self.wrapper.post_url(post_url, data=payload)
    self.logger.info("send_resources: enviado %s → aldeia %s", ...)
    return True
except Exception as e:
    self.logger.warning(...)
    return False
```

`WebWrapper.post_url()` já captura todas as exceções internamente e retorna
`None` ([`core/request.py:101-103`](../core/request.py)). Logo o `except` aqui
é inalcançável e a resposta **nunca é inspecionada** (nem status code, nem
`error_box`).

**Impacto:** `ResourceSharingManager.run()` interpreta o retorno como sucesso,
loga "enviado", desconta do excedente local e grava
`success: true` no histórico da Feature 20
([`resource_sharing.py:115-132`](../game/resource_sharing.py)). A tela
`/resource_sharing` mostra transferências que podem nunca ter acontecido.

**Correção sugerida:** capturar o retorno de `post_url`, checar
`res is not None` e ausência de `<div class="error_box">` — mesmo padrão já
usado em `attack()` e `support()`.

---

## P1-17 — Hunter e PvP Conquest dependem de `village.attack`, que só é criado dentro do farm

> ✅ **CORRIGIDO** no Lote 5 (`42b2ef9`) via `Village.ensure_attack_manager()`.
> Exigiu tornar explícito o bloqueio de paz forçada, que antes vinha de o
> objeto não existir — ver as notas de implementação no fim do documento.

**Confiança:** 🟢 Confirmado.

**Local:** [`game/village.py:702-743`](../game/village.py) ×
[`game/hunter.py:368`](../game/hunter.py) ×
[`game/pvp_conquest.py:163`](../game/pvp_conquest.py)

`self.attack` (AttackManager) só é instanciado dentro de `run_farming()`, e
apenas se **todas** estas condições valerem:

```python
if not self.forced_peace and self.units.can_attack:      # (1)
    if self.area.villages:                               # (2)
        if not self.attack:
            self.attack = AttackManager(...)             # ← única criação
```

Mas quem consome:
- `Hunter._send_attack()`: `if not village.attack: logger.error(...); return False`
  — pelo menos falha explicitamente.
- `PvpConquestManager._step_scout()`: `village.attack.attack(...)` **sem
  guarda** → `AttributeError`, engolido pelo `except Exception` genérico de
  [`pvp_conquest.py:132`](../game/pvp_conquest.py) e logado como
  "error processing target".

**Impacto:** com `farms.farm: false`, durante paz forçada, ou antes do primeiro
fetch de mapa bem-sucedido, a conquista PvP e o Hunter param sem causa óbvia
no log. Acoplamento indevido: enviar um ataque agendado não deveria depender
de o farm estar ligado.

**Correção sugerida:** extrair a criação do `AttackManager` para o próprio
`run()` (ou um método `ensure_attack_manager()` chamado junto de
`ensure_map_loaded()`), independentemente da configuração de farm.

---

## P1-18 — Webmanager: Flask com `DEBUG=True` e alteração de config via GET sem CSRF

> ✅ **CORRIGIDO** no Lote 5 (`e13979d`): `DEBUG=False`, rotas de escrita em
> POST, guarda de mesma origem em `before_request` (cobre também os formulários
> já existentes) e `app.run()` sob `if __name__ == "__main__"`.

**Confiança:** 🟢 Confirmado.

**Locais:** [`webmanager/server.py:17`](../webmanager/server.py),
[`server.py:243-252`](../webmanager/server.py),
[`server.py:516-519`](../webmanager/server.py)

**(a)** `app.config["DEBUG"] = True` + `app.run()`: o Flask lê `config["DEBUG"]`
e ativa o debugger interativo do Werkzeug. Qualquer requisição que provoque
uma exceção expõe um console Python remoto → **execução de código arbitrário**
na máquina do usuário para quem alcançar a porta. Combinado com
`app.run(host="localhost", port=sys.argv[1])` quando um argumento é passado —
e o padrão do Flask é 127.0.0.1, mas basta alguém rodar com bind aberto.

**(b)** `/app/config/set` é um **GET** que grava em `config.json`, sem token
CSRF nem autenticação:

```python
@app.route('/app/config/set', methods=['GET'])
def config_set():
    DataReader.config_set(parameter=request.args.get("parameter"),
                          value=request.args.get("value", None))
```

Qualquer página aberta no navegador do usuário pode alterar a configuração do
bot com um simples `<img src="http://localhost:5000/app/config/set?parameter=bot.delay_factor&value=0">`.

**(c)** `app.run()` é chamado no nível de módulo, sem guarda
`if __name__ == "__main__":`. Hoje é inofensivo porque
`game/pvp_conquest.py` importa `webmanager.utils` (não `server`), mas qualquer
import futuro de `webmanager.server` sobe um servidor HTTP como efeito
colateral.

**Correção sugerida:** `DEBUG = False`; mover as rotas de escrita para `POST`;
envolver o `app.run()` no guard de `__main__`.

---

## P1-19 — `check_update()` roda fora do try/except: falha de rede impede o bot de iniciar

> ✅ **CORRIGIDO** no Lote 5 (`e13979d`): try/except, `timeout=10` e checagem
> de status code.

**Confiança:** 🟢 Confirmado.

**Local:** [`twb.py:709-724`](../twb.py) × [`core/updater.py:33-46`](../core/updater.py)

```python
def main():
    check_update()          # ← fora do try
    for _ in range(3):
        t = TWB()
        try:
            t.start()
        ...
```

E dentro de `check_update()`:

```python
get_remote_version = requests.get(
    "https://raw.githubusercontent.com/SaamCosta/TWB-ADC/master/config.example.json"
).json()
```

Sem timeout, sem try/except, sem checagem de status code.

**Impacto:** GitHub fora do ar, DNS falho, rate-limit (429 → `.json()`
levanta), ou proxy corporativo = o bot **não inicia**, com um traceback bruto,
antes mesmo do loop de retry. Ironicamente, o `internet_online()` que existe
logo depois foi feito exatamente para lidar com esse cenário.

**Correção sugerida:** envolver em try/except, adicionar `timeout=` e checar
`status_code == 200`. `bot.check_update` já é configurável (`true` hoje), então
desligar é um paliativo.

---

# P2 — Robustez / correção lógica

> **Estado (2026-08-09):** dos 20 itens, **17 corrigidos** — P2-20 no Lote 4,
> os demais no Lote 5 (`e13979d`, `ff1c035`, `42b2ef9`, `d9d36e2`). Seguem
> abertos **P2-22**, **P2-29** e **P2-35**; o porquê de cada um está nas notas
> de implementação do Lote 5, no fim do documento.

| ID | Problema | Local | Detalhe |
|----|----------|-------|---------|
| **P2-20** ✅ | ✅ **Corrigido no Lote 4** (`ac67cc5`) — sync de `defense_states` iterava **todas** as aldeias, incluindo as puladas | [`twb.py:600-603`](../twb.py) | Aldeia com `managed: false`, ou ausente de `found_villages`, nunca chega a `update_pre_run()` → `def_man` continua `None` → `AttributeError: 'NoneType' object has no attribute 'my_other_villages'`. Além disso `defense_states` é declarado fora do `while` e **nunca é limpo** entre ciclos, acumulando entradas de aldeias perdidas — o que também mantinha o `attention_lag` da Feature 23 permanentemente desligado. |
| **P2-21** ✅ | `.get("public", {}).get(...)` sem `or {}` | [`server.py:315`](../webmanager/server.py), [`413`](../webmanager/server.py), [`446`](../webmanager/server.py), [`utils.py:988`](../webmanager/utils.py) | `set_cache_vars` grava `"public": None` quando `self.area` é `None` ou a aldeia ainda não está em `cache/villages/` ([`village.py:1162`](../game/village.py)). `.get(k, {})` devolve `None` (a chave existe) → `AttributeError` nas rotas `/hunter`, `/reports`, `/pvp_conquest`, `/zones`. Outros 3 pontos do mesmo arquivo já usam `or {}` — inconsistência. **Latente:** hoje as 4 aldeias têm `public` como dict; dispara em aldeia recém-conquistada. |
| **P2-22** ⚠️ ABERTO | `_calculate_needed_escort` pode reservar o exército inteiro e **parar o farm indefinidamente** | [`attack.py:821-860`](../game/attack.py) | `needed_total = ceil((50 × 4) / 0.5) = 400`, dividido igualmente entre **todos** os tipos presentes, limitado ao que existe (`min(per_unit, current)`). Com 5 tipos → tenta reservar 80 de cada, mas o `min()` faz reservar 100% de qualquer tipo que tenha menos que isso. `AttackManager._get_farmable_troops()` subtrai a reserva → farm e gather param enquanto o escort não fecha, o que pode ser indefinido. |
| **P2-23** ✅ | `BuildingManager.waits` é lista de classe até o primeiro ciclo com fila vazia | [`buildingmanager.py:23`](../game/buildingmanager.py), [`101`](../game/buildingmanager.py) | `self.waits = []` só executa dentro de `if existing_queue == 0`. Antes disso, `put_wait()` faz `.append()` na lista **de classe** → a fila de construção de uma aldeia bloqueia `is_queued()` de outra. |
| **P2-24** ✅ | `self.levels[entry]` sem guarda → `KeyError` para prédio inexistente no mundo | [`buildingmanager.py:286`](../game/buildingmanager.py) | `if min_lvl <= self.levels[entry]` roda **antes** de `if entry not in self.costs`. Um template citando `watchtower`/`church` num mundo sem esses prédios derruba o builder. Mesmo risco em `has_enough` com `self.levels["storage"]` ([`linha 198`](../game/buildingmanager.py)) e `self.levels["farm"]` ([`linha 271`](../game/buildingmanager.py)). |
| **P2-25** ✅ | `entry["extra"]["units_sent"]` / `["defence_units"]` sem guarda | [`reports.py:69-88`](../game/reports.py) | `attack_report()` só popula `units_sent` se a tabela do atacante existir e casar o regex. `safe_to_engage()` acessa direto → `KeyError` em relatório parcial ou gravado por versão antiga. |
| **P2-26** ✅ | `reports[rep]["extra"]["units_losses"]` fora do `try` | [`manager.py:35-38`](../manager.py) | `units_losses` só é gravado quando `len(sent_units) == 2` ([`reports.py:217`](../game/reports.py)). O `try/except` do `farm_manager` cobre só o bloco de loot (linha 39). `KeyError` aqui derruba `farm_manager`, que é chamado direto no loop principal do `twb.py`. Também `data["low_profile"]` sem guarda na [`linha 104`](../manager.py) (a linha 55 checa `"low_profile" in data`, a 104 não). |
| **P2-27** ✅ | Prioridade `new_villages` do resource sharing é uma heurística sem sentido | [`resource_sharing.py:221-224`](../game/resource_sharing.py) | Comentário: *"recém-conquistadas têm last_run menor pois rodaram menos ciclos"*. Mas `last_run` é `int(time.time())` reescrito a **cada ciclo, para toda aldeia** ([`village.py:1171`](../game/village.py)). Ordenar por `last_run` ASC = "a que rodou há mais tempo neste ciclo", não "aldeia nova". Precisa de outro sinal (pontos, `first_seen`, nível do prédio principal). |
| **P2-28** ✅ | `is_active_hours` não trata virada de meia-noite | [`twb.py:362-364`](../twb.py) | `range(active_h[0], active_h[1])` — com `"22-6"` o range é vazio → bot sempre inativo, sem aviso. Mesmo problema em `is_village_active_hours` ([`linha 382`](../twb.py)). Para contraste, `WorldConfig.is_night_bonus_active` ([`world_config.py:149-154`](../core/world_config.py)) trata corretamente. |
| **P2-29** ⚠️ ABERTO | `estimate_moral` usa piso de 70%, o piso real do TW é 30% | [`world_config.py:175-186`](../core/world_config.py) | `floor = 100 - loss_max` = `100 - 30` = **70**. O docstring já admite ser aproximação não-oficial, mas a direção do erro é a perigosa: superestima moral → recomenda conquistas que falham. Só afeta com `pvp_conquest.dynamic_moral_night_bonus: true` (hoje `false`). |
| **P2-30** ✅ | `do_premium_stuff` usa `data` antes de checar se é `None` | [`resources.py:149-167`](../game/resources.py) | `data = Extractor.premium_data(...)` na linha 149, `PremiumExchange(stock=data["stock"], ...)` na 151, e só na **166** vem `if not data:`. `TypeError` antes da checagem. |
| **P2-31** ✅ | Parse do overview quebra a corrida inteira em formato inesperado | [`overview.py:282-293`](../pages/overview.py), [`95-103`](../pages/overview.py) | `_extract_name_cords_continent` retorna `None` implícito quando o regex falha → `name, coordinates, continent = None` → `TypeError: cannot unpack non-sequence NoneType`. `Storage.__init__` faz `resource_values[0]` depois de só **imprimir** o erro de formato → `IndexError` (não `ValueError`, que é o único capturado). `twb.get_overview` só captura `RuntimeError` → o bot cai. |
| **P2-32** ✅ | `BotManager.pid` não é persistido → risco de dois bots simultâneos | [`utils.py:328-364`](../webmanager/utils.py) | `pid` é atributo de classe em memória. Reiniciar o webmanager (ou o reloader do Flask em modo DEBUG, que roda **dois** processos) perde a referência → `is_running()` retorna `False` → `/bot/start` sobe um **segundo** `twb.py` em paralelo. Duas instâncias agindo na mesma conta = risco de ban. |
| **P2-33** ✅ | `cache/reports` cresce sem limite + custo O(farms × reports) por ciclo | [`manager.py:117-126`](../manager.py), [`pvp_conquest.py:533-549`](../game/pvp_conquest.py) | `clean_reports` nunca é passado como `True` por `twb.py` → a poda existe mas nunca roda (286 relatórios hoje). `farm_manager` cruza cada farm com cada relatório a cada ciclo. `PvpConquestManager._find_scout_report` relê **todos** os JSONs de relatório do disco, por alvo, **por aldeia** (ver P2-35), por ciclo. |
| **P2-34** ✅ | `print()` de debug dentro do laço principal do simulador | [`simulator.py:355`](../game/simulator.py) | `print(attackFood, attackFoodSum)` a cada iteração da batalha. Polui stdout e, por causa do `_TeeStream` de [`twb.py:42-62`](../twb.py), também `cache/logs/session_latest.log`. |
| **P2-35** ⚠️ ABERTO | `PvpConquestManager` é instanciado uma vez **por aldeia**, por ciclo | [`village.py:654-690`](../game/village.py) | `run_pvp_conquest()` roda dentro de `Village.run()`, então com 4 aldeias a máquina de estados executa 4× por ciclo, cada vez varrendo `cache/pvp_conquest/` inteiro e, por alvo, `cache/reports/` inteiro. É idempotente (o status é relido do disco), mas é 4× o I/O necessário. |
| **P2-36** ✅ | `nearest_send_time` pode zerar o sleep entre ciclos | [`twb.py:655-664`](../twb.py) | `sleep = max(0, time_to_window)` — se o `send_time` já passou, `sleep = 0` e o bot emenda ciclos completos sem pausa, martelando o servidor. |
| **P2-37** ✅ | `scout()` retorna `None` em caso de sucesso, quebrando o guard do chamador | [`attack.py:269-295`](../game/attack.py) | `scout()` chama `self.attacked(...)` mas não retorna nada. Em `can_attack`: `if self.scout(vid): return False` nunca é verdadeiro → o guard "atacado há mais de 12h, espiar antes" envia o scout **e** segue para enviar o farm no mesmo ciclo. |
| **P2-38** ✅ | `attack()` faz o GET da praça antes de validar `map_pos` | [`attack.py:378-393`](../game/attack.py) | `if vid not in self.map.map_pos: return False` vem **depois** do `pre_attack = self.wrapper.get_url(url)`. Requisição HTTP (com o sleep de delay) desperdiçada. Mesmo padrão em [`defence_manager.py:387-402`](../game/defence_manager.py). |
| **P2-39** ✅ | `evacuate()` escolhe destino arbitrário | [`defence_manager.py:207-217`](../game/defence_manager.py) | Envia para a **primeira** aldeia do dict que não esteja sob ataque — não a mais próxima, não a mais segura. Com `my_other_villages` vindo de `os.listdir`, a ordem é de sistema de arquivos. Tropas frágeis podem viajar para o outro lado do mapa. |

---

# P3 — Dívida técnica, código morto, documentação

## Config declarado mas nunca lido

Todos têm entrada em [`webmanager/helpfile.py`](../webmanager/helpfile.py)
descrevendo comportamento que **não existe no código**:

| Chave | Onde é documentada | Situação |
|---|---|---|
| ~~`village.support_others_max_villages`~~ ✅ | `config.example.json:97`, `helpfile.py:107` | ✅ **Resolvido no Lote 3** (`8c3b79b`): passou a ser lido em `setup_defence_manager()` para `DefenceManager.support_max_villages`, e o `index >= 2` duplicado foi removido. |
| `village.scout_first` | `config.example.json:82`, `helpfile.py:96` | Nenhuma leitura em lugar nenhum. |
| `farms.find_player_owned` | `config.example.json:122`, `helpfile.py:45` | Nenhuma leitura. |
| `conquest.target` | `config.example.json:102`, `helpfile.py:67` | Nenhuma leitura (o único modo é bárbaro, hardcoded). |

## Config lido mas não declarado

- **`village.conquest_enabled`** — lido em
  [`village.py:635`](../game/village.py), documentado em
  [`helpfile.py:109`](../webmanager/helpfile.py), mas **ausente** de
  `config.example.json` e de `village_template`. Viola a regra do próprio
  `CLAUDE.md` ("ao adicionar config nova, atualizar `config.example.json` **e**
  `webmanager/helpfile.py` no mesmo commit").
  ⚠️ Verificado: hoje é inofensivo — a chave ausente cai no default `True` do
  `.get("conquest_enabled", True)`, então a conquista **está** ativa nas 4
  aldeias. Mas se alguém adicionar a chave com valor `null` (como o
  `village_template` faz com `profile`/`building`/`active_hours`), `.get()`
  devolve `None` → falsy → conquista silenciosamente desligada.

## Código morto

| Item | Local | Observação |
|---|---|---|
| `Extractor.get_daily_reward` | [`extractors.py:308-320`](../core/extractors.py) | Nunca chamado. E crasharia se fosse: `json.loads(get_daily.group(1))` sem checar se o `re.search` casou. |
| `SimCache.cache_customize` | [`simulator.py:424-430`](../game/simulator.py) | `for unit in ...: return` — não faz nada. |
| `SnobManager.level_system` | [`snobber.py:25-30`](../game/snobber.py) | Retorna `0`; o docstring admite ser inútil. |
| `AttackManager._unknown_ignored` | [`attack.py:42`](../game/attack.py) | Lido na [`linha 222`](../game/attack.py), nunca populado. |
| `DefenceManager.attacks` | [`defence_manager.py:33`](../game/defence_manager.py) | Nunca usado. |
| `TroopManager.queue` / `_waits` | [`troopmanager.py:28`](../game/troopmanager.py), [`43`](../game/troopmanager.py) | Nunca usados. |
| `BuildingManager.waits_building` | [`buildingmanager.py:25`](../game/buildingmanager.py) | Só zerado, nunca lido. |
| `RemoteReporter.report`/`add_data`/`get_config` | [`reporter.py:16-42`](../core/reporter.py) | Stubs que retornam `None` (usados como no-op quando o connection string não casa nenhum esquema — intencional, mas confuso). |
| Rota `/app/js` | [`server.py:239-241`](../webmanager/server.py) | Serve de `webmanager/public/js.v2.js`; o diretório `public/` **não existe** no repositório. Nenhum template referencia a rota. |
| `reserve_resources`: `create_amount` | [`troopmanager.py:707`](../game/troopmanager.py) | Calculado e nunca usado. |
| `get_next_building_action`: `index -= 1` | [`buildingmanager.py:333`](../game/buildingmanager.py) | Decremento seguido de `return True` — sem efeito. |

## Bugs conhecidos ainda abertos

- **`core/twstats.py::buildings_to_farm_pop`** — `self.max_levels[b][buildings[str(b)]]`
  indexa um `int` como dict ([`twstats.py:44`](../core/twstats.py)). Já
  registrado em `CLAUDE.md`. Também: `get_building_data` grava com
  `open(..., 'w')` sem `encoding`.
- **`DefenceManager.supported` compartilhado entre aldeias** — Bug 3 de
  [`docs/bugs_flags.md`](bugs_flags.md), confirmado nesta auditoria por AST.
  Vira relevante assim que P1-6 for corrigido.

## Infra / estilo

| Item | Local | Detalhe |
|---|---|---|
| `FileManager` faz double-join de caminho | [`filemanager.py:62-68`](../core/filemanager.py) e similares | `read_file` monta `os.path.join(root, path)` e passa para `__open_file`, que **junta de novo**. Funciona por acidente: o primeiro join produz caminho absoluto, e `os.path.join(a, abs)` devolve `abs`. Frágil. |
| Nenhum `open()` do `FileManager` usa `encoding=` | [`filemanager.py:55`](../core/filemanager.py) | No Windows o default é cp1252. JSON escapa não-ASCII por padrão (`ensure_ascii=True`), então os caches sobrevivem — mas `read_file` (usado por `TemplateManager.get_template`) quebraria com acento num template. |
| `AttackManager.ignored` é lista de classe | [`attack.py:34`](../game/attack.py) | Compartilhada entre aldeias. Só afeta log e a contagem de "Ignored targets", mas gera mensagens cruzadas ("Removed X from farm ignore list") entre aldeias. |
| `manage_flags` sorteia o divisor a cada chamada | [`defence_manager.py:291`](../game/defence_manager.py) | `self.runs % random.randint(3, 8) != 0` — cadência caótica, não periódica. |
| Recursão sem guarda de profundidade | [`troopmanager.py:604`](../game/troopmanager.py), [`snobber.py:91`](../game/snobber.py), [`defence_manager.py:384`](../game/defence_manager.py), [`buildingmanager.py:79`](../game/buildingmanager.py), [`village.py:341`](../game/village.py) | Todas são limitadas na prática por recursos/estado do servidor, mas nenhuma tem contador. `village.py:341` (`run_quest_actions` → `self.run()`) é a mais arriscada: re-executa o ciclo **inteiro** da aldeia. |
| `WorldSettings` com defaults inválidos | [`overview.py:200-203`](../pages/overview.py) | `flags: bool = Optional[bool]` — o default é o objeto `typing.Optional[bool]`, não `None`. Sem impacto (sempre sobrescrito por `parse_header_info`), mas errado. |
| `send_farm` loga sucesso antes de saber o resultado | [`attack.py:130-138`](../game/attack.py) | `logger.info("Attacking ...")` e `reporter.report(...)` executam **antes** do `if attack_result:`. Logs e relatórios contam ataques que o servidor recusou. |
| `manage_market` loga valores já reatribuídos | [`resources.py:457-461`](../game/resources.py) | `how_many = self.max_trade_amount` e só então loga `"Lowering trade amount of %d to %d", how_many, self.max_trade_amount` — os dois iguais. |
| Imports dentro de funções | [`village.py:1027`](../game/village.py), [`resources.py:570`](../game/resources.py), [`resource_sharing.py:293`](../game/resource_sharing.py), [`utils.py:357`](../webmanager/utils.py) | `collections` e `re` já estão no topo dos respectivos módulos. |
| `CHANGELOG.md` parado na versão 1.6 | [`CHANGELOG.md`](../CHANGELOG.md) | `build.version` é 2.8 e o fork tem as Features 4–24. |
| `ConquestCache` polui os arquivos com `target_id` | [`attack.py:1099`](../game/attack.py) | `_get_my_conquest()` injeta `data["target_id"]` no dict lido, e `_handle_existing` grava `{**conquest_data, ...}` de volta — o campo redundante aparece no disco. Confirmado em `cache/conquest/39292.json`. |
| `ZoneManager` descarta aldeia com `x` ou `y` = 0 | [`zone_manager.py:172`](../game/zone_manager.py) | `if data and data.get("x") and data.get("y")` — coordenada 0 é falsy. Irrealista no TW (coords ~400-600), mas o mesmo padrão aparece em [`village.py:1008`](../game/village.py) e [`attack.py:669`](../game/attack.py). |

---

# Evidência coletada dos caches (2026-08-08 02:50)

Estado real no momento da auditoria, útil como baseline:

```
cache/managed:      4 aldeias  (38409, 39292, 41123, 44683)
cache/villages:   342 arquivos
cache/reports:    286 arquivos   ← nunca podado (P2-33)
cache/attacks:     26 arquivos
cache/conquest:     2 arquivos   (39292, 44683 — ambos "complete")
cache/pvp_conquest: 1 arquivo    (38409 — "complete")
```

**Confirmações extraídas:**

1. **Conquista bárbara funciona no caminho feliz.** `39292.json` e
   `44683.json` mostram `hits_done: 4`, `hits_needed: 4`,
   `loyalty_after_train: 0`, `status: "complete"` — e as duas aldeias hoje
   constam em `config.json["villages"]`. Só o caminho de trem incompleto está
   quebrado (P1-9).

2. **O double-booking de tropas do PvP deixou rastro.** Em
   `cache/hunter/schedules.json`:
   - `38409_..._clear` → `atk statuses: ['failed']`
   - `38409_..._nobles` → `atk statuses: ['sent', 'sent', 'sent', 'sent']`

   Exatamente o sintoma descrito no comentário de
   [`pvp_conquest.py:385-403`](../game/pvp_conquest.py) (clear e escort
   reivindicando 0.8 + 0.5 = 130% das mesmas tropas). A correção já está no
   código, mas **ainda não foi validada em campo** — a próxima conquista PvP
   é o teste.

3. **`required_resources` idêntico ({}) nas 4 aldeias** — consistente com
   P0-2 e com a Feature 9 nunca ter encontrado uma receptora.

4. **`zones.json`**: as 4 aldeias caem em `zone_1` (raio 10). O
   `cache/managed/39292.json` mostra `zone: null` porque `set_cache_vars` lê o
   `zones.json` do ciclo **anterior** — lag de 1 ciclo, comportamento
   documentado e aceito.

5. **`delay_factor: 3`** no config atual → cada requisição HTTP dorme
   `randint(9, 21)` segundos ([`request.py:66`](../core/request.py)). Não é
   bug, mas explica ciclos longos e amplifica o custo dos itens de
   requisição desperdiçada (P2-38).

---

# Ordem de correção sugerida

Critério: impacto × esforço. Os quatro primeiros são todos correções de
poucas linhas com alto retorno.

> **Progresso (2026-08-08):** Lotes 1 a 4 implementados e pushados. Só o Lote 5
> segue aberto. Ver as notas de implementação no fim deste documento — o Lote 4
> rendeu quatro crashes além dos diagnosticados.

### Lote 1 — estado compartilhado (risco de ban / dados cruzados) ✅
1. ✅ **P0-1** `self.villages = []` em `TWB.__init__` — 1 linha.
2. ✅ **P0-2** `self.actual = {}` / `self.requested = {}` em
   `ResourceManager.__init__` — 2 linhas.
   ⚠️ Vai ativar a Feature 9 de verdade; revisar P2-27 junto.
3. ✅ **P1-15** `self.villages = {}` / `self.map_pos = {}` em `Map.__init__`.
4. ✅ **`DefenceManager.supported`** (Bug 3 de `bugs_flags.md`) — mesma classe de
   problema, aproveitar o lote.

### Lote 2 — integridade de dados ✅
5. ✅ **P0-4** parar de `os.remove` no webmanager + escrita atômica no
   `FileManager`.

### Lote 3 — features ressuscitadas (one-liners) ✅
6. ✅ **P0-5** `unit = i` no simulador.
7. ✅ **P1-6** inverter a condição do suporte entre aldeias.
   ⚠️ Deixa de ser código morto, mas `support_others` segue `false` no config.
8. ✅ **P1-7** `self.` no `forced_peace_today`.
9. ✅ **P1-10** inverter a comparação do relatório de scout antigo.

### Lote 4 — crashes de caminho quente ✅
10. ✅ **P1-11** guarda de `None` no `recruit()`.
    Eram **três** crashes na mesma função, não um — ver notas.
11. ✅ **P1-12** `list()` na iteração do `can_recruit()`.
12. ✅ **P1-13** guardas no `SnobManager`.
13. ✅ **P0-3** guarda no handler de crash do `main()` (feito antes, commit `ebac9d4`).
14. ✅ **P2-20** guarda no sync de `defense_states` + reset por ciclo.

### Lote 5 — o resto ✅ (parcial: 20 itens fechados, 3 abertos)
15. ✅ **P1-19** try/except no `check_update` (+ `timeout`, status code).
16. ✅ **P1-18** `DEBUG=False`, rotas de escrita em POST, guarda de origem, `__main__`.
17. ✅ **P1-8** `farm_score` implementado — rendeu um bug extra no lado da leitura.
18. ✅ **P1-9** guard da conquista reordenado.
19. ✅ **P1-14** parse de recursos a caminho agnóstico de idioma.
20. ✅ **P1-16** `send_resources()` inspeciona a resposta.
21. ✅ **P1-17** `ensure_attack_manager()` — exigiu tornar explícito o bloqueio de paz forçada.
22. ✅ **P2-21, P2-23, P2-24, P2-25, P2-26, P2-27, P2-28, P2-30, P2-31,
    P2-32, P2-33, P2-34, P2-36, P2-37, P2-38, P2-39** e o **P3** de
    `AttackManager.ignored`.
23. ✅ Fora do diagnóstico: `check_forced_peace()` nunca era chamado.

**Ainda abertos:** P2-22 (escort pode travar o farm), P2-29 (piso de moral —
precisa do `<mood>` real do servidor), P2-35 (PvP instanciado por aldeia).

---

# Notas para investigação futura

Pontos que eu **não** consegui resolver offline e precisam de observação em
campo ou de uma sessão logada:

- ⚪ **`"delete": "Verwijderen"`** (remover ofertas do mercado) e
  `"support": "Ondersteunen"` — funcionam em pt-BR? O padrão sugere que o
  servidor só verifica presença da chave, mas nunca foi validado. O caminho do
  suporte deixou de ser código morto no Lote 3 (P1-6) e o perfil defensivo
  passou a nascer com `support_others: true` (`adca64b`), mas as aldeias
  defensivas atuais seguem em `false` — a validação em campo acontece quando a
  primeira aldeia nova conquistada como defensiva enviar suporte de verdade.
  Acompanhar o log `[Support] ... duration` para confirmar.
- ⚪ **`DefenceManager.manage_flags`** — o laço
  `for amount in raw_flags[flag_type][level]` ([`linha 354`](../game/defence_manager.py))
  assume que o valor é iterável. Se a API mudar para `int`, isso vira
  `TypeError`. Não dá para confirmar a forma sem uma amostra do
  `FlagsScreen.setFlagCounts(...)` real.
- ⚪ **Formato de `research_time`** em `TroopManager.research_time`
  ([`linha 252`](../game/troopmanager.py)) — assume `H:M:S` estrito;
  `IndexError` em qualquer outro formato.
- ⚪ **`Extractor.incoming_commands`** (Feature 16) — o parsing de
  `data-endtime`/`data-duration` foi escrito a partir de suposição sobre o
  markup. Vale conferir num ataque real se `incoming_eta` sai preenchido em
  `cache/managed/*.json` (campo `incoming_attack.eta_seconds`); se sair `null`
  com a aldeia sob ataque, o fallback "assume urgente" está sendo usado e a
  Feature 16 não está discriminando nada.
- ⚪ **Escrita de `send_res`** — os nomes de campo do payload em
  `send_resources` ([`resources.py:576`](../game/resources.py)) nunca foram
  validados contra uma resposta real, e como o retorno é ignorado (P1-16),
  não há como saber se algum envio já funcionou.

---

---

# Notas de implementação (2026-08-08)

Registrado aqui o que só apareceu ao corrigir, não ao diagnosticar.

## Lote 1 — nada além do previsto

As quatro correções saíram como descrito. Aproveitando o mesmo lote, também
foram movidos para `__init__` os demais mutáveis de classe do
`DefenceManager` (`attacks`, `flags`, `current_flag`, `my_other_villages`) —
mesma categoria, custo zero. Validado com teste de isolamento temporário
(duas instâncias por classe, mutando uma e conferindo a outra).

**Consequência assumida:** o fix do P0-2 faz `required_resources` refletir
necessidade real por aldeia pela primeira vez, o que ativaria a Feature 9.
Como P2-27 (prioridade por `last_run`) e P1-16 (`send_resources` sempre
`True`) continuam abertos, `resource_sharing.enabled` foi posto em `false`
no `config.json` local. **Religar só depois de corrigir os dois.**

## Lote 2 — a escrita atômica não é de graça no Windows

O diagnóstico propunha `os.replace(tmp, path)`. Implementado às cegas, isso
teria introduzido um **crash novo**: no Windows `os.replace` levanta
`PermissionError` (WinError 5) enquanto qualquer processo tiver o destino
aberto, porque o `open()` do Python não usa `FILE_SHARE_DELETE`. Como o
webmanager relê o cache inteiro a cada request, a colisão acontece de fato —
reproduzida em teste na primeira tentativa.

Três ajustes foram necessários além do plano original:

1. **Retry com backoff** no `os.replace` (o handle do leitor é efêmero:
   `open` → `json.load` → `close`).
2. **Fallback para escrita in-place** se a contenção persistir, com log de
   `WARNING`. Trocar uma corrida de leitura por um crash do bot seria pior
   que o bug original. No caminho degradado o truncamento volta a ser
   possível — coberto pela Frente 1, que agora pula em vez de apagar.
3. **`open()` movido para dentro do `try`** em `cache_grab`, com ramo
   `OSError` próprio. Sem isso o `PermissionError` transitório derrubaria a
   request inteira do webmanager — a correção teria trocado um modo de falha
   por outro.

**Trade-off registrado:** antes, um leitor concorrente via JSON truncado;
agora vê ocasionalmente um `open()` negado. Os leitores do webmanager que
varrem diretório por request já envolvem o `open()` em `try/except`, então
absorvem isso. Quatro pontos não guardados (`ConquestReader._resolve_identifier`,
`add_manual_target`, `cancel_manual`, `PvpConquestReader.set_clear_village`)
são ações de formulário do usuário, não caminho quente.

**Não coberto:** `twb.py:303` grava `config.json` com `json.dump` direto, sem
passar pelo `FileManager` — logo, ainda não é atômico. Corrupção de config é
mais grave que a de cache; candidato natural ao próximo lote.

## Lote 3 — cada "one-liner" trouxe um vizinho

Os quatro itens saíram como diagnosticados, mas três exigiram uma correção
adjacente que só aparece quando a feature volta a executar.

**P0-5 (simulador)** — resolvido com `for unit in self.attack_units[attackType]`
nos dois ramos, em vez de só corrigir o `a < 1`. Validado chamando
`simulate()` com atacante deliberadamente mais fraco (10 axes contra
500 spear + 500 sword, muralha 20): antes `TypeError`, agora retorna o
atacante zerado e o defensor praticamente intacto — o resultado que o
`PvpConquestManager` precisava para marcar o alvo como `failed` em vez de
deixá-lo eternamente em `pending_sim`.

**P1-6 (suporte)** — além de inverter a condição, foram removidos o
`index >= 2` hardcoded e o contador `index` (o `len(self.supported) >=
support_max_villages` já cobria o mesmo teto, com o valor certo), e
`support_others_max_villages` passou a ser lido do config em
`setup_defence_manager()` — a chave existia no `config.example.json` e no
helpfile desde sempre sem nada consumindo. A guarda `if vil ==
self.village_id: continue` foi mantida (não é redundante): `twb.py` atribui
ao fim do ciclo um `my_other_villages` que *inclui* a própria aldeia.
Validado com o laço isolado sobre um dict de 4 aldeias incluindo a própria —
suporta duas, pula a si mesma, para no teto.

⚠️ **A feature continua desligada em campo** (`support_others: false` nas 4
aldeias). O código deixou de ser morto, mas o primeiro envio real ainda é
inédito — junto vem o `"support": "Ondersteunen"` nunca validado em pt-BR
(ver Notas para investigação futura). Ligar numa aldeia só, observando.

**P1-7 (paz forçada)** — o `self.` faltante era metade do problema. Com ele
corrigido, dois defeitos vizinhos passariam a ser alcançáveis:

1. O laço não filtrava por *futuro*, só por *hoje*. Uma janela de paz que já
   terminou daria `forced_peace_time` no passado, e como o teste em
   `attack.py:409` é `now + duration > forced_peace_time`, **todo** ataque
   seria bloqueado pelo resto do dia. Agora só entram janelas com
   `start_dt > now`, e dentre elas vence a **mais cedo** (é um teto de
   chegada — a mais próxima é a restritiva; o diagnóstico sugeria `break`,
   que pegaria a primeira da lista, não a mais próxima).
2. `self.attack` só é construído uma vez (`if not self.attack`) e sobrevive
   entre ciclos, mas `forced_peace_time` só era *atribuído*, nunca limpo —
   o teto de ontem seguiria barrando ataques hoje. Adicionado o ramo `else`
   que zera.

Validado com as quatro combinações (duas janelas futuras hoje, janela
passada, dentro da janela, config vazio).

**P1-10 (scout antigo)** — reescrito como `now - last_attack >
farm_low_prio_wait * 2` em vez de trocar o operador, para a condição ficar
legível na mesma direção da mensagem de log.

## Lote 4 — o P1-11 era a ponta de uma família de cinco

O diagnóstico apontava **um** `None` não guardado em `recruit()`. Escrevendo o
teste que reproduzia o crash, apareceram mais quatro do mesmo tipo — todos
"resposta que não é a tela esperada", todos no caminho que roda para toda
aldeia todo ciclo. Cada um só ficou visível depois de corrigir o anterior:

| # | Onde | Gatilho | Diagnosticado? |
|---|---|---|---|
| 1 | `troopmanager.recruit()` — `get_action` inicial | timeout de rede | ❌ |
| 2 | `troopmanager.recruit()` — `Extractor.recruit_data` devolve `None` | 200 que não é a tela de recrutamento (sessão expirada, bot protection, markup novo) | ❌ |
| 3 | `troopmanager.recruit()` — `get_api_action` | timeout de rede | ✅ P1-11 |
| 4 | `ResourceManager.update(game_state=None)` | idem #2, vindo de 4 chamadores | ❌ |
| 5 | `ResourceManager.logger` é `None` até o primeiro `update()` bem-sucedido | qualquer `self.logger.*` antes disso | ❌ |

O #1 é o mais provável dos três de `recruit()`: é a primeira requisição da
função, e a auditoria só tinha visto a última.

O #4 foi guardado **no destino** (`ResourceManager.update`) em vez de nos
quatro chamadores (`buildingmanager`, `snobber`, `village` ×2), que passam
`Extractor.game_state(...)` cru. Degrada mantendo os valores anteriores: um
resource desatualizado por um ciclo é melhor que derrubar o processo.

O #5 foi descoberto pelo próprio fix do #4 — o `logger.warning` da guarda nova
crashava, porque `logger` é atributo de classe `None` e só era criado na
**última linha** de um `update()` bem-sucedido. Ou seja, `can_recruit()` e
`do_premium_stuff()` já eram `AttributeError` se chamados antes do primeiro
update. Movido para o `__init__`; `update()` continua re-vinculando com o nome
real da aldeia quando o conhece.

**P1-13 (snob)** — além das duas guardas previstas, a decisão não-óbvia foi o
valor de `is_incomplete` quando o markup da academia não casa. Ele é lido em
[`village.py`](../game/village.py) e, com `prioritize_snob` ligado, **barra
todo o recrutamento da aldeia**. Deixá-lo `True` num parse que falhou travaria
a aldeia inteira por um erro de leitura; fica `False` de propósito — não
nobilitar é melhor que não recrutar nada.

**P2-20** — a guarda `if not village.def_man: continue` era metade. A outra é
que `defense_states` era declarado **fora** do `while` e nunca limpo: entradas
de aldeias já perdidas seguiam sendo anunciadas como "sob ataque" para sempre.
Isso também mantinha o `attention_lag` da Feature 23 permanentemente desligado
(`not any(defense_states.values())`). Agora é zerado a cada ciclo. O `print`
que estava dentro do laço (uma linha por aldeia) saiu para fora.

**Não coberto:** o levantamento de #4 olhou só os chamadores de
`resman.update`. Os outros `Extractor.*` que devolvem `None` implícito
(`recruit_data`, `game_state`, `attack_form`, …) têm mais consumidores sem
guarda espalhados — `buildingmanager` e `reports` em particular. É o mesmo
padrão, mas fora do escopo do lote.

## Lote 5 — dois achados fora do diagnóstico, um deles maior que o item original

Dividido em quatro commits (`e13979d`, `ff1c035`, `42b2ef9`, `d9d36e2`).

**Achado 1 — `Village.check_forced_peace()` nunca era chamado.** O P1-7 do
Lote 3 corrigiu o `self.` faltando *dentro* do método, mas ninguém tinha
verificado se o método era chamado: `grep` no repositório inteiro devolve
uma única ocorrência, a própria `def`. Consequência: `self.forced_peace`
ficava no default `False` da classe para sempre, e portanto
`farms.forced_peace_times` era config inerte — o bot atacaria normalmente
dentro da janela de paz forçada. Agora é chamado em `Village.run()`, antes de
`ensure_attack_manager()`, com `try/except` no `strptime` para uma entrada mal
formatada não derrubar o ciclo. **Lição:** corrigir o corpo de uma função não
prova que ela executa; conferir os chamadores no mesmo passo.

**Achado 2 — o P1-8 escondia um segundo bug do lado da leitura.** Ao passar a
gravar `farm_score`, o `score = ....get("farm_score") or default_score` de
`get_targets()` viraria um bug ativo: um farm com score **0** (não rende
nada) é falsy, cairia no `default_score = 9999` e iria para o **topo** da
fila de farm — exatamente o alvo que menos interessa. Era inofensivo enquanto
nada gravava o campo. Trocado por checagem explícita de `None`. Simulado com
5 alvos: a ordem passa de "distância pura" para
`nunca_atacado → rico → médio → pobre → sem_saque`. **Lição:** ao ativar um
caminho que estava morto, reler os consumidores assumindo que eles nunca
foram exercitados.

**Consequência do P1-17.** Extrair a criação do `AttackManager` para
`ensure_attack_manager()` removeu um bloqueio que era *implícito*: durante paz
forçada o objeto simplesmente não existia, e o Hunter falhava por isso. Com o
objeto passando a existir sempre, Hunter e PvP poderiam atacar dentro da
janela de paz. Foi preciso adicionar `AttackManager.in_forced_peace`, checado
no topo de `attack()`, e reescrever os dois campos de paz a cada ciclo.
Padrão a vigiar: **quando um guard vinha de "o objeto não existe", criar o
objeto sempre exige tornar o guard explícito.**

**Escolha conservadora em `evacuate()` (P2-39).** A ordenação por distância
real entrou, mas a primeira versão iterava os candidatos e tentava o próximo
quando `support()` devolvia falso. Descartado: `support()` termina em
`get_api_action()`, que devolve `None` quando a resposta não é parseável — o
envio pode ter acontecido. Retentar mandaria as mesmas tropas para uma
segunda aldeia. Mantida uma tentativa por ciclo, só que agora para o destino
mais próximo.

**P2-33 com default acima do volume atual.** A poda de `cache/reports` existia
mas `clean_reports` nunca era passado. Ligada via `bot.max_cached_reports`
(novo, default `1000`) — acima dos ~286 arquivos de hoje, então não apaga nada
agora e só entra em ação quando o diretório realmente dispara. `config.example.json`
foi para `2.9`; o `config.json` local segue em `2.8`, então o próprio bot faz o
merge (com `config.bak`) e ganha a chave no próximo start.

**Não corrigido de propósito — P2-29 (piso de moral).** O diagnóstico afirma
que o piso real do TW é 30% e o código usa `floor = 100 - loss_max` = 70. Mas
o docstring de `estimate_moral` afirma que `mood.loss_max` foi confirmado ao
vivo, e as duas afirmações não podem ser verificadas offline: não há
`cache/world_config*` neste repositório para inspecionar o `<mood>` real do
br143. Trocar 70 por 30 seria trocar um palpite por outro num campo que hoje
é **inerte** (`pvp_conquest.dynamic_moral_night_bonus: false`). Precisa de uma
amostra do bloco `<mood>` do servidor antes de mexer.

**Também aberto:** P2-22 (`_calculate_needed_escort` pode reservar 100% de um
tipo de tropa e travar o farm indefinidamente) e P2-35 (`PvpConquestManager`
instanciado 1× por aldeia por ciclo). Os dois são mudanças de comportamento em
tropas/escalonamento, não guardas — merecem lote próprio com validação em
campo.

---

**Documento gerado em:** 2026-08-08
**Base:** branch `master`, working tree limpo (`git status` sem alterações).
