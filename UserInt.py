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
"""

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


# ------------------------------------------------------------------ console UI
def _ask(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else str(default)


def run_console():
    import healthMonitor
    print("=== Health Monitor ===  (press Enter to keep the value in brackets)")
    while True:
        try:
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
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                                   QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                                   QVBoxLayout, QWidget)
    import healthMonitor

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
        lay.addWidget(make_label("Enter your details on the left and press \u201cRead watch & analyze\u201d, then \u201cTest solar radiation\u201d.",
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
    button = QPushButton("Read watch && analyze")
    button.setObjectName("primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    sb.addWidget(button)
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

    state = {"sensors": None}

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
        if not test:
            healthMonitor.log_report(report)
        scroll.setWidget(build_results(report, read_scores()))
        rad = healthMonitor.last_radiation_test()
        if test and rad:
            subtitle.setText(f"Radiation tested at {rad['time']} \u2013 {rad['bad']:,} of {rad['cells']:,} cells not null")
        else:
            subtitle.setText(f"Last reading: {report.timestamp}")

    def analyze():
        refresh(False)

    def test_radiation():
        refresh(True)

    button.clicked.connect(analyze)
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