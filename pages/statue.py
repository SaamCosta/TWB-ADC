"""
Feature 24 (fase 1) — leitura do estado do(s) Paladino(s) via screen=statue.

Somente leitura: nenhuma automação ativa (treino por XP, re-especialização,
recrutamento) acontece aqui — apenas extração de dados para exibição no
webmanager. Ver docs/backlog.md (Feature 24) e docs/game_comparison.md item 4.
"""
import json
import re
from typing import Dict, List, Optional

from requests import Response

from core.extractors import Extractor
from core.request import WebWrapper


class StatuePage:
    """
    Representa a página screen=statue&mode=overview — visão de toda a conta
    dos slots de Paladino (paladinos recrutados + slots ainda bloqueados por
    número de aldeias).

    Só precisa ser buscada uma vez por conta (não uma vez por aldeia), já que
    o roster de Paladinos é compartilhado entre todas as aldeias do jogador —
    diferente de, por exemplo, bandeiras ou construção, que são por aldeia.
    """

    def __init__(self, wrapper: WebWrapper, village_id):
        self.wrapper: WebWrapper = wrapper
        self.village_id = village_id
        self.result_get: Optional[Response] = self._get_statue_overview()

        # Guard: timeout de rede ou sessão expirada retorna None de get_url
        if self.result_get is None:
            raise RuntimeError(
                "Statue page returned None — likely a network timeout or expired session. "
                "The bot will retry on the next cycle."
            )

        text = self.result_get.text
        self.statue_level: Optional[int] = self._parse_statue_level(text)
        self.knights: Dict[str, dict] = self._parse_knights(text)
        self.slot_thresholds: List[int] = self._parse_slot_thresholds(text)
        self.village_count: Optional[int] = self._parse_village_count(text)
        self.locked_slot_thresholds: List[int] = self._locked_slots(
            self.slot_thresholds, self.village_count
        )

    def _get_statue_overview(self):
        return self.wrapper.get_action(self.village_id, "statue&mode=overview")

    @staticmethod
    def _parse_statue_level(text: str) -> Optional[int]:
        match = re.search(r"Est[aá]tua\s*\(N[ií]vel\s*(\d+)\)", text)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_balanced(text: str, start: int) -> Optional[str]:
        """
        Dado o índice de um caractere de abertura ('{' ou '['), retorna a
        substring desde esse índice até o fechamento correspondente,
        ignorando corretamente colchetes/chaves que apareçam dentro de
        strings JSON entre aspas (inclusive aspas escapadas).

        Necessário porque o payload de BuildingStatue.receiveKnightsData(...)
        é um JSON profundamente aninhado (skills, branch_investments,
        home_village, usable_regimens...) — um regex não-guloso simples como
        os já usados em core/extractors.py (`\\{.+?\\}`) pararia no primeiro
        "}" interno em vez do fim real do objeto.
        """
        if start >= len(text):
            return None
        open_ch = text[start]
        close_ch = {"{": "}", "[": "]"}.get(open_ch)
        if close_ch is None:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    @staticmethod
    def _call_arguments(text: str, marker: str, count: int) -> List[object]:
        """
        Devolve os `count` primeiros argumentos posicionais da chamada JS que
        começa em `marker`, já parseados de JSON, usando varredura de
        colchetes balanceados em vez de regex guloso.

        Para no primeiro argumento que não seja objeto/array — é o que
        encerra `receiveKnightsData([], {...}, 0)` no `0` literal — e devolve
        o que já tinha coletado. Marcador ausente, JSON inválido ou markup
        diferente do esperado resultam em lista curta/vazia, nunca exceção:
        quem chama decide o fallback.
        """
        start = text.find(marker)
        if start == -1:
            return []

        i = start + len(marker)
        args: List[object] = []
        while len(args) < count:
            while i < len(text) and text[i] in " \t\r\n,":
                i += 1
            if i >= len(text) or text[i] not in "{[":
                break
            raw = StatuePage._extract_balanced(text, i)
            if raw is None:
                break
            try:
                args.append(json.loads(raw, strict=False))
            except (json.JSONDecodeError, ValueError):
                break
            i += len(raw)
        return args

    @staticmethod
    def _parse_knights(text: str) -> Dict[str, dict]:
        """
        Extrai o 2º argumento de:
            BuildingStatue.receiveKnightsData([...], {...knights...}, N);
        (dict de paladinos, chave = knight_id). O 1º argumento é um array
        vazio nas amostras coletadas e o 3º é o literal `0`.
        """
        args = StatuePage._call_arguments(text, "BuildingStatue.receiveKnightsData(", 2)
        if len(args) >= 2 and isinstance(args[1], dict):
            return args[1]
        return {}

    @staticmethod
    def _parse_slot_thresholds(text: str) -> List[int]:
        """
        Número de aldeias necessário para abrir cada slot de Paladino, lido do
        3º argumento posicional de:
            BuildingStatue.initImmutables({skills}, {branches}, [1,3,5,...], {premium});

        Confirmado na resposta HTTP real do br143 em 2026-08-16:
        `[1,3,5,10,20,35,50,65,80,100]`.

        A versão anterior desta leitura regexava o texto renderizado
        ("Obtenha N aldeias para desbloquear este slot") por considerá-lo mais
        fiel que "uma constante fixa do JS". O texto era de fato mais fiel e
        **nunca chegava até aqui**: ele só existe depois que o JS do jogo monta
        o template no navegador, então o parser devolvia lista vazia em todo
        ciclo. O argumento posicional, ao contrário, vem server-side na mesma
        resposta que o bot já lê — e por vir por requisição, continua
        acompanhando a configuração do mundo em vez de ser um número chumbado
        no bot.
        """
        args = StatuePage._call_arguments(text, "BuildingStatue.initImmutables(", 3)
        if len(args) >= 3 and isinstance(args[2], list):
            return sorted({int(n) for n in args[2] if isinstance(n, int)})
        return []

    @staticmethod
    def _parse_village_count(text: str) -> Optional[int]:
        """
        Total de aldeias da conta, de `TribalWars.updateGameData(...)`
        (`player.villages`, que vem como string). É o número que decide quais
        slots estão abertos — e é da conta inteira, não das aldeias que o bot
        gerencia, que podem ser um subconjunto.
        """
        try:
            state = Extractor.game_state(text) or {}
        except (json.JSONDecodeError, ValueError):
            return None
        try:
            return int((state.get("player") or {}).get("villages"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _locked_slots(thresholds: List[int], village_count: Optional[int]) -> List[int]:
        """
        Sem saber quantas aldeias a conta tem não dá para dizer o que está
        bloqueado — devolve vazio em vez de chutar que tudo está bloqueado,
        que apareceria na tela como uma afirmação falsa.
        """
        if village_count is None:
            return []
        return [t for t in thresholds if t > village_count]
