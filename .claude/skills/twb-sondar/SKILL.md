---
name: twb-sondar
description: Protocolo para descobrir um dado do Tribal Wars no servidor antes de escrever código contra ele — sondar uma tela nova, capturar fixture de markup, confirmar uma mecânica de mundo (moral, velocidade, bônus, lealdade, limiares). Use sempre que for escrever ou corrigir um parser, quando precisar saber um número do mundo, e ANTES de concluir que um dado "não existe" ou "não é verificável".
---

# Sondar o servidor do Tribal Wars

Esta skill existe porque o histórico deste projeto tem um padrão claro: as
conclusões erradas mais caras não vieram de código difícil, vieram de **supor
o que o servidor responde em vez de perguntar**. O dado quase sempre estava a
um request de distância.

## Regra de ouro

**"Não achei" só vale como conclusão depois de dizer onde procurou** — e para
número de mundo isso significa citar as duas fontes, não uma.

## As quatro fontes, e o que cada uma dá

| Fonte | Autenticação | Serve para |
|---|---|---|
| `interface.php?func=get_config` | **pública** | valores brutos de regra do mundo, em XML/enum |
| `interface.php?func=get_unit_info` | **pública** | velocidades, ataque/defesa, capacidade, pop |
| `/page/settings` | pública | a **redação em português** das mesmas regras, com campos que o `get_config` não expõe |
| `game.php?...` (tela do jogo) | sessão do bot | markup real, inventário, relatórios, listas |

Já em cache local: `cache/world/config_br143.json`, `config_br142.json`,
`units_br143.json`, `cache/_get_config.xml`, `cache/_get_unit_info.xml`.
**Olhe aqui antes de sair buscando** — e repare que o nome do arquivo pode não
ser o que uma nota antiga diz.

A lista de mundos por mercado sai de `backend/get_servers.php`.

## Protocolo

### 1. O dado já está em disco?

```
ls cache/world/ && grep -rn "<termo>" cache/world/ cache/_get_*.xml
```

### 2. É regra de mundo? Então cruze as DUAS fontes

`get_config` e `/page/settings` **não expõem o mesmo conjunto de campos**.
Ausência num não é ausência no servidor. A regeneração de lealdade do br143
(1/h, contra 1.5 que o config assumia) estava publicada em português numa
tabela do `/page/settings` e em lugar nenhum do `get_config`.

Para **enum** (0/1/2/3), mapear contra o servidor, nunca contra a wiki da
comunidade: o valor bruto vem do `get_config` e a redação correspondente do
`/page/settings`, por mundo. Cruzar ~30 mundos custa dois requests cada e
transforma palpite em tabela.

### 3. É tela do jogo? Então sonde com o cliente do bot

⚠️ **A resposta depende de como você pergunta.** `get_api_data` manda
`tribalwars-ajax: 1` e com esse cabeçalho o mesmo endpoint embrulha tudo em
`{"response": …, "game_data": …}`; sem ele, vem cru. Fixture capturada com um
`requests.Session()` montado à mão é fixture de uma resposta que o bot nunca
vai receber.

Escreva um probe em `cache/_probe_<assunto>.py` seguindo o idioma que já
existe ali (`_probe_reservations.py`, `_probe_scavenge.py`, `_probe_smith.py`):

```python
"""SO-LEITURA: <o que lê e por que existe>. NAO faz POST."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor
from core.filemanager import FileManager
from core.request import WebWrapper

config = FileManager.load_json_file("config.json")
wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(FileManager.load_json_file("cache/session.json")["cookies"])
```

Depois chame **o próprio método do wrapper** (`get_url`, `get_api_data`,
`get_api_action`) — não monte o request na mão.

⛔ **Nunca ligar `priority_mode`.** Ele pula o delay do `get_url`, e com o bot
rodando na mesma conta isso já provocou captcha por cima dele. O probe é
lento de propósito.

Salve a resposta crua em disco antes de escrever qualquer regex.

### 4. É uma LISTA? Conte as linhas antes do regex

A primeira pergunta não é "qual o regex da linha", é **"quantas linhas
existem no total, e este é o total?"**. A tela de reservas da tribo respondia
**10 de 489** num GET — 49 páginas, com o bloco de navegação a 40 KB do
trecho que eu tinha aberto. Um parser escrito ali teria dado 479 alvos como
livres, sem emitir um único erro.

Procure na captura: `page=`, `[2]`, um `<select>` de páginas. Prefira
`&page=all` na querystring. Não mexa em configuração de tamanho de página —
às vezes é compartilhada com a tribo, e mudá-la altera a interface de outras
pessoas.

### 5. O número já vem transformado?

Pergunte: **"isto já inclui o fator X?"** — e repare que a pergunta é
*inrespondível* no seu mundo se lá X=1. As velocidades de `get_unit_info`
**já são** os min/campo efetivos, com `speed` e `unit_speed` embutidos; no
br143 (ambos = 1) as duas hipóteses dão o mesmo número e o erro seria
invisível para sempre. O que separou foi o br139 (`speed=1.4`,
`unit_speed=0.75`) publicando `17,142857` = `18/(1,4×0,75)`.

Regra: quando um valor deveria escalar com um parâmetro do mundo, **buscar uma
instância onde esse parâmetro não seja neutro.**

### 6. É um "+N%" escrito em português? Meça.

Texto de item descreve o **efeito**, não a fórmula. "Apoio irá percorrer 30%
mais rápido" comporta `duração / 1,3` e `duração × 0,7`, que diferem em 5
minutos numa viagem de uma hora — e a leitura ingênua erra **sempre para
menos**. Monte as leituras plausíveis, veja de quanto divergem, e meça uma
instância real: a tela de confirmação da praça de reunião entrega o número
sem enviar nada.

### 7. Antes de dar por pronto: smoke contra o servidor

Testes verdes com fixture não provam que o parser recebe aquilo. Um smoke com
os cabeçalhos do próprio wrapper, **depois** de os testes passarem, não é
redundância — foi o único passo que pegou o embrulho `{"response": …}`.

## Armadilhas que já custaram caro

- **Experimento que só pode confirmar a hipótese não é evidência.** Provocar
  uma recusa mandando 9999 lanceiros de uma aldeia que tem zero produz
  *"Não existem unidades suficientes"* — a mensagem do erro que você mesmo
  fabricou. A causa real das recusas era outra (limite de ataque falso do
  mundo) e só apareceu instrumentando a falha **real** e esperando um ciclo.
  Antes de provocar um erro: *"que resultado deste teste me faria mudar de
  ideia?"*

- **Se você mesmo escreveu qual é a fonte plausível, olhar custa menos que o
  parágrafo justificando não olhar.** Um docstring citava o 3º argumento de
  `BuildingStatue.initImmutables(...)` e o descartava por "poder variar". Era
  ali que o dado estava, server-side, na mesma resposta que o bot já baixava —
  dez segundos de request.

- **"Confirmado ao vivo" é afirmação sobre procedência.** Diga **qual tag**,
  não só que veio do servidor. O piso de moral saiu de `<mood>`, um número
  real lido do servidor, do campo errado — a tag que manda é `<moral>`.

- **Fixture de markup se copia, não se inventa.** Recorte verbatim, sempre.
  Uma versão de `loyalty_from_report()` falhava por ter sido escrita contra um
  markup suposto.

- **Armadilha plausível também precisa ser medida antes de virar comentário no
  código.** Afirmei num teste que um regex ingênuo "não casaria" o markup por
  causa de um `>` dentro do atributo. Rodei: casava.

- **O log é registro das ações do bot, não do estado do mundo.** Ausência de
  linha prova que o bot não fez, não que ninguém fez — o usuário joga na mesma
  conta. E `cache/logs/twb_*.log` (reporter) **não** contém os loggers; esses
  vivem em `cache/logs/session_latest.log`, que tem bytes NUL (use `grep -a`).

- **Meça a partir da fonte que o código lê.** Um diagnóstico mediu o filtro de
  raio sobre `cache/villages` (851 aldeias), mas `find_target()` itera sobre
  `self.map.villages`, o prefetch da própria aldeia. Dois funis em série, e a
  medição descreveu um programa diferente do que roda.

- **"Mais velho" é propriedade do CAMPO, não da fonte.** Para *posse*, o
  `map/village.txt` "velho" era a fonte **nova**: 38 entradas do snapshot
  local diziam bárbara para aldeias que já eram de jogador, e zero no sentido
  inverso. A assimetria 38×0 estava no próprio dado.

## Ao terminar

Se o que você descobriu contradiz o `CLAUDE.md` ou o `docs/backend.md`,
**corrija o documento no mesmo passo**. Esses arquivos são memória, não
especificação — envelhecem e nascem errados como qualquer nota, e o próximo a
ler cai igual.
