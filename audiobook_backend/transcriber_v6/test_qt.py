"""Minimal test - just try to create and show a PyQt5 window."""
import sys
import os
os.environ["QT_QPA_PLATFORM"] = "windows"

from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import QTimer

app = QApplication(sys.argv)
print("QApplication OK")

win = QWidget()
win.setWindowTitle("Test Window")
win.resize(400, 300)
layout = QVBoxLayout()
layout.addWidget(QLabel("If you see this, PyQt5 works!"))
win.setLayout(layout)
win.show()
print("Window shown")

# Auto-close after 3 seconds
def close_it():
    print("Closing after 3s")
    win.close()
    QTimer.singleShot(500, app.quit)

QTimer.singleShot(3000, close_it)
print("Entering event loop...")
code = app.exec_()
print(f"Event loop exited with code {code}")
sys.exit(code)
