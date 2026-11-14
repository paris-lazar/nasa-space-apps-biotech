"""
radiation_detector.py - software "space radiation" detector based on memory bit flips.

IDEA
    Reserve a block of RAM, fill it with a known pattern, scan it again and
    again and count the bits that changed (Single Event Upsets, SEUs).
    Bit flips also happen on Earth, so the program
      1. filters out flips that have other, ordinary causes,
      2. compares the remaining flip rate with the normal background rate,
      3. gives a warning with a % probability of elevated radiation exposure
         when the rate is too high to be normal.

HOW A FLIP IS CLASSIFIED
    stuck_cell         the same bit flips again and again -> damaged memory cell
    localized_fault    several flips inside one 4 KiB page in one scan -> faulty
                       row/chip area (radiation hits are spread out randomly)
    software_overwrite a run of many changed bytes -> a program wrote into the
                       region (radiation flips single bits, rarely 2-3 in a word)
    isolated           everything else -> normal background OR radiation

    Only "isolated" flips are counted for the radiation statistics.

THE PERCENTAGE
    Two hypotheses are compared with Poisson statistics for several time windows:
      H0 normal background : expected flips = baseline_rate x bits x window
      H1 radiation exposure: expected flips = rad_multiplier x H0
    Bayes' rule with a prior (default 5 %) gives P(H1 | observed flips).
    At least `min_events` isolated flips are required before any warning
    (below that the percentage is reported as 0.0).

    The percentage is the probability of an elevated radiation environment,
    not a dose measurement.

IMPORTANT LIMITS (be honest about them in the presentation)
    * baseline_per_bit_hour and rad_multiplier are PLACEHOLDER assumptions
      (about 1e-12 flips/bit/hour on the ground, ~10x higher in low Earth orbit).
      Measure your own baseline with `calibrate`, or use literature values.
    * On the ground flips are very rare: 1 GiB sees only a few per YEAR.
      A laptop demo therefore needs the simulator (`demo`).
    * ECC memory silently CORRECTS single-bit flips, so they cannot be seen
      from software. Non-ECC RAM is needed (or read the ECC/EDAC counters).
    * Python memory may be moved or swapped by the OS; use a dedicated
      process and a size that stays in RAM.

USAGE
    python radiation_detector.py demo                 # 16 simulated hours, all scenarios
    python radiation_detector.py calibrate --hours 24 # measure the ground baseline
    python radiation_detector.py monitor              # real monitoring

    # from the main program (same style as smartwatch.py):
    import radiation_detector as rd
    rd.start()                    # background thread, once
    rd.get_radiation()            # -> float, probability of radiation exposure, 0-100
    rd.get_radiation_report()     # -> dict with level, counts, message ...

Python 3.9+, standard library only.
"""
import argparse
import json
import math
import os
import random
import threading
import time
from collections import Counter
from dataclasses import dataclass

PATTERN = b"\xaa\x55"        # alternating -> every bit position holds both 0 and 1
CHUNK = 64 * 1024            # scan chunk size (bytes)
WORD = 8                     # bytes: flips in one word = one strike (multi-bit upset)
PAGE = 4096                  # bytes
BASELINE_FILE = "radiation_baseline.json"


# ----------------------------------------------------------------- config ----
@dataclass
class Config:
    size_mib: int = 64                    # monitored memory (bigger = more sensitive)
    scan_interval_s: float = 10.0
    baseline_per_bit_hour: float = 1e-12  # normal flip rate (PLACEHOLDER, calibrate!)
    rad_multiplier: float = 10.0          # expected rate increase under radiation
    prior: float = 0.05                   # prior probability of exposure
    min_events: int = 3                   # isolated flips needed before any warning
    windows_h: tuple = (1 / 6, 1.0)       # windows for the CURRENT status (hours)
    history_window_h: float = 6.0         # longer window: recent exposure
    stuck_threshold: int = 3              # same cell flipping this often = stuck
    page_cluster_min: int = 4             # flips in one page in one scan = fault
    run_bytes_min: int = 16               # changed bytes in a run = software write


def load_baseline(path=BASELINE_FILE):
    """Baseline rate measured by `calibrate`, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            return float(json.load(f)["baseline_per_bit_hour"])
    except (OSError, KeyError, ValueError):
        return None


class Clock:
    """Real clock, or a virtual one so a simulation can run hours in seconds."""

    def __init__(self, virtual=False):
        self.virtual = virtual
        self._t = 0.0

    def now(self):
        return self._t if self.virtual else time.time()

    def advance(self, seconds):
        self._t += seconds


@dataclass
class Event:
    t: float
    cells: tuple        # ((byte_address, bit), ...)
    category: str       # isolated | stuck_cell | localized_fault | software_overwrite

    @property
    def page(self):
        return self.cells[0][0] // PAGE


# ------------------------------------------------------------- statistics ----
def poisson_tail(k, lam):
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    total = 0.0
    for i in range(k, k + 200):
        total += math.exp(i * math.log(lam) - lam - math.lgamma(i + 1))
    return min(1.0, total)


def radiation_posterior(k, lam0, multiplier, prior):
    """P(radiation | k flips) comparing Poisson(lam0) with Poisson(multiplier*lam0)."""
    log_lr = k * math.log(multiplier) - (multiplier - 1) * lam0
    log_odds = math.log(prior / (1 - prior)) + log_lr
    log_odds = max(-700.0, min(700.0, log_odds))
    return 1 / (1 + math.exp(-log_odds))


def _level(percent):
    if percent >= 90:
        return "ALERT"
    if percent >= 60:
        return "WARNING"
    if percent >= 30:
        return "WATCH"
    return "NORMAL"


# --------------------------------------------------------------- detector ----
class RadiationDetector:
    def __init__(self, config=None, clock=None):
        self.cfg = config or Config()
        self.clock = clock or Clock()
        size = self.cfg.size_mib * 1024 * 1024
        if size % CHUNK:
            raise ValueError("size_mib must be a whole number of MiB")
        self.size = size
        self.n_bits = size * 8
        self._pat = (PATTERN * (CHUNK // 2))
        self.mem = bytearray(PATTERN * (size // 2))   # <- the monitored region
        self.start_time = self.clock.now()
        self.log = []                  # recent events
        self.cell_hits = Counter()     # (address, bit) -> times flipped
        self.totals = Counter()        # category -> number of events so far
        self.scans = 0
        self._lock = threading.Lock()

    # ---- scanning ----
    def _raw_flips(self):
        """Compare memory with the pattern, repair it, return [(addr, bit), ...]."""
        flips = []
        pat_int = int.from_bytes(self._pat, "big")
        mem, pat = self.mem, self._pat
        for off in range(0, self.size, CHUNK):
            chunk = mem[off:off + CHUNK]
            if chunk == pat:
                continue
            diff = (int.from_bytes(chunk, "big") ^ pat_int).to_bytes(CHUNK, "big")
            for i, x in enumerate(diff):
                if x:
                    for bit in range(8):
                        if x >> bit & 1:
                            flips.append((off + i, bit))
            mem[off:off + CHUNK] = pat          # repair
        return flips

    def scan(self):
        """One scan of the whole region. Returns the new Events."""
        with self._lock:
            now = self.clock.now()
            self.scans += 1
            flips = self._raw_flips()
            events = self._classify(flips, now) if flips else []
            self.log.extend(events)
            horizon = now - max(max(self.cfg.windows_h), self.cfg.history_window_h) * 3600
            if len(self.log) > 5000 or (self.log and self.log[0].t < horizon):
                self.log = [e for e in self.log if e.t >= horizon]
            return events

    def _make(self, t, cells, category):
        self.totals[category] += 1
        return Event(t, tuple(cells), category)

    def _classify(self, flips, now):
        cfg = self.cfg
        events = []
        flips = sorted(flips)

        # 1. software overwrite: many changed bytes close together
        byte_addrs = sorted({a for a, _ in flips})
        groups, cur = [], [byte_addrs[0]]
        for a in byte_addrs[1:]:
            if a - cur[-1] <= 4:
                cur.append(a)
            else:
                groups.append(cur)
                cur = [a]
        groups.append(cur)
        software = set()
        for g in groups:
            if len(g) >= cfg.run_bytes_min:
                software.update(g)
                cells = [(a, b) for a, b in flips if g[0] <= a <= g[-1]]
                events.append(self._make(now, cells[:1], "software_overwrite"))
        flips = [(a, b) for a, b in flips if a not in software]

        # 2. stuck cells: same cell flipping again and again
        rest = []
        for a, b in flips:
            self.cell_hits[(a, b)] += 1
            hits = self.cell_hits[(a, b)]
            if hits >= cfg.stuck_threshold:
                if hits == cfg.stuck_threshold:    # reclassify the earlier hits
                    for e in self.log:
                        if e.category == "isolated" and (a, b) in e.cells:
                            self.totals["isolated"] -= 1
                            self.totals["stuck_cell"] += 1
                            e.category = "stuck_cell"
                events.append(self._make(now, [(a, b)], "stuck_cell"))
            else:
                rest.append((a, b))

        # 3. strikes: flips in the same 8-byte word = one event (multi-bit upset)
        words = {}
        for a, b in rest:
            words.setdefault(a // WORD, []).append((a, b))
        strikes = [self._make(now, cells, "isolated") for cells in words.values()]

        # 4. localized fault: too many strikes inside one page in one scan
        per_page = Counter(s.page for s in strikes)
        for s in strikes:
            if per_page[s.page] >= cfg.page_cluster_min:
                self.totals["isolated"] -= 1
                self.totals["localized_fault"] += 1
                s.category = "localized_fault"
        return events + strikes

    # ---- assessment ----
    def assess(self):
        """Current radiation assessment (dict)."""
        with self._lock:
            cfg = self.cfg
            now = self.clock.now()
            elapsed_h = max((now - self.start_time) / 3600, 1e-9)
            def window_row(w):
                w_eff = min(w, elapsed_h)
                t0 = now - w_eff * 3600
                k = sum(1 for e in self.log if e.t >= t0 and e.category == "isolated")
                lam0 = cfg.baseline_per_bit_hour * self.n_bits * w_eff
                row = {
                    "window_h": round(w, 3),
                    "observed": k,
                    "expected_background": lam0,
                    "p_value": poisson_tail(k, lam0),
                    "percent": 0.0,
                }
                if k >= cfg.min_events:
                    row["percent"] = 100 * radiation_posterior(
                        k, lam0, cfg.rad_multiplier, cfg.prior)
                return row

            best = None
            for w in cfg.windows_h:
                row = window_row(w)
                if best is None or (row["percent"], row["observed"]) > (
                        best["percent"], best["observed"]):
                    best = row
            history = window_row(cfg.history_window_h)

            percent = round(best["percent"], 1)
            level = _level(percent)
            excluded = {c: self.totals[c] for c in
                        ("stuck_cell", "localized_fault", "software_overwrite")}
            ratio = best["observed"] / best["expected_background"] \
                if best["expected_background"] > 0 else None
            if level in ("WARNING", "ALERT"):
                message = (f"{level}: {best['observed']} isolated bit flips in "
                           f"{best['window_h']} h vs {best['expected_background']:.2f} expected "
                           f"from normal background. Estimated {percent}% probability of "
                           f"elevated space-radiation exposure.")
            elif level == "WATCH":
                message = (f"WATCH: flip rate is rising ({best['observed']} flips in "
                           f"{best['window_h']} h, {percent}% radiation probability).")
            elif history["percent"] >= 60:
                message = (f"Normal now, but {history['observed']} isolated flips in the last "
                           f"{history['window_h']} h point to a likely radiation exposure "
                           f"({round(history['percent'], 1)}%).")
            else:
                message = "Normal: flip rate consistent with background."
            return {
                "radiation_percent": percent,
                "level": level,
                "recent_exposure_percent": round(history["percent"], 1),
                "history_window_h": history["window_h"],
                "window_h": best["window_h"],
                "observed_events": best["observed"],
                "expected_background": round(best["expected_background"], 4),
                "rate_ratio": None if ratio is None else round(ratio, 1),
                "p_value": best["p_value"],
                "excluded_non_radiation": excluded,
                "isolated_total": self.totals["isolated"],
                "scans": self.scans,
                "region_mib": cfg.size_mib,
                "message": message,
            }

    # ---- for simulation only ----
    def inject_flip(self, addr, bit):
        self.mem[addr] ^= 1 << bit


# ---------------------------------------------------------- simulator/demo ----
def _poisson(rng, lam):
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


DEMO_PHASES = [          # (start_h, end_h, scenario)
    (0, 6, "normal background"),
    (6, 8, "stuck memory cell"),
    (8, 9, "software overwrite"),
    (9, 11, "faulty DRAM row"),
    (11, 12, "normal background"),
    (12, 13.5, "RADIATION BURST (x25)"),
    (13.5, 16, "normal background"),
]


def run_demo(seed=1, print_every_min=30, verbose=True):
    """Simulates 16 hours of monitoring with several fault scenarios.
    The baseline is scaled up for the demo (real ground rate is ~1e-12)."""
    rng = random.Random(seed)
    cfg = Config(size_mib=1, scan_interval_s=60, baseline_per_bit_hour=1e-7)
    clock = Clock(virtual=True)
    det = RadiationDetector(cfg, clock)
    stuck_addr = rng.randrange(det.size)
    row_page = rng.randrange(det.size // PAGE)
    results = []
    last_phase = None
    for step in range(16 * 60):
        hour = clock.now() / 3600
        scenario = next(s for a, b, s in DEMO_PHASES if a <= hour < b)
        dt_h = cfg.scan_interval_s / 3600
        mult = 25 if scenario.startswith("RADIATION") else 1
        # background / radiation: random single flips (10 % hit 2 bits of a word)
        for _ in range(_poisson(rng, cfg.baseline_per_bit_hour * det.n_bits * dt_h * mult)):
            a = rng.randrange(det.size)
            det.inject_flip(a, rng.randrange(8))
            if rng.random() < 0.1:
                det.inject_flip(a, (rng.randrange(7) + 1) % 8)
        if scenario == "stuck memory cell":
            det.inject_flip(stuck_addr, 3)
        if scenario == "software overwrite" and scenario != last_phase:
            start = rng.randrange(det.size - 64)
            for i in range(64):
                det.mem[start + i] = rng.randrange(256)
        if scenario == "faulty DRAM row" and rng.random() < 1 / 10:
            for _ in range(6):
                det.inject_flip(row_page * PAGE + rng.randrange(PAGE), rng.randrange(8))
        last_phase = scenario
        det.scan()
        clock.advance(cfg.scan_interval_s)
        r = det.assess()
        r["scenario"], r["hour"] = scenario, round(clock.now() / 3600, 2)
        results.append(r)
        if verbose and (step + 1) % print_every_min == 0:
            print(f"t={r['hour']:5.1f} h  {scenario:<24} "
                  f"isolated(window)={r['observed_events']:2d}  "
                  f"radiation={r['radiation_percent']:5.1f}%  {r['level']}")
    if verbose:
        print("\nTotals excluded as NOT radiation:", results[-1]["excluded_non_radiation"])
        warned = sorted({r["scenario"] for r in results if r["level"] in ("WARNING", "ALERT")})
        print("Scenarios that triggered a WARNING/ALERT:", warned)
    return results


# ------------------------------------------------- background use / API ----
_detector = None
_thread = None
_stop = threading.Event()


def start(config=None):
    """Start monitoring in a background thread (call once)."""
    global _detector, _thread
    if _thread and _thread.is_alive():
        return _detector
    if config is None:
        config = Config()
        baseline = load_baseline()
        if baseline:
            config.baseline_per_bit_hour = baseline
    _detector = RadiationDetector(config)
    _stop.clear()

    def loop():
        while not _stop.wait(config.scan_interval_s):
            _detector.scan()

    _thread = threading.Thread(target=loop, daemon=True, name="radiation-monitor")
    _thread.start()
    return _detector


def stop():
    _stop.set()


def get_radiation_report():
    """Full assessment dict (starts monitoring with defaults if needed)."""
    if _detector is None:
        start()
    return _detector.assess()


def get_radiation():
    """Probability (0-100) of elevated space-radiation exposure (float)."""
    return float(get_radiation_report()["radiation_percent"])


# -------------------------------------------------------------------- CLI ----
def _monitor(cfg, hours=None, quiet=False):
    det = RadiationDetector(cfg)
    print(f"Monitoring {cfg.size_mib} MiB every {cfg.scan_interval_s}s "
          f"(baseline {cfg.baseline_per_bit_hour:.2e} flips/bit/h). Ctrl+C to stop.")
    end = None if hours is None else time.time() + hours * 3600
    try:
        while end is None or time.time() < end:
            for e in det.scan():
                if not quiet:
                    print(time.strftime("%H:%M:%S"), e.category, e.cells[0])
            r = det.assess()
            if r["level"] != "NORMAL":
                print(r["message"])
            time.sleep(cfg.scan_interval_s)
    except KeyboardInterrupt:
        print()
    return det


def main(argv=None):
    p = argparse.ArgumentParser(description="Memory bit-flip radiation detector")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="16 simulated hours with all scenarios")
    d.add_argument("--seed", type=int, default=1)
    for name in ("monitor", "calibrate"):
        s = sub.add_parser(name)
        s.add_argument("--size-mib", type=int, default=64)
        s.add_argument("--interval", type=float, default=10.0)
        if name == "calibrate":
            s.add_argument("--hours", type=float, default=24)
        else:
            s.add_argument("--baseline", type=float, help="flips/bit/hour")
            s.add_argument("--multiplier", type=float, default=10.0)
    a = p.parse_args(argv)

    if a.cmd == "demo":
        run_demo(a.seed)
    elif a.cmd == "calibrate":
        cfg = Config(size_mib=a.size_mib, scan_interval_s=a.interval)
        det = _monitor(cfg, a.hours)
        hours = (time.time() - det.start_time) / 3600
        k = det.totals["isolated"]
        rate = k / (det.n_bits * hours) if k else 3 / (det.n_bits * hours)  # 95 % upper bound
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump({"baseline_per_bit_hour": rate, "hours": round(hours, 2),
                       "events": k, "bits": det.n_bits}, f, indent=2)
        print(f"{k} isolated flips in {hours:.1f} h -> baseline {rate:.2e} "
              f"flips/bit/hour saved to {BASELINE_FILE}"
              + ("" if k else " (zero events: 95% upper bound)"))
    else:
        cfg = Config(size_mib=a.size_mib, scan_interval_s=a.interval,
                     rad_multiplier=a.multiplier)
        cfg.baseline_per_bit_hour = a.baseline or load_baseline() or cfg.baseline_per_bit_hour
        _monitor(cfg)


if __name__ == "__main__":
    main()