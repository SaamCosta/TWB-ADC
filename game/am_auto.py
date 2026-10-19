"""
Gerente de conta automático (docs/backend.md §8.68, `P-GERENTE-AUTO`):
leitura das listas da conta e gravação no jogo. A decisão é de
`core/am_auto.py`; aqui só se lê, grava e confere.

Uma instância por processo (como `MintManager`), injetada em toda `Village`.

LEITURAS DA CONTA (no máximo uma vez por `account_refresh_hours`, padrão 24 h,
e de novo quando o gerente volta a ficar ativo)
-------------------------------------------------------------------------
`am_troops` (modelos de tropa com a meta, e a reserva atual de cada aldeia) e
`overview_villages&mode=groups&type=static` (grupo de cada aldeia). As duas
paginam a 50 e a conta tem 55 aldeias (26º padrão), e cada uma pede um
caminho diferente, sondado em 19/10:
- grupos: `page=1` e DEPOIS `page=0`; a visita seguinte sem `page` mostra a
  primeira página, ou seja, a tela do jogador fica como estava;
- tropas: um GET sem `page`. `page=-1` ("todos") FICA GRAVADO como
  preferência (a tela passou a mostrar as 55, e `page=0` não desfez), e
  `page=1` voltou vazio. A página padrão traz os modelos; a reserva de aldeia
  fora dela é a que o bot gravou.
3 GETs por dia.

GRAVAÇÕES (formulários em lote do próprio jogo; payloads lidos das telas,
§8.66 e §8.68)
------------------------------------------------------------------------
- construção / pesquisa: `screen=am_village|am_research&action=village_mass`,
  `action=apply`, `template=<id>`, `villages[]=<vid>`;
- tropas: `screen=am_troops&action=save_village&page=0`, a meta de cada
  unidade + `template_id` + `buffer_*` + `edit[]=<vid>` + `save`. O formulário
  regrava a META junto com a reserva, então a meta enviada é sempre a do modelo
  do papel, lida da própria tela;
- grupos: `screen=overview_villages&action=bulk_edit_villages&mode=groups&type=static&partial`,
  `village_ids[]`, `selected_group`, `add_to_group`/`remove_from_group`.

`auto_manage: "dry_run"` loga o que faria e não grava nada.
"""
import logging
import time

from core import am_auto
from core.extractors import Extractor
from core.filemanager import FileManager
from core.village_label import village_label

STATE_PATH = "cache/am_auto.json"
DEFAULT_REFRESH_HOURS = 24

logger = logging.getLogger("GerenteAuto")


def _refusal(res):
    """Motivo da recusa, ou None. `Extractor.error_box_text` devolve texto
    SEMPRE (ele explica uma recusa já detectada, não detecta): a detecção é a
    presença do `error_box`, a mesma âncora dos outros chamadores."""
    if res is None:
        return "sem resposta"
    text = getattr(res, "text", "") or ""
    if '<div class="error_box">' not in text:
        return None
    return Extractor.error_box_text(res)


class AccountManagerAuto:
    def __init__(self, wrapper, clock=time.time, path=STATE_PATH):
        self.wrapper = wrapper
        self.clock = clock
        self.path = path
        state = FileManager.load_json_file(path) if path else None
        state = state if isinstance(state, dict) else {}
        self.applied = state.get("applied") or {}
        self.account = state.get("account") or {}
        self._manager_was_active = None

    # -- estado ------------------------------------------------------------

    def _save(self):
        if not self.path:
            return
        try:
            FileManager.save_json_file({"applied": self.applied, "account": self.account},
                                       self.path)
        except Exception as exc:
            logger.warning("GerenteAuto: não gravei %s (%s)", self.path, exc)

    def troop_templates(self):
        return self.account.get("templates") or None

    def troop_row(self, vid):
        """A reserva atual do gerente de tropas na aldeia: a linha lida da
        tela; sem ela (aldeia fora da página), a última que o bot gravou; sem
        nenhuma das duas, zero (o padrão do jogo)."""
        row = (self.account.get("troop_rows") or {}).get(str(vid))
        if row is not None:
            return row
        applied = (self.applied.get(str(vid)) or {}).get("troops") or {}
        return dict(applied.get("buffer") or {k: 0 for k in am_auto.BUFFER_KEYS})

    # -- leitura da conta --------------------------------------------------

    def refresh_account(self, cfg, any_vid, manager_active):
        """Relê `am_troops` e grupos quando a leitura passou da validade ou o
        gerente acabou de voltar. Devolve True se leu."""
        just_back = manager_active and self._manager_was_active is False
        self._manager_was_active = manager_active
        if not manager_active:
            return False
        if just_back and self.applied:
            # Renovação: o jogo zerou os modelos, e a trava contra laço não pode
            # segurar a reaplicação de quem foi aplicado antes do vencimento.
            logger.info("GerenteAuto: gerente voltou -- trava de reaplicação zerada")
            self.applied = {}
        hours = float((cfg or {}).get("account_refresh_hours", DEFAULT_REFRESH_HOURS))
        age = self.clock() - float(self.account.get("read_at", 0))
        if not just_back and age < hours * 3600:
            return False
        # Tropas: um GET SEM `page`. Sondado em 19/10: `page=-1` fica gravado
        # como preferência do jogador (a tela passa a mostrar todas, e `page=0`
        # não desfaz), e `page=1` voltou vazio. A página padrão já traz os
        # modelos com a meta; aldeia fora dela usa o que o bot gravou.
        res = self.wrapper.get_url("game.php?village=%s&screen=am_troops" % any_vid)
        troops = Extractor.account_manager_troops(res) if res is not None else None
        groups = self._read_pages(
            "game.php?village=%s&screen=overview_villages&mode=groups&type=static" % any_vid,
            Extractor.village_groups)
        if troops is None or groups is None:
            logger.warning("GerenteAuto: leitura da conta incompleta (tropas %s, grupos %s); "
                           "fica para o próximo ciclo", troops is not None, groups is not None)
            return False
        # Unidades do formulário = colunas da lista (o mundo sem arqueiro não
        # tem `archer`/`marcher`, mas o JSON dos modelos tem, com 0).
        units = sorted({k for row in troops["villages"].values() for k in row
                        if not k.startswith("buffer_")})
        self.account = {
            "read_at": int(self.clock()),
            "templates": troops["templates"],
            "troop_units": units,
            "troop_rows": troops["villages"],
            "groups": groups["groups"],
            "membership": groups["villages"],
        }
        self._save()
        logger.info("GerenteAuto: conta lida -- %d modelo(s) de tropa, %d aldeia(s) no "
                    "gerente de tropas, %d aldeia(s) nos grupos",
                    len(troops["templates"]), len(troops["villages"]), len(groups["villages"]))
        return True

    def _read_pages(self, url, parser):
        """Página 2 e depois a 1 (ver docstring do módulo); junta as aldeias."""
        merged = None
        for page in (1, 0):
            res = self.wrapper.get_url("%s&page=%d" % (url, page))
            data = parser(res) if res is not None else None
            if data is None:
                return None
            if merged is None:
                merged = data
            else:
                merged["villages"].update(data["villages"])
        return merged

    # -- grupos ------------------------------------------------------------

    def sync_groups(self, cfg, village_roles, any_vid):
        """Põe cada aldeia no grupo do papel. Só com leitura de grupos feita."""
        groups = self.account.get("groups")
        membership = self.account.get("membership")
        if not groups or membership is None:
            return 0
        changes = am_auto.group_changes(cfg, village_roles, membership, groups)
        names = {v: k for k, v in groups.items()}
        dry = am_auto.mode(cfg) == "dry_run"
        posts = 0
        for kind, button in (("remove", ("remove_from_group", "Remover")),
                             ("add", ("add_to_group", "Adicionar"))):
            for gid, vids in sorted(changes[kind].items()):
                labels = ", ".join(village_label(v) for v in vids)
                verb = "tira de" if kind == "remove" else "põe em"
                if dry:
                    logger.info("GerenteAuto [simulação]: %s o grupo %s: %s", verb, names[gid], labels)
                    continue
                data = [("village_ids[]", v) for v in vids]
                data += [("selected_group", str(gid)), button]
                res = self.wrapper.post_url(
                    "game.php?village=%s&screen=overview_villages&action=bulk_edit_villages"
                    "&mode=groups&type=static&partial&h=%s" % (any_vid, self.wrapper.last_h), data)
                posts += 1
                refusal = _refusal(res)
                if refusal:
                    logger.warning("GerenteAuto: grupo %s recusado (%s): %s", names[gid], refusal, labels)
                    continue
                for v in vids:
                    current = set(membership.get(v, []))
                    if kind == "add":
                        current.add(names[gid])
                    else:
                        current.discard(names[gid])
                    membership[v] = sorted(current)
                logger.info("GerenteAuto: %s o grupo %s: %s", verb, names[gid], labels)
        if posts:
            self._save()
        return posts

    # -- modelos por aldeia ------------------------------------------------

    def run_village(self, cfg, vid, role, widget, options, pending, reserve, totals_known=True):
        """Decide e aplica os modelos de UMA aldeia. Devolve as ações feitas."""
        vid = str(vid)
        now = self.clock()
        actions = am_auto.village_actions(
            cfg, role, widget, options, pending, self.applied.get(vid), reserve, now,
            troop_templates=self.troop_templates(), troop_row=self.troop_row(vid))
        if not actions:
            return []
        dry = am_auto.mode(cfg) == "dry_run"
        done = []
        for action in actions:
            label = {"construction": "construção", "research": "pesquisa",
                     "troops": "tropas"}[action["phase"]]
            what = "%s %s em %s (%s)" % (label, action["template"], village_label(vid),
                                         action["reason"])
            if dry:
                logger.info("GerenteAuto [simulação]: aplicaria %s", what)
                continue
            ok, detail = self._apply(vid, action)
            if ok:
                entry = {"at": int(now), "template": action["template_id"]}
                if action["phase"] == "troops":
                    entry["buffer"] = action["buffer"]
                self.applied.setdefault(vid, {})[action["phase"]] = entry
                done.append(action)
                logger.info("GerenteAuto: aplicado %s%s", what, detail)
            else:
                logger.warning("GerenteAuto: %s recusado: %s", what, detail)
        if done:
            self._save()
        return done

    def _apply(self, vid, action):
        h = self.wrapper.last_h
        if action["phase"] in ("construction", "research"):
            screen = "am_village" if action["phase"] == "construction" else "am_research"
            res = self.wrapper.post_url(
                "game.php?village=%s&screen=%s&action=village_mass&h=%s" % (vid, screen, h),
                [("action", "apply"), ("template", str(action["template_id"])),
                 ("villages[]", vid)])
            refusal = _refusal(res)
            if refusal:
                return False, refusal
            return True, " -- confere no próximo ciclo pelo widget"
        units = self.account.get("troop_units") or sorted(
            u for u in action["meta"] if u not in ("archer", "marcher"))
        data = [(u, str(action["meta"].get(u, 0))) for u in units]
        data.append(("template_id", str(action["template_id"])))
        data += [(k, str(v)) for k, v in action["buffer"].items()]
        data += [("edit[]", vid), ("save", "Salvar")]
        res = self.wrapper.post_url(
            "game.php?village=%s&screen=am_troops&action=save_village&page=0&h=%s" % (vid, h), data)
        refusal = _refusal(res)
        if refusal:
            return False, refusal
        parsed = Extractor.account_manager_troops(res)
        row = (parsed or {}).get("villages", {}).get(vid)
        rows = self.account.setdefault("troop_rows", {})
        if row is None:
            # Sem como conferir agora: guarda o que foi gravado, senão a
            # próxima aldeia-ciclo veria a reserva antiga e regravaria até a
            # próxima leitura da conta.
            rows[vid] = dict(action["meta"], **action["buffer"])
            return True, " -- aldeia fora da página de resposta, confere na próxima leitura da conta"
        rows[vid] = row
        if all(row.get(k) == v for k, v in action["buffer"].items()):
            return True, " -- conferido na tela"
        return False, "a tela não mostra a reserva gravada: %s" % {
            k: row.get(k) for k in action["buffer"]}
