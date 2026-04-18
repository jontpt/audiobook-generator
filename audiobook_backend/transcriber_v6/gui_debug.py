"""Step-by-step ScoreArranger init test."""
import sys
import traceback
from PyQt5.QtWidgets import QApplication

# Redirect all output to file
import io
log = []
def L(msg):
    log.append(msg)
    print(msg)

try:
    app = QApplication(sys.argv)
    L("1. QApplication OK")

    from transcriber.gui import ScoreArranger
    L("2. Import OK")

    L("3. Instantiating ScoreArranger...")
    win = ScoreArranger()
    L("4. ScoreArranger.__init__ OK")

    L("5. Calling win.show()...")
    win.show()
    L("6. show() OK")

    L("7. Event loop...")
    from PyQt5.QtCore import QTimer
    def auto_close():
        L("8. Closing...")
        win.close()
        QTimer.singleShot(500, app.quit)
    QTimer.singleShot(3000, auto_close)

    code = app.exec_()
    L(f"9. Exit code: {code}")

except Exception:
    L(f"EXCEPTION: {traceback.format_exc()}")

# Write log
with open("gui_debug_log.txt", "w") as f:
    f.write("\n".join(log))
print(f"\nLog written: gui_debug_log.txt ({len(log)} lines)")
