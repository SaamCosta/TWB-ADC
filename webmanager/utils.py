import collections
import datetime
import json
import os
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
            with open(t_path, 'r') as f:
                try:
                    output[existing.replace('.json', '')] = json.load(f)
                except Exception as e:
                    print("Cache read error for %s: %s. Removing broken entry" % (t_path, str(e)))
                    f.close()
                    os.remove(t_path)
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

    def is_running(self):
        if not self.pid:
            return False
        try:
            proc = psutil.Process(self.pid)
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            pass
        self.pid = None
        self._proc = None
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
        "loyalty_regen_per_hour": 1.5,
        "last_hit_timestamp": 1718000000,
        "target_name": "Barbarian village",
        "target_points": 800,
        "target_location": [450, 512]
    }
    """

    STATUS_LABELS = {
        "train_sent":    "Train Enviado",
        "extra_pending": "Extra Pendente",
        "complete":      "Conquistada",
    }
    STATUS_COLORS = {
        "train_sent":    "warning",
        "extra_pending": "info",
        "complete":      "success",
    }

    @staticmethod
    def _estimate_loyalty(data):
        """
        Calcula lealdade estimada atual.
        loyalty_after_nobles = loyalty_start - (hits_done * loyalty_drop_per_noble)
        loyalty_current = loyalty_after_nobles + hours_since_last_hit * loyalty_regen_per_hour
        Clampado em [0, 100].
        """
        loyalty_start       = data.get("loyalty_start", 100)
        hits_done           = data.get("hits_done", 0)
        drop_per_noble      = data.get("loyalty_drop_per_noble", 25)
        regen_per_hour      = data.get("loyalty_regen_per_hour", 1.5)
        last_hit_ts         = data.get("last_hit_timestamp", None)

        loyalty_after_nobles = loyalty_start - (hits_done * drop_per_noble)

        if last_hit_ts:
            hours_elapsed = (datetime.datetime.now().timestamp() - last_hit_ts) / 3600.0
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
                with open(os.path.join(conquest_dir, fname), "r") as f:
                    data = json.load(f)
            except Exception:
                continue

            loyalty_source = data.get('loyalty_source', 'estimate')
            loyalty_now   = ConquestReader._estimate_loyalty(data)
            loyalty_color = ConquestReader._loyalty_color(loyalty_now)

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
                "loyalty_color":  loyalty_color,
                "loyalty_source": loyalty_source,
                "last_hit_fmt":   last_hit_fmt,
                "last_hit_ts":    last_hit_ts or 0,
            })

        # Ordenação: em andamento primeiro (train_sent, extra_pending), depois completas
        order = {"train_sent": 0, "extra_pending": 1, "complete": 2}
        targets.sort(key=lambda t: (order.get(t["status"], 9), -t["last_hit_ts"]))
        return targets


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
    def add_schedule(target_id, arrival_str, attacks):
        """
        Cria um novo schedule no cache.
        attacks: list of dicts {source_village_id, troops{unit: qty}, is_fake}
        """
        try:
            arrival_ts = datetime.datetime.strptime(
                arrival_str, HunterReader.DATETIME_FMT
            ).timestamp()
        except ValueError:
            return False

        sched_key = "%s_%s" % (target_id, arrival_str.replace(" ", "T").replace(":", "-"))

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
                pub = vdata.get("public", {})
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
