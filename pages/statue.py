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
        self.locked_slot_thresholds: List[int] = self._parse_locked_slots(text)

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
    def _parse_knights(text: str) -> Dict[str, dict]:
        """
        Extrai o JSON de:
            BuildingStatue.receiveKnightsData([...], {...knights...}, N);

        O primeiro argumento (array, vazio nas amostras coletadas) e o
        segundo (dict de paladinos, chave = knight_id) são extraídos via
        varredura de colchetes balanceados em vez de regex guloso, para não
        quebrar com o conteúdo aninhado.
        """
        start_marker = "BuildingStatue.receiveKnightsData("
        start = text.find(start_marker)
        if start == -1:
            return {}

        i = start + len(start_marker)
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i >= len(text) or text[i] != "[":
            return {}
        first_arg = StatuePage._extract_balanced(text, i)
        if first_arg is None:
            return {}

        j = i + len(first_arg)
        while j < len(text) and text[j] not in "{[":
            j += 1
        if j >= len(text) or text[j] != "{":
            return {}
        second_arg = StatuePage._extract_balanced(text, j)
        if second_arg is None:
            return {}

        try:
            return json.loads(second_arg, strict=False)
        except (json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def _parse_locked_slots(text: str) -> List[int]:
        """
        Slots bloqueados renderizam "Obtenha N aldeias para desbloquear este
        slot." — parsear esse texto é mais robusto do que depender do 3º
        argumento posicional de BuildingStatue.initImmutables(...), já que
        reflete o que foi de fato renderizado em vez de uma constante fixa do
        JS que teoricamente poderia variar por configuração de mundo.

        Limitação conhecida: não distingue um slot já desbloqueado mas ainda
        sem paladino recrutado (não há amostra desse estado nesta sessão) —
        nesse caso ele simplesmente não aparece nem aqui nem em `knights`.
        """
        return [
            int(n)
            for n in re.findall(r"Obtenha (\d+) aldeias para desbloquear este slot", text)
        ]
