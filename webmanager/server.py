import json
import os
import sys
sys.path.insert(0, "../")

from flask import Flask, jsonify, send_from_directory, request, render_template, redirect, url_for

try:
    from webmanager.helpfile import help_file, buildings, nested_sections
    from webmanager.utils import DataReader, BotManager, MapBuilder, BuildingTemplateManager, UnitTemplateManager, LogReader, FarmScoreReader, ConquestReader, HunterReader, ZoneReader, PvpConquestReader, FlagReader, ResourceSharingReader, ReportReader, StatueReader, EmpireReader
except ImportError:
    from helpfile import help_file, buildings, nested_sections
    from utils import DataReader, BotManager, MapBuilder, BuildingTemplateManager, UnitTemplateManager, LogReader, FarmScoreReader, ConquestReader, HunterReader, ZoneReader, PvpConquestReader, FlagReader, ResourceSharingReader, ReportReader, StatueReader, EmpireReader

bm = BotManager()
app = Flask(__name__)
# P1-18: DEBUG=True liga o debugger interativo do Werkzeug, que expoe um
# console Python remoto em qualquer excecao -- execucao de codigo arbitrario
# para quem alcancar a porta.
app.config["DEBUG"] = False


@app.before_request
def reject_cross_origin_writes():
    """
    Protecao CSRF: toda rota que escreve usa POST (ver abaixo), e um POST
    vindo de outra origem e recusado. O navegador envia `Origin` em todo POST
    cross-origin e nao permite que a pagina atacante o falsifique, entao
    comparar com o `Host` basta -- sem precisar de token por formulario.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    origin = request.headers.get("Origin")
    if origin is None:
        # Sem Origin: ou e um cliente nao-navegador (curl), ou um navegador
        # antigo. Cai para o Referer quando ele existe.
        referer = request.headers.get("Referer")
        if referer is None:
            return None
        origin = referer
    from urllib.parse import urlparse
    if urlparse(origin).netloc != request.host:
        return jsonify({"error": "cross-origin request rejected"}), 403
    return None


def pre_process_bool(key, value, village_id=None):
    if value is None: value = False
    vid_attr = ('data-village-id="%s" ' % village_id) if village_id else ''
    cls = "btn-success" if value else "btn-danger"
    label = "Enabled" if value else "Disabled"
    return '<button class="btn btn-sm %s" %sdata-type-option="%s" data-type="toggle">%s</button>' % (cls, vid_attr, key, label)

def preprocess_select(key, value, templates, village_id=None):
    vid_attr = ('data-village-id="%s" ' % village_id) if village_id else ''
    output = '<select %sdata-type-option="%s" data-type="select" class="form-control">' % (vid_attr, key)
    for template in DataReader.template_grab(templates):
        output += '<option value="%s" %s>%s</option>' % (template, 'selected' if template == value else '', template)
    output += '</select>'
    return output

def pre_process_string(key, value, village_id=None):
    if value is None: value = ''
    templates = {
        'units.default': 'templates.troops', 'village.units': 'templates.troops',
        'building.default': 'templates.builder', 'village_template.units': 'templates.troops',
        'village.building': 'templates.builder', 'village_template.building': 'templates.builder'
    }
    if key in templates:
        return preprocess_select(key, value, templates[key], village_id)
    vid_attr = ('data-village-id="%s" ' % village_id) if village_id else ''
    return '<input type="text" class="form-control" %sdata-type="text" value="%s" data-type-option="%s" />' % (vid_attr, value, key)

def pre_process_number(key, value, village_id=None):
    if value is None: value = 0
    vid_attr = ('data-village-id="%s" ' % village_id) if village_id else ''
    return '<input type="number" data-type="number" class="form-control" %svalue="%s" data-type-option="%s" />' % (vid_attr, value, key)

def pre_process_list(key, value, village_id=None):
    if value is None: value = []
    vid_attr = ('data-village-id="%s" ' % village_id) if village_id else ''
    return '<input type="text" data-type="list" class="form-control" %svalue="%s" data-type-option="%s" />' % (vid_attr, ', '.join(str(v) for v in value), key)

def pre_process_null(key, village_id=None):
    vid_attr = ('data-village-id="%s" ' % village_id) if village_id else ''
    return '<input type="text" class="form-control" %sdata-type="text" placeholder="null" value="" data-type-option="%s" />' % (vid_attr, key)

def render_value(key, value, village_id=None):
    if isinstance(value, bool): return pre_process_bool(key, value, village_id)
    if value is None: return pre_process_null(key, village_id)
    if isinstance(value, str): return pre_process_string(key, value, village_id)
    if isinstance(value, list): return pre_process_list(key, value, village_id)
    if isinstance(value, (int, float)): return pre_process_number(key, value, village_id)
    return ''

def fancy(key, prefix=None):
    name = key.split('.')[-1] if '.' in key else key
    name = name[0].upper() + name[1:].replace('_', ' ')
    out = '<hr /><strong>%s</strong>' % name
    help_key = (prefix + '.' + key if prefix else key).replace('village_template', 'village')
    if help_key in help_file:
        out += '<br /><i>%s</i>' % help_file[help_key]
    return out

def pre_process_config():
    config = sync()['config']
    to_hide = ["build", "villages", "profile_templates", "hunter"]
    sections = {}
    for section in config:
        if section in to_hide: continue
        section_data = config[section]
        config_html = ""
        if section in nested_sections and isinstance(section_data, dict):
            for param, value in section_data.items():
                kvp = "%s.%s" % (section, param)
                if isinstance(value, dict):
                    config_html += '<hr /><strong>%s</strong>' % param
                    for sub_param, sub_value in value.items():
                        sub_kvp = "%s.%s.%s" % (section, param, sub_param)
                        config_html += fancy(sub_kvp) + render_value(sub_kvp, sub_value)
                else:
                    config_html += fancy(kvp) + render_value(kvp, value)
        elif isinstance(section_data, dict):
            for param, value in section_data.items():
                if isinstance(value, dict): continue
                kvp = "%s.%s" % (section, param)
                config_html += fancy(kvp) + render_value(kvp, value)
        else:
            continue
        sections[section] = config_html
    return sections

def pre_process_village_config(village_id):
    config = sync()['config']['villages']
    village_cfg = config.get(village_id) or (config[list(config.keys())[0]] if config else {})
    config_html = ""
    for parameter, value in village_cfg.items():
        if isinstance(value, dict): continue
        kvp = "village.%s" % parameter
        config_html += fancy(kvp) + render_value(kvp, value, village_id)
    return config_html

def sync():
    reports = DataReader.cache_grab("reports")
    villages = DataReader.cache_grab("villages")
    attacks = DataReader.cache_grab("attacks")
    config = DataReader.config_grab()
    managed = DataReader.cache_grab("managed")
    sort_reports = {k: v for k, v in sorted(reports.items(), key=lambda i: int(i[0]))}
    return {
        "attacks": attacks, "villages": villages, "config": config,
        "reports": {k: sort_reports[k] for k in list(sort_reports)[:100]},
        "bot": managed, "status": bm.is_running()
    }


@app.route('/api/get', methods=['GET'])
def get_vars():
    return jsonify(sync())

@app.route('/bot/start', methods=['POST'])
def start_bot():
    bm.start()
    import time; time.sleep(0.5)
    return jsonify({"running": bm.is_running(), "pid": bm.pid})

@app.route('/bot/stop', methods=['POST'])
def stop_bot():
    bm.stop()
    return jsonify({"running": bm.is_running()})

@app.route('/bot/output', methods=['GET'])
def bot_output():
    return jsonify({"lines": BotManager.read_output_log(lines=300)})

@app.route('/config', methods=['GET'])
def get_config():
    return render_template('config.html', data=sync(), config=pre_process_config(), helpfile=help_file)

@app.route('/village', methods=['GET'])
def get_village_config():
    data = sync()
    vid = request.args.get("id", None)
    return render_template('village.html', data=data, config=pre_process_village_config(village_id=vid),
                           current_select=vid, helpfile=help_file)

@app.route('/map', methods=['GET'])
def get_map():
    sync_data = sync()
    center_id = request.args.get("center", None)
    center = next(iter(sync_data['bot'])) if not center_id else center_id
    map_data = json.dumps(MapBuilder.build(sync_data['villages'], current_village=center, size=15))
    return render_template('map.html', data=sync_data, map=map_data)

@app.route('/villages', methods=['GET'])
def get_village_overview():
    return render_template('villages.html', data=sync())

@app.route('/building_templates', methods=['GET', 'POST'])
def get_building_templates():
    if request.method == 'POST':
        if request.form.get('new', None):
            plain = os.path.basename(request.form.get('new'))
            if not plain.endswith('.txt'): plain = "%s.txt" % plain
            tempfile = os.path.join(os.path.dirname(__file__), '..', 'templates', 'builder', plain)
            if not os.path.exists(tempfile):
                open(tempfile, 'w').write("")
        if request.form.get('action') == 'add_row':
            t_name = request.form.get('template')
            rows = BuildingTemplateManager.template_cache_list().get(t_name, [])
            rows.append({'building': request.form.get('building'), 'to': int(request.form.get('to_level', 1))})
            DataReader.template_save(t_name, rows)
        if request.form.get('action') == 'delete_row':
            t_name = request.form.get('template')
            row_idx = int(request.form.get('row_index', -1))
            if row_idx >= 0:
                DataReader.template_delete_row(t_name, row_idx)
    selected = request.args.get('t', None)
    return render_template('templates.html', templates=BuildingTemplateManager.template_cache_list(),
                           selected=selected, buildings=buildings)

@app.route('/unit_templates', methods=['GET', 'POST'])
def get_unit_templates():
    # Feature 14: CRUD de templates de tropas (templates/troops/*.txt).
    # Edicao via textarea de JSON bruto (ver UnitTemplateManager para o
    # porque — a estrutura de build/farm/upgrades/research varia demais
    # para um formulario por campo). Nada e escrito se o JSON for invalido
    # ou se o delete for bloqueado por uso em config.json.
    error = None
    selected = None
    edited_raw = None
    if request.method == 'POST':
        action = request.form.get('action')
        t_name = request.form.get('template')
        if action == 'new':
            new_name = request.form.get('new')
            if new_name:
                selected = UnitTemplateManager.create(new_name)
        elif action == 'save' and t_name:
            raw = request.form.get('raw', '')
            selected = t_name
            try:
                UnitTemplateManager.save(t_name, raw)
            except (json.JSONDecodeError, ValueError) as e:
                error = "JSON inválido, nada foi salvo: %s" % str(e)
                edited_raw = raw
        elif action == 'delete' and t_name:
            usages = UnitTemplateManager.used_by(t_name)
            if usages:
                error = "Não foi possível deletar: template em uso por %s" % ", ".join(usages)
                selected = t_name
            else:
                UnitTemplateManager.delete(t_name)
                selected = None
    if selected is None:
        selected = request.args.get('t', None)
    templates = UnitTemplateManager.template_cache_list()
    if edited_raw is not None and selected in templates:
        templates[selected] = dict(templates[selected], raw=edited_raw, valid=False, error=error)
    return render_template('unit_templates.html', templates=templates, selected=selected, error=error)

@app.route('/', methods=['GET'])
def get_home():
    return render_template('bot.html', data=sync(), session=DataReader.get_session())

@app.route('/app/js', methods=['GET'])
def get_js():
    return send_from_directory(os.path.join(os.path.dirname(__file__), "public"), "js.v2.js")

@app.route('/app/config/set', methods=['POST'])
def config_set():
    vid = request.args.get("village_id", None)
    if not vid:
        DataReader.config_set(parameter=request.args.get("parameter"), value=request.args.get("value", None))
    else:
        param = request.args.get("parameter")
        if param.startswith("village."): param = param.replace("village.", "")
        DataReader.village_config_set(village_id=vid, parameter=param, value=request.args.get("value", None))
    return jsonify(sync())

@app.route('/logs', methods=['GET'])
def get_logs():
    log_files = LogReader.list_log_files()
    selected = request.args.get("f", log_files[0] if log_files else None)
    entries = LogReader.parse_log(selected) if selected else []
    event_types = sorted(set(e["event_type"] for e in entries if e["event_type"] not in ("BOT_START", "RAW")))
    village_ids = sorted(set(e["village_id"] for e in entries if e["village_id"]))
    return render_template("logs.html", log_files=log_files, selected_file=selected,
                           entries=entries, event_types=event_types, village_ids=village_ids)

@app.route('/farmscores', methods=['GET'])
def get_farm_scores():
    farms, village_ids = FarmScoreReader.load()
    return render_template('farmscores.html', farms=farms, village_ids=village_ids)

@app.route('/conquest', methods=['GET', 'POST'])
def get_conquest():
    # Feature 15: define/cancela alvo manual de conquista bárbara. Erros são
    # exibidos inline (nada é escrito em cache/conquest se a validação falhar
    # -- ver ConquestReader.add_manual_target/cancel_manual).
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'manual_add':
                ConquestReader.add_manual_target(request.form.get('identifier', ''))
                return redirect(url_for('get_conquest'))
            elif action == 'manual_cancel':
                ConquestReader.cancel_manual(request.form.get('target_id', ''))
                return redirect(url_for('get_conquest'))
            elif action == 'force_clear':
                # Feature (2026-08-07): limpa o cache de um alvo em qualquer
                # status (train_sent/extra_pending/complete incluídos) -- para
                # quando o usuário cancelou o noble train manualmente no jogo
                # e o cache/conquest/{id}.json ficaria "reservado" para
                # sempre sem essa opção. Ver ConquestReader.force_clear().
                ConquestReader.force_clear(request.form.get('target_id', ''))
                return redirect(url_for('get_conquest'))
        except ValueError as e:
            error = str(e)
    targets = ConquestReader.load()
    config = DataReader.config_grab()
    conquest_enabled = config.get("conquest", {}).get("enabled", False)
    return render_template(
        'conquest.html',
        data=sync(),
        targets=targets,
        error=error,
        conquest_enabled=conquest_enabled,
    )

# Unidades disponíveis para o formulário de schedules
HUNTER_UNITS = ["spear", "sword", "archer", "spy", "light", "marcher", "heavy", "axe", "ram", "catapult", "knight", "snob"]

@app.route('/hunter', methods=['GET'])
def get_hunter():
    config = DataReader.config_grab()
    enabled = config.get("hunter", {}).get("enabled", False)
    schedules = HunterReader.load()
    managed = sync()["bot"]
    # {village_id: name_or_empty} para o dropdown
    villages = {vid: (managed[vid].get("public") or {}).get("name", "") for vid in managed}
    village_options_json = json.dumps(villages)
    return render_template(
        "hunter.html",
        enabled=enabled,
        schedules=schedules,
        villages=villages,
        village_options_json=village_options_json,
        units=HUNTER_UNITS,
    )

@app.route('/hunter/add', methods=['POST'])
def hunter_add():
    target_id = request.form.get("target_id", "").strip()
    arrival_raw = request.form.get("arrival_time", "").strip()
    # datetime-local devolve "YYYY-MM-DDTHH:MM" — normalizar para "YYYY-MM-DD HH:MM:SS"
    arrival_str = arrival_raw.replace("T", " ")
    if len(arrival_str) == 16:
        arrival_str += ":00"

    # Coletar ataques do formulário: attacks[0][source_village_id], attacks[0][is_fake], attacks[0][troops][axe], ...
    attacks = []
    idx = 0
    while True:
        source = request.form.get("attacks[%d][source_village_id]" % idx)
        if source is None:
            break
        is_fake = request.form.get("attacks[%d][is_fake]" % idx) == "1"
        troops = {}
        for unit in HUNTER_UNITS:
            val = request.form.get("attacks[%d][troops][%s]" % (idx, unit), "0")
            try:
                qty = int(val)
            except ValueError:
                qty = 0
            if qty > 0:
                troops[unit] = qty
        if troops:
            attacks.append({"source_village_id": source, "troops": troops, "is_fake": is_fake})
        idx += 1

    HunterReader.add_schedule(target_id, arrival_str, attacks)
    return redirect(url_for("get_hunter"))

@app.route('/hunter/delete', methods=['POST'])
def hunter_delete():
    sched_key = request.form.get("sched_key", "")
    if sched_key:
        HunterReader.delete_schedule(sched_key)
    return redirect(url_for("get_hunter"))

@app.route('/hunter/toggle', methods=['POST'])
def hunter_toggle():
    enabled = request.args.get("enabled", "0") == "1"
    result = HunterReader.set_enabled(enabled)
    return jsonify({"enabled": result})

@app.route('/zones', methods=['GET'])
def get_zones():
    sync_data = sync()
    zone_data = ZoneReader.enrich(sync_data['bot'])
    zones_json = json.dumps(zone_data)
    config = DataReader.config_grab()
    radius = config.get("zones", {}).get("radius", 10)
    enabled = config.get("zones", {}).get("enabled", True)
    return render_template('zones.html', data=sync_data, zone_data=zone_data,
                           zones_json=zones_json, radius=radius, enabled=enabled)


@app.route('/flags', methods=['GET'])
def get_flags():
    sync_data = sync()
    flag_entries = FlagReader.load(sync_data["bot"])
    return render_template('flags.html', entries=flag_entries)


@app.route('/resource_sharing', methods=['GET'])
def get_resource_sharing():
    config = DataReader.config_grab()
    sharing_cfg = config.get("resource_sharing", {})
    enabled = sharing_cfg.get("enabled", False)
    sync_data = sync()
    entries, totals = ResourceSharingReader.load(managed_cache=sync_data["bot"])
    return render_template(
        'resource_sharing.html',
        enabled=enabled,
        sharing_cfg=sharing_cfg,
        entries=entries,
        totals=totals,
    )


@app.route('/reports', methods=['GET'])
def get_reports():
    dest_filter = request.args.get("dest", "").strip() or None
    type_filter = request.args.get("type", "").strip() or None
    entries, stats = ReportReader.load(dest_filter=dest_filter, type_filter=type_filter)
    managed = sync()["bot"]
    village_options = {vid: (managed[vid].get("public") or {}).get("name", "") for vid in managed}
    return render_template(
        'reports.html',
        entries=entries,
        stats=stats,
        village_options=village_options,
        dest_filter=dest_filter,
        type_filter=type_filter,
    )


@app.route('/statue', methods=['GET'])
def get_statue():
    config = DataReader.config_grab()
    enabled = config.get("statue", {}).get("enabled", False)
    managed = sync()["bot"]
    data = StatueReader.load(managed_cache=managed)
    # Fallback: quem decide os slots e o total de aldeias da CONTA, que o
    # StatueManager le do game_data e grava em data["village_count"]. Aqui so da
    # pra contar as gerenciadas, que podem ser um subconjunto -- serve para
    # cache gravado antes desse campo existir.
    village_count = len(managed)
    return render_template(
        'statue.html',
        enabled=enabled,
        data=data,
        village_count=village_count,
    )


@app.route('/pvp_conquest', methods=['GET'])
def get_pvp_conquest():
    config = DataReader.config_grab()
    enabled = config.get("pvp_conquest", {}).get("enabled", False)
    pvp_cfg = config.get("pvp_conquest", {})
    targets = PvpConquestReader.load()
    managed = sync()["bot"]
    managed_villages = {vid: (managed[vid].get("public") or {}).get("name", "") for vid in managed}
    return render_template(
        "pvp_conquest.html",
        enabled=enabled,
        targets=targets,
        managed_villages=managed_villages,
        pvp_cfg=pvp_cfg,
    )


@app.route('/pvp_conquest/add', methods=['POST'])
def pvp_conquest_add():
    target_id = request.form.get("target_id", "").strip()
    arrival_raw = request.form.get("arrival_time", "").strip()
    arrival_str = arrival_raw.replace("T", " ")
    if len(arrival_str) == 16:
        arrival_str += ":00"
    clear_vid = request.form.get("clear_village_id", "").strip() or None
    PvpConquestReader.add(target_id, arrival_str, clear_village_id=clear_vid)
    return redirect(url_for("get_pvp_conquest"))


@app.route('/pvp_conquest/delete', methods=['POST'])
def pvp_conquest_delete():
    target_id = request.form.get("target_id", "")
    if target_id:
        PvpConquestReader.delete(target_id)
    return redirect(url_for("get_pvp_conquest"))


@app.route('/pvp_conquest/set_clear', methods=['POST'])
def pvp_conquest_set_clear():
    target_id = request.form.get("target_id", "")
    clear_vid  = request.form.get("clear_village_id", "").strip() or None
    if target_id:
        PvpConquestReader.set_clear_village(target_id, clear_vid)
    return redirect(url_for("get_pvp_conquest"))


@app.route('/empire', methods=['GET'])
def get_empire():
    # Feature 17: dashboard agregado do imperio -- so leitura, reaproveita
    # os mesmos caches que sync() ja grava (managed/villages/attacks) mais
    # ConquestReader.load() (cache/conquest), sem nenhum cache novo.
    data = sync()
    managed = data["bot"]

    totals = {
        "villages": len(managed),
        "points": sum(int(v.get("points") or 0) for v in managed.values()),
        "under_attack": sum(1 for v in managed.values() if v.get("under_attack")),
    }

    conquest_targets = ConquestReader.load()
    # Bugfix (2026-08-07): merge in PvP Conquest (Feature 13, the system
    # actually enabled/used) alongside barbarian conquest (Feature 8, usually
    # disabled) -- see EmpireReader.conquest_timeline() docstring.
    pvp_targets = PvpConquestReader.load()

    return render_template(
        'empire.html',
        data=data,
        totals=totals,
        troop_totals=EmpireReader.troop_totals(managed),
        resources=EmpireReader.resources_by_village(managed),
        heatmap=EmpireReader.farm_heatmap(data["attacks"], data["villages"], managed),
        timeline=EmpireReader.conquest_timeline(conquest_targets, pvp_targets, data["villages"]),
    )


if __name__ == "__main__":
    # P1-18(c): sem esta guarda, qualquer `import webmanager.server` subia um
    # servidor HTTP como efeito colateral.
    if len(sys.argv) > 1:
        app.run(host="localhost", port=sys.argv[1])
    else:
        app.run()
