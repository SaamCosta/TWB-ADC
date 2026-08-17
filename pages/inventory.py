"""
Feature 25 (fase 1) — leitura do inventário (Perfil > Inventário).

Somente leitura: nenhum item é ativado, consumido ou presenteado aqui — só
extração do catálogo e das quantidades para exibição no webmanager. A política
de "qual boost ativar e quando" é a fase 2 e ainda não tem desenho
(ver docs/backlog.md, Feature 25).

⚠️ De onde vem o dado, e por que são DUAS requisições.

O levantamento de campo de 2026-08-16 catalogou os itens a partir de
`window.Inventory.item_data` no navegador. Esse objeto **não existe** na
resposta HTTP que o bot lê: o `<script>` inline de `screen=inventory` traz só
os enums e um `Inventory.init(0)`; o catálogo chega depois, por AJAX. Escrever
o parser contra o objeto do navegador teria reproduzido exatamente o bug do
`_parse_locked_slots()` da Feature 24 — um parser que devolve vazio em todo
ciclo e falha em silêncio. Confirmado buscando as duas URLs com a sessão do
bot antes de escrever qualquer linha daqui.

  1. `screen=inventory` (HTML) — traz os **enums traduzidos**:
     `Inventory.item_types`, `Inventory.item_categories`, `Inventory.item_tags`.
     Eles não vêm no JSON do AJAX, que só tem os números. Ler daqui em vez de
     chumbar "1 = Premium, 2 = Consumível…" no código é a mesma regra do quinto
     padrão do CLAUDE.md: enum de jogo se mapeia contra o servidor.
  2. `screen=inventory&ajax=get_inventory` (JSON) — traz os **itens**:
     `{"inventory": {chave: {amount, ...}}, "data": {chave: {name, ...}},
       "expire": ...}`. Endpoint nomeado no próprio JS do jogo
     (`Inventory.dff6db.js_`, `loadInventory`), GET, sem token `h`.

O HTML é opcional: sem ele os itens continuam sendo lidos, só ficam com
rótulos genéricos ("Categoria 4"). O JSON é obrigatório — sem ele não há o que
mostrar, e o manager tenta de novo no ciclo seguinte.
"""
import html as html_lib
import json
import re
from typing import Dict, List, Optional

from core.extractors import Extractor
from core.request import WebWrapper

# `<br>` em qualquer das formas que o jogo usa (`<br />`, `<br/>`, `<br>`).
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


class InventoryPage:
    """
    Estado do inventário da conta. Como o inventário é do jogador e não da
    aldeia, basta buscar a partir de uma aldeia qualquer — o `village_id` só
    entra na URL porque o jogo exige um contexto de aldeia.
    """

    def __init__(self, wrapper: WebWrapper, village_id):
        self.wrapper: WebWrapper = wrapper
        self.village_id = village_id

        screen_text = self._get_inventory_screen()
        payload = self._get_inventory_payload()

        if payload is None:
            raise RuntimeError(
                "ajax=get_inventory não devolveu JSON utilizável — timeout, "
                "sessão expirada ou markup novo. O bot tenta de novo no "
                "próximo ciclo."
            )

        self.item_types: Dict[str, str] = self._parse_enum(screen_text, "item_types")
        self.item_categories: Dict[str, str] = self._parse_enum(screen_text, "item_categories")
        self.item_tags: Dict[str, list] = self._parse_tag_labels(screen_text)
        self.enums_available: bool = bool(self.item_types and self.item_categories)

        self.items: List[dict] = self._build_items(payload)

    # ------------------------------------------------------------------ rede

    def _get_inventory_screen(self) -> str:
        """
        HTML da tela, só pelos enums. `get_url` devolve None em qualquer
        exceção (core/request.py), então a ausência é tratada como "sem
        rótulos", não como falha: os itens ainda valem sem eles.
        """
        res = self.wrapper.get_action(self.village_id, "inventory")
        if res is None:
            return ""
        return res.text

    def _get_inventory_payload(self) -> Optional[dict]:
        """
        `get_api_data` devolve o dict do JSON, mas também devolve o próprio
        Response quando `.json()` falha e None quando a requisição falha ou
        não veio 200 — daí o isinstance em vez de confiar no retorno.

        ⚠️ O jogo responde em **duas formas** para a mesma URL, conforme o
        cabeçalho `TribalWars-Ajax`:

          * com ele (é o que `get_api_data` sempre manda), o payload vem
            embrulhado em `{"response": {...}, "game_data": {...}}`;
          * sem ele, vem cru: `{"inventory": ..., "data": ..., "expire": ...}`.

        Custou um smoke test contra o servidor: a exploração inicial usou só
        `X-Requested-With` e viu a forma crua, então um parser escrito contra
        ela teria falhado em produção com o wrapper de verdade — passando nos
        testes o tempo todo. `{"response": false}` é o que o jogo devolve para
        uma ação desconhecida, e cai no mesmo `isinstance` sem virar exceção.
        """
        raw = self.wrapper.get_api_data(
            self.village_id, "get_inventory", {"screen": "inventory"}
        )
        if not isinstance(raw, dict):
            return None
        payload = raw.get("response") if isinstance(raw.get("response"), dict) else raw
        if not isinstance(payload.get("data"), dict):
            # Inventário vazio ainda traz "data": {}; a chave sumir significa
            # que a resposta não é a que esperamos.
            return None
        return payload

    # ----------------------------------------------------------------- enums

    @staticmethod
    def _parse_enum(text: str, name: str) -> Dict[str, str]:
        """
        `Inventory.item_types = {"1":"Funcionalidade", ...};` — chaves vêm como
        string no JSON do jogo e são mantidas assim, para não depender de os
        ids serem sempre numéricos.
        """
        data = Extractor.js_object_after(text, r"Inventory\.%s\s*=\s*" % name)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    @staticmethod
    def _parse_tag_labels(text: str) -> Dict[str, list]:
        """
        `Inventory.item_tags = {"rarity":[...], "use_type":[...]}` — listas
        indexadas pelo valor da tag, com o índice 0 significando "Nenhum".
        """
        data = Extractor.js_object_after(text, r"Inventory\.item_tags\s*=\s*")
        if not isinstance(data, dict):
            return {}
        return {
            str(k): [str(item) for item in v]
            for k, v in data.items()
            if isinstance(v, list)
        }

    # ----------------------------------------------------------------- itens

    def _build_items(self, payload: dict) -> List[dict]:
        catalog = payload.get("data") or {}
        owned = payload.get("inventory") or {}
        expiry = self._normalize_expiry(payload.get("expire"))

        items = []
        for key, entry in catalog.items():
            if not isinstance(entry, dict):
                continue
            own = owned.get(key) if isinstance(owned.get(key), dict) else {}
            type_id = self._int(entry.get("type"))
            category_id = self._int(entry.get("category"))
            items.append({
                "item_key": key,
                "item_id": self._int(entry.get("item_id")),
                "instance_id": self._int(entry.get("instance_id")),
                "name": entry.get("name") or key,
                # admin_name é o nome interno, e é o único campo que carrega
                # percentual e duração juntos ("Bônus de ataque (5%) 1 day").
                "admin_name": entry.get("admin_name") or "",
                "amount": self._int(own.get("amount")),
                "type": type_id,
                "type_name": self.item_types.get(str(type_id), "Tipo %s" % type_id),
                "category": category_id,
                "category_name": self.item_categories.get(
                    str(category_id), "Categoria %s" % category_id
                ),
                "tags": self._resolve_tags(entry.get("tags")),
                "description_lines": self._description_lines(entry.get("descriptions")),
                "actions": [
                    {"name": a.get("name") or "", "link": a.get("link") or ""}
                    for a in (entry.get("actions") or [])
                    if isinstance(a, dict)
                ],
                "instance_data": self._parse_instance_data(own.get("instance_data")),
                "image": entry.get("image") or "",
                "expires_at": expiry.get(key, []),
            })

        items.sort(key=lambda i: (i["category"], i["name"], i["item_key"]))
        return items

    @staticmethod
    def _normalize_expiry(expire) -> Dict[str, list]:
        """
        Veio `[]` na amostra real — o PHP serializa array associativo vazio
        como lista. Quando houver item expirando vira objeto
        (`{chave: [ts, ...]}`, que é como o JS o percorre). Aceitar as duas
        formas evita um crash que só apareceria com um item ativo no relógio.
        """
        if not isinstance(expire, dict):
            return {}
        out = {}
        for key, stamps in expire.items():
            if not isinstance(stamps, (list, tuple)):
                stamps = [stamps]
            parsed = [InventoryPage._int(s) for s in stamps]
            out[str(key)] = [s for s in parsed if s]
        return out

    def _resolve_tags(self, tags) -> List[dict]:
        resolved = []
        for tag in (tags or []):
            if not isinstance(tag, dict):
                continue
            tag_type = str(tag.get("type") or "")
            index = self._int(tag.get("tag"))
            labels = self.item_tags.get(tag_type) or []
            label = labels[index] if 0 <= index < len(labels) else ""
            # O índice 0 é "Nenhum" em todas as listas — não vira badge.
            resolved.append({
                "type": tag_type,
                "value": index,
                "label": label if index > 0 else "",
            })
        return resolved

    @staticmethod
    def _description_lines(descriptions) -> List[dict]:
        """
        Achata as descrições em linhas de texto puro. O jogo manda HTML aqui:
        `<br />` separando linhas e `<img>` de unidade antes do nome dela
        ("<img unit_spear /> Lanceiro (~3.5%)"). Guardar o HTML cru obrigaria
        o template a renderizá-lo com `| safe`, o que é injeção de markup do
        servidor direto na página do webmanager — preferimos texto.
        """
        lines = []
        for block in (descriptions or []):
            if not isinstance(block, dict):
                continue
            color = block.get("color") or ""
            for chunk in BR_RE.split(str(block.get("text") or "")):
                text = html_lib.unescape(TAG_RE.sub("", chunk)).strip()
                if text:
                    lines.append({"text": text, "color": color})
        return lines

    @staticmethod
    def _parse_instance_data(raw) -> Optional[dict]:
        """
        Vem como *string* de JSON quando existe (livro de habilidade:
        `"{\\"skill_id\\":8}"`), e como null na maioria dos itens.
        """
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            parsed = json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _int(value) -> int:
        """Quantidades e ids vêm como string no JSON do jogo ("amount": "4")."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
