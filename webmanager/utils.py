import collections
import datetime
import json
import os
import re
import subprocess

import psutil


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
                # Ver P0-4 em docs/auditoria_codigo_2026-08-08.md
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
        with open(os.path.join(os.path.dirname(__file__), "..", "config.json"), 'r') as f:
            return json.load(f)

    @staticmethod
    def config_set(parameter, value):
        if value is None or value == "null":
            parsed_value = None
        else:
            try:
                parsed_value = json.loads(value)
            except Exception:
                parsed_value = value
        config_file_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_file_path, 'r') as config_file:
            template = json.load(config_file, object_pairs_hook=collections.OrderedDict)
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
        with open(config_file_path, 'w') as newcf:
            json.dump(template, newcf, indent=2, sort_keys=False)
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
        config_file_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_file_path, 'r') as config_file:
            template = json.load(config_file, object_pairs_hook=collections.OrderedDict)
        if village_id not in template['villages']:
            return False
        template['villages'][str(village_id)][parameter] = parsed_value
        with open(config_file_path, 'w') as newcf:
            json.dump(template, newcf, indent=2, sort_keys=False)
            return True

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
    pid = None
    _proc = None
    OUTPUT_LOG = os.path.join(os.path.dirname(__file__), "..", "cache", "logs", "bot_output.log")
    # P2-32: o pid vivia so em memoria, entao reiniciar o webmanager perdia a
    # referencia -> is_running() retornava False -> /bot/start subia um SEGUNDO
    # twb.py na mesma conta (risco de ban). Persistir em disco.
    PID_FILE = os.path.join(os.path.dirname(__file__), "..", "cache", "bot.pid")

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

    @staticmethod
    def _is_twb_process(pid):
        """
        Confirma que o pid ainda e um twb.py nosso, e nao um pid reciclado
        pelo SO apontando para um processo qualquer.
        """
        try:
            proc = psutil.Process(pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return False
            return any("twb.py" in str(arg) for arg in (proc.cmdline() or []))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def is_running(self):
        pid = self.pid or self._read_pid_file()
        if not pid:
            return False
        if self._is_twb_process(pid):
            self.pid = pid
            return True
        self.pid = None
        self._proc = None
        self._write_pid_file(None)
        return False

    def start(self):
        if self.is_running():
            return
        wd = os.path.join(os.path.dirname(__file__), "..")
        log_dir = os.path.join(wd, "cache", "logs")
        os.makedirs(log_dir, exist_ok=True)
        output_log = os.path.join(log_dir, "bot_output.log")
        log_file = open(output_log, "a", encoding="utf-8")
        log_file.write("\n--- Bot iniciado em %s ---\n" % datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        log_file.flush()
        kwargs = {"cwd": wd, "stdout": log_file, "stderr": log_file, "shell": False}
        if os.name == "nt":
            import sys
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            cmd = [sys.executable, "twb.py"]
        else:
            cmd = ["python3", "twb.py"]
        self._proc = subprocess.Popen(cmd, **kwargs)
        self.pid = self._proc.pid
        self._write_pid_file(self.pid)
        print("Bot started (PID %d)" % self.pid)

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
            self._write_pid_file(None)

    @staticmethod
    def read_output_log(lines=200):
        log_path = os.path.join(os.path.dirname(__file__), "..", "cache", "logs", "bot_output.log")
        if not os.path.exists(log_path):
            return []
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        recent = all_lines[-lines:]
        recent.reverse()
        return [l.rstrip() for l in recent if l.strip()]


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
            "manual": -1, "train_sent": 0, "extra_pending": 1,
            "assumed_done": 2, "lost": 3, "conquered": 4,
            "complete": 5, "invalid": 6,
        }
        targets.sort(key=lambda t: (order.get(t["status"], 9), -t["last_hit_ts"]))
        return targets

    # ------------------------------------------------------------------
    # Feature 15 — seleção manual de alvo de conquista bárbara
    # ------------------------------------------------------------------

    @staticmethod
    def _villages_dir():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "villages")

    @staticmethod
    def _conquest_dir():
        return os.path.join(os.path.dirname(__file__), "..", "cache", "conquest")

    @staticmethod
    def _resolve_identifier(identifier):
        """
        Aceita um ID de aldeia puro ("12345") ou coordenadas
        ("512|487", "512,487", "512 487"). Resolve consultando
        cache/villages/ (populado pelo fetch de mapa de qualquer aldeia
        gerenciada — ver game/map.py::Map.build_cache_entry). Lança
        ValueError com mensagem amigável se não encontrar; nunca inventa
        dados.
        """
        identifier = (identifier or "").strip()
        if not identifier:
            raise ValueError("Informe um ID de aldeia ou coordenadas (ex: 512|487).")

        v_dir = ConquestReader._villages_dir()
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
                "name": vdata.get("name") or target_id,
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


class PvpConquestReader:
    """
    Lê, cria e deleta alvos PvP em cache/pvp_conquest/*.json.
    """

    DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

    STATUS_LABELS = {
        "pending_scout": "Aguardando Scout",
        "pending_sim":   "Aguardando Simulação",
        "scheduled":     "Agendado",
        "complete":      "Conquistado",
        "failed":        "Falhou",
    }
    STATUS_COLORS = {
        "pending_scout": "secondary",
        "pending_sim":   "warning",
        "scheduled":     "primary",
        "complete":      "success",
        "failed":        "danger",
    }
    FAIL_REASON_LABELS = {
        "no_clear_village":  "Nenhuma aldeia ofensiva disponível para limpeza.",
        "simulation_failed": "Simulação indicou ataque inviável (tropas insuficientes).",
        "no_nobles":         "Nenhuma aldeia com noble disponível.",
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
                "scout_village_id":    data.get("scout_village_id"),
                "last_simulation":     sim,
                "fail_reason":         data.get("fail_reason"),
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

        order = {"pending_scout": 0, "pending_sim": 1, "scheduled": 2, "failed": 3, "complete": 4}
        out.sort(key=lambda x: (order.get(x["status"], 9), x["arrival_ts"]))
        return out

    @staticmethod
    def add(target_id, arrival_str, clear_village_id=None):
        try:
            arrival_ts = datetime.datetime.strptime(
                arrival_str, PvpConquestReader.DATETIME_FMT
            ).timestamp()
        except ValueError:
            return False
        data = {
            "target_id":        str(target_id),
            "arrival_time":     arrival_ts,
            "arrival_str":      arrival_str,
            "status":           "pending_scout",
            "clear_village_id": str(clear_village_id) if clear_village_id else None,
        }
        PvpConquestReader._save(str(target_id), data)
        return True

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
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
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
    config["statue"]["enabled"] esteve ligado. Ver docs/backlog.md Feature 24.
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
    nenhum. Ver docs/backlog.md Feature 25.
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
        # "Pop" da Feature 17 (ver docs/backlog.md) -- ali a saida foi trocar
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
    def load(dest_filter=None, type_filter=None, limit=150):
        reports_dir = os.path.join(os.path.dirname(__file__), "..", "cache", "reports")
        if not os.path.exists(reports_dir):
            return [], {}

        entries = []
        stats = {"total": 0, "attacks": 0, "scouts": 0, "clean": 0, "with_losses": 0,
                  "loot": {"wood": 0, "stone": 0, "iron": 0}}

        for fname in os.listdir(reports_dir):
            if not fname.endswith(".json"):
                continue
            report_id = fname.replace(".json", "")
            try:
                with open(os.path.join(reports_dir, fname), "r") as f:
                    data = json.load(f)
            except Exception:
                continue

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

            entries.append({
                "report_id": report_id,
                "type": r_type,
                "type_label": ReportReader.TYPE_LABELS.get(r_type, r_type),
                "origin": origin,
                "dest": dest,
                "when": when,
                "when_fmt": when_fmt,
                "loot": loot,
                "units_sent": extra.get("units_sent") or {},
                "losses": losses,
                "loyalty_after": extra.get("loyalty_after"),
                "outcome_label": outcome_label,
                "outcome_color": outcome_color,
            })

            # Stats agregadas sobre TODOS os relatorios (nao so os filtrados na pagina),
            # respeitando apenas o type_filter para nao misturar contextos.
            if type_filter and r_type != type_filter:
                pass
            else:
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
        return entries[:limit], stats


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
