"""
Cessão de fases ao gerente de conta, aldeia por aldeia (docs/backend.md §8.68).

POR QUE EXISTE
--------------
Com o gerente de conta ativo, construção, pesquisa e recrutamento tinham dois
donos (§8.25, achado 2): o modelo do gerente no servidor e o manager do bot,
com o mesmo destino. O bot cede a fase quando o gerente está cuidando DAQUELA
aldeia, e retoma sozinho quando o gerente vence ou a aldeia fica sem modelo.

O SINAL, E POR QUE ELE E POR ALDEIA
-----------------------------------
"Gerente ativo na conta" (`game_data.features.AccountManager.active`, lido ao
vivo por core/paid_features.py) não basta: o jogo diz "Sem gerência" tanto na
aldeia que já cumpriu o modelo (ele o retira) quanto na que nunca recebeu um
(a 81571, conquistada em 18/10). Ceder olhando só a conta deixaria essa aldeia
sem ninguém. Por isso a segunda metade do sinal é o widget do gerente na visão
geral da própria aldeia (`Extractor.account_manager_widget`), que o bot já baixa
no início de toda aldeia: custo zero.

REGRAS
------
- Cede só com as duas metades afirmativas: gerente ativo AGORA (True, não
  None) e modelo ativo na linha da fase. Qualquer dúvida (gerente não lido,
  widget ausente, linha ilegível) é "o bot faz": ceder por engano para a fase
  de vez, fazer por engano só repete o que o gerente faria.
- A decisão é recalculada na hora de agir, a cada fase, nunca guardada. O que
  se guarda é só o último estado, para logar a TROCA e não toda aldeia.
- Só construção, pesquisa e recrutamento se cedem por aqui. Nobre, cunhagem,
  farm, coleta, defesa, apoio e mercado o gerente não faz.
"""

# fase do bot -> linha do widget
PHASE_WIDGET_ROW = {
    "construction": "construction",
    "research": "research",
    "recruitment": "troops",
}

PHASE_LABELS = {
    "construction": "construção",
    "research": "pesquisa",
    "recruitment": "recrutamento",
}

DEFAULTS = {
    "cede_enabled": True,
    "cede_construction": True,
    "cede_research": True,
    "cede_recruitment": True,
}


def setting(cfg, key):
    """Valor de `account_manager.<key>`, com o padrão quando falta."""
    section = cfg if isinstance(cfg, dict) else {}
    value = section.get(key, DEFAULTS.get(key))
    return bool(value)


def decide(phase, cfg, manager_active, widget):
    """
    (cedida, motivo) para `phase` nesta aldeia, agora.

    `cfg` é a seção `account_manager` do config, `manager_active` é o
    `PaidFeatures.active("AccountManager")` cru (True/False/None) e `widget` é
    o que `Extractor.account_manager_widget` leu da visão geral desta aldeia
    neste ciclo.
    """
    if phase not in PHASE_WIDGET_ROW:
        return False, "fase que o gerente não faz"
    if not setting(cfg, "cede_enabled") or not setting(cfg, "cede_" + phase):
        return False, "cessão desligada no config"
    if manager_active is not True:
        if manager_active is False:
            return False, "gerente vencido"
        return False, "gerente ainda não lido"
    if widget is None:
        return False, "widget do gerente ausente na visão geral"
    row = widget.get(PHASE_WIDGET_ROW[phase])
    if not isinstance(row, dict):
        return False, "linha do widget ilegível"
    if not row.get("active"):
        return False, "sem modelo"
    template = row.get("template") or "sem nome"
    return True, "modelo %s" % template


def transition_message(phase, previous, current):
    """
    Linha de log da troca de estado de uma fase, ou None quando não há troca
    que valha logar.

    `previous`/`current` são (cedida, motivo); `previous` é None na primeira
    decisão do processo para esta aldeia e fase. A primeira só loga se cedeu:
    "o bot faz" é o estado de sempre e logar isso para 55 aldeias e 3 fases a
    cada reinício só esconderia as linhas que importam.
    """
    label = PHASE_LABELS.get(phase, phase)
    ceded, reason = current
    if previous is None:
        if ceded:
            return "Gerente: %s cedida ao gerente (%s)" % (label, reason)
        return None
    was_ceded = previous[0]
    if ceded and not was_ceded:
        return "Gerente: %s cedida ao gerente (%s)" % (label, reason)
    if was_ceded and not ceded:
        return "Gerente: %s retomada pelo bot -- %s" % (label, reason)
    return None
