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


def _parse_bp(text):
    parts = text.replace(",", "/").replace(" ", "/").split("/")
    parts = [p for p in parts if p]
    if len(parts) != 2:
        raise ValueError("Blood pressure must look like 120/80")
    return int(parts[0]), int(parts[1])


def _apply(w, h, bp, a, s, act):
    """Store validated values in the module variables."""
    global weight, height, bloodPressure, age, sex, activity
    weight = float(w)
    height = float(h)
    bloodPressure = _parse_bp(bp) if isinstance(bp, str) else tuple(bp)
    age = int(a)
    sex = s.strip().lower()
    activity = act.strip().lower()


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
        except ValueError as err:
            print(f"Invalid input: {err}")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            again = input("\nMeasure again? (y/n) [n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if again != "y":
            return


# ------------------------------------------------------------------ window UI (PySide6 / Qt)
def run_window():
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout,
                                   QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                                   QVBoxLayout, QWidget)
    import healthMonitor

    app = QApplication.instance() or QApplication(sys.argv)

    win = QWidget()
    win.setWindowTitle("Health Monitor")
    win.resize(1150, 700)

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

    form = QFormLayout()
    form.addRow("Weight (kg)", weight_in)
    form.addRow("Height (cm)", height_in)
    form.addRow("Blood pressure (sys/dia)", bp_in)
    form.addRow("Age (years)", age_in)
    form.addRow("Sex", sex_in)
    form.addRow("Activity", act_in)

    button = QPushButton("Read watch && analyze")
    left = QVBoxLayout()
    left.addLayout(form)
    left.addWidget(button)
    left.addStretch()

    output = QPlainTextEdit()
    output.setReadOnly(True)
    output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

    layout = QHBoxLayout(win)
    layout.addLayout(left, 0)
    layout.addWidget(output, 1)

    def analyze():
        try:
            _apply(weight_in.text(), height_in.text(), bp_in.text(),
                   age_in.text(), sex_in.currentText(), act_in.currentText())
            text = healthMonitor.format_report(healthMonitor.build_report())
        except ValueError as err:
            QMessageBox.warning(win, "Invalid input", str(err))
            return
        output.setPlainText(text)

    button.clicked.connect(analyze)
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