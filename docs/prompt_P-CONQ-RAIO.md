# Prompt para novo chat — `P-CONQ-RAIO`

> Copie daqui para baixo.

---

Preciso corrigir um defeito que eu mesmo introduzi ontem (2026-09-17) no
planejador de trem de nobres bárbaro, mais um ajuste de configuração que depende
dele. Está documentado em `docs/backend.md` §8.6 — **leia essa seção antes de
mexer em qualquer coisa**, ela tem todas as medições já feitas e evita você
refazer trabalho.

Contexto de por que isso importa: minha tribo definiu no fórum (SQUAD 02, br143)
que devemos dominar o miolo do K25 e avançar até metade do K26. O bot já tem uma
"área de interesse" configurada para isso (`conquest.area_of_interest` =
`500–650 | 270–299`), e ela funciona. O problema é outro.

## O defeito

`BarbarianTrainPlanner._anchor_village()` em `game/conquest_planner.py` escolhe
**a aldeia com mais nobres** como referência, e `ConquestManager.find_target()`
aplica o filtro de `conquest.max_radius` a partir *dessa aldeia apenas*.

Consequência medida com o cache real das 28 aldeias:

| Medindo de… | Bárbaras do K25 alcançáveis com raio 30 |
|---|---|
| Qualquer aldeia gerenciada | **46 de 46** |
| BBM 001 (577\|306, a âncora de hoje) | **35 de 46** |

As 11 que somem são o bolsão a oeste, vizinho da BBM 023 (553|300): por exemplo
`#40382 543|296` está a 35,4 campos da BBM 001 mas a **10,8** da BBM 023.

Ou seja: o conjunto de alvos visíveis depende de onde os nobres se acumularam,
que é circunstância e não geografia. O comentário que justifica a âncora no
código está certo sobre *encurtar a viagem* e errado sobre *visibilidade* — vale
corrigir o comentário junto, senão o próximo leitor cai igual.

## O que eu quero

**1. Corrigir o desenho.** O planejador deve considerar os alvos alcançáveis por
**qualquer aldeia com nobres livres**, e usar a âncora só para ordenar/pontuar —
não para decidir quem entra na lista de candidatos.

**2. Subir `conquest.max_radius`** de 30 para **50** em `config.json`. Com 50,
as 46 do K25 ficam visíveis mesmo pela BBM 001. Não quero 70 (o máximo legal do
mundo): 70 campos são 40,8 h de voo só de ida, e 50 já resolve.

Faça na ordem que você achar melhor, mas me explique a decisão antes de
executar.

## Coisas que já foram verificadas — não refaça, mas confirme se for agir sobre elas

- **Alcance do nobre no br143 = 70 campos**, lido do servidor em
  `interface.php?func=get_config` → `<snob><max_dist>70</max_dist>`. O bot já lê
  isso desde 2026-09-17 (`WorldConfig._parse_snob` / `noble_max_distance`) e
  `ConquestManager._effective_radius()` já limita `max_radius` por ele. Ou seja,
  não dá mais para configurar acima do que o jogo aceita.
- **`no_barb_conquer` vem vazia** = conquistar bárbara é permitido neste mundo.
- **Pior caso origem → alvo entre todas as combinações: 50,5 campos**
  (BBM 024 588|314 → 543|291), dentro dos 70. Nenhuma aldeia seria recusada pelo
  jogo ao compor o trem multi-origem contra qualquer bárbara do K25.
- **Aumentar o raio muda a ordem dos candidatos a partir da 5ª posição**, porque
  a pontuação normaliza distância por `max_radius` mas o termo de pontos é fixo
  — então pontos passam a pesar relativamente mais. Com raio 70 o `#50833`
  (15,1 campos, 551 pts) cai da 5ª para a 8ª. Não é bug, é troca de preferência
  (~2 campos a mais por ~450 pontos a mais), e com raio 50 o efeito é menor.
  **Meça de novo com 50 antes de aplicar** e me diga o tamanho do efeito.

## Buraco conhecido, decide você se entra no escopo

O planejador monta o trem com todas as aldeias que têm nobre, mas **não verifica
se cada origem está dentro dos 70 campos do alvo**. Hoje não pode acontecer
(teto medido de 50,5 campos), e a falha seria segura — a sondagem de duração não
retorna valor e nada é agendado — mas sem dizer o motivo no log. Se for barato,
inclua uma guarda com mensagem clara.

## Estado do sistema

- O bot **não rodou ainda** com o planejador multi-origem. Todo esse código é de
  2026-09-17 e **nunca foi exercitado em campo** — 36 arquivos de teste cobrem a
  lógica, nenhum cobre a rede. O primeiro trem real ainda vai acontecer.
- `conquest.enabled: true`, `hunter.enabled: true`, `pvp_conquest.enabled: true`.
- 28 aldeias em x 553–588, y 296–318 (quase todas no K35, três já no K25).
- Nobres hoje: 3 na BBM 001, 2 na BBM 011, zero nas outras 26.

## Regras do repositório que se aplicam aqui

`CLAUDE.md` é leitura obrigatória. Os pontos que mais pegam neste trabalho:

- **Mudanças em `ConquestManager` afetam tropas reais.** Revisar com cautela
  extra antes de considerar pronto.
- **Ao alargar o conjunto de valores que uma função devolve, reler cada
  consumidor** (3º padrão, corolário do Lote 6). Mudar quem entra na lista de
  candidatos é exatamente isso.
- **Nunca commitar `config.json`.** Só `config.example.json`.
- **Não rodar teste que escreva em `cache/`** — é estado real de produção. Mede
  o tamanho e a contagem de `cache/` antes e depois da suíte para confirmar.
- Rodar a suíte assim (cada arquivo roda sozinho, sem pytest):
  ```powershell
  foreach ($t in (Get-ChildItem tests/test_*.py)) { python $t.FullName; if ($LASTEXITCODE -ne 0) { $t.Name } }
  ```
  ⚠️ Não use `2>&1` com `$?` no PowerShell 5.1 — ele marca falha mesmo com exit
  0. Use `$LASTEXITCODE`.
- **Escreva teste pontual** para a lógica nova, com os números reais acima como
  fixture.
- O webmanager roda com `DEBUG=False` e **não recarrega template nem módulo**;
  se mexer nele, precisa reiniciar para ver.

## Depois

Quando terminar, os próximos dois itens da minha fila (já registrados em
`docs/backend.md` §8.5) são a coleta: um botão no painel para ativar em todas as
aldeias, e depois o teto automático + desbloqueio automático de coletas. **Não
faça esses agora**, só não me deixe perder de vista.
