import collections
import datetime
import json
import os
import re
import subprocess
import time

import psutil

from core.filemanager import FileManager


def village_display_name(entry, vid, fallback=None):
    """
    Nome exibivel de uma aldeia lida do cache de mapa (cache/villages) ou de
    cache/managed.

    Existe porque o jogo manda `name` = 0 (int, nao string) para aldeia sem
    nome proprio, e `Map.build_cache_entry()` guarda esse 0 verbatim
    (`name = entry[2]`, game/map.py:259) -- quem renderiza "Aldeia de
    barbaros" a partir dele e o cliente do jogo, nao o dado. Medido no cache
    real em 2026-08-31: 184 das 734 aldeias estao nesse estado e TODAS as 184
    tem `owner == "0"`, zero excecoes, entao mapear para "Barbara" e exato e
    nao heuristico.

    Sem isso, qualquer tabela de alvo de farm mostra id cru: na /reports eram
    99 de 100 linhas, e no mapa de calor da /empire todo tooltip de barbara.
    """
    entry = entry or {}
    name = entry.get("name")
    if not name:
        pub = entry.get("public") or {}
        name = pub.get("name")
        if not name and str(entry.get("owner", pub.get("owner"))) == "0":
            name = "Bárbara"
    return name or fallback or ("#%s" % vid)


def villages_cache_dir():
    return os.path.join(os.path.dirname(__file__), "..", "cache", "villages")


def resolve_village_identifier(identifier):
    """
    Aceita um ID de aldeia puro ("12345") ou coordenadas
    ("512|487", "512,487", "512 487") e devolve `(village_id, dados)`.
    Resolve consultando cache/villages/ (populado pelo fetch de mapa de
    qualquer aldeia gerenciada -- ver game/map.py::Map.build_cache_entry).
    Lanca ValueError com mensagem amigavel se nao encontrar; nunca inventa
    dados.

    Vive no nivel de modulo porque duas telas precisam dele: a conquista
    barbara (Feature 15) e a conquista PvP. Ate 2026-09-20 so a primeira
    tinha, e o formulario da segunda gravava o texto digitado direto como
    nome de arquivo -- coordenadas geravam
    `OSError: [Errno 22] '...\\557|293.json'` (500 na cara do usuario) porque
    `|` e ilegal em nome de arquivo no Windows.
    """
    identifier = (identifier or "").strip()
    if not identifier:
        raise ValueError("Informe um ID de aldeia ou coordenadas (ex: 512|487).")

    v_dir = villages_cache_dir()
    os.makedirs(v_dir, exist_ok=True)

    if identifier.isdigit():
        path = os.path.join(v_dir, "%s.json" % identifier)
        if not os.path.exists(path):
            raise ValueError(
                "Aldeia #%s não encontrada no cache local. Aguarde o bot "
                "mapear essa região (cache/villages/) e tente novamente." % identifier
            )
        with open(path, "r", encoding="utf-8") as f:
            return identifier, json.load(f)

    m = re.match(r"^\s*(\d+)\D+(\d+)\s*$", identifier)
    if not m:
        raise ValueError(
            "Formato inválido. Use um ID de aldeia (ex: 12345) ou "
            "coordenadas (ex: 512|487)."
        )
    x, y = int(m.group(1)), int(m.group(2))
    for fname in os.listdir(v_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(v_dir, fname), "r", encoding="utf-8") as f:
                vdata = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        loc = vdata.get("location")
        if loc and len(loc) == 2 and int(loc[0]) == x and int(loc[1]) == y:
            return fname.replace(".json", ""), vdata

    raise ValueError(
        "Nenhuma aldeia encontrada em %d|%d no cache local. Aguarde o bot "
        "mapear essa região e tente novamente." % (x, y)
    )


class DataReader:
    @staticmethod
    def cache_grab(cache_location):
        output = {}
        c_path = os.path.join(os.path.dirname(__file__), "..", "cache", cache_location)
        if not os.path.exists(c_path):
            return output
        for existing in os.listdir(c_path):
            existing = str(existing)
            if not existing.endswith(".json"):
                continue
            t_path = os.path.join(os.path.dirname(__file__), "..", "cache", cache_location, existing)
            try:
                with open(t_path, 'r') as f:
                    output[existing.replace('.json', '')] = json.load(f)
            except OSError as e:
                # O open() precisa estar DENTRO do try: no Windows o arquivo
                # fica brevemente inacessível enquanto o bot faz o os.replace()
                # da escrita atômica, e um PermissionError aqui derrubaria a
                # request inteira do webmanager. É transitório e o dado não
                # está corrompido -- pula e pega no próximo request.
                print("Cache locked/unavailable for %s: %s. Skipping entry" % (t_path, str(e)))
                continue
            except Exception as e:
                # JSON inválido: NÃO apagar. Este é um processo LEITOR e o
                # arquivo pertence ao bot. sync() roda a cada request, então
                # isso é quase sempre uma leitura que caiu no meio de uma
                # escrita -- não corrupção real. Apagar custava o histórico de
                # farm (cache/attacks -> last_attack, fazendo o bot re-atacar
                # fora do cooldown) ou o estado da aldeia (cache/managed).
                # Ver P0-4 em docs/backend.md
                print("Cache read error for %s: %s. Skipping entry (file left untouched)" % (t_path, str(e)))
                continue
        return output

    @staticmethod
    def template_grab(template_location):
        output = []
        template_location = template_location.replace('.', '/')
        c_path = os.path.join(os.path.dirname(__file__), "..", template_location)
        if not os.path.exists(c_path):
            return output
        for existing in os.listdir(c_path):
            existing = str(existing)
            if not existing.endswith(".txt"):
                continue
            output.append(existing.split('.')[0])
        return output

    @staticmethod
    def config_grab():
        return FileManager.load_json_file("config.json")

    @staticmethod
    def config_set(parameter, value):
        if value is None or value == "null":
            parsed_value = None
        else:
            try:
                parsed_value = json.loads(value)
            except Exception:
                parsed_value = value
        template = FileManager.load_json_file(
            "config.json", object_pairs_hook=collections.OrderedDict
        )
        if "." in parameter:
            parts = parameter.split('.')
            if len(parts) == 3:
                section, subsection, param = parts
                if section in template and subsection in template[section]:
                    template[section][subsection][param] = parsed_value
            else:
                section, param = parts
                if section in template:
                    template[section][param] = parsed_value
        else:
            template[parameter] = parsed_value
        FileManager.save_json_file(template, "config.json")
        return True

    @staticmethod
    def village_config_set(village_id, parameter, value):
        if value is None or value == "null":
            parsed_value = None
        else:
            try:
                parsed_value = json.loads(value)
            except (json.decoder.JSONDecodeError, TypeError):
                parsed_value = value
        template = FileManager.load_json_file(
            "config.json", object_pairs_hook=collections.OrderedDict
        )
        if village_id not in template['villages']:
            return False
        template['villages'][str(village_id)][parameter] = parsed_value
        FileManager.save_json_file(template, "config.json")
        return True

    @staticmethod
    def gather_config_summary(config=None):
        """Aggregate the persisted per-village scavenging configuration."""
        config = config if config is not None else DataReader.config_grab()
        if not isinstance(config, dict):
            config = {}
        villages = config.get("villages") or {}
        if not isinstance(villages, dict):
            villages = {}

        def selection_uses_all_options(village):
            if not isinstance(village, dict):
                return False
            try:
                return int(village.get("gather_selection", 1) or 1) >= 4
            except (TypeError, ValueError):
                return False

        enabled = sum(
            1 for village in villages.values()
            if isinstance(village, dict) and village.get("gather_enabled") is True
        )
        all_options = sum(
            1 for village in villages.values() if selection_uses_all_options(village)
        )
        managed = sum(
            1 for village in villages.values()
            if isinstance(village, dict) and village.get("managed", True) is not False
        )
        return {
            "total": len(villages),
            "managed": managed,
            "enabled": enabled,
            "all_options": all_options,
        }

    @staticmethod
    def gather_bulk_set(enabled, use_all_unlocked=False):
        """Update every configured village in one atomic config write.

        ``gather_selection = 4`` remains a ceiling.  TroopManager calibrates it
        to the highest option the game actually reports as unlocked, so this
        does not attempt locked options and automatically grows into newly
        unlocked ones.
        """
        config = FileManager.load_json_file(
            "config.json", object_pairs_hook=collections.OrderedDict
        )
        if not isinstance(config, dict) or not isinstance(config.get("villages"), dict):
            raise ValueError("config.json não contém um mapa de aldeias válido")
        for village in config["villages"].values():
            if not isinstance(village, dict):
                continue
            village["gather_enabled"] = bool(enabled)
            if use_all_unlocked:
                village["gather_selection"] = 4
        FileManager.save_json_file(config, "config.json")
        return DataReader.gather_config_summary(config)

    @staticmethod
    def template_save(template_name, rows):
        base = os.path.basename(template_name)
        if not base.endswith('.txt'):
            base = "%s.txt" % base
        t_path = os.path.join(os.path.dirname(__file__), "..", "templates", "builder", base)
        lines = []
        prev_levels = {}
        for row in rows:
            building = row.get('building', '')
            to_level = int(row.get('to', 1))
            from_level = prev_levels.get(building, 0)
            if to_level > from_level:
                lines.append("%s:%d" % (building, to_level))
                prev_levels[building] = to_level
        with open(t_path, 'w') as f:
            f.write('\n'.join(lines))
        return True

    @staticmethod
    def template_delete_row(template_name, row_index):
        base = os.path.basename(template_name)
        if not base.endswith('.txt'):
            base = "%s.txt" % base
        t_path = os.path.join(os.path.dirname(__file__), "..", "templates", "builder", base)
        with open(t_path, 'r') as f:
            lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('#') and ':' in l]
        if 0 <= row_index < len(lines):
            lines.pop(row_index)
        with open(t_path, 'w') as f:
            f.write('\n'.join(lines))
        return True

    @staticmethod
    def get_session():
        c_path = os.path.join(os.path.dirname(__file__), "..", "cache", "session.json")
        if not os.path.exists(c_path):
            return {"raw": "", "endpoint": "None", "server": "None", "world": "None"}
        with open(c_path, 'r') as session_file:
            session_data = json.load(session_file)
            cookies = []
            for c in session_data['cookies']:
                cookies.append("%s=%s" % (c, session_data['cookies'][c]))
            session_data['raw'] = ';'.join(cookies)
            return session_data


class BuildingTemplateManager:
    @staticmethod
    def template_cache_list():
        c_path = os.path.join(os.path.dirname(__file__), "..", "templates", "builder")
        output = {}
        for existing in os.listdir(c_path):
            if not existing.endswith(".txt"):
                continue
            with open(os.path.join(os.path.dirname(__file__), "..", "templates", "builder", existing), 'r') as tf:
                output[existing] = BuildingTemplateManager.template_to_dict([x.strip() for x in tf.readlines()])
        return output

    @staticmethod
    def template_to_dict(t_list):
        out_data = {}
        rows = []
        for entry in t_list:
            if entry.startswith('#') or ':' not in entry:
                continue
            building, next_level = entry.split(':')
            next_level = int(next_level)
            old = out_data.get(building, 0)
            rows.append({'building': building, 'from': old, 'to': next_level})
            out_data[building] = next_level
        return rows


class UnitTemplateManager:
    """
    Feature 14 — CRUD de templates de tropas (JSON em templates/troops/*.txt)
    via webmanager. Diferente de BuildingTemplateManager (formato simples
    "building:level" por linha), templates de tropas são JSON aninhado
    (build/farm/upgrades/research por estágio) — em vez de tentar montar um
    formulário por campo para uma estrutura tão variável, a edição é feita
    via textarea de JSON bruto, validado antes de gravar no disco.
    """

    @staticmethod
    def _dir():
        return os.path.join(os.path.dirname(__file__), "..", "templates", "troops")

    @staticmethod
    def _safe_name(template_name):
        base = os.path.basename(template_name or "")
        if not base.endswith(".txt"):
            base = "%s.txt" % base
        return base

    @staticmethod
    def template_cache_list():
        """
        Retorna {nome_arquivo: {"raw": <json formatado>, "valid": bool,
        "error": str|None, "stages": int}} — parseia cada arquivo só para
        exibir contagem de estágios e detectar corrupção; nunca lança.
        """
        output = {}
        t_dir = UnitTemplateManager._dir()
        if not os.path.isdir(t_dir):
            return output
        for existing in sorted(os.listdir(t_dir)):
            if not existing.endswith(".txt"):
                continue
            path = os.path.join(t_dir, existing)
            try:
                with open(path, 'r', encoding="utf-8") as tf:
                    raw = tf.read()
            except OSError:
                continue
            entry = {"raw": raw, "valid": True, "error": None, "stages": 0}
            try:
                parsed = json.loads(raw) if raw.strip() else []
                if not isinstance(parsed, list):
                    raise ValueError("O template deve ser uma lista JSON de estágios ([...])")
                entry["stages"] = len(parsed)
                entry["raw"] = json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError) as e:
                entry["valid"] = False
                entry["error"] = str(e)
            output[existing] = entry
        return output

    @staticmethod
    def used_by(template_name):
        """
        Verifica config.json em busca de referências a este template
        (units.default, village_template.units, villages.*.units) — usado
        para bloquear delete de um template em uso, já que um arquivo
        faltando/corrompido faz o bot inteiro levantar
        InvalidUnitTemplateException (game/village.py::units_get_template).
        Best-effort: lê config.json diretamente, não falha se ausente.
        """
        base = os.path.splitext(UnitTemplateManager._safe_name(template_name))[0]
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        usages = []
        try:
            with open(config_path, 'r', encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            return usages
        if cfg.get("units", {}).get("default") == base:
            usages.append("padrão global (units.default)")
        village_template = cfg.get("village_template") or {}
        if isinstance(village_template, dict) and village_template.get("units") == base:
            usages.append("village_template (padrão de novas aldeias)")
        for vid, vcfg in (cfg.get("villages") or {}).items():
            if isinstance(vcfg, dict) and vcfg.get("units") == base:
                usages.append("aldeia %s" % (vcfg.get("name") or vid))
        for profile_name, pcfg in (cfg.get("profile_templates") or {}).items():
            if isinstance(pcfg, dict) and pcfg.get("units") == base:
                usages.append("profile_templates.%s (herança de aldeias conquistadas)" % profile_name)
        return usages

    @staticmethod
    def create(template_name):
        base = UnitTemplateManager._safe_name(template_name)
        path = os.path.join(UnitTemplateManager._dir(), base)
        if not os.path.exists(path):
            with open(path, 'w', encoding="utf-8") as f:
                f.write("[]")
        return base

    @staticmethod
    def save(template_name, raw_text):
        """
        Valida e grava. Lança json.JSONDecodeError/ValueError se o texto não
        for uma lista JSON válida — o caller decide como reportar o erro sem
        nada ser escrito no disco.
        """
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            raise ValueError("O template deve ser uma lista JSON de estágios ([...])")
        base = UnitTemplateManager._safe_name(template_name)
        path = os.path.join(UnitTemplateManager._dir(), base)
        with open(path, 'w', encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
        return True

    @staticmethod
    def delete(template_name):
        base = UnitTemplateManager._safe_name(template_name)
        path = os.path.join(UnitTemplateManager._dir(), base)
        if os.path.exists(path):
            os.remove(path)
        return True


class MapBuilder:
    @staticmethod
    def build(villages, current_village=None, size=None):
        out_map = {}
        min_x = 999; max_x = 0; min_y = 999; max_y = 0
        current_location = None
        grid_vils = {}
        extra_data = {}
        for v in villages:
            vdata = villages[v]
            x, y = vdata['location']
            if x < min_x: min_x = x
            if x > max_x: max_x = x
            if y < min_y: min_y = y
            if y > max_y: max_y = y
            if current_village and vdata['id'] == current_village:
                current_location = vdata['location']
                extra_data['owner'] = vdata['owner']
                extra_data['tribe'] = vdata['tribe']
            grid_vils["%d:%d" % (x, y)] = vdata
        if current_location and size:
            min_x = current_location[0] - size
            min_y = current_location[1] - size
            max_x = current_location[0] + size
            max_y = current_location[1] + size
        for location_x in range(min_x, max_x):
            if location_x not in out_map:
                out_map[location_x - min_x] = {}
            ylocs = {}
            for location_y in range(min_y, max_y):
                location = "%d:%d" % (location_x, location_y)
                ylocs[location_y - min_y] = grid_vils[location] if location in grid_vils else None
            out_map[location_x - min_x] = ylocs
        return {"grid": out_map, "extra": extra_data}


class BotManager:
    """
    Controla o processo do bot a partir do painel.

    Tres decisoes valem explicacao, porque as tres nasceram de sintomas medidos
    em 2026-09-14 e nao de preferencia de desenho:

    1. **O processo sobe num console visivel** (`CREATE_NEW_CONSOLE`), sem
       redirecionar stdout. A versao anterior usava `CREATE_NO_WINDOW` com
       stdout num arquivo, e isso e incompativel com o bot: `core/request.py`
       chama `input("Enter browser cookie string> ")` quando a sessao expira, e
       `twb.py` pergunta URL/user-agent no primeiro run. Sem console nao ha
       como responder -- o processo fica vivo e parado para sempre, com o
       painel dizendo "rodando". O `bot_output.log` de 30/06/2026 registra
       exatamente isso duas vezes seguidas: as duas tentativas morreram no
       prompt do cookie.

       ⚠️ **Atualizado em 2026-09-20: o prompt do cookie nao existe mais.**
       Sessao vencida passou a ser resolvida por `cache/cookies.txt` (o bot
       espera o arquivo aparecer e retoma sozinho) e o captcha e reconferido em
       laco em vez de esperar tecla -- ver `core/request.py::start` e
       `_await_captcha_clear`. O console continua necessario **so** para o
       primeiro run (`twb.py::manual_config`, que so roda quando nao existe
       `config.json`): a decisao fica de pe, com um motivo a menos.
    2. **`is_running()` adota qualquer twb.py do repo**, tenha sido iniciado
       pelo painel ou pelo `cmd`. O P2-32 persistiu o pid em disco para cobrir
       o restart do webmanager, mas o caso comum aqui e o usuario rodar
       `python twb.py` na mao: sem pid file, o painel dizia "nao detectado" e o
       botao Iniciar subiria um SEGUNDO bot na mesma conta -- o risco de ban
       que o P2-32 existia para matar, por outra porta.
    3. **O output vem do `session_latest.log`**, nao do `bot_output.log`. O tee
       de `twb.py` ja escreve tudo la (linha a linha, `buffering=1`),
       independente de quem iniciou o processo. O `bot_output.log` so recebia
       algo quando o painel redirecionava stdout, e passou a nao receber nada.
    """

    pid = None
    _proc = None
    _started_by_panel = False
    # Mantido so para leitura do historico antigo; nada escreve mais aqui.
    OUTPUT_LOG = os.path.join(os.path.dirname(__file__), "..", "cache", "logs", "bot_output.log")
    SESSION_LOG = os.path.join(os.path.dirname(__file__), "..", "cache", "logs", "session_latest.log")
    # P2-32: o pid vivia so em memoria, entao reiniciar o webmanager perdia a
    # referencia -> is_running() retornava False -> /bot/start subia um SEGUNDO
    # twb.py na mesma conta (risco de ban). Persistir em disco.
    PID_FILE = os.path.join(os.path.dirname(__file__), "..", "cache", "bot.pid")
    REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _read_pid_file(self):
        try:
            with open(self.PID_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _write_pid_file(self, pid):
        try:
            os.makedirs(os.path.dirname(self.PID_FILE), exist_ok=True)
            if pid is None:
                if os.path.exists(self.PID_FILE):
                    os.remove(self.PID_FILE)
            else:
                with open(self.PID_FILE, "w", encoding="utf-8") as f:
                    f.write(str(pid))
        except OSError:
            pass

    @classmethod
    def _is_twb_process(cls, pid):
        """
        Confirma que o pid ainda e um twb.py DESTE repo, e nao um pid reciclado
        pelo SO apontando para um processo qualquer.
        """
        try:
            proc = psutil.Process(pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return False
            return cls._cmdline_is_twb(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    @classmethod
    def _cmdline_is_twb(cls, proc):
        try:
            cmdline = proc.cmdline() or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        # O primeiro argumento depois do interpretador e o script. Casar so
        # pelo basename evitaria confundir com tests/ ou com outro .py que
        # mencione twb.py num argumento.
        if not any(os.path.basename(str(arg)) == "twb.py" for arg in cmdline[1:]):
            return False
        try:
            # Se o cwd for legivel, exigir que seja este repo -- assim um
            # segundo clone rodando em outra pasta nao e confundido com o
            # nosso. Quando nao da para ler, aceitar: o nome do script ja e um
            # sinal forte e o custo do falso negativo (subir um bot duplicado)
            # e maior que o do falso positivo.
            return os.path.normcase(proc.cwd()) == os.path.normcase(cls.REPO_DIR)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True

    @classmethod
    def _scan_for_twb(cls):
        """
        Procura um twb.py vivo que o painel nao conhece -- tipicamente um que o
        usuario subiu na mao pelo cmd. Sem isto o painel diz "nao detectado"
        para um bot que esta rodando, e o botao Iniciar sobe um segundo bot na
        mesma conta.
        """
        me = os.getpid()
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["pid"] == me:
                continue
            name = (proc.info["name"] or "").lower()
            if "python" not in name and "pythonw" not in name:
                continue
            if cls._cmdline_is_twb(proc):
                return proc.info["pid"]
        return None

    def is_running(self):
        pid = self.pid or self._read_pid_file()
        if pid and self._is_twb_process(pid):
            self.pid = pid
            return True
        # Pid conhecido morreu (ou nunca houve): varrer antes de concluir que
        # nao ha bot rodando.
        self.pid = None
        self._proc = None
        adopted = self._scan_for_twb()
        if adopted:
            self.pid = adopted
            self._started_by_panel = False
            self._write_pid_file(adopted)
            return True
        self._started_by_panel = False
        self._write_pid_file(None)
        return False

    def started_at(self):
        """Momento em que o processo detectado subiu, lido do proprio SO."""
        if not self.pid:
            return None
        try:
            return psutil.Process(self.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    # "Dead for 11.62 minutes (next run at: 18:23:52.530554)" -- o que twb.py
    # imprime antes de cada sono entre ciclos.
    SLEEP_RE = re.compile(r"Dead for ([\d.]+) minutes \(next run at: (\d{2}:\d{2}:\d{2})")

    @classmethod
    def _sleep_hint(cls):
        """
        Distingue "parado de proposito" de "congelado". O log so avanca quando
        o bot trabalha, entao idade alta sozinha nao diz nada: entre ciclos ele
        dorme `inactive_delay` (2000 s na config atual) em silencio. Quando a
        ultima linha e o aviso de sono, da para dizer ate quando.
        """
        tail = cls.read_output_log(lines=3)
        if not tail:
            return None
        match = cls.SLEEP_RE.search(tail[0])
        if not match:
            return None
        return {"minutes": float(match.group(1)), "next_run": match.group(2)}

    def status(self):
        running = self.is_running()
        return {
            "running": running,
            "pid": self.pid if running else None,
            "started_at": self.started_at() if running else None,
            "started_by_panel": bool(running and self._started_by_panel),
            "log_age": self.output_log_age(),
            "sleeping": self._sleep_hint() if running else None,
        }

    def start(self):
        """
        Sobe o bot num console proprio e visivel. Devolve o dict de status.

        O console nao e enfeite: o bot faz `input()` no primeiro run (URL /
        user-agent, `twb.py::manual_config`). Sem janela nao ha como responder e
        o processo fica parado sem sinal nenhum. O outro motivo -- cookie do
        navegador quando a sessao expira -- deixou de existir em 2026-09-20:
        agora vem de `cache/cookies.txt`, sem prompt.
        """
        if self.is_running():
            return self.status()
        wd = self.REPO_DIR
        os.makedirs(os.path.join(wd, "cache", "logs"), exist_ok=True)
        kwargs = {"cwd": wd, "shell": False}
        if os.name == "nt":
            import sys
            # CREATE_NEW_CONSOLE da ao processo um console proprio, com stdin
            # funcional. Nao redirecionar stdout aqui: quem registra tudo em
            # disco e o tee do proprio twb.py (cache/logs/session_latest.log),
            # que roda tenha o bot sido iniciado pelo painel ou pelo cmd.
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            # `-u` derruba o buffer de bloco do stdout. Sem isto a janela
            # cospe o output em rajadas de 8 KB e parece travada.
            cmd = [sys.executable, "-u", "twb.py"]
        else:
            cmd = self._posix_console_command()
        try:
            self._proc = subprocess.Popen(cmd, **kwargs)
        except OSError as exc:
            return {"running": False, "pid": None, "error": str(exc)}
        self.pid = self._proc.pid
        self._started_by_panel = True
        self._write_pid_file(self.pid)
        print("Bot started (PID %d)" % self.pid)
        return self.status()

    @staticmethod
    def _posix_console_command():
        """
        Em Linux/macOS nao ha equivalente universal do CREATE_NEW_CONSOLE.
        Tenta um emulador de terminal instalado; se nao houver, cai para o
        processo sem janela -- com o aviso de que um prompt de cookie ali fica
        invisivel.
        """
        import shutil
        for term, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"), ("xterm", "-e")):
            if shutil.which(term):
                return [term, flag, "python3", "-u", "twb.py"]
        return ["python3", "-u", "twb.py"]

    def stop(self):
        if not self.is_running():
            return
        try:
            proc = psutil.Process(self.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
        except psutil.NoSuchProcess:
            pass
        finally:
            self.pid = None
            self._proc = None
            self._started_by_panel = False
            self._write_pid_file(None)

    @classmethod
    def output_log_age(cls):
        """
        Segundos desde a ultima escrita no log de sessao. E o unico sinal
        disponivel de que o processo esta *trabalhando*, e nao apenas vivo --
        um bot parado num prompt de input fica com pid valido e log congelado.
        """
        try:
            return max(0.0, time.time() - os.path.getmtime(cls.SESSION_LOG))
        except OSError:
            return None

    @classmethod
    def read_output_log(cls, lines=200):
        """
        Le o fim do `session_latest.log` -- o tee que o proprio twb.py mantem,
        que funciona tenha o bot sido iniciado pelo painel ou pelo cmd.

        Le so o final do arquivo: ele passa de 2 MB numa sessao longa e isto e
        chamado em polling. Somente leitura, nunca escrita: o bot esta com o
        arquivo aberto (ver o vigesimo primeiro padrao no CLAUDE.md).
        """
        log_path = cls.SESSION_LOG
        if not os.path.exists(log_path):
            log_path = cls.OUTPUT_LOG  # historico pre-2026-09-14
            if not os.path.exists(log_path):
                return []
        # ~400 bytes por linha de log deste bot, com folga.
        window = max(64 * 1024, lines * 500)
        try:
            with open(log_path, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                f.seek(max(0, size - window))
                raw = f.read()
        except OSError:
            return []
        if size > window:
            raw = raw.split(b"\n", 1)[-1]  # descarta a primeira linha cortada
        # O log pode conter bytes NUL (ver vigesimo primeiro padrao): um
        # truncate concorrente deixa buracos que viram \x00 no meio do texto.
        text = raw.replace(b"\x00", b"").decode("utf-8", errors="replace")
        recent = [l.rstrip() for l in text.splitlines() if l.strip()][-lines:]
        recent.reverse()
        return recent


class LogReader:
    LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "logs")

    @staticmethod
    def list_log_files():
        if not os.path.exists(LogReader.LOG_DIR):
            return []
        files = [f for f in os.listdir(LogReader.LOG_DIR) if f.endswith(".log")]
        files.sort(reverse=True)
        return files

    @staticmethod
    def parse_log(filename, max_entries=500):
        filepath = os.path.join(LogReader.LOG_DIR, os.path.basename(filename))
        if not os.path.exists(filepath):
            return []
        entries = []
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        lines = lines[-max_entries:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("Starting bot at "):
                try:
                    ts = int(line.split("Starting bot at ")[1])
                    dt = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")
                except Exception:
                    ts = 0; dt = "?"
                entries.append({"timestamp": ts, "datetime": dt, "village_id": None,
                                 "event_type": "BOT_START", "message": line})
                continue
            parts = line.split(" - ", 3)
            if len(parts) < 3:
                entries.append({"timestamp": 0, "datetime": "?", "village_id": None,
                                 "event_type": "RAW", "message": line})
                continue
            try:
                ts = int(parts[0])
                dt = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                ts = 0; dt = parts[0]
            entries.append({
                "timestamp": ts, "datetime": dt,
                "village_id": parts[1].strip(), "event_type": parts[2].strip(),
                "message": parts[3].strip() if len(parts) > 3 else "",
            })
        entries.reverse()
        return entries


class ConquestReader:
    """
    Lê cache/conquest/*.json e calcula lealdade estimada em tempo real.

    Estrutura esperada de cada arquivo:
    {
        "target_id": "12345",
        "status": "train_sent" | "extra_pending" | "complete",
        "reserved_by": "225114",
        "hits_done": 2,
        "hits_needed": 4,
        "loyalty_start": 100,
        "loyalty_drop_per_noble": 25,
        "loyalty_regen_per_hour": 1,
        "last_hit_timestamp": 1718000000,
        "target_name": "Barbarian village",
        "target_points": 800,
        "target_location": [450, 512]
    }
    """

    # "Conquistada" verde so para posse COMPROVADA. Ate 2026-08-13 um unico
    # status "complete" cobria tanto a prova (cache de aldeias ou nosso
    # relatorio de nobre) quanto a mera estimativa aritmetica, e a tela pintava
    # os dois de verde igual. No incidente da Barbara #40314 o alvo apareceu
    # como "Conquistada" as 20:19:37 com o nobre ainda voando e a aldeia ainda
    # barbara -- a tela afirmava um fato que ninguem tinha verificado.
    STATUS_LABELS = {
        # Trem multi-origem montado e registrado no Hunter, ainda sem sair: o
        # envio de cada origem é recuado a partir de uma hora de chegada comum,
        # então essa janela dura de minutos a horas
        # (game/conquest_planner.py::BarbarianTrainPlanner).
        "train_scheduled": "Trem agendado (aguardando janela de envio)",
        "train_sent":    "Train Enviado",
        "extra_pending": "Extra Pendente",
        "conquered":     "Conquistada (confirmada)",
        "assumed_done":  "Sem confirmação — verifique no jogo",
        # Bárbara conquistada por outro jogador enquanto nosso trem voava.
        # O bot desiste do alvo em vez de virar conquista de PvP por acidente
        # (game/attack.py::_handle_existing, Priority 2).
        "lost":          "Perdida para outro jogador",
        "manual":        "Alvo Manual (na fila)",
        "invalid":       "Alvo Manual Inválido",
        # Registros gravados antes da separacao acima. Nao da para saber se
        # foram prova ou palpite, entao nao levam verde.
        "complete":      "Concluída (registro antigo)",
    }
    STATUS_COLORS = {
        "train_scheduled": "info",
        "train_sent":    "warning",
        "extra_pending": "info",
        "conquered":     "success",
        "assumed_done":  "warning",
        "lost":          "danger",
        "manual":        "primary",
        "invalid":       "secondary",
        "complete":      "secondary",
    }

    @staticmethod
    def _estimate_loyalty(data, drop_override=None):
        """
        Calcula lealdade estimada atual.
        loyalty_after_nobles = loyalty_start - (hits_done * loyalty_drop_per_noble)
        loyalty_current = loyalty_after_nobles + hours_since_last_hit * loyalty_regen_per_hour
        Clampado em [0, 100].

        `drop_override` permite refazer a conta com o outro extremo da faixa
        de queda do mundo (20-35 no br143), para a tela mostrar o intervalo em
        vez de um numero unico com precisao que ele nao tem.
        """
        loyalty_start       = data.get("loyalty_start", 100)
        hits_done           = data.get("hits_done", 0)
        drop_per_noble      = drop_override or data.get("loyalty_drop_per_noble", 25)
        regen_per_hour      = data.get("loyalty_regen_per_hour", 1)
        last_hit_ts         = data.get("last_hit_timestamp", None)

        loyalty_after_nobles = loyalty_start - (hits_done * drop_per_noble)

        if last_hit_ts:
            # last_hit_timestamp passou a ser o *pouso* do ultimo nobre
            # (game/attack.py::_send_train, 2026-08-13), nao mais o envio.
            # Enquanto o nobre voa esse timestamp esta no futuro, e sem o
            # max(0, ...) o tempo decorrido ficaria negativo -- a tela
            # mostraria lealdade abaixo da real, ou zero, para um alvo que
            # ainda nem foi atingido. Antes do pouso nao ha regeneracao a
            # contar: zero decorrido e a resposta certa, nao um acidente.
            hours_elapsed = max(
                0.0,
                (datetime.datetime.now().timestamp() - last_hit_ts) / 3600.0
            )
            loyalty_current = loyalty_after_nobles + (hours_elapsed * regen_per_hour)
        else:
            loyalty_current = loyalty_after_nobles

        return round(max(0.0, min(100.0, loyalty_current)), 1)

    @staticmethod
    def _loyalty_color(loyalty):
        """Retorna classe Bootstrap com base no risco de regen."""
        if loyalty <= 10:
            return "danger"
        if loyalty <= 30:
            return "warning"
        return "success"

    @staticmethod
    def _fmt_ts(ts):
        if not ts:
            return "—"
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")
        except (OSError, OverflowError, ValueError):
            return "—"

    @staticmethod
    def load():
        conquest_dir = os.path.join(os.path.dirname(__file__), "..", "cache", "conquest")
        if not os.path.exists(conquest_dir):
            return []

        targets = []
        for fname in os.listdir(conquest_dir):
            if not fname.endswith(".json"):
                continue
            target_id = fname.replace(".json", "")
            try:
                # utf-8-sig e nao o encoding do locale: queue_manual() abaixo
                # grava com ensure_ascii=False, entao "Bárbara #NNNN" vai ao
                # disco com o acento em bytes reais. Lido em cp1252 (padrao no
                # Windows pt-BR) viraria "BÃ¡rbara". Mesmo motivo do
                # FileManager.load_json_file.
                with open(os.path.join(conquest_dir, fname), "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception:
                continue

            loyalty_source = data.get('loyalty_source', 'estimate')
            # loyalty_now usa o piso da faixa de queda (o bot grava
            # loyalty_drop_per_noble = drop_min), entao e o cenario PESSIMISTA:
            # "no minimo isto de lealdade sobrou". O outro extremo vira
            # loyalty_best, e a tela mostra os dois quando a fonte e
            # estimativa -- um numero unico sugeriria uma precisao que a
            # mecanica nao tem, ja que cada nobre sorteia a queda.
            loyalty_now   = ConquestReader._estimate_loyalty(data)
            loyalty_color = ConquestReader._loyalty_color(loyalty_now)
            drop_range    = data.get("loyalty_drop_range") or []
            loyalty_best  = None
            if len(drop_range) == 2 and drop_range[0] != drop_range[1]:
                loyalty_best = ConquestReader._estimate_loyalty(
                    data, drop_override=drop_range[1]
                )

            last_hit_ts  = data.get("last_hit_timestamp", None)
            last_hit_fmt = "—"
            if last_hit_ts:
                try:
                    last_hit_fmt = datetime.datetime.fromtimestamp(last_hit_ts).strftime("%d/%m %H:%M")
                except Exception:
                    pass

            status      = data.get("status", "train_sent")
            hits_done   = data.get("hits_done", 0)
            hits_needed = data.get("hits_needed", 4)
            hits_pct    = round((hits_done / hits_needed) * 100) if hits_needed > 0 else 0

            location = data.get("target_location", None)
            location_str = ("%d|%d" % tuple(location)) if location else "—"

            targets.append({
                "target_id":      target_id,
                "target_name":    data.get("target_name", "Bárbara #%s" % target_id),
                "target_points":  data.get("target_points", "?"),
                "location_str":   location_str,
                "reserved_by":    data.get("reserved_by", "—"),
                "status":         status,
                "status_label":   ConquestReader.STATUS_LABELS.get(status, status),
                "status_color":   ConquestReader.STATUS_COLORS.get(status, "secondary"),
                "hits_done":      hits_done,
                "hits_needed":    hits_needed,
                "hits_pct":       hits_pct,
                "loyalty_now":    loyalty_now,
                "loyalty_best":   loyalty_best,
                "loyalty_drop_range": drop_range or None,
                "loyalty_color":  loyalty_color,
                "loyalty_source": loyalty_source,
                "last_hit_fmt":   last_hit_fmt,
                "last_hit_ts":    last_hit_ts or 0,
                # Feature 15 — alvos manuais na fila (ainda não reivindicados
                # por nenhuma aldeia) ou invalidados (deixaram de ser bárbaras).
                "queued_at":      data.get("queued_at"),
                "queued_at_fmt":  ConquestReader._fmt_ts(data.get("queued_at")),
                # Trem multi-origem ainda por sair: a chegada e uma PREVISAO
                # (o horario comum que o planejador escolheu), nao um pouso
                # observado -- por isso campo proprio, separado de
                # last_hit_ts, que so existe depois do despacho.
                "scheduled_arrival":     data.get("scheduled_arrival"),
                "scheduled_arrival_fmt": ConquestReader._fmt_ts(data.get("scheduled_arrival")),
                "sources":        data.get("sources") or {},
                "invalid_reason": data.get("invalid_reason"),
                # Quem levou a bárbara antes de nós (status "lost").
                "lost_to_owner":  data.get("lost_to_owner"),
                # Como a posse foi comprovada: "village_cache" ou
                # "noble_report" (status "conquered"). Ausente nos registros
                # antigos e nos "assumed_done", que por definição não têm prova.
                "confirmed_by":   data.get("confirmed_by"),
                "assumed_reason": data.get("assumed_reason"),
            })

        # Ordenação por quanto pedem atenção, não por progresso: alvo manual na
        # fila primeiro, depois em andamento, depois os dois casos que pedem
        # olho humano (sem confirmação, e perdida para outro jogador), e por
        # último o que está resolvido.
        order = {
            "manual": -1, "train_scheduled": 0, "train_sent": 1,
            "extra_pending": 2, "assumed_done": 3, "lost": 4,
            "conquered": 5, "complete": 6, "invalid": 7,
        }
        targets.sort(key=lambda t: (order.get(t["status"], 9), -t["last_hit_ts"]))
        return targets

    # ------------------------------------------------------------------
    # Área de interesse — para que lado o bot cresce
    # ------------------------------------------------------------------

    @staticmethod
    def area_of_interest(config=None):
        """
        Estado da `conquest.area_of_interest` mais uma contagem REAL de quantas
        bárbaras conhecidas caem dentro dela.

        Por que a contagem e não só a caixa: uma caixa com os eixos trocados,
        ou apontada para o hemisfério errado, é indistinguível de uma caixa
        correta olhando só os números. O que separa as duas é quantos alvos ela
        seleciona — e esse é justamente o valor que o operador não consegue
        calcular de cabeça.

        Custo medido em 17/09/2026: 0,112 s para os 850 arquivos de
        `cache/villages` (contra os 8,3 s que a varredura de `cache/reports`
        custava antes de ser indexada — são 850 arquivos pequenos, não 1.056
        relatórios). Sem índice de propósito: `Map.build_cache_entry` reescreve
        esses arquivos in-place quando dono ou pontos mudam, então um índice
        por nome de arquivo serviria dado velho, e um por mtime não pagaria o
        próprio custo em 0,1 s.

        `dentro` NÃO aplica o raio: o raio é medido a partir de cada aldeia de
        origem, então não existe um número global. É contagem de elegíveis por
        dono e pontos, e a interface diz isso.
        """
        config = config if config is not None else DataReader.config_grab()
        cq = (config or {}).get("conquest", {}) or {}
        area = cq.get("area_of_interest") or {}
        out = {
            "enabled": bool(area.get("enabled", False)),
            "x_min": area.get("x_min"), "x_max": area.get("x_max"),
            "y_min": area.get("y_min"), "y_max": area.get("y_max"),
            "min_points": cq.get("min_points"), "max_points": cq.get("max_points"),
            "max_radius": cq.get("max_radius"),
            "label": None, "inside": 0, "total": 0, "usable": False,
        }
        try:
            box = (int(area["x_min"]), int(area["x_max"]),
                   int(area["y_min"]), int(area["y_max"]))
        except (KeyError, TypeError, ValueError):
            return out
        out["usable"] = True
        out["label"] = "%d–%d | %d–%d" % box

        x_min, x_max, y_min, y_max = box
        lo = cq.get("min_points", 0) or 0
        hi = cq.get("max_points", 10 ** 9) or 10 ** 9
        v_dir = ConquestReader._villages_dir()
        if not os.path.isdir(v_dir):
            return out
        for entry in os.scandir(v_dir):
            if not entry.name.endswith(".json"):
                continue
            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    v = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            loc = v.get("location")
            if not loc or len(loc) != 2:
                continue
            if str(v.get("owner", "0")) != "0":
                continue
            pts = v.get("points") or 0
            if pts < lo or pts > hi:
                continue
            out["total"] += 1
            x, y = int(loc[0]), int(loc[1])
            if x_min <= x <= x_max and y_min <= y <= y_max:
                out["inside"] += 1
        return out

    # ------------------------------------------------------------------
    # Feature 15 — seleção manual de alvo de conquista bárbara
    # ------------------------------------------------------------------

    @staticmethod
    def _villages_dir():
        return villages_cache_dir()

    @staticmethod
    def _conquest_dir():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "conquest")

    @staticmethod
    def _resolve_identifier(identifier):
        """Alias historico de `resolve_village_identifier()` (nivel de modulo)."""
        return resolve_village_identifier(identifier)

    @staticmethod
    def add_manual_target(identifier):
        """
        Enfileira um alvo manual de conquista bárbara. Cria
        cache/conquest/{id}.json com status "manual" -- será consumido pela
        primeira aldeia com noble train pronto que rodar seu ciclo
        (ConquestManager._get_manual_target(), game/attack.py), em ordem de
        chegada (queued_at). Rejeita e lança ValueError (sem escrever nada)
        se: identificador não resolver, aldeia não for bárbara, ou já
        existir uma conquista ativa/pendente para o mesmo alvo.
        """
        target_id, village_data = ConquestReader._resolve_identifier(identifier)

        owner = str(village_data.get("owner", "0"))
        if owner != "0":
            raise ValueError(
                "Aldeia #%s (%s) não é bárbara (dono atual: %s) — apenas "
                "aldeias bárbaras podem ser conquistadas." % (
                    target_id, village_data.get("name", "?"), owner
                )
            )

        conquest_path = os.path.join(ConquestReader._conquest_dir(), "%s.json" % target_id)
        if os.path.exists(conquest_path):
            with open(conquest_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("status") in ("train_sent", "extra_pending", "manual"):
                raise ValueError(
                    "Já existe uma conquista (%s) para a aldeia #%s." % (
                        ConquestReader.STATUS_LABELS.get(
                            existing.get("status"), existing.get("status")
                        ),
                        target_id
                    )
                )

        os.makedirs(ConquestReader._conquest_dir(), exist_ok=True)
        entry = {
            "status": "manual",
            "queued_at": datetime.datetime.now().timestamp(),
            "target_name": village_data.get("name") or ("Bárbara #%s" % target_id),
            "target_points": village_data.get("points"),
            "target_location": village_data.get("location"),
        }
        with open(conquest_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2, ensure_ascii=False)
        return target_id

    @staticmethod
    def cancel_manual(target_id):
        """
        Cancela um alvo manual ainda não reivindicado (status "manual" ou
        "invalid"). Bloqueia cancelamento de conquistas já em andamento --
        apagar o cache nesse caso não recuperaria os nobles já enviados, só
        quebraria o acompanhamento no webmanager.
        """
        target_id = (target_id or "").strip()
        path = os.path.join(ConquestReader._conquest_dir(), "%s.json" % target_id)
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("status") not in ("manual", "invalid"):
            raise ValueError(
                "Não é possível cancelar: alvo #%s já está em '%s' (nobles podem "
                "já ter sido enviados)." % (
                    target_id,
                    ConquestReader.STATUS_LABELS.get(data.get("status"), data.get("status"))
                )
            )
        os.remove(path)

    @staticmethod
    def force_clear(target_id):
        """
        Feature (2026-08-07): apaga cache/conquest/{id}.json independente do
        status -- diferente de cancel_manual() (que só cobre "manual"/
        "invalid" de propósito, pra não perder o rastreio de nobles
        realmente em rota). Este método existe pro caso oposto: o usuário
        cancelou o noble train manualmente *no jogo* (fora do bot), então o
        cache já está desatualizado e a validação de cancel_manual bloquearia
        exatamente a limpeza que faz sentido aqui. Sem essa opção, o alvo
        ficava "reservado" pra sempre em ConquestCache.all_reserved()
        (game/attack.py::ConquestManager.find_target()), nunca mais
        reavaliado automaticamente. Não tenta desfazer nada no jogo -- só
        remove o registro de acompanhamento do bot.
        """
        target_id = (target_id or "").strip()
        path = os.path.join(ConquestReader._conquest_dir(), "%s.json" % target_id)
        if os.path.exists(path):
            os.remove(path)


class HunterReader:
    """
    Lê, cria e deleta schedules em cache/hunter/schedules.json.
    O bot (hunter.py) proba os send_times no próximo ciclo.
    """

    DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

    STATUS_LABELS = {
        "pending":  "Pendente",
        "sent":     "Enviado",
        "complete": "Completo",
        "failed":   "Falhou",
    }
    STATUS_COLORS = {
        "pending":  "warning",
        "sent":     "info",
        "complete": "success",
        "failed":   "danger",
    }

    @staticmethod
    def _cache_path():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "hunter", "schedules.json")

    @staticmethod
    def _load_raw():
        path = HunterReader._cache_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _save_raw(data):
        path = HunterReader._cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load():
        """Retorna lista de schedules com campos formatados para o template."""
        raw = HunterReader._load_raw()
        schedules = []
        now = datetime.datetime.now().timestamp()

        for sched_key, sched in raw.items():
            arrival_ts = sched.get("arrival_time", 0)
            arrival_str = sched.get("arrival_str", "")
            if not arrival_str and arrival_ts:
                arrival_str = datetime.datetime.fromtimestamp(arrival_ts).strftime(HunterReader.DATETIME_FMT)

            time_to_arrival = round(arrival_ts - now) if arrival_ts else None
            if time_to_arrival is not None:
                abs_t = abs(time_to_arrival)
                h, rem = divmod(abs_t, 3600)
                m, s = divmod(rem, 60)
                time_to_arrival_fmt = "%dh%02dm%02ds" % (h, m, s)
            else:
                time_to_arrival_fmt = ""

            status = sched.get("status", "pending")

            # Formata cada ataque
            attacks_fmt = []
            for atk in sched.get("attacks", []):
                st = atk.get("send_time")
                send_time_fmt = ""
                if st:
                    try:
                        send_time_fmt = datetime.datetime.fromtimestamp(st).strftime("%d/%m %H:%M:%S")
                    except Exception:
                        pass
                attacks_fmt.append({
                    "source_village_id": atk.get("source_village_id", "?"),
                    "troops": atk.get("troops", {}),
                    "is_fake": atk.get("is_fake", False),
                    "status": atk.get("status", "pending"),
                    "send_time_fmt": send_time_fmt,
                })

            schedules.append({
                "sched_key":          sched_key,
                "target_id":          sched.get("target_id", "?"),
                "arrival_str":        arrival_str,
                "arrival_ts":         arrival_ts,
                "time_to_arrival":    time_to_arrival,
                "time_to_arrival_fmt": time_to_arrival_fmt,
                "status":             status,
                "status_label":       HunterReader.STATUS_LABELS.get(status, status),
                "status_color":       HunterReader.STATUS_COLORS.get(status, "secondary"),
                "attacks":            attacks_fmt,
            })

        # Pendentes primeiro, depois por arrival_ts
        order = {"pending": 0, "sent": 1, "failed": 2, "complete": 3}
        schedules.sort(key=lambda s: (order.get(s["status"], 9), s["arrival_ts"]))
        return schedules

    @staticmethod
    def add_schedule(target_id, arrival_str, attacks, label=None):
        """
        Cria um novo schedule no cache.
        attacks: list of dicts {source_village_id, troops{unit: qty}, is_fake}

        Bugfix (2026-08-07): `target_id` here MUST be the real game village
        id -- it's stored verbatim as the schedule's "target_id" field, and
        Hunter.run() (game/hunter.py) uses that exact field both to probe
        travel duration (village.area.map_pos lookup) and to actually fire
        the attack (village.attack.attack(target_id, ...)). Neither of
        those work with anything other than a real village id.

        PvpConquestManager used to pass "{target_id}_pvp_{label}" here (e.g.
        "38409_pvp_clear") purely so its own clear/nobles schedules for the
        same target wouldn't collide as the same sched_key. That silently
        broke every single PvP-conquest-scheduled attack: the duration
        probe always failed ("target ... not in map_pos"), and even if it
        hadn't, the actual attack() call would have too (same map_pos
        check). This bug meant no PvP Conquest attack could ever fire for
        real, from the very first version of this Hunter integration --
        masked because attacks silently stayed "pending" and the schedule
        just failed once its arrival time passed, indistinguishable in the
        logs from "hasn't happened yet".

        Fixed by keeping `target_id` as the real id and moving the
        distinguishing suffix to the optional `label` param instead, which
        only affects `sched_key` (the cache dict key) and is stored
        separately as its own "label" field -- never touches what Hunter
        actually uses to act in-game.
        """
        try:
            arrival_ts = datetime.datetime.strptime(
                arrival_str, HunterReader.DATETIME_FMT
            ).timestamp()
        except ValueError:
            return False

        sched_key = "%s_%s" % (target_id, arrival_str.replace(" ", "T").replace(":", "-"))
        if label:
            sched_key = "%s_%s" % (sched_key, label)

        attack_entries = []
        for atk in attacks:
            # Strip zero-qty units
            troops = {u: int(q) for u, q in atk.get("troops", {}).items() if int(q) > 0}
            if not troops:
                continue
            attack_entries.append({
                "source_village_id": str(atk["source_village_id"]),
                "troops": troops,
                "is_fake": bool(atk.get("is_fake", False)),
                "send_time": None,
                "status": "pending",
            })

        if not attack_entries:
            return False

        raw = HunterReader._load_raw()
        raw[sched_key] = {
            "target_id":    str(target_id),
            "label":        label,
            "arrival_time": arrival_ts,
            "arrival_str":  arrival_str,
            "status":       "pending",
            "attacks":      attack_entries,
        }
        HunterReader._save_raw(raw)
        return True

    @staticmethod
    def delete_schedule(sched_key):
        raw = HunterReader._load_raw()
        raw.pop(sched_key, None)
        HunterReader._save_raw(raw)
        return True

    @staticmethod
    def set_enabled(enabled):
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_path, "r") as f:
            config = json.load(f, object_pairs_hook=collections.OrderedDict)
        if "hunter" not in config:
            config["hunter"] = {}
        config["hunter"]["enabled"] = bool(enabled)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        return bool(enabled)


class ZoneReader:
    """
    Lê cache/zones.json (gerado pelo ZoneManager a cada ciclo do bot)
    e enriquece com dados de cache/managed para renderização no webmanager.
    """

    # Paleta de cores por zona — indexada ciclicamente
    ZONE_COLORS = [
        "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
        "#9b59b6", "#1abc9c", "#e67e22", "#34495e",
    ]

    @staticmethod
    def load_raw():
        """Retorna o conteúdo bruto de cache/zones.json ou None."""
        path = os.path.join(os.path.dirname(__file__), "..", "cache", "zones.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def enrich(managed_cache):
        """
        Combina zones.json com cache/managed/*.json.
        Retorna dict com:
          - zones: lista de zonas enriquecidas
          - radius: raio atual
          - all_villages: lista plana de todas as aldeias com x, y e zona
        """
        zone_data = ZoneReader.load_raw()
        if not zone_data:
            return {"zones": [], "radius": 10, "all_villages": []}

        radius = zone_data.get("radius", 10)
        zones_out = []
        all_villages = []

        for i, (zone_name, village_ids) in enumerate(zone_data.get("zones", {}).items()):
            color = ZoneReader.ZONE_COLORS[i % len(ZoneReader.ZONE_COLORS)]
            villages = []
            for vid in village_ids:
                vdata = managed_cache.get(vid, {})
                # P2-21: set_cache_vars grava "public": None quando a aldeia
                # ainda nao tem dados publicos -- a chave existe, entao o
                # default do .get() nao entra. Precisa do `or {}`.
                pub = vdata.get("public", {}) or {}
                entry = {
                    "id": vid,
                    "name": pub.get("name", "Aldeia %s" % vid),
                    "x": vdata.get("x", 0),
                    "y": vdata.get("y", 0),
                    "profile": vdata.get("profile"),
                    "under_attack": vdata.get("under_attack", False),
                    "zone": zone_name,
                    "color": color,
                }
                villages.append(entry)
                all_villages.append(entry)

            zones_out.append({
                "name": zone_name,
                "color": color,
                "villages": villages,
                "count": len(villages),
            })

        return {"zones": zones_out, "radius": radius, "all_villages": all_villages}


class EmpireReader:
    """
    Feature 17 — dashboard /empire. Agrega dados já persistidos por outras
    features/managers em uma visão de "império inteiro": tropas totais por
    tipo, recursos por aldeia, mapa de calor de atividade de farm e
    timeline de conquistas. Não cria nenhum diretório de cache novo — só
    lê e cruza cache/managed, cache/villages, cache/attacks (já lidos por
    sync(), ver server.py) e a saída de ConquestReader.load() (cache/conquest).
    """

    @staticmethod
    def troop_totals(managed):
        """
        Soma o campo "troops" (TroopManager.total_troops, persistido por
        Village.set_cache_vars() — conta unidades totais, incluindo as que
        estão em rota, não só as paradas em casa) de todas as aldeias
        gerenciadas. Retorna [(unit, total), ...] ordenado por total desc.
        """
        totals = {}
        for data in (managed or {}).values():
            for unit, count in (data.get("troops") or {}).items():
                try:
                    totals[unit] = totals.get(unit, 0) + int(count)
                except (TypeError, ValueError):
                    continue
        return sorted(totals.items(), key=lambda kv: -kv[1])

    @staticmethod
    def resources_by_village(managed):
        """
        Uma linha por aldeia gerenciada com recursos atuais, pontos e
        status de ataque — para a tabela "Recursos por aldeia".
        """
        rows = []
        for vid, data in (managed or {}).items():
            resources = data.get("resources") or {}
            rows.append({
                "village_id": vid,
                "name": data.get("name") or vid,
                "wood": resources.get("wood", 0),
                "stone": resources.get("stone", 0),
                "iron": resources.get("iron", 0),
                "pop": resources.get("pop", 0),
                "points": data.get("points"),
                "under_attack": data.get("under_attack", False),
            })
        rows.sort(key=lambda r: r["name"])
        return rows

    @staticmethod
    def resource_totals(rows):
        """
        Linha de rodape somando o imperio inteiro para a tabela "Recursos por
        aldeia" (polimento pendente da Feature 17).

        Somado em Python de proposito, e nao com `{{ rows | sum(attribute=..) }}`
        no Jinja2: o campo se chama `pop`, e o filtro `sum` com `attribute`
        resolve por getattr antes de getitem -- pegaria `dict.pop`, o metodo,
        que e exatamente o oitavo padrao do CLAUDE.md (o mesmo bug que ja
        apareceu nesta tabela e obrigou o `{{ r['pop'] }}` do template).
        """
        totals = {"wood": 0, "stone": 0, "iron": 0, "pop": 0, "points": 0, "villages": 0}
        for r in rows or []:
            totals["villages"] += 1
            for key in ("wood", "stone", "iron", "pop", "points"):
                try:
                    totals[key] += int(r.get(key) or 0)
                except (TypeError, ValueError):
                    continue
        return totals

    @staticmethod
    def farm_heatmap(attacks, villages, managed):
        """
        Cruza cache/attacks/*.json (contagem de ataques por alvo, mantida
        por AttackManager) com cache/villages/*.json (coordenada do alvo,
        populada pelo fetch de mapa de qualquer aldeia gerenciada — ver
        game/map.py::Map.build_cache_entry) para plotar os alvos de farm
        como pontos coloridos por intensidade (attack_count). Alvos nunca
        vistos por nenhum fetch de mapa (sem entrada correspondente em
        cache/villages) são ignorados — não há coordenada para posicioná-los.

        As próprias aldeias gerenciadas entram como pontos separados
        ("own"), usando x/y de cache/managed diretamente (sempre presente,
        não depende do cache de mapa) para servir de referência visual no
        mapa de calor.
        """
        points = []
        max_count = 0
        for target_id, adata in (attacks or {}).items():
            vdata = (villages or {}).get(target_id)
            if not vdata or not vdata.get("location"):
                continue
            count = adata.get("attack_count", 0) or 0
            max_count = max(max_count, count)
            points.append({
                "target_id": target_id,
                # name=0 vindo do jogo para barbara -- ver village_display_name
                "name": village_display_name(vdata, target_id),
                "x": vdata["location"][0],
                "y": vdata["location"][1],
                "attack_count": count,
                "farm_score": adata.get("farm_score"),
                "safe": adata.get("safe", True),
                "reserved_by": adata.get("reserved_by"),
            })

        own = []
        for vid, data in (managed or {}).items():
            if "x" not in data or "y" not in data:
                continue
            own.append({
                "village_id": vid,
                "name": data.get("name") or vid,
                "x": data["x"],
                "y": data["y"],
            })

        return {"points": points, "own": own, "max_count": max_count}

    PVP_STATUS_LABEL_PREFIX = {
        "pending_scout": "PvP: Aguardando Scout",
        "pending_troops": "PvP: Aguardando Tropa",
        "pending_sim":   "PvP: Aguardando Simulação",
        "scheduled":     "PvP: Agendado",
        "complete":      "PvP: Conquistado",
        "failed":        "PvP: Falhou",
    }

    @staticmethod
    def pvp_conquest_timeline_entries(pvp_targets, villages):
        """
        Bugfix (2026-08-07): the /empire timeline widget only ever read
        ConquestReader.load() (cache/conquest -- barbarian conquest,
        Feature 8), which stays empty forever on this project's config
        (conquest.enabled=false). PvP Conquest (Feature 13) is the system
        actually used, and it had a real, confirmed conquest (target 38409,
        validated live) that never showed up here -- the widget's empty-state
        even pointed at "/conquest", the wrong/unused page. This normalizes
        PvpConquestReader.load() output into the same shape ConquestReader
        entries use, so conquest_timeline() below can merge both.

        villages: dict {village_id: cache/villages/{id}.json content} (same
        shape sync() already loads for farm_heatmap) -- used for target
        name/points/coords, since PvpConquestReader doesn't carry those.
        """
        out = []
        for t in (pvp_targets or []):
            vdata = (villages or {}).get(t["target_id"]) or {}
            location = vdata.get("location")
            location_str = ("%d|%d" % tuple(location)) if location else "—"

            # Best single representative timestamp for sort/display order:
            # prefer the most advanced milestone actually reached so far.
            event_ts = t.get("completed_at") or t.get("failed_at") or t.get("scheduled_at") or 0
            event_fmt = "—"
            if event_ts:
                try:
                    event_fmt = datetime.datetime.fromtimestamp(event_ts).strftime("%d/%m %H:%M")
                except (OSError, OverflowError, ValueError):
                    pass

            noble_count = len(t.get("noble_villages") or [])
            status = t["status"]

            out.append({
                "target_id":      t["target_id"],
                "target_name":    t.get("target_name") or vdata.get("name") or ("Aldeia %s" % t["target_id"]),
                "target_points":  vdata.get("points", "?"),
                "location_str":   location_str,
                "reserved_by":    t.get("clear_village_id") or "—",
                "status":         status,
                "status_label":   EmpireReader.PVP_STATUS_LABEL_PREFIX.get(status, "PvP: %s" % status),
                "status_color":   t.get("status_color", "secondary"),
                "hits_done":      noble_count if status == "complete" else 0,
                "hits_needed":    noble_count or "?",
                "loyalty_now":    "—",
                "last_hit_ts":    event_ts,
                "last_hit_fmt":   event_fmt,
                "queued_at":      None,
                "queued_at_fmt":  None,
            })
        return out

    @staticmethod
    def conquest_timeline(conquest_targets, pvp_targets=None, villages=None, limit=30):
        """
        Reordena a lista já processada por ConquestReader.load() (bárbaro,
        Feature 8) e, agora, também PvpConquestReader.load() normalizado via
        pvp_conquest_timeline_entries() (PvP, Feature 13 -- o sistema
        realmente usado neste projeto), em ordem cronológica (evento mais
        recente primeiro) — usa last_hit_ts (progresso real do noble train)
        quando disponível, senão queued_at (alvo manual bárbaro ainda não
        reivindicado, Feature 15). Entradas sem nenhum timestamp (não deveria
        acontecer, mas por segurança) ficam de fora da timeline.
        """
        def event_ts(t):
            return t.get("last_hit_ts") or t.get("queued_at") or 0

        merged = list(conquest_targets or []) + EmpireReader.pvp_conquest_timeline_entries(pvp_targets, villages)
        ordered = sorted(
            (t for t in merged if event_ts(t) > 0),
            key=event_ts, reverse=True,
        )
        return ordered[:limit]


class PlayerStatsReader:
    """
    Le `cache/player_stats.json` (Feature 37, `game/player_stats.py`) — a
    serie "Saqueado" x "Coletado" que o proprio jogo publica por dia, ja
    agregada server-side em `screen=info_player&mode=stats_own`.

    Contexto: docs/backend.md 8.13 (P-STATS-JOGO) e docs/frontend.md 6.1.2,
    item 6. Existe para responder de graca a pergunta "a coleta rendeu mais
    que o farm nas ultimas 24h" — algo que nenhuma outra fonte do painel
    enxerga, porque tambem conta o que o USUARIO fez na mao fora do bot.

    QUATRO CONTRATOS QUE O TEMPLATE PRECISA RESPEITAR (nao so este reader):
      (a) CONTA INTEIRA — nunca rotular como "desta aldeia". As tabelas de
          farm por aldeia continuam sendo ReportReader/FarmScoreReader;
      (b) so os dias que o jogo mandou (ate 7) — sem acumular localmente,
          entao uma janela maior aqui seria inventada, nao lida;
      (c) `percent`, se algum dia for exibido, e participacao NO TOTAL DO
          DIA (saqueado + coletado + gasto), nao "aproveitamento" — este
          reader nem repassa o campo hoje, de proposito, para nao criar a
          tentacao de rotula-lo errado antes de decidir a UI dele;
      (d) SALDO por dia, nao evento — o dia mais recente pode estar parcial
          (o jogo ainda esta acumulando), e o template mostra isso, nao
          finge que e um total fechado.
    """

    CACHE_PATH = os.path.join(
        os.path.dirname(__file__), "..", "cache", "player_stats.json"
    )

    @staticmethod
    def load():
        empty = {
            "available": False,
            "fetched_at": None,
            "fetched_at_fmt": "—",
            "days": [],
        }
        if not os.path.exists(PlayerStatsReader.CACHE_PATH):
            return empty
        try:
            with open(PlayerStatsReader.CACHE_PATH, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            # JSON parcial: o bot grava atomicamente (FileManager.save_json_file),
            # mas o fallback in-place existe. Ausente e honesto — nao se
            # inventa um dia que a leitura anterior nao confirmou.
            return empty

        series = data.get("series") or {}
        looted = {row.get("observed_at"): row for row in series.get("Saqueado") or []}
        gathered = {row.get("observed_at"): row for row in series.get("Coletado") or []}
        stamps = sorted(
            {s for s in list(looted) + list(gathered) if s is not None}, reverse=True
        )

        days = []
        for i, stamp in enumerate(stamps):
            l = looted.get(stamp) or {}
            g = gathered.get(stamp) or {}
            try:
                date_fmt = datetime.datetime.fromtimestamp(stamp).strftime("%d/%m")
            except (OSError, OverflowError, ValueError):
                date_fmt = "—"
            days.append({
                "observed_at": stamp,
                "date_fmt": date_fmt,
                # O dia mais recente que o jogo publica pode ainda estar
                # acumulando (a resposta nao diz "fechado"/"em aberto") --
                # marcado para o template avisar em vez de apresentar como
                # total definitivo (contrato d acima).
                "maybe_partial": i == 0,
                "looted_total": l.get("total"),
                "looted_wood": l.get("wood"),
                "looted_stone": l.get("stone"),
                "looted_iron": l.get("iron"),
                "gathered_total": g.get("total"),
                "gathered_wood": g.get("wood"),
                "gathered_stone": g.get("stone"),
                "gathered_iron": g.get("iron"),
            })

        fetched_at = data.get("fetched_at")
        fetched_fmt = "—"
        if fetched_at:
            try:
                fetched_fmt = datetime.datetime.fromtimestamp(fetched_at).strftime("%d/%m %H:%M")
            except (OSError, OverflowError, ValueError):
                pass

        return {
            "available": bool(days),
            "fetched_at": fetched_at,
            "fetched_at_fmt": fetched_fmt,
            "days": days,
        }


class InFlightReader:
    """
    Le `cache/in_flight.json` (Feature 38, `game/in_flight.py`) — todo comando
    que esta no ar saindo desta conta, com a hora de chegada calculada pelo
    SERVIDOR, lida de `screen=overview_villages&mode=commands`.

    Contexto: docs/frontend.md 6.1.2, item 1 ("Painel Em voo"), descrito la
    como o mais valioso e o unico nao cosmetico da lista.

    OS DOIS CONTRATOS QUE O TEMPLATE TAMBEM PRECISA RESPEITAR:
      (a) o que se le e HORA DE CHEGADA, nao barra de progresso generica, e
          ela precisa dizer de onde veio. Aqui vem toda do overview do jogo
          (`source: "overview"`), nunca de `Extractor.attack_duration()` —
          que devolve 0 quando o regex falha e faz o nobre nascer "pousado";
      (b) a lista NAO e derivada de `status` nenhum do cache de conquista —
          foi esse campo que dizia "complete" com quatro nobres voando.

    ⚠️ O QUE ESTE READER FAZ DE DIFERENTE DOS OUTROS, E POR QUE:
    o dado envelhece entre a leitura do bot e o carregamento da pagina, porque
    comandos POUSAM. Um comando cuja chegada ja passou pode ter chegado — ou o
    bot pode so nao ter relido ainda. Como nao da para saber qual, ele vai
    para um balde PROPRIO (`landed`), nunca somado aos que ainda voam nem
    escondido. Esconder seria mentir por omissao; deixar em "no ar" seria
    mentir por afirmacao. A idade da leitura sai junto para a conta poder ser
    refeita por quem olha.
    """

    CACHE_PATH = os.path.join(
        os.path.dirname(__file__), "..", "cache", "in_flight.json"
    )

    # Rotulo pt-BR por unidade. Chave = nome do icone servido pelo jogo, que e
    # o mesmo sinal independente de idioma usado no extractor.
    UNIT_LABELS = {
        "spear": "Lanceiro", "sword": "Espadachim", "axe": "Bárbaro",
        "archer": "Arqueiro", "spy": "Explorador", "light": "Cavalaria leve",
        "marcher": "Arqueiro a cavalo", "heavy": "Cavalaria pesada",
        "ram": "Aríete", "catapult": "Catapulta", "knight": "Paladino",
        "snob": "Nobre",
    }

    # `attack`/`support` saem daqui; `return`/`back` sao tropa VOLTANDO, que e
    # uma leitura diferente (nao ha nada a fazer a respeito) e por isso ganham
    # rotulo proprio em vez de virarem "ataque" na tela.
    TYPE_LABELS = {
        "attack": "Ataque",
        "support": "Apoio",
        "return": "Retorno",
        "back": "Retirada",
    }

    OUTBOUND_TYPES = ("attack", "support")

    @staticmethod
    def _fmt_eta(seconds):
        """"3h 41m" / "12m 03s". Sem valor absoluto disfarcado de relativo."""
        seconds = int(seconds)
        sign = "-" if seconds < 0 else ""
        seconds = abs(seconds)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return "%s%dh %02dm" % (sign, hours, minutes)
        return "%s%dm %02ds" % (sign, minutes, secs)

    @staticmethod
    def load(now=None):
        """
        `now` e injetavel para o teste nao depender do relogio da maquina.
        """
        now = int(now if now is not None else time.time())
        empty = {
            "available": False,
            "fetched_at": None,
            "fetched_at_fmt": "—",
            "age_seconds": None,
            "age_fmt": "—",
            "flying": [],
            "landed": [],
            "unknown": [],
            "nobles_flying": 0,
            "totals": {},
        }
        if not os.path.exists(InFlightReader.CACHE_PATH):
            return empty
        try:
            with open(InFlightReader.CACHE_PATH, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return empty

        flying, landed, unknown = [], [], []
        totals = {}
        for cmd in data.get("commands") or []:
            arrival = cmd.get("arrival_ts")
            units = cmd.get("units") or {}
            row = {
                "command_id": cmd.get("command_id"),
                "command_type": cmd.get("command_type"),
                "type_label": InFlightReader.TYPE_LABELS.get(
                    cmd.get("command_type"), cmd.get("command_type") or "—"),
                "is_outbound": cmd.get("command_type") in InFlightReader.OUTBOUND_TYPES,
                "icon_hint": cmd.get("icon_hint"),
                "label": cmd.get("label"),
                "origin_label": cmd.get("origin_label"),
                "origin_coords": cmd.get("origin_coords"),
                "origin_village_id": cmd.get("origin_village_id"),
                "target_coords": cmd.get("target_coords"),
                "arrival_ts": arrival,
                "arrival_text": cmd.get("arrival_text"),
                "arrival_error": cmd.get("arrival_error"),
                # Procedencia da hora, exigida pelo contrato (a). Hoje e
                # sempre "overview" porque nao ha outra fonte ligada -- o
                # campo existe para que, no dia em que alguem acrescentar uma
                # estimativa, a tela nao passe a misturar as duas caladas.
                "source": "overview",
                "has_snob": bool(cmd.get("has_snob")),
                "units": units,
                "units_fmt": ", ".join(
                    "%s %s" % (v, InFlightReader.UNIT_LABELS.get(k, k))
                    for k, v in sorted(units.items(), key=lambda kv: -kv[1])
                ) or "—",
            }
            if arrival is None:
                unknown.append(row)
                continue
            row["eta_seconds"] = arrival - now
            row["eta_fmt"] = InFlightReader._fmt_eta(arrival - now)
            try:
                row["arrival_fmt"] = datetime.datetime.fromtimestamp(
                    arrival).strftime("%d/%m %H:%M:%S")
            except (OSError, OverflowError, ValueError):
                row["arrival_fmt"] = "—"
            if arrival > now:
                flying.append(row)
                for unit, count in units.items():
                    totals[unit] = totals.get(unit, 0) + count
            else:
                landed.append(row)

        flying.sort(key=lambda r: r["arrival_ts"])
        landed.sort(key=lambda r: r["arrival_ts"], reverse=True)

        fetched_at = data.get("fetched_at")
        fetched_fmt, age_seconds, age_fmt = "—", None, "—"
        if fetched_at:
            try:
                fetched_fmt = datetime.datetime.fromtimestamp(
                    fetched_at).strftime("%d/%m %H:%M:%S")
                age_seconds = now - int(fetched_at)
                age_fmt = InFlightReader._fmt_eta(age_seconds)
            except (OSError, OverflowError, ValueError):
                pass

        return {
            "available": bool(flying or landed or unknown),
            "fetched_at": fetched_at,
            "fetched_at_fmt": fetched_fmt,
            "age_seconds": age_seconds,
            "age_fmt": age_fmt,
            "flying": flying,
            "landed": landed,
            "unknown": unknown,
            "nobles_flying": sum(1 for r in flying if r["has_snob"]),
            "totals": {
                InFlightReader.UNIT_LABELS.get(k, k): v
                for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
            },
        }


class PvpConquestReader:
    """
    Lê, cria e deleta alvos PvP em cache/pvp_conquest/*.json.
    """

    DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

    STATUS_LABELS = {
        "pending_scout":  "Aguardando Scout",
        "pending_troops": "Aguardando Tropa",
        "pending_sim":    "Aguardando Simulação",
        "scheduled":      "Agendado",
        "complete":       "Conquistado",
        "failed":         "Falhou",
    }
    STATUS_COLORS = {
        "pending_scout":  "secondary",
        "pending_troops": "info",
        "pending_sim":    "warning",
        "scheduled":      "primary",
        "complete":       "success",
        "failed":         "danger",
    }
    FAIL_REASON_LABELS = {
        "no_clear_village":  "Nenhuma aldeia ofensiva disponível para limpeza.",
        "no_free_clear_troops": "A chegada passou sem tropa livre para a limpeza: o exército estava reservado por outro alvo ou pelo trem bárbaro.",
        "simulation_failed": "Simulação indicou ataque inviável (tropas insuficientes).",
        "no_nobles":         "Nenhuma aldeia com noble disponível.",
        "scout_deadline_missed": (
            "Nenhum relatório de scout válido chegou antes do primeiro horário "
            "de saída. Nenhum ataque foi agendado."
        ),
        "departure_deadline_missed": (
            "O primeiro horário de saída já passou. Nem a autorização sem scout "
            "permite enviar um ataque atrasado."
        ),
        "hunter_schedule_failed": (
            "O Hunter recusou ou não conseguiu enviar um dos comandos. Confira a "
            "aba Hunter; ataques com horário de saída vencido nunca são enviados."
        ),
        "train_arrived_no_conquest": (
            "O train chegou mas a aldeia continua com o dono antigo — a lealdade não "
            "zerou, ou os nobles morreram (clear insuficiente/falhou). Não haverá nova "
            "tentativa automática: revise e, se quiser tentar de novo, remova o alvo e "
            "adicione outra vez."
        ),
        "train_outcome_unknown": (
            "O train chegou e não foi possível confirmar o dono da aldeia (sem dados de "
            "mapa para o alvo). Confira no jogo — não haverá nova tentativa automática."
        ),
    }

    @staticmethod
    def _dir():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "pvp_conquest")

    @staticmethod
    def _load_all():
        d = PvpConquestReader._dir()
        os.makedirs(d, exist_ok=True)
        out = {}
        for fname in os.listdir(d):
            if not fname.endswith(".json"):
                continue
            tid = fname.replace(".json", "")
            try:
                with open(os.path.join(d, fname)) as f:
                    out[tid] = json.load(f)
            except Exception:
                pass
        return out

    @staticmethod
    def _save(target_id, data):
        d = PvpConquestReader._dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{target_id}.json"), "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load():
        raw = PvpConquestReader._load_all()
        now = datetime.datetime.now().timestamp()
        out = []
        for tid, data in raw.items():
            arrival_ts = data.get("arrival_time", 0)
            arrival_str = data.get("arrival_str", "")
            if not arrival_str and arrival_ts:
                arrival_str = datetime.datetime.fromtimestamp(arrival_ts).strftime(
                    PvpConquestReader.DATETIME_FMT
                )

            time_to_arrival = round(arrival_ts - now) if arrival_ts else None
            if time_to_arrival is not None:
                abs_t = abs(time_to_arrival)
                h, rem = divmod(abs_t, 3600)
                m, s   = divmod(rem, 60)
                time_to_arrival_fmt = "%dh%02dm%02ds" % (h, m, s)
            else:
                time_to_arrival_fmt = ""

            status = data.get("status", "pending_scout")
            sim    = data.get("last_simulation")
            first_send_time = data.get("first_send_time")
            time_to_first_send = (
                round(float(first_send_time) - now) if first_send_time else None
            )
            first_send_str = (
                datetime.datetime.fromtimestamp(float(first_send_time)).strftime(
                    "%d/%m %H:%M:%S"
                ) if first_send_time else ""
            )

            # Horários de saída já formatados aqui, e não no Jinja2: o
            # template recebia o timestamp cru e imprimia o número.  Cada
            # entrada ganha "source_village_id" -> nome legível pelo mesmo
            # caminho que o resto da página usa.
            departures = []
            for d in (data.get("departure_deadlines") or []):
                send_ts = d.get("send_time")
                duration = d.get("duration_seconds") or 0
                entry = dict(d)
                entry["send_str"] = (
                    datetime.datetime.fromtimestamp(float(send_ts)).strftime(
                        "%d/%m %H:%M:%S"
                    ) if send_ts else ""
                )
                dh, drem = divmod(int(duration), 3600)
                dm, ds = divmod(drem, 60)
                entry["duration_fmt"] = "%dh%02dm%02ds" % (dh, dm, ds) if duration else ""
                entry["is_late"] = bool(send_ts) and float(send_ts) < now
                departures.append(entry)
            departures.sort(key=lambda e: e.get("send_time") or 0)

            out.append({
                "target_id":           tid,
                "target_name":         data.get("target_name", ""),
                "arrival_str":         arrival_str,
                "arrival_ts":          arrival_ts,
                "time_to_arrival":     time_to_arrival,
                "time_to_arrival_fmt": time_to_arrival_fmt,
                "status":              status,
                "status_label":        PvpConquestReader.STATUS_LABELS.get(status, status),
                "status_color":        PvpConquestReader.STATUS_COLORS.get(status, "secondary"),
                "clear_village_id":    data.get("clear_village_id"),
                "clear_village_name":  data.get("clear_village_name", ""),
                "noble_villages":      data.get("noble_villages", []),
                "farm_suspended_villages": data.get(
                    "farm_suspended_villages", []
                ),
                "first_send_time":      first_send_time,
                "first_send_str":       first_send_str,
                "time_to_first_send":   time_to_first_send,
                "departure_deadlines":  departures,
                # Estágio "aguardando tropa": quanto do exército das origens
                # está em casa.  None = ainda não medido (nenhuma origem com
                # dados), diferente de 0.0 = medido e o exército está fora.
                "troops_home_pct":      data.get("troops_home_pct"),
                "troops_home_sources":  data.get("troops_home_sources", []),
                "troop_wait_started_at": data.get("troop_wait_started_at"),
                "troops_wait_forced_reason": data.get("troops_wait_forced_reason"),
                "scout_override":       bool(data.get("scout_override")),
                "scout_override_at":    data.get("scout_override_at"),
                "scout_village_id":    data.get("scout_village_id"),
                "last_simulation":     sim,
                "fail_reason":         data.get("fail_reason"),
                "hunter_fail_reason":  data.get("hunter_fail_reason"),
                "fail_reason_label":   PvpConquestReader.FAIL_REASON_LABELS.get(
                                           data.get("fail_reason", ""), data.get("fail_reason", "")
                                       ),
                # Passthrough for EmpireReader.pvp_conquest_timeline_entries()
                # (Feature 17 /empire timeline) -- these aren't otherwise
                # shown on the /pvp_conquest page itself, only used to pick a
                # single representative event timestamp for the timeline.
                "scheduled_at":        data.get("scheduled_at"),
                "completed_at":        data.get("completed_at"),
                "failed_at":           data.get("failed_at"),
            })

        order = {
            "pending_scout": 0, "pending_troops": 1, "pending_sim": 2,
            "scheduled": 3, "failed": 4, "complete": 5,
        }
        out.sort(key=lambda x: (order.get(x["status"], 9), x["arrival_ts"]))
        return out

    @staticmethod
    def add(target_id, arrival_str, clear_village_id=None):
        """
        Registra um alvo PvP. `target_id` aceita ID ou coordenadas -- e
        sempre resolvido contra cache/villages antes de virar nome de
        arquivo (`resolve_village_identifier()`), entao o que chega em disco
        e sempre o ID numerico do jogo.

        Levanta ValueError (sem escrever nada) se o alvo nao resolver, se a
        data nao for valida ou se ja existir operacao para o mesmo alvo --
        antes isso devolvia False em silencio e a rota descartava o retorno,
        ou estourava 500 no `open()`.
        """
        resolved_id, village_data = resolve_village_identifier(target_id)

        try:
            arrival_ts = datetime.datetime.strptime(
                arrival_str, PvpConquestReader.DATETIME_FMT
            ).timestamp()
        except ValueError:
            raise ValueError(
                "Chegada desejada inválida (%s). Informe data e hora completas."
                % (arrival_str or "vazia")
            )

        path = os.path.join(PvpConquestReader._dir(), "%s.json" % resolved_id)
        if os.path.exists(path):
            raise ValueError(
                "Já existe uma operação PvP para a aldeia #%s. Exclua a "
                "operação atual antes de registrar outra." % resolved_id
            )

        data = {
            "target_id":        resolved_id,
            "target_name":      village_display_name(village_data, resolved_id),
            "target_location":  village_data.get("location"),
            "arrival_time":     arrival_ts,
            "arrival_str":      arrival_str,
            "status":           "pending_scout",
            "clear_village_id": str(clear_village_id) if clear_village_id else None,
            "created_at":        int(datetime.datetime.now().timestamp()),
            "scout_override":    False,
        }
        PvpConquestReader._save(resolved_id, data)
        return resolved_id

    @staticmethod
    def delete(target_id):
        path = os.path.join(PvpConquestReader._dir(), f"{target_id}.json")
        if os.path.exists(path):
            os.remove(path)
        return True

    @staticmethod
    def set_clear_village(target_id, clear_village_id):
        path = os.path.join(PvpConquestReader._dir(), f"{target_id}.json")
        if not os.path.exists(path):
            return False
        with open(path) as f:
            data = json.load(f)
        data["clear_village_id"] = str(clear_village_id) if clear_village_id else None
        # Source changed: the server-derived travel-time preflight must be
        # repeated for the new command composition/source.
        data.pop("departure_deadlines", None)
        data.pop("first_send_time", None)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True

    @staticmethod
    def set_scout_override(target_id):
        """Explicitly authorize scheduling without a currently valid scout."""
        path = os.path.join(PvpConquestReader._dir(), f"{target_id}.json")
        if not os.path.exists(path):
            return False
        with open(path) as f:
            data = json.load(f)
        if data.get("status", "pending_scout") not in (
                "pending_scout", "pending_troops", "pending_sim"):
            return False
        first_send = data.get("first_send_time")
        if first_send and datetime.datetime.now().timestamp() >= float(first_send):
            return False
        data["scout_override"] = True
        data["scout_override_at"] = int(datetime.datetime.now().timestamp())
        PvpConquestReader._save(str(target_id), data)
        return True


class FlagReader:
    """
    Le o estado de bandeiras persistido por Village.set_cache_vars() em
    cache/managed/{village_id}.json (chave "flags", Feature 19).

    DefenceManager mantem esse estado apenas em memoria, um processo por
    aldeia dentro do bot -- o webmanager roda separado e so ve o que foi
    salvo em disco no ultimo ciclo daquela aldeia.
    """

    # Mesmo mapeamento de game/defence_manager.py::FLAG_TYPES, duplicado aqui
    # para nao acoplar o webmanager a um import de game/ (mantem o webmanager
    # rodavel mesmo sem as dependencias do bot instaladas).
    FLAG_TYPE_NAMES = {
        1: "Produção", 2: "Recrutamento", 3: "Ataque", 4: "Defesa",
        5: "Sorte", 6: "População", 7: "Custo de cunhagem", 8: "Saque",
    }

    @staticmethod
    def load(managed_cache):
        """
        managed_cache: dict {village_id: cache/managed/{id}.json content},
        ja carregado por DataReader.cache_grab("managed") via sync().
        Retorna lista de entradas formatadas para o template, uma por aldeia
        que tenha alguma informacao de flags salva.
        """
        out = []
        for vid, vdata in managed_cache.items():
            flags = vdata.get("flags")
            if flags is None:
                continue
            pub = vdata.get("public", {}) or {}
            current = flags.get("current_flag")
            current_type = current[0] if current else None
            current_level = current[1] if current else None
            confirmed = flags.get("flag_state_confirmed", False)

            if not confirmed:
                flag_label = "Estado ainda não lido"
                flag_color = "secondary"
            elif current_type is None:
                flag_label = "Nenhuma bandeira equipada"
                flag_color = "warning"
            else:
                type_name = FlagReader.FLAG_TYPE_NAMES.get(current_type, "Tipo %s" % current_type)
                flag_label = "%s (nível %s)" % (type_name, current_level)
                flag_color = "success"

            can_change = flags.get("can_change_flag", True)
            cooldown_label = "Livre" if can_change else "Em cooldown"
            cooldown_color = "success" if can_change else "danger"

            available = flags.get("available_flags", {}) or {}
            available_fmt = [
                {"type_id": t, "type_name": FlagReader.FLAG_TYPE_NAMES.get(int(t), "Tipo %s" % t), "level": lvl}
                for t, lvl in available.items()
            ]

            attempts_fmt = []
            for key, count in (flags.get("upgrade_attempts") or {}).items():
                flag_type, level = (key.split(":") + ["?"])[:2]
                attempts_fmt.append({
                    "type_name": FlagReader.FLAG_TYPE_NAMES.get(int(flag_type), "Tipo %s" % flag_type) if flag_type.isdigit() else flag_type,
                    "level": level,
                    "count": count,
                    "exhausted": count >= 2,
                })

            # Politica em vigor (2026-08-31): explica POR QUE a aldeia esta com
            # a bandeira que esta, em vez de so mostrar qual e.
            has_academy = flags.get("has_academy")
            preferred = flags.get("preferred_flags") or []
            preferred_fmt = [
                FlagReader.FLAG_TYPE_NAMES.get(int(t), "Tipo %s" % t) for t in preferred
            ]
            if has_academy is None:
                policy_label = "Aguardando leitura dos edifícios"
                policy_color = "secondary"
            elif has_academy:
                policy_label = "Com academia — prioriza custo de cunhagem"
                policy_color = "info"
            else:
                policy_label = "Sem academia — prioriza produção"
                policy_color = "light"

            # A bandeira atual esta fora da preferencia? Duas causas legitimas:
            # e uma escolha manual (ataque/sorte) ou e a de defesa, sob ataque.
            off_policy = bool(
                confirmed and current_type is not None
                and preferred and current_type not in preferred
            )

            out.append({
                "village_id": vid,
                "village_name": pub.get("name", vdata.get("name", "Aldeia %s" % vid)),
                "manage_flags_enabled": flags.get("manage_flags_enabled", True),
                "flag_label": flag_label,
                "flag_color": flag_color,
                "cooldown_label": cooldown_label,
                "cooldown_color": cooldown_color,
                "under_attack": vdata.get("under_attack", False),
                "available_flags": available_fmt,
                "upgrade_attempts": attempts_fmt,
                "last_run": vdata.get("last_run", 0),
                "has_academy": has_academy,
                "policy_label": policy_label,
                "policy_color": policy_color,
                "preferred_flags": preferred_fmt,
                "off_policy": off_policy,
            })

        out.sort(key=lambda v: v["village_name"])
        return out


class ResourceSharingReader:
    """
    Le o historico de transferencias diretas de recursos entre aldeias
    (Feature 9, game/resource_sharing.py), persistido em
    cache/resource_sharing/history.json a cada envio/falha (Feature 20).
    """

    REASON_LABELS = {
        "no_merchants": "Sem mercadores disponíveis",
        "send_failed":  "Falha ao enviar (mercado recusou)",
    }

    # As duas regras da reformulação de 2026-08-11 (ver game/resource_sharing.py).
    # Entradas antigas do histórico não têm "kind" -- ficam como "—".
    KIND_LABELS = {
        "need":     "Necessidade",
        "overflow": "Transbordo",
    }

    RES_ICONS = {"wood": "🌲", "stone": "🪨", "iron": "⛏"}

    @staticmethod
    def _path():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "resource_sharing", "history.json")

    @staticmethod
    def load(managed_cache=None, limit=100):
        """
        Retorna (entries, totals) onde entries é a lista formatada (mais
        recente primeiro, limitada a `limit`) e totals é um dict agregando
        o total enviado por recurso entre todas as entradas com sucesso.
        managed_cache (opcional): dict {village_id: cache/managed/*.json} usado
        para resolver nomes de aldeia em vez de só o ID.
        """
        path = ResourceSharingReader._path()
        if not os.path.exists(path):
            return [], {}
        try:
            with open(path, "r") as f:
                raw = json.load(f)
        except Exception:
            return [], {}
        if not isinstance(raw, list):
            return [], {}

        managed_cache = managed_cache or {}

        def _name(vid):
            if not vid:
                return "—"
            vdata = managed_cache.get(str(vid), {})
            pub = vdata.get("public", {}) or {}
            return pub.get("name") or vdata.get("name") or ("Aldeia %s" % vid)

        entries = []
        totals = {}
        for entry in raw:
            success = entry.get("success", False)
            resources = entry.get("resources") or {}
            ts = entry.get("timestamp", 0)
            ts_fmt = "—"
            if ts:
                try:
                    ts_fmt = datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M:%S")
                except Exception:
                    pass
            reason = entry.get("reason")
            kind = entry.get("kind")
            entries.append({
                "kind": kind,
                "kind_label": ResourceSharingReader.KIND_LABELS.get(kind, "—"),
                "timestamp": ts,
                "timestamp_fmt": ts_fmt,
                "source_id": entry.get("source"),
                "source_name": _name(entry.get("source")),
                "target_id": entry.get("target"),
                "target_name": _name(entry.get("target")),
                "resources": resources,
                "success": success,
                "reason": reason,
                "reason_label": ResourceSharingReader.REASON_LABELS.get(reason, reason),
            })
            if success:
                for res, amt in resources.items():
                    totals[res] = totals.get(res, 0) + amt

        entries.sort(key=lambda e: e["timestamp"], reverse=True)
        return entries[:limit], totals


class StatueReader:
    """
    Le cache/statue/status.json (persistido por game/statue_manager.py,
    Feature 24 fase 1) e formata os dados do(s) Paladino(s) para o
    webmanager -- nivel, XP, skills investidos por arvore, regimes de
    treino por XP disponiveis e slots ainda bloqueados por numero de
    aldeias.

    Somente leitura: esta feature nao automatiza treino por XP nem
    re-especializacao, so exibe o estado coletado no ultimo ciclo em que
    config["statue"]["enabled"] esteve ligado. Ver docs/backend.md Feature 24.
    """

    # Mapeamento dos 12 skills do Paladino, coletado de
    # BuildingStatue.initImmutables(...) numa amostra real do br143
    # (2026-08-02). Duplicado aqui em vez de importado de game/ pelo mesmo
    # motivo de FlagReader: manter o webmanager rodavel sem as dependencias
    # do bot instaladas.
    SKILL_NAMES = {
        1: "Investida", 2: "Equitação", 3: "Destruição", 4: "Arrebentar",
        5: "Motivação", 6: "Arquitetura", 7: "Instrução", 8: "Persuasão",
        9: "Esgrima", 10: "Falange", 11: "Fortificação", 12: "Óleo Fervente",
    }

    BRANCHES = [
        {"name": "Ofensiva", "color": "danger", "skills": [1, 2, 3, 4]},
        {"name": "Aldeia", "color": "success", "skills": [5, 6, 7, 8]},
        {"name": "Defesa", "color": "primary", "skills": [9, 10, 11, 12]},
    ]

    @staticmethod
    def _path():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "statue", "status.json")

    @staticmethod
    def _fmt_duration(seconds):
        seconds = int(seconds or 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours and minutes:
            return "%dh%02dm" % (hours, minutes)
        if hours:
            return "%dh" % hours
        return "%dm" % minutes

    @staticmethod
    def load(managed_cache=None):
        """
        Retorna um dict pronto para o template, ou None se ainda nao houver
        cache (feature desligada ou bot ainda nao completou um ciclo com ela
        ligada).
        """
        path = StatueReader._path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                raw = json.load(f)
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None

        managed_cache = managed_cache or {}
        fetched_at = raw.get("fetched_at", 0)
        fetched_fmt = "—"
        if fetched_at:
            try:
                fetched_fmt = datetime.datetime.fromtimestamp(fetched_at).strftime("%d/%m %H:%M:%S")
            except Exception:
                pass

        village_used = raw.get("village_used")
        village_used_name = village_used
        if village_used and str(village_used) in managed_cache:
            pub = managed_cache[str(village_used)].get("public", {}) or {}
            village_used_name = pub.get("name") or village_used

        knights = []
        for kid, k in (raw.get("knights") or {}).items():
            if not isinstance(k, dict):
                continue
            xp = k.get("xp") or {}
            progress = xp.get("progress", 0)
            goal = xp.get("goal", 0) or 1
            xp_pct = round(min(100, (progress / goal) * 100), 1) if goal else 0

            skills_by_id = {}
            for sid, sdata in (k.get("skills") or {}).items():
                try:
                    skills_by_id[int(sid)] = sdata.get("level", 0)
                except (TypeError, ValueError, AttributeError):
                    continue

            investments = {
                inv.get("branch_name"): inv.get("points", 0)
                for inv in (k.get("branch_investments") or [])
            }
            branches = []
            for branch in StatueReader.BRANCHES:
                branch_skills = [
                    {
                        "id": sid,
                        "name": StatueReader.SKILL_NAMES.get(sid, "Skill %s" % sid),
                        "level": skills_by_id.get(sid, 0),
                    }
                    for sid in branch["skills"]
                ]
                branches.append({
                    "name": branch["name"],
                    "color": branch["color"],
                    "points_invested": investments.get(branch["name"], 0),
                    "skills": branch_skills,
                })

            home = k.get("home_village") or {}
            activity = k.get("activity") or {}
            regimens = []
            for r in (k.get("usable_regimens") or []):
                cost = r.get("res_cost") or {}
                regimens.append({
                    "id": r.get("id"),
                    "wood": cost.get("wood", 0),
                    "stone": cost.get("stone", 0),
                    "iron": cost.get("iron", 0),
                    "xp_payout": r.get("xp_payout", 0),
                    "duration_fmt": StatueReader._fmt_duration(r.get("duration", 0)),
                })

            knights.append({
                "id": kid,
                "name": k.get("name") or ("Paladino %s" % kid),
                "level": k.get("level", 0),
                "xp_progress": progress,
                "xp_goal": goal,
                "xp_pct": xp_pct,
                "skill_points_held": k.get("skill_points", 0),
                "branches": branches,
                "home_village_name": home.get("display_name") or home.get("name") or "—",
                "activity_description": activity.get("description") or "—",
                "has_active_regimen": bool(k.get("current_regimen")),
                "usable_regimens": regimens,
            })

        knights.sort(key=lambda kn: kn["name"])

        return {
            "fetched_at": fetched_at,
            "fetched_at_fmt": fetched_fmt,
            "village_used_name": village_used_name,
            "statue_level": raw.get("statue_level"),
            "knights": knights,
            "slot_thresholds": raw.get("slot_thresholds") or [],
            "village_count": raw.get("village_count"),
            "locked_slot_thresholds": raw.get("locked_slot_thresholds") or [],
        }


class InventoryReader:
    """
    Le cache/inventory/status.json (persistido por game/inventory_manager.py,
    Feature 25 fase 1) e agrupa os itens por categoria para o webmanager.

    Deliberadamente fino: pages/inventory.py ja normalizou tudo (quantidade
    como int, rotulos de tipo/categoria resolvidos contra os enums do
    servidor, descricoes achatadas em texto puro). Duplicar essa logica aqui
    daria duas versoes da mesma leitura divergindo com o tempo -- o que este
    repositorio ja pagou caro no par hits/hits_done da Feature 15.

    Somente leitura: esta feature nao ativa, consome nem presenteia item
    nenhum. Ver docs/backend.md Feature 25.
    """

    @staticmethod
    def _path():
        return os.path.join(
            os.path.dirname(__file__), "..", "cache", "inventory", "status.json"
        )

    @staticmethod
    def load(managed_cache=None):
        """
        Retorna um dict pronto para o template, ou None se ainda nao houver
        cache (feature desligada ou bot ainda nao completou um ciclo com ela
        ligada).
        """
        path = InventoryReader._path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None

        managed_cache = managed_cache or {}
        fetched_at = raw.get("fetched_at", 0)
        fetched_fmt = "—"
        if fetched_at:
            try:
                fetched_fmt = datetime.datetime.fromtimestamp(fetched_at).strftime(
                    "%d/%m %H:%M:%S"
                )
            except Exception:
                pass

        village_used = raw.get("village_used")
        village_used_name = village_used
        if village_used and str(village_used) in managed_cache:
            pub = managed_cache[str(village_used)].get("public", {}) or {}
            village_used_name = pub.get("name") or village_used

        categories = collections.OrderedDict()
        for item in (raw.get("items") or []):
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["expires_fmt"] = [
                InventoryReader._fmt_timestamp(ts) for ts in (item.get("expires_at") or [])
            ]
            name = item.get("category_name") or "Sem categoria"
            categories.setdefault(name, []).append(item)

        # A chave e "entries", nao "items": no Jinja2, `group.items` resolve
        # para o METODO dict.items antes de tentar a chave, e o template
        # renderiza um <built-in method> em vez da lista. Foi o bug da coluna
        # "Pop" da Feature 17 (ver docs/backend.md) -- ali a saida foi trocar
        # por acesso por chave; aqui o nome muda, para a armadilha nao voltar
        # na proxima edicao do template.
        groups = [
            {
                "name": name,
                "entries": items,
                "distinct": len(items),
                "amount": sum(i.get("amount", 0) for i in items),
            }
            for name, items in categories.items()
        ]
        groups.sort(key=lambda g: g["name"])

        return {
            "fetched_at": fetched_at,
            "fetched_at_fmt": fetched_fmt,
            "village_used_name": village_used_name,
            "groups": groups,
            "total_distinct": raw.get("total_distinct", 0),
            "total_amount": raw.get("total_amount", 0),
            # Os rotulos vem do <script> da tela; se ela nao pode ser lida, os
            # itens ainda aparecem, so que com "Categoria 4" no lugar do nome.
            "labels_resolved": bool(raw.get("item_categories")),
        }

    @staticmethod
    def _fmt_timestamp(ts):
        try:
            return datetime.datetime.fromtimestamp(int(ts)).strftime("%d/%m %H:%M")
        except Exception:
            return "—"


class ReportReader:
    """
    Le cache/reports/*.json (escrito por game/reports.py::ReportManager) e
    formata uma view resumida para o webmanager (Feature 21) -- perdas,
    ganhos e um veredito "safe to engage" por relatorio, sem precisar abrir
    os JSONs manualmente.

    Estrutura de cada arquivo (ver ReportManager.put/attack_report):
    {
        "type": "attack" | "scout" | outro (ex: "ReportFoundCrew"),
        "origin": "12345" | None,
        "dest": "54321" | None,
        "losses": {"axe": 10, ...},
        "extra": {
            "when": 1718000000,
            "units_sent": {...}, "units_losses": {...},
            "defence_units": {...}, "defence_losses": {...},
            "loot": {"wood": ..., "stone": ..., "iron": ...},
            "resources": {...} (scout),
            "loyalty_after": 45.0 (noble),
        }
    }
    """

    TYPE_LABELS = {
        "attack": "Ataque", "scout": "Scout", "support": "Apoio",
    }

    # Caches de processo, deliberadamente atributos de classe mutaveis: o
    # ReportReader nunca e instanciado (so @staticmethod) e o objetivo aqui e
    # justamente compartilhar entre requests. Nao e o "primeiro padrao" do
    # CLAUDE.md (estado vazando entre instancias) porque instancia nao existe.
    _reports_cache = {"sig": None, "data": None}
    _labels_cache = {"sig": None, "data": None}

    @staticmethod
    def _dir_signature(path):
        """
        (conjunto de nomes, maior mtime) via os.scandir -- sem abrir arquivo.

        Para `cache/reports` o conjunto de nomes sozinho ja seria exato:
        `ReportManager.read()` pula id que ja esta em cache (`reports.py:174`),
        entao um relatorio nasce e morre mas nunca e reescrito sob o mesmo nome
        -- mesma premissa que `PvpConquestManager._scout_report_index()` (P2-35)
        verificou antes de usar a tecnica. O mtime entra junto porque sai de
        graca do scandir e tira a dependencia dessa premissa continuar valendo.

        Para `cache/villages` o mtime NAO e opcional: o scan de mapa reescreve
        esses arquivos in-place (dono, pontos), entao chavear so por nome
        serviria nome/coordenada velhos para sempre.
        """
        names, newest = [], 0.0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if not entry.name.endswith(".json"):
                        continue
                    names.append(entry.name)
                    try:
                        newest = max(newest, entry.stat().st_mtime)
                    except OSError:
                        pass
        except (FileNotFoundError, NotADirectoryError):
            return None
        return frozenset(names), newest

    @staticmethod
    def _all_reports():
        """
        Todo cache/reports/*.json, relido so quando o diretorio muda.

        Sem isto, cada carregamento de /reports abria os 1000+ arquivos da
        pasta (nao so os exibidos -- as stats agregadas varrem tudo), que e o
        gargalo registrado no backlog da Feature 21.
        """
        reports_dir = os.path.join(os.path.dirname(__file__), "..", "cache", "reports")
        sig = ReportReader._dir_signature(reports_dir)
        if sig is None:
            return {}
        if ReportReader._reports_cache["sig"] == sig:
            return ReportReader._reports_cache["data"]

        data = {}
        for fname in sig[0]:
            try:
                with open(os.path.join(reports_dir, fname), "r") as f:
                    data[fname[:-5]] = json.load(f)
            except Exception:
                continue
        ReportReader._reports_cache = {"sig": sig, "data": data}
        return data

    @staticmethod
    def _entry_label(vid, entry, own):
        """
        Normaliza uma entrada de cache/villages ou cache/managed em
        {"name", "coords", "own", "label"}.

        `cache/managed` guarda name/x/y no topo e repete o formato de mapa em
        `public`; `cache/villages` so tem o formato de mapa. Le os dois.
        """
        pub = entry.get("public") or {}
        loc = entry.get("location") or pub.get("location")
        if not loc and entry.get("x") is not None:
            loc = [entry.get("x"), entry.get("y")]
        coords = ""
        if loc and len(loc) == 2 and loc[0] is not None:
            coords = "%s|%s" % (loc[0], loc[1])

        # A regra do name=0 (barbara) mora em village_display_name -- ver la
        # a medicao que a justifica.
        name = village_display_name(entry, vid, fallback="#" + vid)
        return {
            "name": name if not name.startswith("#") else "",
            "coords": coords,
            "own": own,
            "label": name + ((" (%s)" % coords) if coords else ""),
        }

    @staticmethod
    def _village_labels():
        """
        id -> {"name", "coords", "label"} cruzando cache/managed (aldeias
        proprias) e cache/villages (o que o scan de mapa ja viu).

        Sem isto a tabela mostrava `origin`/`dest` como id cru, e a maioria dos
        relatorios e contra alvo de farm, que nunca esta em cache/managed.
        """
        base = os.path.join(os.path.dirname(__file__), "..", "cache")
        v_dir = os.path.join(base, "villages")
        m_dir = os.path.join(base, "managed")
        sig = (ReportReader._dir_signature(v_dir), ReportReader._dir_signature(m_dir))
        if ReportReader._labels_cache["sig"] == sig:
            return ReportReader._labels_cache["data"]

        labels = {}

        def _absorb(directory, signature, own):
            if signature is None:
                return
            for fname in signature[0]:
                try:
                    with open(os.path.join(directory, fname), "r") as f:
                        entry = json.load(f)
                except Exception:
                    continue
                labels[fname[:-5]] = ReportReader._entry_label(fname[:-5], entry, own)

        # villages primeiro, managed por cima: aldeia propria tem o nome mais
        # confiavel (o bot renomeia) e o dado de mapa pode estar defasado.
        _absorb(v_dir, sig[0], False)
        _absorb(m_dir, sig[1], True)
        ReportReader._labels_cache = {"sig": sig, "data": labels}
        return labels

    @staticmethod
    def _label_for(vid, labels):
        if not vid:
            return "—", False
        info = labels.get(str(vid))
        if not info:
            return "#%s" % vid, False
        return info["label"], info["own"]

    @staticmethod
    def _outcome(report):
        """
        Classifica o relatorio do ponto de vista de quem enviou as tropas
        (mesma logica de ReportManager.safe_to_engage, mas por relatorio
        individual em vez de "ultimo relatorio contra a aldeia X").
        Retorna (label, color).
        """
        r_type = report.get("type")
        losses = report.get("losses") or {}
        extra = report.get("extra") or {}

        if r_type == "scout":
            def_units = extra.get("defence_units") or {}
            def_losses = extra.get("defence_losses") or {}
            if not losses and (not def_units or def_units == def_losses):
                return "Seguro (sem defesa detectada)", "success"
            return "Alvo com defesa", "warning"

        if r_type != "attack":
            return "—", "secondary"

        units_sent = extra.get("units_sent") or {}
        if not losses:
            return "Sem perdas", "success"

        # Perda total: todas as unidades enviadas foram perdidas
        total_loss = bool(units_sent) and all(
            losses.get(u, 0) >= units_sent.get(u, 0) for u in units_sent
        )
        if total_loss:
            return "Perda total", "danger"
        return "Perdas parciais", "warning"

    @staticmethod
    def types_present():
        """
        Tipos realmente presentes no cache, para o dropdown de filtro -- em vez
        da lista fixa attack/scout/support, que deixava de fora tipos reais
        (ex: ReportFoundCrew) que apareciam na tabela mas nao eram
        selecionaveis. Mesmo padrao que /logs ja usa com event_types.
        """
        seen = {}
        for data in ReportReader._all_reports().values():
            r_type = data.get("type", "?")
            seen[r_type] = seen.get(r_type, 0) + 1
        return [
            {"value": t, "label": ReportReader.TYPE_LABELS.get(t, t), "count": n}
            for t, n in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    @staticmethod
    def load(dest_filter=None, type_filter=None, page=0, per_page=100):
        all_reports = ReportReader._all_reports()
        if not all_reports:
            return [], {}, {"page": 0, "pages": 0, "total": 0, "per_page": per_page}
        labels = ReportReader._village_labels()

        entries = []
        stats = {"total": 0, "attacks": 0, "scouts": 0, "clean": 0, "with_losses": 0,
                  "loot": {"wood": 0, "stone": 0, "iron": 0}}

        for report_id, data in all_reports.items():
            r_type = data.get("type", "?")
            dest = data.get("dest")
            origin = data.get("origin")
            extra = data.get("extra") or {}
            losses = data.get("losses") or {}

            if dest_filter and dest != dest_filter:
                continue
            if type_filter and r_type != type_filter:
                continue

            when = extra.get("when", 0)
            when_fmt = "—"
            if when:
                try:
                    when_fmt = datetime.datetime.fromtimestamp(int(when)).strftime("%d/%m %H:%M:%S")
                except Exception:
                    pass

            outcome_label, outcome_color = ReportReader._outcome(data)
            loot = extra.get("loot") or {}
            origin_label, origin_own = ReportReader._label_for(origin, labels)
            dest_label, dest_own = ReportReader._label_for(dest, labels)

            entries.append({
                "report_id": report_id,
                "type": r_type,
                "type_label": ReportReader.TYPE_LABELS.get(r_type, r_type),
                "origin": origin,
                "dest": dest,
                "origin_label": origin_label,
                "dest_label": dest_label,
                "origin_own": origin_own,
                "dest_own": dest_own,
                "when": when,
                "when_fmt": when_fmt,
                "loot": loot,
                "units_sent": extra.get("units_sent") or {},
                "losses": losses,
                "loyalty_after": extra.get("loyalty_after"),
                "outcome_label": outcome_label,
                "outcome_color": outcome_color,
            })

            # Stats sobre o conjunto FILTRADO inteiro (todas as paginas), nao so
            # sobre a pagina exibida. O comentario anterior aqui dizia "sobre
            # TODOS os relatorios, respeitando apenas o type_filter", e era
            # falso nas duas metades: os dois `continue` acima ja tinham
            # descartado o que nao casa com dest_filter/type_filter antes de
            # chegar nesta linha, entao o ramo `if type_filter ...: pass` era
            # morto por construcao.
            stats["total"] += 1
            if r_type == "attack":
                stats["attacks"] += 1
            elif r_type == "scout":
                stats["scouts"] += 1
            if losses:
                stats["with_losses"] += 1
            else:
                stats["clean"] += 1
            for res in ("wood", "stone", "iron"):
                try:
                    stats["loot"][res] += int(loot.get(res, 0) or 0)
                except (TypeError, ValueError):
                    pass

        entries.sort(key=lambda e: (int(e["when"] or 0), e["report_id"]), reverse=True)

        total = len(entries)
        per_page = max(1, int(per_page or 100))
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(max(0, int(page or 0)), pages - 1)
        start = page * per_page
        pagination = {
            "page": page, "pages": pages, "total": total, "per_page": per_page,
            "start": start + 1 if total else 0,
            "end": min(start + per_page, total),
            "has_prev": page > 0, "has_next": page < pages - 1,
        }
        return entries[start:start + per_page], stats, pagination

    # Veredito agregado por aldeia-alvo: 1 seguro, 0 inseguro, -1 desconhecido.
    VERDICT_LABELS = {
        1: ("Seguro", "success"), 0: ("Inseguro", "danger"), -1: ("Sem informacao", "secondary"),
    }

    @staticmethod
    def _safe_to_engage(reports_for_target):
        """
        Replica `ReportManager.safe_to_engage()` (game/reports.py:106) --
        o valor que de fato influencia o AttackManager -- em vez do veredito
        por relatorio individual que `_outcome()` produz.

        `reports_for_target` deve vir na MESMA ordem que o bot percorre, que e
        a de `ReportCache.cache_grab()` -> `os.listdir`, e nao a cronologica.
        Ver a nota de ordenacao em `aggregate_by_target()`.
        """
        for entry in reports_for_target:
            extra = entry.get("extra") or {}
            losses = entry.get("losses") or {}
            if entry.get("type") == "attack" and losses == {}:
                return 1
            if (
                entry.get("type") == "scout"
                and losses == {}
                and (
                    extra.get("defence_units", {}) == {}
                    or extra.get("defence_units") == extra.get("defence_losses")
                )
            ):
                return 1
            units_sent = extra.get("units_sent") or {}
            for sent_type in units_sent:
                if sent_type in losses:
                    if units_sent[sent_type] == losses[sent_type]:
                        return 0
                    elif losses[sent_type] <= 1:
                        return 1
            if losses != {}:
                return 0
        return -1

    @staticmethod
    def aggregate_by_target():
        """
        Uma linha por aldeia-alvo com o veredito agregado que o bot usa.

        NOTA DE ORDENACAO (medida em 2026-08-31, nao suposta): o
        `safe_to_engage()` do bot itera `self.last_reports`, cuja ordem e a de
        `os.listdir` sobre cache/reports -- ou seja alfabetica por nome de
        arquivo, que para ids numericos de tamanhos diferentes nao e nem
        cronologica nem numerica. O backlog descrevia essa funcao como "olha o
        relatorio mais recente contra aquele alvo", o que o codigo nao faz.
        Rodado contra os 1040 relatorios reais: dos 63 alvos com mais de um
        relatorio, o veredito pela ordem real e o veredito pelo mais recente
        divergem em ZERO casos -- alvo de farm tende a ser consistentemente
        seguro ou consistentemente perigoso. E erro de documentacao, nao bug
        ativo; a coluna "mais recente" abaixo existe para que uma futura
        divergencia fique visivel em vez de silenciosa.
        """
        all_reports = ReportReader._all_reports()
        labels = ReportReader._village_labels()

        by_target = {}
        for report_id in sorted(all_reports):  # espelha os.listdir (alfabetico)
            data = all_reports[report_id]
            dest = data.get("dest")
            if not dest:
                continue
            by_target.setdefault(str(dest), []).append((report_id, data))

        rows = []
        for target, pairs in by_target.items():
            verdict = ReportReader._safe_to_engage([d for _, d in pairs])
            newest_sorted = sorted(
                pairs, key=lambda p: int((p[1].get("extra") or {}).get("when") or 0), reverse=True
            )
            verdict_newest = ReportReader._safe_to_engage([d for _, d in newest_sorted])
            last_when = int((newest_sorted[0][1].get("extra") or {}).get("when") or 0)
            last_fmt = "—"
            if last_when:
                try:
                    last_fmt = datetime.datetime.fromtimestamp(last_when).strftime("%d/%m %H:%M")
                except Exception:
                    pass
            label, own = ReportReader._label_for(target, labels)
            v_label, v_color = ReportReader.VERDICT_LABELS.get(verdict, ("?", "secondary"))
            rows.append({
                "target_id": target,
                "target_label": label,
                "target_own": own,
                "verdict": verdict,
                "verdict_label": v_label,
                "verdict_color": v_color,
                "verdict_newest": verdict_newest,
                "disagrees": verdict != verdict_newest,
                "report_count": len(pairs),
                "last_when": last_when,
                "last_when_fmt": last_fmt,
            })
        rows.sort(key=lambda r: (r["verdict"], -r["last_when"]))
        return rows


class FarmExclusionReader:
    """
    Por que cada alvo de farm desta aldeia nao foi atacado no ultimo ciclo.

    Le `cache/farm_exclusions/<village_id>.json`, escrito por
    `AttackManager.run()` (ver `game/farm_exclusions.py`). O vocabulario de
    motivos vem do modulo do bot, nao daqui: duplicar os rotulos faria a
    interface descrever uma versao propria das regras, que envelhece separado.

    Tres coisas que o retorno precisa deixar o template dizer, e que a pagina
    erraria por omissao:

    - **Arquivo ausente nao e "nenhuma exclusao".** E "esta aldeia nao rodou
      farm desde que a instrumentacao existe". As duas coisas renderizariam
      igual se `load()` devolvesse uma lista vazia nos dois casos, entao ha um
      campo `available` explicito.
    - **A leitura tem idade.** O motivo e uma afirmacao sobre um estado que
      muda em horas; `observed_at` viaja junto e o template mostra a idade.
    - **`truncated` existe porque lista curta e indistinguivel de lista
      completa** (vigesimo sexto padrao). O resumo conta tudo; a lista
      individual da fase de selecao e que e cortada.
    """

    @staticmethod
    def _path(village_id):
        return os.path.join(
            os.path.dirname(__file__), "..", "cache", "farm_exclusions",
            "%s.json" % village_id,
        )

    @staticmethod
    def load(village_id):
        from game.farm_exclusions import REASONS, FASE_TENTATIVA

        empty = {
            "available": False,
            "village_id": village_id,
            "observed_at": None,
            "observed_at_fmt": "—",
            "truncated": False,
            "summary": [],
            "attempts": [],
            "selection_sample": [],
            "attacked_count": 0,
            "total": 0,
        }
        if not village_id:
            return empty
        path = FarmExclusionReader._path(village_id)
        if not os.path.exists(path):
            return empty
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            # JSON parcial: o bot grava atomicamente, mas o fallback in-place
            # existe (ver FileManager.save_json_file). Tratar como ausente e
            # honesto -- o que nao se pode e apagar nem inventar.
            return empty

        labels = ReportReader._village_labels()

        def describe(code):
            meta = REASONS.get(code)
            if not meta:
                return {"label": code, "help": "Motivo nao catalogado nesta versao "
                                               "do painel; codigo mostrado cru.",
                        "knob": None, "phase": FASE_TENTATIVA}
            return {"label": meta["label"], "help": meta["detail_help"],
                    "knob": meta["knob"], "phase": meta["phase"]}

        raw_summary = data.get("summary") or {}
        summary = []
        for code, count in sorted(raw_summary.items(), key=lambda kv: -kv[1]):
            info = describe(code)
            summary.append({
                "code": code, "count": count, "label": info["label"],
                "help": info["help"], "knob": info["knob"], "phase": info["phase"],
            })

        attempts, selection = [], []
        for target_id, entry in (data.get("targets") or {}).items():
            info = describe(entry.get("code"))
            label, own = ReportReader._label_for(target_id, labels)
            row = {
                "target_id": target_id,
                "target_label": label,
                "code": entry.get("code"),
                "label": info["label"],
                "help": info["help"],
                "knob": info["knob"],
                "detail": entry.get("detail"),
                "observed_at": entry.get("observed_at"),
                "attacked": entry.get("code") == "atacado",
            }
            if entry.get("phase") == FASE_TENTATIVA:
                attempts.append(row)
            else:
                selection.append(row)

        # Atacados por ultimo: a pergunta desta tela e sobre quem NAO foi.
        attempts.sort(key=lambda r: (r["attacked"], r["label"], r["target_label"]))
        selection.sort(key=lambda r: (r["label"], r["target_label"]))

        # Formatado no servidor de proposito: sem JS o template mostraria o
        # epoch cru. O JS do shell substitui por idade relativa; ele formata,
        # nao inventa o valor.
        observed_at = data.get("observed_at")
        observed_fmt = "—"
        if observed_at:
            try:
                observed_fmt = datetime.datetime.fromtimestamp(
                    observed_at
                ).strftime("%d/%m %H:%M")
            except (OSError, OverflowError, ValueError):
                observed_fmt = "—"

        return {
            "available": True,
            "village_id": data.get("village_id", village_id),
            "observed_at": observed_at,
            "observed_at_fmt": observed_fmt,
            "cycle_started_at": data.get("cycle_started_at"),
            "truncated": bool(data.get("truncated")),
            "max_selecao": data.get("max_selecao"),
            "summary": summary,
            "attempts": attempts,
            "selection_sample": selection,
            "attacked_count": raw_summary.get("atacado", 0),
            "total": sum(raw_summary.values()),
        }


class FarmScoreReader:
    @staticmethod
    def load():
        attacks_dir = os.path.join(os.path.dirname(__file__), "..", "cache", "attacks")
        if not os.path.exists(attacks_dir):
            return [], []
        farms = []
        for fname in os.listdir(attacks_dir):
            if not fname.endswith(".json"):
                continue
            target_id = fname.replace(".json", "")
            try:
                with open(os.path.join(attacks_dir, fname), "r") as f:
                    data = json.load(f)
            except Exception:
                continue
            farm_score   = data.get("farm_score", None)
            last_attack  = data.get("last_attack", None)
            last_attack_fmt = "—"
            if last_attack:
                try:
                    last_attack_fmt = datetime.datetime.fromtimestamp(last_attack).strftime("%d/%m %H:%M")
                except Exception:
                    pass
            if not data.get("safe", False):
                status_key = "unsafe"
            elif farm_score is None or farm_score == 9999:
                status_key = "new"
            else:
                status_key = "scored"
            farms.append({
                "target_id": target_id, "farm_score": farm_score,
                "attack_count": data.get("attack_count", 0),
                "last_attack": last_attack, "last_attack_fmt": last_attack_fmt,
                "safe": data.get("safe", False), "scout": data.get("scout", False),
                "high_profile": data.get("high_profile", False),
                "low_profile": data.get("low_profile", False),
                "status_key": status_key,
                "reserved_by": data.get("reserved_by", None),
            })

        def sort_key(f):
            s = f["farm_score"]
            if not f["safe"]: return (3, 0)
            if s is None or s == 9999: return (1, 0)
            return (0, -s)

        farms.sort(key=sort_key)
        village_ids = sorted(set(f["reserved_by"] for f in farms if f["reserved_by"]))
        return farms, village_ids
