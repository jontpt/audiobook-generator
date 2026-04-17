#!/usr/bin/env python3
"""
Brass Ensemble Transcriber v6.0 - Main entry point
With detailed crash logging.
"""
import sys
import os
import traceback
from pathlib import Path

LOG_FILE = Path(__file__).parent / "main_error.txt"

def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# Clear previous log
if LOG_FILE.exists():
    LOG_FILE.unlink()

log("=== START ===")

try:
    log("1. Setting env...")
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    log("   env set")

    log("2. Importing PyQt5...")
    from PyQt5.QtWidgets import QApplication, QMessageBox
    log("   PyQt5 OK")

    log("3. Importing music21...")
    from music21 import converter, stream
    log("   music21 OK")

    log("4. Creating QApplication...")
    app = QApplication(sys.argv)
    log("   QApplication OK")

    log("5. Importing ScoreArranger...")
    from transcriber.gui import ScoreArranger
    log("   Import OK")

    log("6. Creating window...")
    win = ScoreArranger()
    log("   Window created")

    log("7. Showing window...")
    win.show()
    
    # Center on screen and bring to front
    from PyQt5.QtCore import Qt
    screen = app.primaryScreen().geometry()
    x = (screen.width() - win.width()) // 2
    y = (screen.height() - win.height()) // 2
    win.move(max(50, x), max(50, y))
    
    # Ensure it's visible
    win.setWindowState(win.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
    win.activateWindow()
    
    log("   Window shown and centered")

    log("8. Starting event loop...")
    sys.exit(app.exec_())

except Exception as e:
    tb = traceback.format_exc()
    log(f"EXCEPTION: {e}")
    log(tb)
    
    # Try to show error dialog
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app2 = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Crash", f"{e}\n\n{tb}")
    except:
        pass
    
    log("DONE")
    sys.exit(1)

def _qt_excepthook(exc_type, exc_value, exc_tb):
    """Capture uncaught Qt callback exceptions to the same crash log."""
    try:
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:
        tb = f"{exc_type}: {exc_value}"
    try:
        log("UNCAUGHT QT EXCEPTION:")
        log(tb)
    except Exception:
        pass
    # Preserve default stderr behavior as well.
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass

sys.excepthook = _qt_excepthook
