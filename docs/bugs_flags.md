# Sistema de Bandeiras (DefenceManager) — Diagnóstico e plano de correção

**Arquivo:** `game/defence_manager.py`
**Servidor onde foi observado:** br142.tribalwars.com.br

**Impacto já registrado:** o bot tentou rebaixar a bandeira de produção de 16%
para 12%, causando cooldown de 24h sem possibilidade de reversão.

---

## Bug 1 — Troca constante de bandeira a cada ciclo

**Status:** ativo, sem ataque detectado.

### Sintoma
O bot tenta reatribuir a bandeira em praticamente todos os ciclos de execução,
mesmo com a bandeira correta já ativa e sem nenhum ataque em curso.

### Causa raiz
`flag_logic()` é chamada em todo ciclo dentro de `update()`. A proteção de
randomização (3–8 ciclos) existe apenas em `manage_flags()`, não em
`flag_logic()`. Fluxo real:

```
update() → flag_logic() [todo ciclo]
         → not self.current_flag?
         → True → flag_set() disparado
```

`self.current_flag` vira `None`/vazio sempre que:
- o parse do HTML falha (regex não encontra o padrão esperado);
- a div de bandeira atual está com `display: none` (nenhuma bandeira ativa
  no servidor);
- `manage_flags()` ainda não rodou neste ciclo (estado inicial).

Entre execuções de `manage_flags()`, `flag_logic()` continua disparando
`flag_set()` a cada ciclo porque `not self.current_flag` avalia como `True`,
sem confirmar o estado real pelo servidor.

### Agravante — comparação com `is not`
A condição usa `is not` em vez de `!=` para comparar inteiros:
```python
self.current_flag[0] is not set_flag
```
Para valores pequenos (1, 4), o CPython faz cache de inteiros e `is not`
funciona como `!=` na prática. Mas se o tipo de bandeira vier como string
convertida ou de outro contexto, essa comparação pode falhar silenciosamente
e disparar uma troca desnecessária.

### Correção sugerida
Guard no início de `flag_logic()` que aborta silenciosamente quando
`current_flag` é desconhecido, aguardando o próximo ciclo de
`manage_flags()` para ter estado confirmado — e comparação por `==`:

```python
def flag_logic(self, set_flag):
    if not self.manage_flags_enabled:
        return

    # Guard: sem estado confirmado, não age
    if not self.current_flag:
        return

    highest = self.get_highest_flag_possible(flag_id=set_flag)
    if not highest:
        return

    already_correct = self.current_flag[0] == set_flag  # == em vez de is not
    already_best = self.current_flag[1] >= highest

    if already_correct and already_best:
        return  # nada a fazer

    if not self._can_change_flag:
        ...  # log de cooldown
        return

    self.flag_set(set_flag, level=highest)
    self.current_flag = [set_flag, highest]  # atualiza local imediatamente
```

A atualização local de `current_flag` ao final evita re-triggers nos ciclos
intermediários antes do próximo `manage_flags()`.

---

## Bug 2 — Loop infinito de upgrade de bandeira

**Status:** ativo, requer intervenção manual para encerrar.

### Sintoma
Quando há 3+ bandeiras do mesmo tipo e nível (condição de upgrade
disponível), o bot tenta upar repetidamente sem sucesso. O loop só termina se
o upgrade for feito manualmente pelo jogador.

### Causa raiz
Em `manage_flags()`, ao detectar `amount >= 3`, chama `flag_upgrade()` e
depois se chama recursivamente:

```python
if int(amount) >= 3:
    self.flag_upgrade(flag=flag_type, level=level)
    upgraded += 1
...
if upgraded:
    return self.manage_flags()  # recursão imediata
```

Não há verificação de sucesso da chamada à API. Se `flag_upgrade()` falhar
silenciosamente (timeout, erro de servidor, cooldown de upgrade), o HTML
relido na chamada recursiva ainda mostrará `amount >= 3`, e o ciclo se repete
indefinidamente — ou até o próximo restart do bot.

Adicionalmente, não há limite de tentativas nem delay entre a chamada ao
servidor e a releitura do HTML — race condition onde o inventário ainda não
foi atualizado quando `manage_flags()` re-parseia.

### Correções sugeridas (por ordem de robustez)

**1. Delay antes da recursão (fix mínimo)**
```python
if upgraded:
    import time
    time.sleep(2)
    return self.manage_flags()
```

**2. Limite de tentativas por sessão (fix robusto)**
```python
upgrade_attempts = {}  # {(flag_type, level): count}

key = (flag_type, level)
upgrade_attempts[key] = upgrade_attempts.get(key, 0) + 1

if upgrade_attempts[key] <= 2:
    self.flag_upgrade(flag=flag_type, level=level)
else:
    self.logger.warning(
        'Upgrade de bandeira %s/%s falhou após 2 tentativas', flag_type, level
    )
```

**3. Verificação de sucesso pela resposta da API (fix definitivo)**
Checar o retorno de `flag_upgrade()` antes de marcar `upgraded = True`. Se a
API retornar erro ou resposta vazia, logar e não incrementar o contador de
upgrades.

---

## Tipos de bandeira — mapeamento completo

O bot hoje reconhece apenas os tipos 1 (produção) e 4 (defesa). O jogo possui
8 tipos com 9 níveis cada:

| Tipo | ID interno | Efeito | Quando usar | Prioridade |
|------|-----------|--------|-------------|------------|
| 1 | production | Produção de recursos | Passivo — manter sempre ativo fora de combate | Padrão (sem ataque) |
| 2 | recruitment | Velocidade de recrutamento | Ativar ao iniciar produção de noble train ou escolta | Temporário — produção em massa |
| 3 | attack | Força de ataque | Útil em fakes ou ataques coordenados; conflito com tipo 4 | Feature 10+ |
| 4 | defense | Força de defesa | Ativar automaticamente ao detectar ataque recebido | Padrão (sob ataque) |
| 5 | luck | Equilíbrio de sorte do atacante | Reduz variância nas batalhas; aplicação tática em PvP | Feature 13+ |
| 6 | population | Aumento de população | Útil em gargalo de população; raramente necessário | Situacional |
| 7 | coin_cost | Redução no custo de cunhagem | Ativar antes de cunhar moedas para nobles | Feature 8/10 |
| 8 | loot | Capacidade de saque | Maximiza retorno de farm; combina com Feature 5 (farm score) | Hoje (farm) |

### Uso planejado
- **Tipo 1 (produção)** — fora de ataque, maximiza renda passiva de recursos.
- **Tipo 4 (defesa)** — ao detectar `command/attack.png` no HTML principal.
- **Tipo 8 (saque)** — pode ser ativado manualmente nas aldeias com perfil
  farm (Feature 5).
- **Tipo 7 (coin_cost)** — antes de cunhar moedas, reduz custo por noble
  (Feature 8/10).
- **Tipo 3 (attack)** — nas aldeias ofensivas durante janela de ataque
  (Feature 10, ataques coordenados).
- **Tipo 5 (luck)** — reduzir variância em conquistas de jogadores
  (Feature 13+, PvP).

### Constante de mapeamento para o código
```python
FLAG_TYPES = {
    1: 'production',    # produção de recursos
    2: 'recruitment',   # velocidade de recrutamento
    3: 'attack',         # força de ataque
    4: 'defense',        # força de defesa
    5: 'luck',           # equilíbrio de sorte do atacante
    6: 'population',     # aumento de população
    7: 'coin_cost',      # redução no custo de cunhagem
    8: 'loot',           # capacidade de saque
}
```

## Bug 3 — `supported` compartilhado entre todas as aldeias

> ✅ **CORRIGIDO no Lote 1 da auditoria** (`self.supported` movido para
> `__init__`). O texto abaixo é o diagnóstico original, mantido pelo histórico.
> A tarefa em background citada no fim não é mais necessária.

**Status original:** ativo, encontrado em 2026-08-02, não corrigido ainda.

`DefenceManager` declara `supported = []` como atributo de **classe** (não é
reatribuído em `__init__`). `game/village.py` instancia um `DefenceManager` por
aldeia gerenciada, mas como o código só faz `self.supported.append(vil)`
(mutação in-place, dentro de `update()`) e nunca `self.supported = [...]`, todas
as instâncias — ou seja, todas as aldeias — compartilham o mesmo objeto lista em
memória. Suporte enviado pela aldeia A marca o alvo como "já suportado" também
para a aldeia B, mesmo que B nunca tenha enviado nada, bloqueando indevidamente
`support_max_villages` por aldeia.

`current_flag` e `flags` (mesma classe) parecem seguros porque são sempre
reatribuídos por completo (`self.current_flag = cflag`, `self.flags = {}`) antes
de qualquer mutação — a primeira atribuição já cria um atributo de instância que
sombreia o de classe. `my_other_villages` também é seguro pois é reatribuído
externamente em `game/village.py`.

**Correção sugerida:** mover `self.supported = []` para dentro de `__init__`.
Revisar também se a lista deveria resetar periodicamente (hoje acumula
indefinidamente dentro de uma mesma instância, sem reset por ciclo).

**Nota:** existe uma tarefa em background já criada para isso
(`task_82df90dc`, chip pendente no momento em que este doc foi atualizado) —
se ainda não foi iniciada ou descartada, pode ser usada diretamente em vez de
reabrir a investigação do zero.

---

## Estado medido em 2026-08-31

Lido de `cache/managed/*.json` (bloco `flags` da Feature 19), que é estado real
persistido pelo bot e **não depende de log**. As 18 aldeias:

| sinal | resultado |
|---|---|
| `manage_flags_enabled` | **18/18** |
| `flag_state_confirmed` | **18/18** |
| bandeira equipada | 16/18 |
| `upgrade_attempts` presas | **0/18** |

**Inventário disponível (idêntico nas 18, é da conta):**
`{2: 7, 3: 7, 4: 6, 5: 7, 6: 7, 7: 4, 8: 7}`.

⚠️ **Não há bandeira do tipo 1 (produção) sobrando** — as 13 que existem estão
todas equipadas. E `set_flag_not_under_attack = 1` é hardcoded. Consequência,
calculada aldeia por aldeia contra o estado atual: `get_highest_flag_possible(1)`
devolve `None` e **`flag_logic()` não faz nada, em todas as 18, todo ciclo**.

Isso tem três desdobramentos:

1. **O Bug 1 não pode se manifestar hoje** — mas por *dois* motivos
   independentes, o guard `_flag_state_confirmed` e a ausência de tipo 1 no
   inventário. Não dá para dizer qual dos dois está segurando.
2. **BBM 016 e BBM 017 estão sem bandeira nenhuma e vão continuar assim.**
   Há 7 tipos disponíveis no inventário e o bot não equipa nenhum, porque só
   sabe pedir o tipo 1. É perda pura — qualquer bandeira rende mais que
   nenhuma. **Qual equipar é decisão de jogo, não de código: é exatamente a
   Feature 32.**
3. **Três aldeias (BBM 001, 010, 011) estão com o tipo 7 (custo de cunhagem)**,
   que o bot nunca equipa — foi escolha manual. Hoje ele não reverte, mas
   **só porque não tem tipo 1 disponível**: se uma bandeira de produção voltar
   ao inventário, `flag_logic` troca as três sem perguntar. Vale saber antes de
   desequipar qualquer coisa.

**O que ficou de evidência positiva:** a BBM 018 está com **tipo 4 (defesa)
nível 7** equipado e `can_change_flag: False`. Ou seja o caminho
`flag_logic(4)` executou `flag_set()` com sucesso em campo e o cooldown de 24h
está sendo respeitado. É a única parte do sistema com execução confirmada.

⚠️ **O que NÃO foi possível verificar, e por quê.** As mensagens de log do
`DefenceManager` (`Managing flags`, `Setting flag`, `Upgraded flag`, os avisos
de tentativa de upgrade) só existiam em `cache/logs/session_latest.log`. Esse
arquivo foi **destruído em 2026-08-31 ao rodar a suíte de testes** — `twb.py`
truncava o log no import (corrigido no mesmo dia, ver
`tests/test_session_log_guard.py`). Os 238 `twb_*.log` sobreviveram mas são do
*reporter* (eventos `TWB_*`), e não carregam nenhuma linha do `DefenceManager`.
Portanto **a frequência de `Setting flag` continua não medida** — que é o sinal
direto do Bug 1. Próxima sessão do bot já o registra de novo.

## Próximos passos

| Item | Status | Ação necessária |
|------|--------|------------------|
| Bug 1 — troca constante | ✅ Corrigido (código), **não validado** | Contar `Setting flag` por aldeia no próximo `session_latest.log`. Deve ser raro; hoje deve ser **zero**, porque não há tipo 1 no inventário. |
| Bug 2 — loop de upgrade | ✅ Corrigido (código), **não exercitado** | `upgrade_attempts` vazio em 18/18, mas o caminho só roda com 3 bandeiras do mesmo tipo+nível. Sem evidência de que o limite de 2 tentativas já tenha segurado algo. |
| Bug 3 — `supported` compartilhado | ✅ Corrigido no Lote 1 | Nada. |
| Duas aldeias sem bandeira | 🔴 Aberto | BBM 016/017. Decidir que tipo equipar quando o preferido não está disponível — é a Feature 32. |
| Mapeamento de 8 tipos | ✅ `FLAG_TYPES` existe no código | Falta quem *escolha* entre eles (Feature 32). Percentuais por nível já levantados, ver `docs/backlog.md`. |
| Cooldown de 24h | ℹ️ Normal | BBM 018 em cooldown por ter trocado para defesa. Comportamento esperado. |
