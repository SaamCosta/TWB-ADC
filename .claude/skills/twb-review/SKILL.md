---
name: twb-review
description: Revisão de diff específica do TWB-ADC. Roda a checklist mecânica dos padrões de bug recorrentes deste repo — atributo de classe mutável, None vindo de rede, função órfã, lista paginada, valor de falha disfarçado de resultado, config sem template. Use antes de considerar "pronto" qualquer mudança em game/, core/ ou webmanager/, e sempre que o usuário pedir revisão, "revisa isso", "está pronto?", ou for commitar mudança em manager de jogo.
---

# Revisão TWB-ADC

Esta skill é a parte **mecânica** dos padrões de bug do `CLAUDE.md`: as
verificações que são um grep e uma leitura, e que por isso falham por
esquecimento, não por dificuldade. Ela não substitui a revisão de mérito —
substitui o "achei que tinha olhado".

Regra de uso: rode sobre o **diff**, não sobre o repo inteiro. O alvo é
`git diff` (ou `git diff --cached`, ou o range que o usuário indicar).

## Passo 0 — delimitar o alvo

```
git status --short
git diff --stat
```

Liste os arquivos tocados. Os checks abaixo só se aplicam aos arquivos e às
linhas **do diff**; um hit pré-existente fora do diff é dívida, não achado
desta revisão — mencione no máximo como nota de rodapé.

## Check 1 — atributo de classe mutável (1º padrão)

Quase toda classe aqui declara campos no corpo da classe. Para `list`/`dict`
mutados in-place isso é estado compartilhado entre todas as instâncias — e
existe uma instância de quase todo manager **por aldeia**.

```
grep -rnE "^    [a-z_]+ *= *(\[\]|\{\})" <arquivos do diff>
```

⚠️ **O grep tem falso positivo alto.** Muitos desses já foram corrigidos: o
campo continua declarado no corpo da classe *e* reatribuído no `__init__`, o
que resolve. Para cada hit, confirme:

```
grep -n "self\.<nome> *=" <arquivo>
```

Só é achado se **não houver** atribuição no `__init__` **e** o campo for
mutado in-place (`.append(`, `.update(`, `[k] =`). Se for só lido ou
reatribuído inteiro, é inofensivo.

Aplica-se a campo **novo** introduzido pelo diff, não à declaração herdada.

## Check 2 — `None` não guardado vindo de rede/parse (2º padrão)

`WebWrapper.get_url()` devolve `None` em qualquer exceção, e por tabela
`get_action` / `get_api_data` / `get_api_action` também. Vários `Extractor.*`
têm `return None` implícito quando o regex não casa — o que acontece numa
resposta 200 que não é a tela esperada (sessão expirada, bot protection,
markup novo).

No diff, para cada chamada a `get_url`, `post_url`, `get_action`,
`get_api_data`, `post_api_data`, `get_api_action` ou `Extractor.*`, perguntar:
**o valor é consumido sem guarda?** Os consumos que derrubam o processo são
`res.text`, `x in res`, `res["chave"]`, `res.json()`, iteração.

```
grep -nE "get_url|post_url|get_action|get_api_data|post_api_data|get_api_action|Extractor\." <arquivos do diff>
```

Corolário a conferir junto: **o logger já existe naquele ponto?** Vários
managers criam `self.logger` no meio de um `update()` bem-sucedido, então uma
guarda nova que loga no caminho de erro crasha antes de logar.

## Check 3 — valor de falha indistinguível de resultado válido (6º padrão)

Variante do Check 2 que o grep de `None` não pega. Para cada parser consumido
no diff, abrir a definição e responder: **o que ele devolve quando falha, e
esse valor é distinguível de um resultado legítimo?**

O caso canônico é `Extractor.attack_duration()`, que devolve `0` — somado à
hora de envio, faz o nobre nascer "já pousado". `[]` de um parser de lista tem
o mesmo problema: lista vazia é indistinguível de "não achei nada".

## Check 4 — função definida e nunca chamada (3º padrão)

Para cada `def` **nova ou modificada** no diff:

```
grep -rn "<nome_da_funcao>" --include=*.py .
```

Se a única ocorrência for a própria `def`, é código morto — e "corrigir um bug
dentro de função órfã" já aconteceu aqui.

Segunda metade, que vale mais: se o diff **alargou o conjunto de valores de
retorno** de uma função existente (passou a devolver `{}`, `None` ou `[]` num
caso que antes era raro), reler **cada consumidor** perguntando "e se vier
este valor agora?". Foi exatamente assim que a reserva de escolta ficou presa
para sempre.

## Check 5 — config sem template / sem help (regras de config)

Se o diff introduz leitura de config nova:

```
python tests/test_config_integrity.py
```

Esse teste varre por AST toda chamada a `get_config`/`get_village_config` e
exige que a chave exista em `config.example.json` (e em `village_template`, se
for por aldeia) e esteja documentada em `webmanager/helpfile.py`. É a
verificação automática das três regras de config do `CLAUDE.md` — não refaça
na mão.

Se o diff adiciona **bloco** de config novo, conferir à parte que
`build.version` foi bumpado **só** em `config.example.json`. Versões iguais
nos dois arquivos **desligam** o merge (`twb.py`: o merge roda quando elas
divergem) e a seção nunca chega ao `config.json` do usuário — falha muda.

## Check 6 — lista do jogo sem paginação (26º padrão)

Se o diff parseia uma **tela que é uma lista** do jogo, a primeira pergunta
não é o regex da linha: é **quantas linhas existem no total**. Contar os
casamentos e procurar navegação (`page=`, `[2]`, um `<select>` de páginas) na
captura. Preferir `&page=all` na querystring a mexer em configuração de
tamanho de página — esta última às vezes é compartilhada com a tribo.

Lista curta é indistinguível de lista completa: a falha não emite erro.

## Check 7 — guarda que nunca dispara ou sempre dispara (15º / 21º padrão)

Para cada condição/WARNING novo no diff:

- **Sempre dispara?** Perguntar em que *outro* lugar da página aquele sinal
  aparece (o caso real: `Chegando` também é item do menu de navegação).
  Ancorar a guarda no mesmo padrão que o parser real usa, não numa versão
  frouxa dele.
- **Nunca dispara?** Se é limiar de tempo num sistema que roda em ciclos,
  comparar com o **período do ciclo** (~1h39 entre dois ciclos da mesma aldeia,
  medido em 2026-08-21). Janela mais estreita que o ciclo = condição correta e
  nunca observada.

## Check 8 — efeito colateral no corpo do módulo (20º padrão)

Se o diff adiciona código **fora** de `def`/`class` num módulo importável:
ele roda em todo `import`, inclusive nos testes e no webmanager. Se escreve,
apaga, abre conexão ou muda estado global, precisa estar sob
`if __name__ == "__main__":` ou ser preguiçoso. Truncar arquivo não levanta
exceção — some em silêncio.

Neste repo o custo é real: `cache/` é estado de produção não regenerável.

## Check 9 — mudança de alto risco

Se o diff toca `game/attack.py`, `game/defence_manager.py` ou
`game/pvp_conquest.py`, dizer isso explicitamente no relatório: são tropas
reais em jogo, com latência de horas entre decidir e o efeito acontecer.
Perguntar, do 6º padrão: **a premissa é reconferida no momento de agir, ou só
no momento de decidir?** E se há guarda, ela se apoia num campo que pode estar
inconsistente (`status`) ou num fato físico (tempo de chegada)?

## Passo final — rodar a suíte

```powershell
foreach ($t in (Get-ChildItem tests/test_*.py)) { python $t.FullName; if ($LASTEXITCODE -ne 0) { Write-Host "FALHOU: $($t.Name)" } }
```

⚠️ Checar **`$LASTEXITCODE`, não `$?`**. Vários testes escrevem WARNING em
stderr, e no PowerShell 5.1 isso torna `$?` falso mesmo com código 0 — já
produziu 15 falhas inexistentes numa suíte 100% verde.

Os `tests/smoke_*.py` ficam fora do glob de propósito (vão à rede ou abrem
processo). Se o diff toca `BotManager`, rodar `tests/smoke_bot_manager.py` na
mão.

## Formato do relatório

Por achado: arquivo:linha, qual check disparou, e **o cenário concreto de
falha** (entrada/estado → resultado errado). Sem cenário, é observação de
estilo, não achado — não reportar.

Ao fim, listar em uma linha os checks que rodaram e não acharam nada. Silêncio
não é o mesmo que "verificado", e este repo já pagou por essa confusão.
