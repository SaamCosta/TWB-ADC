"""
Gerente de conta automático (docs/backend.md §8.68, `P-GERENTE-AUTO`):
decisão pura, sem rede. Quem executa é `game/am_auto.py`.

POR QUE EXISTE
--------------
Pedido do usuário em 19/10/2026: "tudo tem que ser automatizado". Em 18/10 os
grupos e os modelos do gerente foram aplicados à mão (§8.66), e três coisas os
desfazem sem ninguém ver: o gerente vence e volta com tudo zerado (visto em
18/10), aldeia nova chega sem papel nem modelo (a 81571), e a aldeia que forma
nobre muda com os alvos (o NobleRecruitGate, §8.48), então a reserva de tropas
do gerente também precisa mudar.

O QUE O BOT MANTÉM, POR PAPEL (`config.villages[vid].building`)
---------------------------------------------------------------
`account_manager.roles[papel]` dá, por NOME (como aparece no jogo), o grupo e
os modelos de construção, pesquisa e tropas. O nome vira id pelo que o próprio
jogo oferece (widget da aldeia, `<select>` de grupos, `initTroopManagement`).

- Modelo de construção/pesquisa/tropas: aplicado quando a linha do widget diz
  "Sem gerência" (ou outro modelo) **e** o bot sabe que a aldeia ainda não
  chegou lá (`pending`). "Sem gerência" sozinho não basta: o jogo tira o modelo
  cumprido, e reaplicar um cumprido é um POST que o jogo desfaz na hora.
  `pending` desconhecido (None) não aplica.
- Reserva (buffer) do gerente de tropas = reserva do próximo nobre
  (`Village.noble_reserve()`) nas recrutadoras do portão, zero nas outras.
- Grupo: a aldeia entra no grupo do papel e sai dos grupos dos OUTROS papéis
  (um papel trocado deixa a aldeia nos dois). Grupo fora do mapa não é tocado.
- Trava contra laço: o mesmo modelo não é reaplicado na mesma aldeia antes de
  `reapply_backoff_hours` (168 h), mesmo que o jogo o tire de novo. Medido em
  19/10: o template do bot pede fazenda 30 na BBM 012 e o modelo do gerente
  para antes (o jogo o tirou como cumprido), então a reaplicação só seria um
  POST desfeito. Quando o gerente volta de um vencimento, a trava zera
  (`game/am_auto.py`): a renovação precisa reaplicar tudo na hora.
"""

PHASES = ("construction", "research", "troops")
BUFFER_KEYS = ("buffer_wood", "buffer_stone", "buffer_iron", "buffer_pop")
DEFAULT_BACKOFF_HOURS = 168


def mode(cfg):
    """`account_manager.auto_manage`: "on" (true), "dry_run" ou "off" (false).
    Sem a chave: "off" -- grava no jogo, então só liga quem pediu."""
    value = (cfg or {}).get("auto_manage", False)
    if value is True or value == "on":
        return "on"
    if value == "dry_run":
        return "dry_run"
    return "off"


def role_targets(cfg, role):
    roles = (cfg or {}).get("roles") or {}
    targets = roles.get(role) if isinstance(roles, dict) else None
    return targets if isinstance(targets, dict) else {}


def buffer_from_reserve(reserve):
    reserve = reserve or {}
    return {
        "buffer_wood": int(reserve.get("wood", 0)),
        "buffer_stone": int(reserve.get("stone", 0)),
        "buffer_iron": int(reserve.get("iron", 0)),
        "buffer_pop": int(reserve.get("pop", 0)),
    }


def troops_pending(template, totals):
    """True se alguma unidade do modelo está abaixo da meta; None sem dado.

    Contagem VAZIA também é "sem dado": a aldeia sem praça de reunião não tem a
    tela de tropas, e o bot lê {} (BBM 002, 19/10). Tratar isso como zero
    aplicaria o modelo numa aldeia que já o cumpre."""
    if not template or not totals:
        return None
    for unit, meta in template.items():
        if unit == "id" or unit.startswith("buffer_"):
            continue
        if int(meta or 0) > int(totals.get(unit, 0) or 0):
            return True
    return False


def construction_pending(template_entries, levels):
    """
    True se algum `predio:nivel` do template de construção do bot passa do
    nível atual. É o mesmo destino do modelo do gerente (§8.25, achado 2).
    None sem template ou sem níveis.
    """
    if not template_entries or not levels:
        return None
    for entry in template_entries:
        try:
            building, level = str(entry).split(":")
            if int(level) > int(levels.get(building, 0)):
                return True
        except (ValueError, TypeError):
            continue
    return False


def _backoff(applied_phase, template_id, now, hours):
    if not applied_phase:
        return False
    if applied_phase.get("template") != template_id:
        return False
    return now - float(applied_phase.get("at", 0)) < hours * 3600


def village_actions(cfg, role, widget, options, pending, applied, reserve, now,
                    troop_templates=None, troop_row=None):
    """
    Ações do gerente para UMA aldeia, agora: lista de dicts
    `{"phase", "template", "template_id", "reason"}` (+ `"meta"` e `"buffer"`
    em tropas). Lista vazia = nada a fazer.

    - `widget`/`options`: `Extractor.account_manager_widget[_options]` da visão
      geral desta aldeia neste ciclo (None = sem widget: nada a fazer).
    - `pending`: {fase: True/False/None} do que o bot sabe da aldeia.
    - `applied`: o que o bot já aplicou nela ({fase: {"at", "template", "buffer"}}).
    - `troop_templates`/`troop_row`: da leitura de `am_troops` (modelos e a
      linha desta aldeia, com a reserva atual). Sem eles, tropas não decide.
    """
    targets = role_targets(cfg, role)
    if not targets or widget is None or options is None:
        return []
    hours = float((cfg or {}).get("reapply_backoff_hours", DEFAULT_BACKOFF_HOURS))
    applied = applied or {}
    pending = pending or {}
    actions = []
    for phase in ("construction", "research"):
        name = targets.get(phase)
        template_id = (options.get(phase) or {}).get(name) if name else None
        row = widget.get(phase)
        if not template_id or not isinstance(row, dict):
            continue
        if row.get("active") and row.get("template") in (name, ""):
            continue
        if pending.get(phase) is not True:
            continue
        if _backoff(applied.get(phase), template_id, now, hours):
            continue
        reason = ("modelo trocado (%s)" % row.get("template")) if row.get("active") else "sem modelo"
        actions.append({"phase": phase, "template": name, "template_id": template_id,
                        "reason": reason})

    name = targets.get("troops")
    template = (troop_templates or {}).get(name) if name else None
    row = widget.get("troops")
    if template and isinstance(row, dict):
        template_id = int(template.get("id") or (options.get("troops") or {}).get(name) or 0)
        meta = {u: int(v) for u, v in template.items()
                if u != "id" and not u.startswith("buffer_")}
        buffer = buffer_from_reserve(reserve)
        reason = None
        if not row.get("active"):
            if pending.get("troops") is True:
                reason = "sem modelo"
        elif row.get("template") not in (name, ""):
            reason = "modelo trocado (%s)" % row.get("template")
        elif troop_row is not None:
            current = {k: int(troop_row.get(k, 0)) for k in BUFFER_KEYS}
            if current != buffer:
                reason = "reserva do nobre %s -> %s" % (
                    _short(current), _short(buffer))
        if reason and template_id and not (
                reason == "sem modelo"
                and _backoff(applied.get("troops"), template_id, now, hours)):
            actions.append({"phase": "troops", "template": name, "template_id": template_id,
                            "reason": reason, "meta": meta, "buffer": buffer})
    return actions


def _short(buffer):
    if not any(buffer.values()):
        return "0"
    return "%d/%d/%d+%dpop" % tuple(buffer[k] for k in BUFFER_KEYS)


def group_changes(cfg, village_roles, membership, groups):
    """
    {"add": {group_id: [vid]}, "remove": {group_id: [vid]}} para deixar cada
    aldeia no grupo do papel. `membership` = {vid: [nomes]} lido do jogo
    (aldeia ausente = não lida: não decide); `groups` = {nome: id}.
    """
    roles = (cfg or {}).get("roles") or {}
    managed = {t.get("group") for t in roles.values()
               if isinstance(t, dict) and t.get("group") in groups}
    add, remove = {}, {}
    for vid, role in sorted((village_roles or {}).items()):
        current = (membership or {}).get(vid)
        if current is None:
            continue
        want = role_targets(cfg, role).get("group")
        if want not in groups:
            want = None
        if want and want not in current:
            add.setdefault(groups[want], []).append(vid)
        for name in current:
            if name in managed and name != want and want is not None:
                remove.setdefault(groups[name], []).append(vid)
    return {"add": add, "remove": remove}
