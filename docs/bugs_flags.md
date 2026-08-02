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

---

## Estado atual e próximos passos

| Item | Status | Ação necessária |
|------|--------|------------------|
| Bug 1 — troca constante | ✅ Corrigido (código) | Aplicado guard `_flag_state_confirmed` + comparação `==` em `flag_logic()`. Aguardando validação em campo. |
| Bug 2 — loop de upgrade | ✅ Corrigido (código) | Aplicado `sleep(2)` + limite de 2 tentativas por `(flag_type, level)` em `manage_flags()`. Aguardando validação em campo. |
| Mapeamento de 8 tipos | 📋 Documentado | Implementar `FLAG_TYPES` no código; ativar tipos 7/8 quando relevante |
| Cooldown de 24h ativo | 🔴 Em curso | Aguardar expirar; monitorar logs após fix do Bug 1 |

**Pré-requisito para fechar este item:**
- Validação em campo dos fixes dos Bugs 1 e 2 (branch `master`, commits de correção
  em `game/defence_manager.py`).
- Feature 8 (conquest) validada antes de ativar uso do tipo 7 (coin_cost).
