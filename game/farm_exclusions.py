"""
Por que este alvo de farm nao foi atacado neste ciclo.

O `AttackManager` ja calcula o motivo de cada descarte -- e joga fora. Tudo
que sobra e um par de contadores no log (`Farm targets: N Ignored targets: M`)
e uma coleção de linhas em DEBUG que ninguem le. O custo disso ja foi medido
em campo: em 2026-08-19 uma aldeia teve 100% dos ataques recusados pelo
servidor e ninguem soube por que ate alguem instrumentar a falha na mao
(decimo terceiro e decimo quarto padroes do CLAUDE.md). O motivo estava
disponivel o tempo todo, no `error_box` que o proprio jogo devolve.

Este modulo e so o registrador: guarda `(alvo, codigo, detalhe, quando)` do
ciclo corrente de farm de UMA aldeia e grava em
`cache/farm_exclusions/<village_id>.json` no fim do `run()`.

Tres decisoes que nao sao detalhe:

1. **E snapshot do ultimo ciclo, nao log acumulado.** O arquivo e reescrito
   inteiro a cada `flush()`. Motivo do sexto padrao: o motivo de exclusao e uma
   afirmacao sobre um estado do mundo que muda em horas ("intervalo entre
   ataques", "aguardando relatorio de espiao"). Acumular produziria uma lista
   onde a maioria das linhas ja e mentira, sem nada distinguindo as vivas das
   mortas. Quem quiser serie historica precisa de um contrato de evento com
   `observed_at` por ocorrencia -- que e o `FND-01`, e nao existe ainda.

2. **`observed_at` e obrigatorio e por entrada.** O consumidor precisa poder
   dizer a idade da leitura; o painel nao pode apresentar isso como estado
   atual.

3. **O teto so corta a fase de selecao.** Uma aldeia ve centenas de aldeias no
   scan de mapa e descarta quase todas por distancia ou dono -- entradas
   numerosas e sem valor diagnostico. As da fase de tentativa sao no maximo
   `max_farms` e sao exatamente as interessantes. Cortar as duas pelo mesmo
   teto perderia as que importam; por isso o corte e por fase, e `truncated`
   diz que houve corte em vez de a lista simplesmente terminar curta (vigesimo
   sexto padrao: lista curta e indistinguivel de lista completa).
"""
import time

from core.filemanager import FileManager

CACHE_DIR = "cache/farm_exclusions"

# Fase de selecao: filtros de `get_targets()`, avaliados contra toda aldeia do
# scan de mapa desta aldeia.
FASE_SELECAO = "selecao"
# Fase de tentativa: o alvo sobreviveu aos filtros e o bot chegou a decidir
# sobre ele individualmente (`can_attack()` / `send_farm()` / `attack()`).
FASE_TENTATIVA = "tentativa"

# Vocabulario fechado. Cada codigo carrega a fase, um rotulo curto para a
# interface e o que o usuario poderia mexer -- ou `None` quando nao ha nada a
# mexer e a exclusao e uma observacao sobre o mundo, nao uma escolha nossa.
REASONS = {
    # --- selecao -----------------------------------------------------------
    "dono_jogador": {
        "phase": FASE_SELECAO,
        "label": "Aldeia de jogador",
        "detail_help": "O farm automatico so ataca barbara; aldeia de jogador "
                       "precisa estar em `additional_farms` da aldeia de origem.",
        "knob": "villages.<id>.additional_farms",
    },
    "janela_noturna_jogador": {
        "phase": FASE_SELECAO,
        "label": "Janela 23h-8h (alvo de jogador)",
        "detail_help": "Alvo de jogador nao e atacado entre 23h e 8h. Regra fixa "
                       "no codigo, sem chave de configuracao.",
        "knob": None,
    },
    "pontos_acima_max": {
        "phase": FASE_SELECAO,
        "label": "Pontos acima do maximo",
        "detail_help": "O alvo passou do teto de pontos aceito para farm.",
        "knob": "farms.max_points",
    },
    "pontos_abaixo_min": {
        "phase": FASE_SELECAO,
        "label": "Pontos abaixo do minimo",
        "detail_help": "O alvo e pequeno demais para valer o envio.",
        "knob": "farms.min_points",
    },
    "pontos_maiores_que_os_meus": {
        "phase": FASE_SELECAO,
        "label": "Alvo maior que a aldeia de origem",
        "detail_help": "Comparacao com os pontos da propria aldeia.",
        "knob": "farms.attack_higher_points",
    },
    "longe_demais": {
        "phase": FASE_SELECAO,
        "label": "Fora do raio de farm",
        "detail_help": "Distancia maior que o raio configurado. Raio maior tambem "
                       "significa viagem mais longa, nao so mais alvos.",
        "knob": "farms.search_radius",
    },
    "alvo_de_conquista": {
        "phase": FASE_SELECAO,
        "label": "Alvo de conquista",
        "detail_help": "A aldeia esta na lista de conquista (barbara agendada, "
                       "com nobre no ar ou aguardando nobre extra, ou alvo PvP "
                       "em preparacao/agendado). O farm nunca ataca: um farm "
                       "que chega depois do nobre bate na propria guarnicao.",
        "knob": None,
    },
    "bloqueado_pelo_jogo": {
        "phase": FASE_SELECAO,
        "label": "Bloqueado pelo jogo",
        "detail_help": "O jogo ja recusou este alvo antes por um motivo que nao "
                       "depende de nos (protecao de iniciante, aldeia que sumiu).",
        "knob": None,
    },
    # --- tentativa ---------------------------------------------------------
    "fora_do_teto": {
        "phase": FASE_TENTATIVA,
        "label": "Fora do teto de alvos por ciclo",
        "detail_help": "O alvo passou nos filtros mas ficou abaixo da linha de "
                       "corte de `max_farms` na ordenacao por eficiencia.",
        "knob": "farms.max_farms",
    },
    "ciclo_encerrado_sem_tropa": {
        "phase": FASE_TENTATIVA,
        "label": "Ciclo encerrado antes de chegar aqui",
        "detail_help": "Nem o menor pacote cabia no que sobrou em casa, entao o "
                       "laco parou. Nao e uma afirmacao sobre este alvo.",
        "knob": None,
    },
    "sem_tropa_em_casa": {
        "phase": FASE_TENTATIVA,
        "label": "Tropa insuficiente em casa",
        "detail_help": "Contagem local, ja descontadas as reservas de conquista.",
        "knob": None,
    },
    "espiao_enviado": {
        "phase": FASE_TENTATIVA,
        "label": "Explorador enviado no lugar do ataque",
        "detail_help": "O bot precisa de relatorio antes de atacar este alvo. "
                       "Nao e exclusao: e a etapa anterior.",
        "knob": "farms.farm_scout_amount",
    },
    "sem_espiao": {
        "phase": FASE_TENTATIVA,
        "label": "Explorador indisponivel",
        "detail_help": "O bot quis explorar antes de atacar e nao havia espioes "
                       "suficientes em casa. O alvo fica parado ate haver.",
        "knob": "farms.farm_scout_amount",
    },
    "aguardando_relatorio_espiao": {
        "phase": FASE_TENTATIVA,
        "label": "Aguardando relatorio de exploracao",
        "detail_help": "O explorador saiu e o relatorio ainda nao chegou.",
        "knob": None,
    },
    "relatorio_viu_tropa": {
        "phase": FASE_TENTATIVA,
        "label": "Relatorio viu tropa inimiga",
        "detail_help": "O ultimo relatorio mostrou defesa no alvo; ele sera "
                       "reavaliado quando o relatorio envelhecer.",
        "knob": None,
    },
    "inseguro_sem_relatorio": {
        "phase": FASE_TENTATIVA,
        "label": "Marcado inseguro e sem relatorio",
        "detail_help": "O cache marca o alvo como inseguro e nao ha exploracao "
                       "para revisar a decisao.",
        "knob": None,
    },
    "intervalo_entre_ataques": {
        "phase": FASE_TENTATIVA,
        "label": "Dentro do intervalo entre ataques",
        "detail_help": "O alvo foi atacado ha pouco e ainda nao recompos saque.",
        "knob": "farms.default_away_time / full_loot_away_time / low_loot_away_time",
    },
    "recusado_pelo_jogo": {
        "phase": FASE_TENTATIVA,
        "label": "Recusado pelo jogo",
        "detail_help": "Texto lido do `error_box` da resposta do servidor. E a "
                       "unica fonte que diz o motivo real da recusa.",
        "knob": None,
    },
    "paz_forcada": {
        "phase": FASE_TENTATIVA,
        "label": "Paz forcada",
        "detail_help": "O ataque nao sai, ou chegaria depois do inicio da janela.",
        "knob": "farms.forced_peace_times",
    },
    "sem_coordenada": {
        "phase": FASE_TENTATIVA,
        "label": "Sem coordenada conhecida",
        "detail_help": "Nem o scan desta aldeia nem `cache/villages` sabem onde o "
                       "alvo fica; o ataque nao pode nem ser montado.",
        "knob": None,
    },
    "falha_de_rede": {
        "phase": FASE_TENTATIVA,
        "label": "Requisicao sem resposta",
        "detail_help": "Timeout ou erro de rede. Resultado desconhecido: nao prova "
                       "que o ataque nao saiu.",
        "knob": None,
    },
    # --- desfecho positivo, registrado de proposito -------------------------
    "atacado": {
        "phase": FASE_TENTATIVA,
        "label": "Atacado neste ciclo",
        "detail_help": "Envio confirmado pelo servidor.",
        "knob": None,
    },
}

# Teto de entradas guardadas da fase de selecao. Uma aldeia ve algumas centenas
# de aldeias no scan; guardar todas nao acrescenta diagnostico e infla o
# arquivo que o webmanager le a cada request.
MAX_SELECAO = 400


class FarmExclusionLog:
    """
    Registrador por aldeia. Uma instancia vive junto com o `AttackManager`
    daquela aldeia e e reaproveitada entre ciclos -- por isso `begin()` zera o
    buffer, e por isso os mutaveis nascem em `__init__` (primeiro padrao do
    CLAUDE.md).
    """

    def __init__(self, village_id=None):
        self.village_id = str(village_id) if village_id is not None else None
        self.entries = {}
        self.summary = {}
        self.truncated = False
        self.cycle_started_at = None
        self._selecao_guardadas = 0

    def begin(self):
        """Comeca um ciclo de farm. Descarta o que sobrou do anterior."""
        self.entries = {}
        self.summary = {}
        self.truncated = False
        self._selecao_guardadas = 0
        self.cycle_started_at = int(time.time())
        return self

    def record(self, target_id, code, detail=None):
        """
        Registra o motivo pelo qual `target_id` nao recebeu ataque agora.

        Codigo desconhecido e aceito e contabilizado: recusar aqui trocaria um
        diagnostico incompleto por um crash no caminho quente do farm, que e o
        oposto do que esta feature existe para fazer. O consumidor degrada
        mostrando o codigo cru.
        """
        if target_id is None or not code:
            return
        target_id = str(target_id)
        self.summary[code] = self.summary.get(code, 0) + 1

        phase = REASONS.get(code, {}).get("phase", FASE_TENTATIVA)
        if phase == FASE_SELECAO:
            if target_id not in self.entries and self._selecao_guardadas >= MAX_SELECAO:
                self.truncated = True
                return
            if target_id not in self.entries:
                self._selecao_guardadas += 1

        self.entries[target_id] = {
            "code": code,
            "detail": None if detail is None else str(detail),
            "phase": phase,
            "observed_at": int(time.time()),
        }

    def attacked(self, target_id, detail=None):
        """Desfecho positivo. Sobrescreve uma recusa anterior do mesmo ciclo."""
        self.record(target_id, "atacado", detail)

    def flush(self):
        """
        Grava o snapshot do ciclo. Nunca levanta: uma falha de disco aqui nao
        pode derrubar o farm, que e a operacao real.
        """
        if self.village_id is None:
            return False
        payload = {
            "village_id": self.village_id,
            "cycle_started_at": self.cycle_started_at,
            "observed_at": int(time.time()),
            "truncated": self.truncated,
            "max_selecao": MAX_SELECAO,
            "summary": dict(sorted(self.summary.items(), key=lambda kv: -kv[1])),
            "targets": self.entries,
        }
        try:
            FileManager.create_directory(FileManager.get_path(CACHE_DIR))
            FileManager.save_json_file(
                payload, "%s/%s.json" % (CACHE_DIR, self.village_id)
            )
            return True
        except Exception:
            return False
