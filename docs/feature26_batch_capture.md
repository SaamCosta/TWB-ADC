# Feature 26 — captura real do envio em lote

Captura feita em 04/09/2026 no Mundo 143 para remover o bloqueio descrito na
Feature 26 do backlog. Tokens de sessão e CSRF não são reproduzidos neste
documento; o que importa para a implementação é a estrutura do formulário, e
os valores sensíveis continuam sendo extraídos da resposta ao vivo pelo bot.

## Ensaio controlado

- origem: BBM 001 (`village=41123`, `577|306`);
- destino: aldeia-bônus bárbara `42248` (`578|297`);
- ataque principal: 98 bárbaros (`axe`);
- ataque adicional: 98 bárbaros (`axe`);
- nenhuma outra unidade e nenhum nobre;
- POST final: `game.php?village=41123&screen=place&action=command`;
- resultado: dois comandos aceitos, chegando em `18:14:06.428` e
  `18:14:06.543` — diferença de **115 ms**.

## Estrutura observada

O formulário `#command-data-form` contém os campos normais do ataque principal:

```text
attack, ch, cb, x, y, source_village, village
spear, sword, axe, spy, light, heavy, ram, catapult, knight, snob
building, submit_confirm, h
```

Depois de clicar em “Adicionar ataque adicional”, a primeira nova linha é:

```text
train[2][spear]
train[2][sword]
train[2][axe]
train[2][spy]
train[2][light]
train[2][heavy]
train[2][ram]
train[2][catapult]
train[2][knight]
train[2][snob]
```

Não existe `train[1]`: o ataque #1 é representado pelos campos sem prefixo.
Linhas seguintes avançam para `train[3]`, `train[4]`, etc. Todas compartilham
`x`/`y` e os tokens do formulário principal.

Depois do envio controlado, um segundo formulário foi aberto apenas para
inspeção e abandonado sem submissão. Três cliques no botão adicional geraram,
como esperado, todos os campos de `train[2]`, `train[3]` e `train[4]`. Isso
confirma diretamente o formato necessário ao trem padrão de quatro nobres.

## Cuidado operacional observado

Ao adicionar uma linha pela interface, o JavaScript preencheu automaticamente
o ataque #2 com todas as tropas restantes, incluindo um nobre. Para o ensaio,
esses campos foram explicitamente zerados depois de definir os 98 bárbaros.
O código não reproduz esse comportamento da interface: ele escreve todas as
unidades da linha, usando zero para tudo que não foi solicitado.

Esta captura valida tanto o formato quanto a atomicidade prática do endpoint:
um POST criou os dois comandos, sem o intervalo de dezenas de segundos causado
por repetir GET → confirmação → envio para cada ataque.
