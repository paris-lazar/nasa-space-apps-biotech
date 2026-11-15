"""
UserInt.py - user interface of the health app AND the starting file.

Run:   python UserInt.py          (PySide6 window, or console if PySide6 is missing)
       python UserInt.py --cli    (force console mode)

healthMonitor.py reads these module-level variables:
    weight        kg
    height        cm
    bloodPressure (systolic, diastolic) in mmHg
Optional extras (healthMonitor falls back to defaults if missing):
    age, sex ("male"/"female"), activity ("sedentary", "light", "moderate", "active", "very_active")
    radiationTest  demo only: % of the ~100 MB radiation-test list to corrupt before a test (0 = real scan only)

Watch data: "Analyze (demo)" re-analyses the latest measurement stored in health_log.csv; otherwise
the user uploads a smartwatch export (Apple Health .zip/.xml, .json or .csv).
The file is first passed through smartwatch.py, which cleans / normalises the format, and the
cleaned values are then read by healthMonitor.py and shown here.
"""

import os
import sys

# When this file is the starting script it is "__main__". Register it under its
# real name so `import UserInt` inside healthMonitor returns THIS module (with the
# values typed by the user) instead of loading a second, default copy.
if __name__ == "__main__":
    sys.modules.setdefault("UserInt", sys.modules["__main__"])

# ---- variables read by healthMonitor.py (defaults until the user enters data) ----
weight = 70.0                 # kg
height = 175.0                # cm
bloodPressure = (118, 76)     # (systolic, diastolic) mmHg
age = 30                      # years
sex = "male"                  # "male" / "female"
activity = "light"            # activity level
radiationTest = 0.0           # demo only: % of cells to corrupt before the test (0 = real scan only)

# demo presets -> % of cells corrupted (one NOAA S level per tenfold step)
STORM_PRESETS = {"off": 0.0, "minor": 0.0005, "moderate": 0.005,
                 "strong": 0.05, "severe": 0.5, "extreme": 2.0}


def _parse_bp(text):
    parts = text.replace(",", "/").replace(" ", "/").split("/")
    parts = [p for p in parts if p]
    if len(parts) != 2:
        raise ValueError("Blood pressure must look like 120/80")
    return int(parts[0]), int(parts[1])


def _apply(w, h, bp, a, s, act):
    """Validate the typed values and store them in the module variables."""
    global weight, height, bloodPressure, age, sex, activity
    try:
        new_weight = float(str(w).replace(",", "."))
        new_height = float(str(h).replace(",", "."))
        new_age = int(str(a).strip())
    except ValueError:
        raise ValueError("Weight, height and age must be numbers.") from None
    try:
        new_bp = _parse_bp(bp) if isinstance(bp, str) else tuple(int(x) for x in bp)
    except ValueError:
        raise ValueError("Blood pressure must look like 120/80.") from None
    weight, height, bloodPressure, age = new_weight, new_height, new_bp, new_age
    sex = s.strip().lower()
    activity = act.strip().lower()


def _set_demo_storm(key):
    """Choose how many cells the demo corrupts before the radiation test (off = none)."""
    global radiationTest
    key = key.strip().lower()
    if key not in STORM_PRESETS:
        raise ValueError("Demo storm must be one of: " + ", ".join(STORM_PRESETS))
    radiationTest = STORM_PRESETS[key]
    return radiationTest


# ------------------------------------------------------------------ smartwatch export upload
WATCH_EXTENSIONS = (".zip", ".xml", ".json", ".csv")
FILE_FILTER = ("Smartwatch exports (*.zip *.xml *.json *.csv);;Apple Health (*.zip *.xml);;"
               "JSON (*.json);;CSV (*.csv);;All files (*)")
NO_FILE_TEXT = "No file loaded \u2013 Apple Health (.zip / .xml), .json or .csv"
_METRIC_NAMES = {"heart_rate": "heart rate", "resting_hr": "resting HR", "hrv": "HRV",
                 "resp_rate": "respiration", "spo2": "SpO2", "systolic": "blood pressure",
                 "diastolic": "blood pressure", "temp": "temperature", "sleep_hours": "sleep",
                 "sleep_intervals": "sleep", "stress": "stress"}


# health_log.csv (written by healthMonitor after every measurement) -> names smartwatch.py knows
_LOG_COLUMNS = {
    "timestamp": ("timestamp", "time", "date", "datetime", "ts"),
    "sleep_hours": ("sleep", "sleep_hours", "sleep_h", "sleep_total_h"),
    "resting_hr": ("hr", "heart_rate", "resting_hr", "resting_heart_rate", "pulse", "bpm"),
    "stress": ("stress", "stress_score"),
    "resp_rate": ("pr", "resp_rate", "respiratory_rate", "respiration", "breathing", "breathing_rate"),
    "temp": ("temp", "temperature", "body_temperature", "skin_temperature"),
    "spo2": ("ox", "spo2", "oxygen", "oxygen_saturation", "blood_oxygen"),
    "systolic": ("systolic", "sys", "bp_sys", "bp_systolic", "blood_pressure_systolic"),
    "diastolic": ("diastolic", "dia", "bp_dia", "bp_diastolic", "blood_pressure_diastolic"),
    "bp": ("bp", "blood_pressure", "bloodpressure"),          # one column like "120/80"
}
_UNIT_SUFFIXES = ("_c", "_bpm", "_pct", "_percent", "_h", "_hours", "_mmhg", "_brpm")


def health_log_path():
    """The CSV healthMonitor logs every measurement to (healthMonitor.LOG_FILE)."""
    try:
        import healthMonitor
        path = healthMonitor.LOG_FILE
    except Exception:
        path = None
    return str(path) if path else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                               "health_log.csv")


def _log_column(header):
    import re
    name = re.sub(r"[^a-z0-9]+", "_", str(header).lower()).strip("_")   # "SpO2 (%)" -> "spo2"
    for suffix in _UNIT_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    for target, aliases in _LOG_COLUMNS.items():
        if name in aliases:
            return target
    return None


LOG_PROFILE = {}      # weight / height of the last logged measurement (filled by prepare_health_log)


def prepare_health_log(path, last=1):
    """Copy the last `last` rows of health_log.csv (default: the latest measurement) into a
    temporary CSV whose columns use the names smartwatch.py understands.
    Returns the temporary file's path (caller deletes it)."""
    import csv
    import tempfile
    import smartwatch
    if not os.path.isfile(path):
        raise ValueError(f"{os.path.basename(path)} not found yet - run \u201cUpload watch & analyze\u201d "
                         "once so a measurement is logged.")
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)[-last:]
    except (OSError, UnicodeDecodeError, csv.Error) as err:
        raise ValueError(f"Could not read {os.path.basename(path)} ({err}).") from None
    if not rows:
        raise ValueError(f"{os.path.basename(path)} has no measurements yet.")
    mapping = {}                                   # canonical name -> original header (first wins)
    for header in headers:
        target = _log_column(header)
        if target and target not in mapping:
            mapping[target] = header
    if not set(mapping) - {"timestamp"}:
        raise ValueError(f"No vital-sign columns recognised in {os.path.basename(path)} "
                         f"(columns: {', '.join(h for h in headers if h)}).")
    LOG_PROFILE.clear()
    for key, names in (("weight", ("weight", "weight_kg")), ("height", ("height", "height_cm"))):
        for header in headers:
            if str(header).strip().lower() in names and str(rows[-1].get(header) or "").strip():
                LOG_PROFILE[key] = str(rows[-1][header]).strip()
                break
    columns = ["ts"] + [t for t in mapping if t not in ("timestamp", "bp")]
    if "bp" in mapping:
        columns += [c for c in ("systolic", "diastolic") if c not in columns]
    fd, tmp = tempfile.mkstemp(suffix=".csv", prefix="health_log_clean_")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            writer.writerow(columns)
            for i, row in enumerate(rows):
                try:                               # real time if parseable, else row order
                    ts = smartwatch._ts(row.get(mapping.get("timestamp"), ""))
                except (TypeError, ValueError):
                    ts = i
                values = {t: row.get(h) for t, h in mapping.items()}
                if "bp" in values and not values.get("systolic"):
                    try:
                        values["systolic"], values["diastolic"] = _parse_bp(values["bp"] or "")
                    except ValueError:
                        pass
                writer.writerow([ts] + [values.get(c) if values.get(c) is not None else ""
                                        for c in columns[1:]])
    except Exception:
        os.remove(tmp)
        raise
    return tmp


def load_health_log(path=None):
    """Step 1 for the demo: health_log.csv -> clean columns -> smartwatch.py (same route as an
    uploaded file). Returns {metric: number of records}."""
    tmp = prepare_health_log(path or health_log_path())
    try:
        return load_watch_file(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _describe(found):
    """'heart rate, SpO2, sleep' - the vitals smartwatch.py found in the file."""
    names = []
    for key in found:
        name = _METRIC_NAMES.get(key, key)
        if name not in names:
            names.append(name)
    return ", ".join(names)


def _reset_watch():
    """Forget any loaded export, so smartwatch.py is back to its simulated values."""
    import smartwatch
    smartwatch._DATA.clear()
    smartwatch._SLEEP.clear()
    smartwatch._SOURCE.clear()


def load_watch_file(path):
    """Step 1: pass the user's export file through smartwatch.py (it parses + cleans the
    format). Returns {metric: number of records}. Raises ValueError with a readable message."""
    import json
    import xml.etree.ElementTree as ET
    import zipfile
    import smartwatch

    path = os.path.expanduser(str(path).strip().strip('"').strip("'"))
    if not os.path.isfile(path):
        raise ValueError(f"File not found: {path}")
    if not path.lower().endswith(WATCH_EXTENSIONS):
        raise ValueError("Unsupported file. Use Apple Health (.zip / .xml), .json or .csv.")
    try:
        found = smartwatch.smartwatch(path)
    except zipfile.BadZipFile:
        raise ValueError("This .zip is not a valid Apple Health export.") from None
    except StopIteration:
        raise ValueError("No export.xml inside the zip. Use the zip from Health > profile > "
                         "Export All Health Data.") from None
    except ET.ParseError:
        raise ValueError("The XML file is damaged or is not an Apple Health export.xml.") from None
    except json.JSONDecodeError:
        raise ValueError("The JSON file is damaged or not valid JSON.") from None
    except (ValueError, AttributeError, TypeError, KeyError, UnicodeDecodeError) as err:
        raise ValueError(f"Unexpected file layout ({err}).") from None
    except OSError as err:
        raise ValueError(f"Could not read the file ({err}).") from None
    if not found:
        raise ValueError("No supported vital signs found in this file (looked for heart rate, "
                         "SpO2, respiration, temperature, sleep, stress, blood pressure).")
    return found


def use_watch_bp():
    """If the loaded export contains blood pressure, store it in bloodPressure and return it."""
    global bloodPressure
    import smartwatch
    sys_, dia = smartwatch.get_bp()
    if sys_ is None:
        return None
    bloodPressure = (sys_, dia)
    return bloodPressure


# ------------------------------------------------------------------ console UI
def _ask(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else str(default)


def run_console():
    import healthMonitor
    print("=== Health Monitor ===  (press Enter to keep the value in brackets)")
    while True:
        try:
            path = input("Smartwatch export (.zip/.xml Apple Health, .json, .csv) "
                         "[Enter = keep current]: ").strip()
            if path:
                try:
                    found = load_watch_file(path)
                except ValueError:
                    _reset_watch()
                    raise
                print("Loaded: " + _describe(found))
                use_watch_bp()
            _apply(
                _ask("Weight (kg)", weight),
                _ask("Height (cm)", height),
                _ask("Blood pressure (sys/dia)", f"{bloodPressure[0]}/{bloodPressure[1]}"),
                _ask("Age (years)", age),
                _ask("Sex (male/female)", sex),
                _ask("Activity (sedentary/light/moderate/active/very_active)", activity),
            )
            healthMonitor.run()
            while True:
                choice = input("\n[t] test solar radiation   [m] measure again   [q] quit: ").strip().lower()
                if choice == "t":
                    demo = _ask("Demo: inject radiation hits first? (off/" + "/".join(list(STORM_PRESETS)[1:]) + ")", "off")
                    percent = _set_demo_storm(demo)
                    result = healthMonitor.run_radiation_test(percent)
                    print()
                    print(healthMonitor.format_radiation_result(result))
                elif choice == "m":
                    break
                else:
                    return
        except ValueError as err:
            print(f"Invalid input: {err}")
        except (EOFError, KeyboardInterrupt):
            print()
            return


# ------------------------------------------------------------------ window UI (PySide6 / Qt)
BG, SIDEBAR, CARD, BORDER = "#0B1220", "#0F172A", "#162033", "#243049"
TEXT, MUTED = "#E2E8F0", "#8A9AB5"
ACCENT = "#38BDF8"
LEVEL_COLORS = {0: "#22C55E", 1: "#F59E0B", 2: "#EF4444"}
LEVEL_NAMES = {0: "Healthy", 1: "Watch", 2: "Attention"}


def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _score_color(score):
    return LEVEL_COLORS[0] if score >= 75 else LEVEL_COLORS[1] if score >= 55 else LEVEL_COLORS[2]


def read_scores(limit=20):
    """Overall scores of previous measurements, read from the CSV log."""
    import csv
    import healthMonitor
    try:
        with open(healthMonitor.LOG_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    scores = []
    for row in rows[-limit:]:
        try:
            scores.append(int(float(row["score"])))
        except (KeyError, TypeError, ValueError):
            continue
    return scores


def run_window():
    from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGridLayout,
                                   QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                                   QSizePolicy, QVBoxLayout, QWidget)
    import healthMonitor
    import smartwatch

    AlignCenter = Qt.AlignmentFlag.AlignCenter
    AlignLeft = Qt.AlignmentFlag.AlignLeft
    AlignTop = Qt.AlignmentFlag.AlignTop

    STYLE = f"""
    QWidget {{ background: {BG}; color: {TEXT};
              font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; font-size: 13px; }}
    QLabel {{ background: transparent; }}
    QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
    QFrame#sidebar QLabel {{ background: transparent; }}
    QLabel#brand {{ font-size: 20px; font-weight: 700; }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#fieldLabel {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
    QLabel#section {{ font-size: 15px; font-weight: 700; }}
    QLabel#error {{ color: {LEVEL_COLORS[2]}; }}
    QLineEdit, QComboBox {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 8px;
                           padding: 8px 10px; color: {TEXT}; }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox QAbstractItemView {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
                                  selection-background-color: {ACCENT}; selection-color: {BG}; }}
    QPushButton#primary {{ background: {ACCENT}; color: {BG}; border: none; border-radius: 10px;
                          padding: 12px; font-weight: 700; font-size: 14px; }}
    QPushButton#primary:hover {{ background: #7DD3FC; }}
    QPushButton#primary:pressed {{ background: #0EA5E9; }}
    QPushButton#secondary {{ background: transparent; color: {ACCENT}; border: 1px solid {ACCENT};
                            border-radius: 10px; padding: 11px; font-weight: 700; font-size: 14px; }}
    QPushButton#secondary:hover {{ background: {_rgba(ACCENT, 38)}; }}
    QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
    QScrollArea {{ border: none; background: {BG}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """

    def card_style(color=None):
        left = f"border-left: 4px solid {color};" if color else ""
        return (f"QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; {left} "
                f"border-radius: 14px; }}")

    def make_label(text, name=None, size=None, bold=False, color=None, wrap=False, align=None):
        lab = QLabel(text)
        if name:
            lab.setObjectName(name)
        extra = []
        if size:
            extra.append(f"font-size: {size}px;")
        if bold:
            extra.append("font-weight: 700;")
        if color:
            extra.append(f"color: {color};")
        if extra:
            lab.setStyleSheet("background: transparent; " + " ".join(extra))
        lab.setWordWrap(wrap)
        if align is not None:
            lab.setAlignment(align)
        return lab

    def make_card(color=None):
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet(card_style(color))
        return frame

    class WatchLoader(QThread):
        """Reads the export through smartwatch.py in the background (Apple exports can be huge)."""
        loaded = Signal(object)
        failed = Signal(str)

        def __init__(self, path, load=None):
            super().__init__()
            self.path = path
            self.load = load or load_watch_file

        def run(self):
            try:
                self.loaded.emit(self.load(self.path))
            except ValueError as err:
                self.failed.emit(str(err))
            except Exception as err:  # never let the thread die silently
                self.failed.emit(f"Could not read the file: {err}")

    # ------------------------------------------------------------ custom widgets
    class ScoreGauge(QWidget):
        def __init__(self, score):
            super().__init__()
            self.score = score
            self.setMinimumSize(190, 190)
            self.setStyleSheet("background: transparent;")

        def paintEvent(self, event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            side = min(self.width(), self.height()) - 28
            rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
            pen = QPen(QColor(BORDER), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 225 * 16, -270 * 16)
            color = _score_color(self.score)
            pen.setColor(QColor(color))
            p.setPen(pen)
            p.drawArc(rect, 225 * 16, int(-270 * 16 * self.score / 100))
            p.setPen(QColor(TEXT))
            big = QFont(self.font())
            big.setPointSize(34)
            big.setBold(True)
            p.setFont(big)
            p.drawText(QRectF(rect.x(), rect.y() + side * 0.22, side, side * 0.35), AlignCenter, str(self.score))
            small = QFont(self.font())
            small.setPointSize(10)
            p.setFont(small)
            p.setPen(QColor(color))
            p.drawText(QRectF(rect.x(), rect.y() + side * 0.55, side, side * 0.15), AlignCenter,
                       healthMonitor.score_label(self.score).upper())
            p.end()

    class TrendChart(QWidget):
        def __init__(self, scores):
            super().__init__()
            self.scores = scores
            self.setMinimumHeight(170)
            self.setStyleSheet("background: transparent;")

        def paintEvent(self, event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            left, right, top, bottom = 34, 16, 14, 22
            w = self.width() - left - right
            h = self.height() - top - bottom
            small = QFont(self.font())
            small.setPointSize(8)
            p.setFont(small)
            for value in (0, 50, 100):
                y = top + h * (1 - value / 100)
                p.setPen(QPen(QColor(BORDER), 1))
                p.drawLine(QPointF(left, y), QPointF(left + w, y))
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(0, y - 8, left - 6, 16),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(value))
            n = len(self.scores)
            if n == 0:
                p.end()
                return
            xs = [left + (w / 2 if n == 1 else w * i / (n - 1)) for i in range(n)]
            ys = [top + h * (1 - s / 100) for s in self.scores]
            if n > 1:
                area = QPainterPath()
                area.moveTo(xs[0], top + h)
                for x, y in zip(xs, ys):
                    area.lineTo(x, y)
                area.lineTo(xs[-1], top + h)
                area.closeSubpath()
                p.fillPath(area, QColor(56, 189, 248, 38))
                line = QPainterPath()
                line.moveTo(xs[0], ys[0])
                for x, y in zip(xs[1:], ys[1:]):
                    line.lineTo(x, y)
                p.setPen(QPen(QColor(ACCENT), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawPath(line)
            p.setPen(Qt.PenStyle.NoPen)
            for i, (x, y) in enumerate(zip(xs, ys)):
                last = i == n - 1
                p.setBrush(QColor(_score_color(self.scores[i])) if last else QColor(ACCENT))
                r = 5.5 if last else 3.5
                p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(xs[-1] - 30, ys[-1] - 26, 60, 16), AlignCenter, str(self.scores[-1]))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(left, self.height() - 18, w, 16), AlignLeft,
                       f"last {n} measurement{'s' if n != 1 else ''}")
            p.end()

    # ------------------------------------------------------------ result sections
    def metric_card(m):
        color = MUTED if m.value == "Not tested" else LEVEL_COLORS[m.level]
        card = make_card(color)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(6)
        lay.addWidget(make_label(m.name.upper(), color=MUTED, size=11, bold=True))
        lay.addWidget(make_label(m.value, size=24, bold=True))
        pill = make_label(m.status, size=12, bold=True, color=color)
        pill.setStyleSheet(f"background: {_rgba(color, 38)}; color: {color}; border-radius: 10px; "
                           f"padding: 3px 10px; font-size: 12px; font-weight: 700;")
        lay.addWidget(pill, 0, AlignLeft)
        if m.advice:
            lay.addWidget(make_label(m.advice, color=MUTED, size=12, wrap=True))
        lay.addStretch()
        return card

    def build_results(report, scores):
        page = QWidget()
        page.setStyleSheet(f"background: {BG};")
        v = QVBoxLayout(page)
        v.setContentsMargins(28, 8, 28, 28)
        v.setSpacing(18)

        # --- summary row: gauge + alerts
        top = QHBoxLayout()
        top.setSpacing(18)
        gauge_card = make_card()
        gauge_card.setFixedWidth(260)
        gl = QVBoxLayout(gauge_card)
        gl.setContentsMargins(16, 16, 16, 14)
        gl.addWidget(ScoreGauge(report.score))
        gl.addWidget(make_label("Overall health score", color=MUTED, size=12, align=AlignCenter))
        top.addWidget(gauge_card)

        n_ok = sum(1 for m in report.metrics if m.level == 0 and m.value != "Not tested")
        n_warn = sum(1 for m in report.metrics if m.level == 1)
        n_alert = len(report.alerts)
        banner_color = LEVEL_COLORS[2] if n_alert else (LEVEL_COLORS[1] if n_warn else LEVEL_COLORS[0])
        banner = make_card(banner_color)
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(22, 18, 22, 18)
        bl.setSpacing(8)
        if n_alert:
            bl.addWidget(make_label("Needs attention", size=20, bold=True, color=banner_color))
            for a in report.alerts:
                bl.addWidget(make_label("\u2022  " + a, size=13, wrap=True))
            bl.addWidget(make_label("Consider medical advice. For chest pain, severe breathlessness, "
                                    "fainting or confusion call emergency services (112 in Greece/EU).",
                                    color=MUTED, size=12, wrap=True))
        else:
            headline = "No urgent alerts" if n_warn else "All readings look healthy"
            bl.addWidget(make_label(headline, size=20, bold=True, color=banner_color))
            bl.addWidget(make_label("No vital sign is in a range that needs urgent attention.",
                                    color=MUTED, size=13, wrap=True))
        bl.addStretch()
        chips = QHBoxLayout()
        chips.setSpacing(10)
        for count, level in ((n_ok, 0), (n_warn, 1), (n_alert, 2)):
            chip = make_label(f"{count}  {LEVEL_NAMES[level]}")
            col = LEVEL_COLORS[level]
            chip.setStyleSheet(f"background: {_rgba(col, 38)}; color: {col}; border-radius: 10px; "
                               f"padding: 4px 12px; font-size: 12px; font-weight: 700;")
            chips.addWidget(chip)
        chips.addStretch()
        bl.addLayout(chips)
        top.addWidget(banner, 1)
        v.addLayout(top)

        # --- vital signs grid
        v.addWidget(make_label("Vital signs", name="section"))
        grid = QGridLayout()
        grid.setSpacing(16)
        for i, m in enumerate(report.metrics):
            grid.addWidget(metric_card(m), i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)

        # --- insights
        v.addWidget(make_label("Insights & daily targets", name="section"))
        ins = make_card()
        il = QVBoxLayout(ins)
        il.setContentsMargins(22, 16, 22, 16)
        il.setSpacing(12)
        for label, text in report.extras:
            row = QHBoxLayout()
            row.setSpacing(16)
            key = make_label(label, size=13, bold=True, color=ACCENT)
            key.setFixedWidth(130)
            key.setAlignment(AlignTop)
            row.addWidget(key)
            row.addWidget(make_label(text, size=13, wrap=True), 1)
            il.addLayout(row)
        v.addWidget(ins)

        # --- trend
        v.addWidget(make_label("Score history", name="section"))
        trend_card = make_card()
        tl = QVBoxLayout(trend_card)
        tl.setContentsMargins(18, 14, 18, 10)
        tl.addWidget(TrendChart(scores))
        v.addWidget(trend_card)

        v.addWidget(make_label("Informational only \u2013 not a medical device and not a diagnosis. "
                               "Reference ranges: WHO, ACC/AHA, AASM/NSF, NEWS2.",
                               color=MUTED, size=11, wrap=True))
        v.addStretch()
        return page

    def placeholder():
        page = QWidget()
        page.setStyleSheet(f"background: {BG};")
        lay = QVBoxLayout(page)
        lay.addStretch()
        lay.addWidget(make_label("No reading yet", size=22, bold=True, align=AlignCenter))
        lay.addWidget(make_label("Enter your details on the left, press \u201cUpload watch & analyze\u201d and choose your smartwatch export, then \u201cTest solar radiation\u201d.",
                                 color=MUTED, size=14, align=AlignCenter))
        lay.addStretch()
        return page

    # ------------------------------------------------------------ main window
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)

    win = QWidget()
    win.setWindowTitle("Health Monitor")
    win.resize(1320, 840)
    win.setMinimumSize(1080, 660)

    # sidebar
    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    sidebar.setFixedWidth(310)
    sb = QVBoxLayout(sidebar)
    sb.setContentsMargins(24, 28, 24, 24)
    sb.setSpacing(6)
    sb.addWidget(make_label("Health Monitor", name="brand"))
    sb.addWidget(make_label("Personal vitals dashboard", name="muted"))
    sb.addSpacing(22)
    sb.addWidget(make_label("YOUR PROFILE", name="fieldLabel"))
    sb.addSpacing(4)

    weight_in = QLineEdit(str(weight))
    height_in = QLineEdit(str(height))
    bp_in = QLineEdit(f"{bloodPressure[0]}/{bloodPressure[1]}")
    age_in = QLineEdit(str(age))
    sex_in = QComboBox()
    sex_in.addItems(["male", "female"])
    sex_in.setCurrentText(sex)
    act_in = QComboBox()
    act_in.addItems(["sedentary", "light", "moderate", "active", "very_active"])
    act_in.setCurrentText(activity)
    storm_in = QComboBox()
    storm_in.addItems(list(STORM_PRESETS))

    def field(text, widget):
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(make_label(text.upper(), name="fieldLabel"))
        box.addWidget(widget)
        return box

    def pair(left, right):
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addLayout(left)
        row.addLayout(right)
        return row

    sb.addLayout(pair(field("Weight (kg)", weight_in), field("Height (cm)", height_in)))
    sb.addSpacing(8)
    sb.addLayout(field("Blood pressure (sys/dia)", bp_in))
    sb.addSpacing(8)
    sb.addLayout(pair(field("Age", age_in), field("Sex", sex_in)))
    sb.addSpacing(8)
    sb.addLayout(field("Activity level", act_in))
    sb.addSpacing(18)
    button = QPushButton("Upload watch && analyze")
    button.setObjectName("primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    sb.addWidget(button)
    sb.addSpacing(8)
    demo_button = QPushButton("Analyze (demo)")
    demo_button.setObjectName("secondary")
    demo_button.setCursor(Qt.CursorShape.PointingHandCursor)
    sb.addWidget(demo_button)
    file_label = make_label(NO_FILE_TEXT, name="muted", size=11, wrap=True)
    sb.addWidget(file_label)
    sb.addSpacing(10)
    test_button = QPushButton("Test solar radiation")
    test_button.setObjectName("secondary")
    test_button.setCursor(Qt.CursorShape.PointingHandCursor)
    sb.addWidget(test_button)
    sb.addSpacing(6)
    sb.addLayout(field("Demo: inject radiation hits", storm_in))
    sb.addWidget(make_label("Leave on \u201coff\u201d for a real scan of the 100 MB memory list.",
                            name="muted", size=11, wrap=True))
    error_label = make_label("", name="error", wrap=True)
    sb.addWidget(error_label)
    sb.addStretch()
    sb.addWidget(make_label("Sensors: smartwatch.py", name="muted", size=11))

    # main area
    main_col = QVBoxLayout()
    main_col.setContentsMargins(0, 0, 0, 0)
    main_col.setSpacing(0)
    header = QVBoxLayout()
    header.setContentsMargins(28, 26, 28, 12)
    header.setSpacing(2)
    header.addWidget(make_label("Dashboard", size=24, bold=True))
    subtitle = make_label("Waiting for the first reading", color=MUTED, size=13)
    header.addWidget(subtitle)
    main_col.addLayout(header)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(placeholder())
    main_col.addWidget(scroll, 1)

    root = QHBoxLayout(win)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    root.addWidget(sidebar)
    root.addLayout(main_col, 1)

    state = {"sensors": None, "file": None, "pending": None, "loader": None, "log": True,
             "dir": os.path.expanduser("~")}

    def source_text():
        """Which values came from the uploaded file and which are simulated."""
        if not state["file"]:
            return "simulated watch data"
        names = {"sleep": "sleep", "hr": "heart rate", "stress": "stress",
                 "pr": "respiration", "temp": "temperature", "ox": "SpO2"}
        simulated = [names.get(k, k) for k, v in smartwatch.data_source().items() if v == "simulated"]
        if simulated:
            return f"{state['file']} (not in file, simulated: {', '.join(simulated)})"
        return f"{state['file']} (all values from file)"

    def refresh(test):
        """test=False: read the watch and analyse.  test=True: run the radiation test on the
        100 MB memory list, then rebuild the dashboard with the same watch readings."""
        try:
            _apply(weight_in.text(), height_in.text(), bp_in.text(),
                   age_in.text(), sex_in.currentText(), act_in.currentText())
            if test:
                healthMonitor.run_radiation_test(_set_demo_storm(storm_in.currentText()))
            report = healthMonitor.build_report(state["sensors"] if test else None)
        except (ValueError, KeyError, TypeError) as err:
            error_label.setText(str(err))
            return
        error_label.setText("")
        state["sensors"] = {k: report.raw[k] for k in healthMonitor.SENSOR_LIMITS}
        if not test and state["log"]:
            healthMonitor.log_report(report)
        scroll.setWidget(build_results(report, read_scores()))
        rad = healthMonitor.last_radiation_test()
        if test and rad:
            subtitle.setText(f"Radiation tested at {rad['time']} \u2013 {rad['bad']:,} of {rad['cells']:,} cells not null")
        else:
            subtitle.setText(f"Last reading: {report.timestamp} \u2013 {source_text()}")

    def analyze():
        """Re-analyse with the data already loaded (e.g. after editing weight or age)."""
        if state["loader"] is None:
            refresh(False)

    def set_busy(busy):
        button.setEnabled(not busy)
        demo_button.setEnabled(not busy)
        test_button.setEnabled(not busy)
        button.setText("Reading file\u2026" if busy else "Upload watch && analyze")

    def finish_loader():
        loader = state["loader"]
        if loader is not None:
            loader.wait()
            state["loader"] = None
        set_busy(False)

    def on_loaded(found):
        finish_loader()
        state["file"] = os.path.basename(state["pending"])
        bp = use_watch_bp()          # blood pressure from the file, if the watch recorded it
        if bp:
            bp_in.setText(f"{bp[0]}/{bp[1]}")
        if not state["log"]:         # demo (health_log.csv): also restore weight / height
            if "weight" in LOG_PROFILE:
                weight_in.setText(LOG_PROFILE["weight"])
            if "height" in LOG_PROFILE:
                height_in.setText(LOG_PROFILE["height"])
        file_label.setText(f"{state['file']}\nFound: {_describe(found)}")
        refresh(False)               # step 2: analyse the cleaned values

    def on_failed(message):
        finish_loader()
        _reset_watch()
        state["file"] = None
        file_label.setText(NO_FILE_TEXT)
        subtitle.setText("Waiting for the first reading")
        error_label.setText(message)

    def upload_and_analyze():
        if state["loader"] is not None:
            return
        path, _ = QFileDialog.getOpenFileName(win, "Choose your smartwatch export",
                                              state["dir"], FILE_FILTER)
        if not path:
            return
        state["dir"] = os.path.dirname(path)
        begin_load(path)

    def analyze_demo():
        """Demo: analyse the latest measurement already stored in health_log.csv."""
        if state["loader"] is None:
            begin_load(health_log_path(), load=load_health_log, log=False)

    def begin_load(path, load=None, log=True):
        """Pass the file through smartwatch.py in the background, then analyse (see on_loaded).
        log=False: do not write the result back to the log (it was read from the log)."""
        state["pending"] = path
        state["log"] = log
        error_label.setText("")
        subtitle.setText(f"Reading {os.path.basename(path)} \u2026")
        set_busy(True)
        loader = WatchLoader(path, load)
        loader.loaded.connect(on_loaded)
        loader.failed.connect(on_failed)
        state["loader"] = loader
        loader.start()

    def test_radiation():
        refresh(True)

    button.clicked.connect(upload_and_analyze)
    demo_button.clicked.connect(analyze_demo)
    app.aboutToQuit.connect(lambda: state["loader"] and state["loader"].wait())
    test_button.clicked.connect(test_radiation)
    for line in (weight_in, height_in, bp_in, age_in):
        line.returnPressed.connect(analyze)

    win.show()
    app.exec()


def main():
    if "--cli" in sys.argv:
        run_console()
        return
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print("PySide6 is not installed (pip install PySide6) - using console mode.\n")
        run_console()
        return
    try:
        run_window()
    except Exception as err:  # e.g. no display available
        print(f"Window could not open ({err}) - using console mode.\n")
        run_console()


if __name__ == "__main__":
    main()