"""
Quanto uma tarefa do bot vai durar, a partir do que ela durou nos ultimos
ciclos (`cache/cycles`, gravado pelo `core/cycle_meter.py`).

Quem pergunta e o `Hunter.gate()`: antes de cada fase (farm, mercado,
compartilhamento...) ele precisa saber se ela termina antes da proxima saida
agendada. O medidor ja registrava, por (aldeia, fase), o tempo de parede de
cada ciclo; aqui esse registro vira previsao.

Medido em 80 ciclos (2026-10-08): mediana de fase por aldeia entre 0 e 100 s,
mas maximos de 2.090 s no farm, 1.831 s na defesa e 7.570 s no
compartilhamento. A previsao e o MAIOR valor recente da mesma fase na mesma
aldeia, nao a mediana: errar para mais custa adiar uma tarefa uma passada,
errar para menos custa um nobre.

Detalhes do dado que importam aqui:
- o tempo de cada balde e EXCLUSIVO (o Hunter, quando roda dentro de uma
  fase, cai no balde dele), entao a espera do Hunter nao infla a previsao;
- a espera de captcha e descontada: ela nao se repete por ser da fase;
- uma fase que aparece duas vezes na mesma aldeia (`init`, `mercado`) soma
  as duas no balde. A previsao sai maior que cada bloco, que e o lado
  seguro.
"""
import json
import os

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "cycles"
)


class PhaseForecast:
    # Ciclos lidos do disco e amostras usadas por (aldeia, fase).
    FILES = 30
    SAMPLES = 10
    # Fase nunca vista em lugar nenhum: chute conservador, da ordem do p90
    # das fases medidas.
    DEFAULT_SECONDS = 120.0
    # Fases que chamam o Hunter POR DENTRO a cada iteracao: o farm antes de
    # cada alvo (`AttackManager.run`) e a defesa antes de cada upgrade de
    # bandeira (`DefenceManager.manage_flags`). Para o gate o que conta nelas
    # e o maior trecho entre dois checkpoints, nao a fase inteira -- uma
    # iteracao e ~3 requisicoes (~60 s; 16 s/req mediana em 80 ciclos). Sem
    # este teto o farm de 1.300 s da 57689 seria adiado a 25 min de qualquer
    # saida, e a defesa (nao adiavel, ate 1.831 s) seguraria o bot 30 min.
    INTERRUPTIBLE_CAP = {"farm": 180.0, "defesa": 180.0}

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or CACHE_DIR
        # Mutaveis em __init__ (primeiro padrao do CLAUDE.md).
        self._by_key = {}
        self._by_phase = {}
        self._signature = None

    def reload(self):
        """Rele o historico se apareceu ciclo novo. Nunca levanta."""
        try:
            names = sorted(
                n for n in os.listdir(self.cache_dir) if n.endswith(".json")
            )[-self.FILES:]
        except OSError:
            return
        signature = tuple(names)
        if signature == self._signature:
            return
        by_key, by_phase = {}, {}
        for name in names:
            try:
                with open(os.path.join(self.cache_dir, name), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            for bucket in data.get("buckets") or []:
                phase = bucket.get("phase")
                if not phase:
                    continue
                wall = float(bucket.get("wall") or 0) - float(bucket.get("captcha") or 0)
                village = bucket.get("village")
                key = (str(village) if village is not None else None, phase)
                by_key.setdefault(key, []).append(max(0.0, wall))
                by_phase.setdefault(phase, []).append(max(0.0, wall))
        self._by_key, self._by_phase = by_key, by_phase
        self._signature = signature

    def predict(self, phase, village=None):
        """Segundos previstos para `phase` na aldeia `village` (None = conta)."""
        cap = self.INTERRUPTIBLE_CAP.get(phase)
        value = self._predict_whole(phase, village)
        return min(value, cap) if cap is not None else value

    def _predict_whole(self, phase, village):
        key = (str(village) if village is not None else None, phase)
        samples = self._by_key.get(key)
        if samples:
            return max(samples[-self.SAMPLES:])
        everyone = self._by_phase.get(phase)
        if everyone:
            ordered = sorted(everyone)
            return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
        return self.DEFAULT_SECONDS
