import sys
import traceback
from pathlib import Path

try:
    print("Launching ScoreArranger...")
    from PyQt5.QtWidgets import QApplication
    from transcriber.gui import ScoreArranger

    app = QApplication(sys.argv)
    print("QApplication created, instantiating ScoreArranger...")

    win = ScoreArranger()
    print("ScoreArranger created, showing...")

    win.show()
    print("show() called, entering event loop...")

    sys.exit(app.exec_())

except Exception as e:
    log_path = Path(__file__).parent / "crash_log.txt"
    tb = traceback.format_exc()
    with open(log_path, "w") as f:
        f.write(f"ERROR: {e}\n\n{tb}")
    print(f"CRASHED - see {log_path}")
    print(tb)
