"""
PyQt5 GUI for the Brass Ensemble Transcriber.

Provides file selection, target instrument configuration,
processing log, and export options.
"""

import copy
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from music21 import chord, converter, instrument, note, stream

from .constants import (
    DEFAULT_TITLE_FONT_SIZE,
    MUSESCORE_SEARCH_NAMES,
    MUSESCORE_SEARCH_PATHS,
    SETTINGS_PATH_NAME,
    VOCAL_MIDI_PROGRAMS,
    DEFAULT_INSTRUMENTAL_MIDI,
)
from .engine import ArrangementEngine
from .instruments import (
    ENSEMBLE_DB,
    ENSEMBLE_PRESETS,
    INSTRUMENT_DB,
    parse_free_text,
)
from .pdf_export import (
    convert_to_pdf,
    find_java_executable,
    find_musescore_executable,
    load_settings,
    run_audiveris,
    save_settings,
)
from .source_classifier import classify_source_part


# ═══════════════════════════════════════════════════════════════════════
#  CONVERSION THREAD
# ═══════════════════════════════════════════════════════════════════════

class ConversionThread(QThread):
    """Background thread for score arrangement and conversion."""
    log = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        input_path: str,
        output_path: str,
        target_instruments: List[str],
        ensemble_def: Optional[Dict[str, Any]] = None,
        excluded_part_names: Optional[List[str]] = None,
        also_midi: bool = False,
        audiveris_jar: Optional[str] = None,
        java_exe: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.target_instruments = target_instruments
        self.ensemble_def = ensemble_def
        self.excluded_part_names = set(excluded_part_names or [])
        self.also_midi = also_midi
        self.audiveris_jar = audiveris_jar
        self.java_exe = java_exe

    def run(self) -> None:
        tmp_dir = None
        try:
            music_path = self.input_path

            # PDF → MusicXML via Audiveris
            if Path(self.input_path).suffix.lower() == ".pdf":
                if not self.audiveris_jar:
                    raise RuntimeError("No Audiveris JAR configured. Use '⚙ PDF Setup'.")
                self.log.emit("Converting PDF via Audiveris...")
                self.log.emit("  (this may take 30-90 seconds)")
                tmp_dir = tempfile.mkdtemp(prefix="utrans_audiveris_")
                music_path = run_audiveris(
                    self.audiveris_jar, self.input_path, tmp_dir,
                    log_fn=self.log.emit, java_exe=self.java_exe,
                )
                self.log.emit(f"  ✓ OMR complete → {Path(music_path).name}")

            # Parse score
            self.log.emit(f"Loading {Path(music_path).name}...")
            score = converter.parse(music_path)
            if not score.parts:
                raise ValueError("No parts found in score")
            self.log.emit(f"Found {len(score.parts)} parts")

            if self.excluded_part_names:
                kept_parts = []
                removed = []
                for i, part in enumerate(score.parts):
                    name = part.partName or f"Part {i + 1}"
                    if name in self.excluded_part_names:
                        removed.append(name)
                    else:
                        kept_parts.append(copy.deepcopy(part))
                if removed:
                    self.log.emit(f"Excluding {len(removed)} source part(s): {', '.join(removed)}")
                filtered_score = stream.Score()
                if getattr(score, "metadata", None):
                    filtered_score.metadata = copy.deepcopy(score.metadata)
                for part in kept_parts:
                    filtered_score.append(part)
                score = filtered_score
                if not score.parts:
                    raise ValueError("All source parts were excluded")

            # Arrange
            engine = ArrangementEngine(log_fn=self.log.emit)
            result = engine.arrange(score, self.target_instruments, self.ensemble_def)

            if not result.parts:
                raise ValueError("Arrangement produced no parts!")

            # Save
            self.log.emit("\nSaving...")
            ext = Path(self.output_path).suffix.lower()
            fmt = "midi" if ext in (".mid", ".midi") else "musicxml"
            write_score = result.toSoundingPitch() if fmt == "midi" else result
            write_score.write(fmt, fp=self.output_path)
            self.log.emit(f"  ✓ {Path(self.output_path).name}")

            # Optional MIDI
            if self.also_midi and fmt != "midi":
                midi_path = str(Path(self.output_path).with_suffix(".mid"))
                result.toSoundingPitch().write("midi", fp=midi_path)
                self.log.emit(f"  ✓ {Path(midi_path).name}")

            self.log.emit("\n✅ Done")
            self.finished.emit(True, self.output_path)

        except Exception as e:
            import traceback
            self.log.emit(f"\n❌ {e}\n{traceback.format_exc()}")
            self.finished.emit(False, str(e))
        finally:
            if tmp_dir and Path(tmp_dir).exists():
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════
#  AUDIVERIS SETUP DIALOG
# ═══════════════════════════════════════════════════════════════════════

class AudiverisSetupDialog(QDialog):
    """Configure paths to Java, Audiveris.jar and MuseScore."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        current_jar: Optional[str] = None,
        current_java: Optional[str] = None,
        current_mscore: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("External Tools Setup")
        self.setModal(True)
        self.setMinimumWidth(600)
        self.selected_jar = current_jar
        self.selected_java = current_java
        self.selected_mscore = current_mscore

        layout = QVBoxLayout()
        layout.setSpacing(14)
        layout.setContentsMargins(22, 22, 22, 22)

        title = QLabel("External Tools Setup")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2196F3;")
        layout.addWidget(title)

        info = QLabel(
            "PDF Import via Audiveris OMR requires Java 11+ and the Audiveris JAR.\n"
            "PDF Export requires MuseScore 3 or 4.\n\n"
            "  Java:       java.com  (or Adoptium / OpenJDK)\n"
            "  Audiveris:  github.com/Audiveris/audiveris/releases\n"
            "  MuseScore:  musescore.org"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #444; font-size: 12px;")
        layout.addWidget(info)

        # Java section
        java_box = QGroupBox("Java Executable")
        java_bl = QVBoxLayout()
        auto_java = find_java_executable()
        self._auto_java = auto_java
        self.java_status_lbl = QLabel(
            f"✓ Auto-detected: {auto_java}" if auto_java
            else "✗ Not found — browse to java.exe or install Java 11+"
        )
        self.java_status_lbl.setWordWrap(True)
        self.java_status_lbl.setStyleSheet(
            "color: #4CAF50; font-size: 11px; font-weight: bold;" if auto_java
            else "color: #f44336; font-size: 11px; font-weight: bold;"
        )
        java_bl.addWidget(self.java_status_lbl)

        java_path_row = QHBoxLayout()
        self.java_edit = QLineEdit(current_java or "")
        self.java_edit.setPlaceholderText("Leave blank for auto-detect, or browse to java.exe")
        java_path_row.addWidget(self.java_edit)
        java_browse_btn = QPushButton("Browse…")
        java_browse_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 6px 12px;")
        java_browse_btn.clicked.connect(self._browse_java)
        java_path_row.addWidget(java_browse_btn)
        java_bl.addLayout(java_path_row)

        recheck_btn = QPushButton("Re-scan for Java")
        recheck_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 4px 10px; font-size: 11px;")
        recheck_btn.setFixedWidth(130)
        recheck_btn.clicked.connect(self._recheck_java)
        java_bl.addWidget(recheck_btn)
        java_box.setLayout(java_bl)
        layout.addWidget(java_box)

        # Audiveris JAR
        jar_box = QGroupBox("Audiveris JAR")
        jar_l = QHBoxLayout()
        self.jar_edit = QLineEdit(current_jar or "")
        self.jar_edit.setPlaceholderText(r"e.g. C:\tools\Audiveris-5.3.1.jar")
        jar_l.addWidget(self.jar_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 6px 12px;")
        browse_btn.clicked.connect(self._browse_jar)
        jar_l.addWidget(browse_btn)
        jar_box.setLayout(jar_l)
        layout.addWidget(jar_box)

        # MuseScore
        mscore_box = QGroupBox("MuseScore Executable (for PDF export)")
        mscore_bl = QVBoxLayout()
        auto_mscore = find_musescore_executable()
        self._auto_mscore = auto_mscore
        self.mscore_status_lbl = QLabel(
            f"Auto-detected: {auto_mscore}" if auto_mscore
            else "Not found — browse to MuseScore4.exe or install MuseScore"
        )
        self.mscore_status_lbl.setWordWrap(True)
        self.mscore_status_lbl.setStyleSheet(
            "color: #4CAF50; font-size: 11px; font-weight: bold;" if auto_mscore
            else "color: #f44336; font-size: 11px; font-weight: bold;"
        )
        mscore_bl.addWidget(self.mscore_status_lbl)

        mscore_path_row = QHBoxLayout()
        self.mscore_edit = QLineEdit(current_mscore or "")
        self.mscore_edit.setPlaceholderText("Leave blank for auto-detect, or browse to the .exe")
        mscore_path_row.addWidget(self.mscore_edit)
        ms_browse_btn = QPushButton("Browse...")
        ms_browse_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 6px 12px;")
        ms_browse_btn.clicked.connect(self._browse_mscore)
        mscore_path_row.addWidget(ms_browse_btn)
        mscore_bl.addLayout(mscore_path_row)

        ms_rescan_btn = QPushButton("Re-scan for MuseScore")
        ms_rescan_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 4px 10px; font-size: 11px;")
        ms_rescan_btn.setFixedWidth(160)
        ms_rescan_btn.clicked.connect(self._recheck_mscore)
        mscore_bl.addWidget(ms_rescan_btn)
        mscore_box.setLayout(mscore_bl)
        layout.addWidget(mscore_box)

        # Buttons
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #ddd;")
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background-color: #9E9E9E; color: white; padding: 8px 20px; font-size: 12px;")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px 24px; font-size: 12px; font-weight: bold;")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def _recheck_java(self) -> None:
        auto = find_java_executable()
        self._auto_java = auto
        self.java_status_lbl.setText(
            f"✓ Auto-detected: {auto}" if auto
            else "✗ Not found — browse to java.exe or install Java 11+"
        )
        self.java_status_lbl.setStyleSheet(
            "color: #4CAF50; font-size: 11px; font-weight: bold;" if auto
            else "color: #f44336; font-size: 11px; font-weight: bold;"
        )

    def _browse_java(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select java.exe", "C:/Program Files", "Executable (java.exe java);;All Files (*)")
        if p:
            self.java_edit.setText(p)

    def _browse_jar(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select Audiveris JAR", "", "JAR files (*.jar);;All Files (*)")
        if p:
            self.jar_edit.setText(p)

    def _browse_mscore(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Select MuseScore executable", "C:/Program Files", "Executable (*.exe);;All Files (*)")
        if p:
            self.mscore_edit.setText(p)

    def _recheck_mscore(self) -> None:
        auto = find_musescore_executable()
        self._auto_mscore = auto
        self.mscore_status_lbl.setText(
            f"Auto-detected: {auto}" if auto
            else "Not found — browse to MuseScore4.exe or install MuseScore"
        )
        self.mscore_status_lbl.setStyleSheet(
            "color: #4CAF50; font-size: 11px; font-weight: bold;" if auto
            else "color: #f44336; font-size: 11px; font-weight: bold;"
        )

    def _save(self) -> None:
        jar = self.jar_edit.text().strip()
        java = self.java_edit.text().strip()
        mscore = self.mscore_edit.text().strip()

        if jar and not Path(jar).exists():
            QMessageBox.warning(self, "File Not Found", f"The Audiveris JAR was not found:\n{jar}")
            return
        if java and not Path(java).exists():
            QMessageBox.warning(self, "File Not Found", f"The Java executable was not found:\n{java}")
            return
        if mscore and not Path(mscore).exists():
            QMessageBox.warning(self, "File Not Found", f"The MuseScore executable was not found:\n{mscore}")
            return

        resolved_java = java or self._auto_java or None
        resolved_mscore = mscore or self._auto_mscore or None

        if not resolved_java:
            reply = QMessageBox.question(
                self, "Java Not Found",
                "No Java executable was found.\n\nPDF import will fail without Java 11+.\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        self.selected_jar = jar or None
        self.selected_java = resolved_java
        self.selected_mscore = resolved_mscore

        cfg = load_settings()
        cfg["audiveris_jar"] = self.selected_jar
        cfg["java_exe"] = self.selected_java
        cfg["musescore_exe"] = self.selected_mscore
        save_settings(cfg)
        self.accept()


class OctaveEditorDialog(QDialog):
    """Visual note editor for octave and cross-part voicing fixes."""

    class StaffNoteItem(QGraphicsEllipseItem):
        """Clickable notehead bound to an editable score event/pitch."""

        def __init__(
            self,
            x: float,
            y: float,
            width: float,
            height: float,
            part_label: str,
            source_measure: stream.Measure,
            event_obj: Any,
            pitch_obj: Any,
            measure_num: int,
            beat: float,
            duration_ql: float,
            pitch_text: str,
        ) -> None:
            super().__init__(x, y, width, height)
            self.part_label = part_label
            self.source_measure = source_measure
            self.event_obj = event_obj
            self.pitch_obj = pitch_obj
            self.measure_num = measure_num
            self.beat = beat
            self.duration_ql = duration_ql
            self.pitch_text = pitch_text
            self.setFlag(QGraphicsItem.ItemIsSelectable, True)
            self.setFlag(QGraphicsItem.ItemIsFocusable, True)
            self.setZValue(10)
            self._apply_style(False)

        def _apply_style(self, selected: bool) -> None:
            if selected:
                self.setBrush(Qt.yellow)
                self.setPen(Qt.black)
            else:
                self.setBrush(Qt.black)
                self.setPen(Qt.black)

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.LeftButton:
                self.setSelected(not self.isSelected())
                event.accept()
                return
            super().mousePressEvent(event)

    def __init__(self, musicxml_path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.musicxml_path = musicxml_path
        self.score: Optional[stream.Score] = None
        self.part_map: Dict[str, stream.Part] = {}
        self.active_part_label: str = ""
        self._selection_by_part: Dict[str, Set[Tuple[int, float, int]]] = {}
        self._suspend_selection_updates = False
        self.undo_stack: List[Dict[str, Any]] = []
        self.redo_stack: List[Dict[str, Any]] = []
        self.max_history = 50
        self.note_items: List[OctaveEditorDialog.StaffNoteItem] = []
        self.copy_btn: Optional[QPushButton] = None
        self.move_btn: Optional[QPushButton] = None
        self.undo_btn: Optional[QPushButton] = None
        self.redo_btn: Optional[QPushButton] = None
        self.setWindowTitle("Visual Octave + Voicing Editor")
        self.setModal(True)
        self.resize(1180, 790)
        self._init_ui()
        self._load_score()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(10)

        title = QLabel("Visual Octave + Voicing Editor")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2196F3;")
        layout.addWidget(title)

        hint = QLabel(
            "Select notes directly on the staff. Use +8va/-8va for octave edits, "
            "or move/copy selected notes to another part for voicing corrections. "
            "Rubber-band phrase selections persist while you keep editing."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(hint)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Edit Part:"))
        self.part_combo = QComboBox()
        self.part_combo.currentTextChanged.connect(self._on_part_changed)
        top_row.addWidget(self.part_combo, 2)
        top_row.addWidget(QLabel("Move/Copy To:"))
        self.target_part_combo = QComboBox()
        top_row.addWidget(self.target_part_combo, 2)
        top_row.addWidget(QLabel("Measures:"))
        self.measure_edit = QLineEdit()
        self.measure_edit.setPlaceholderText("e.g. 21-23, 53, 80-83")
        self.measure_edit.textChanged.connect(self._refresh_note_list)
        top_row.addWidget(self.measure_edit, 3)
        layout.addLayout(top_row)

        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._update_selection_summary)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view.setStyleSheet("background-color: white; border: 1px solid #ddd;")
        layout.addWidget(self.view, 1)

        self.status_box = QPlainTextEdit()
        self.status_box.setReadOnly(True)
        self.status_box.setMaximumHeight(90)
        self.status_box.setStyleSheet("background-color: #fafafa; color: #333; font-family: monospace; font-size: 11px;")
        layout.addWidget(self.status_box)

        self.selection_label = QLabel("No notes selected")
        self.selection_label.setWordWrap(True)
        self.selection_label.setStyleSheet("color: #444; font-size: 11px;")
        layout.addWidget(self.selection_label)

        btn_row = QHBoxLayout()
        raise_btn = QPushButton("+8va Selected")
        raise_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px 16px;")
        raise_btn.clicked.connect(self._raise_selected)
        btn_row.addWidget(raise_btn)

        lower_btn = QPushButton("-8va Selected")
        lower_btn.setStyleSheet("background-color: #455A64; color: white; padding: 8px 16px;")
        lower_btn.clicked.connect(self._lower_selected)
        btn_row.addWidget(lower_btn)

        self.copy_btn = QPushButton("Copy To Part")
        self.copy_btn.setStyleSheet("background-color: #6A1B9A; color: white; padding: 8px 16px;")
        self.copy_btn.clicked.connect(lambda: self._transfer_selected(move=False))
        btn_row.addWidget(self.copy_btn)

        self.move_btn = QPushButton("Move To Part")
        self.move_btn.setStyleSheet("background-color: #8E24AA; color: white; padding: 8px 16px;")
        self.move_btn.clicked.connect(lambda: self._transfer_selected(move=True))
        btn_row.addWidget(self.move_btn)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.setStyleSheet("background-color: #C62828; color: white; padding: 8px 16px;")
        delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(delete_btn)

        select_all_btn = QPushButton("Select Visible")
        select_all_btn.setStyleSheet("background-color: #546E7A; color: white; padding: 8px 16px;")
        select_all_btn.clicked.connect(self._select_visible)
        btn_row.addWidget(select_all_btn)

        clear_sel_btn = QPushButton("Clear Selection")
        clear_sel_btn.setStyleSheet("background-color: #8D6E63; color: white; padding: 8px 16px;")
        clear_sel_btn.clicked.connect(self._clear_selection)
        btn_row.addWidget(clear_sel_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet("background-color: #607D8B; color: white; padding: 8px 16px;")
        refresh_btn.clicked.connect(self._refresh_note_list)
        btn_row.addWidget(refresh_btn)

        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setStyleSheet("background-color: #3949AB; color: white; padding: 8px 16px;")
        self.undo_btn.clicked.connect(self._undo)
        btn_row.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("Redo")
        self.redo_btn.setStyleSheet("background-color: #5C6BC0; color: white; padding: 8px 16px;")
        self.redo_btn.clicked.connect(self._redo)
        btn_row.addWidget(self.redo_btn)

        btn_row.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 18px;")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background-color: #9E9E9E; color: white; padding: 8px 18px;")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        self.setLayout(layout)
        self._update_history_buttons()

    def _log(self, text: str) -> None:
        self.status_box.appendPlainText(text)

    def _note_item_key(self, item: "OctaveEditorDialog.StaffNoteItem") -> Tuple[int, float, int]:
        return (item.measure_num, round(float(item.beat), 6), int(item.pitch_obj.midi))

    def _capture_selection(self, part_label: Optional[str] = None) -> None:
        label = part_label or self.part_combo.currentText()
        if not label:
            return
        keys = {self._note_item_key(item) for item in self.note_items if item.isSelected()}
        self._selection_by_part[label] = keys

    def _restore_selection(self, part_label: str) -> None:
        saved = self._selection_by_part.get(part_label, set())
        if not saved:
            return
        self._suspend_selection_updates = True
        self.scene.blockSignals(True)
        try:
            for item in self.note_items:
                item.setSelected(self._note_item_key(item) in saved)
        finally:
            self.scene.blockSignals(False)
            self._suspend_selection_updates = False

    def _snapshot_state(self, action: str) -> Dict[str, Any]:
        if self.score is None:
            return {}
        self._capture_selection(self.part_combo.currentText())
        return {
            "action": action,
            "score": copy.deepcopy(self.score),
            "selection": copy.deepcopy(self._selection_by_part),
            "active_part": self.part_combo.currentText(),
            "target_part": self.target_part_combo.currentText(),
            "measure_filter": self.measure_edit.text(),
        }

    def _push_undo_snapshot(self, action: str) -> None:
        snap = self._snapshot_state(action)
        if not snap:
            return
        self.undo_stack.append(snap)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack = self.undo_stack[-self.max_history:]
        self.redo_stack.clear()
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        if self.undo_btn is not None:
            self.undo_btn.setEnabled(bool(self.undo_stack))
        if self.redo_btn is not None:
            self.redo_btn.setEnabled(bool(self.redo_stack))

    def _restore_snapshot(self, snap: Dict[str, Any]) -> None:
        if not snap:
            return
        restored_score = snap.get("score")
        if restored_score is None:
            return
        self.score = copy.deepcopy(restored_score)
        self._selection_by_part = copy.deepcopy(snap.get("selection", {}))
        preferred_part = snap.get("active_part", "")
        preferred_target = snap.get("target_part", "")
        measure_filter = snap.get("measure_filter", "")
        self._populate_part_controls(preferred_current=preferred_part, preferred_target=preferred_target)
        self.measure_edit.blockSignals(True)
        self.measure_edit.setText(measure_filter)
        self.measure_edit.blockSignals(False)
        self._refresh_note_list()

    def _undo(self) -> None:
        if not self.undo_stack:
            return
        current = self._snapshot_state("redo")
        snap = self.undo_stack.pop()
        if current:
            self.redo_stack.append(current)
            if len(self.redo_stack) > self.max_history:
                self.redo_stack = self.redo_stack[-self.max_history:]
        self._restore_snapshot(snap)
        self._log(f"Undo: {snap.get('action', 'edit')}")
        self._update_history_buttons()

    def _redo(self) -> None:
        if not self.redo_stack:
            return
        current = self._snapshot_state("undo")
        snap = self.redo_stack.pop()
        if current:
            self.undo_stack.append(current)
            if len(self.undo_stack) > self.max_history:
                self.undo_stack = self.undo_stack[-self.max_history:]
        self._restore_snapshot(snap)
        self._log(f"Redo: {snap.get('action', 'edit')}")
        self._update_history_buttons()

    def _populate_part_controls(
        self,
        preferred_current: Optional[str] = None,
        preferred_target: Optional[str] = None,
    ) -> None:
        self.part_map = {}
        self.part_combo.blockSignals(True)
        self.part_combo.clear()
        if self.score is None:
            self.part_combo.blockSignals(False)
            self.target_part_combo.clear()
            self.active_part_label = ""
            return
        for i, part in enumerate(self.score.parts):
            base_label = part.partName or f"Part {i + 1}"
            label = base_label
            suffix = 2
            while label in self.part_map:
                label = f"{base_label} ({suffix})"
                suffix += 1
            self.part_map[label] = part
            self.part_combo.addItem(label)
        if preferred_current and preferred_current in self.part_map:
            self.part_combo.setCurrentText(preferred_current)
        elif self.part_combo.count() > 0:
            self.part_combo.setCurrentIndex(0)
        self.part_combo.blockSignals(False)
        self.active_part_label = self.part_combo.currentText()
        self._refresh_target_parts()
        if preferred_target:
            idx = self.target_part_combo.findText(preferred_target)
            if idx >= 0:
                self.target_part_combo.setCurrentIndex(idx)

    def _load_score(self) -> None:
        self.score = converter.parse(self.musicxml_path)
        self._populate_part_controls()
        self._log(f"Loaded: {Path(self.musicxml_path).name}")
        self._refresh_note_list()

    def _on_part_changed(self) -> None:
        if self.active_part_label:
            self._capture_selection(self.active_part_label)
        self.active_part_label = self.part_combo.currentText()
        self._refresh_target_parts()
        self._refresh_note_list()

    def _refresh_target_parts(self) -> None:
        current = self.part_combo.currentText()
        self.target_part_combo.blockSignals(True)
        self.target_part_combo.clear()
        for label in self.part_map:
            if label != current:
                self.target_part_combo.addItem(label)
        self.target_part_combo.blockSignals(False)
        has_other = self.target_part_combo.count() > 0
        if self.copy_btn is not None:
            self.copy_btn.setEnabled(has_other)
        if self.move_btn is not None:
            self.move_btn.setEnabled(has_other)

    def _parse_measure_filter(self) -> Optional[set]:
        text = self.measure_edit.text().strip()
        if not text:
            return None
        result = set()
        for chunk in [c.strip() for c in text.split(",") if c.strip()]:
            if "-" in chunk:
                try:
                    start_s, end_s = chunk.split("-", 1)
                    start = int(start_s.strip())
                    end = int(end_s.strip())
                except ValueError:
                    continue
                if end < start:
                    start, end = end, start
                result.update(range(start, end + 1))
            else:
                try:
                    result.add(int(chunk))
                except ValueError:
                    continue
        return result

    def _refresh_note_list(self) -> None:
        if self.active_part_label and self.note_items:
            self._capture_selection(self.active_part_label)
        self.scene.clear()
        self.note_items = []
        part_label = self.part_combo.currentText()
        self.active_part_label = part_label
        part = self.part_map.get(part_label)
        if not part:
            return

        allowed_measures = self._parse_measure_filter()
        measures = []
        for measure in part.getElementsByClass(stream.Measure):
            if allowed_measures is not None and measure.number not in allowed_measures:
                continue
            measures.append(measure)

        if not measures:
            self._log("No measures matched the current filter")
            self.selection_label.setText("No notes selected")
            return

        part_midis = [
            n.pitch.midi
            for n in part.recurse().notes
            if hasattr(n, "pitch")
        ]
        center_midi = int(sum(part_midis) / len(part_midis)) if part_midis else 67

        measure_width = 220
        measure_height = 170
        measures_per_row = 4
        x_margin = 28
        y_margin = 24
        self.scene.setBackgroundBrush(Qt.white)

        for idx, measure in enumerate(measures):
            col = idx % measures_per_row
            row = idx // measures_per_row
            origin_x = col * measure_width
            origin_y = row * measure_height
            self._draw_measure(
                part_label=part_label,
                measure=measure,
                origin_x=origin_x,
                origin_y=origin_y,
                measure_width=measure_width,
                measure_height=measure_height,
                center_midi=center_midi,
                x_margin=x_margin,
                y_margin=y_margin,
            )

        rows = (len(measures) + measures_per_row - 1) // measures_per_row
        self.scene.setSceneRect(0, 0, measures_per_row * measure_width, rows * measure_height)
        self._restore_selection(part_label)
        self._log(f"Showing {len(measures)} measure(s), {len(self.note_items)} selectable note(s)")
        self._update_selection_summary()

    def _draw_measure(
        self,
        part_label: str,
        measure: stream.Measure,
        origin_x: float,
        origin_y: float,
        measure_width: float,
        measure_height: float,
        center_midi: int,
        x_margin: float,
        y_margin: float,
    ) -> None:
        staff_top = origin_y + y_margin + 28
        staff_spacing = 12
        staff_left = origin_x + x_margin
        staff_right = origin_x + measure_width - x_margin
        note_area_width = staff_right - staff_left - 12

        label = QGraphicsSimpleTextItem(f"M{measure.number}")
        label.setPos(origin_x + 8, origin_y + 4)
        self.scene.addItem(label)

        for i in range(5):
            y = staff_top + i * staff_spacing
            line = QGraphicsLineItem(staff_left, y, staff_right, y)
            self.scene.addItem(line)

        bar = QGraphicsLineItem(staff_right, staff_top, staff_right, staff_top + 4 * staff_spacing)
        self.scene.addItem(bar)

        try:
            bar_ql = float(measure.barDuration.quarterLength or 4.0)
        except Exception:
            bar_ql = 4.0
        if bar_ql <= 0:
            bar_ql = 4.0

        center_y = staff_top + 2 * staff_spacing
        for el in measure.notes:
            if hasattr(el, "pitches"):
                pitches = list(el.pitches)
            else:
                pitches = [el.pitch]
            if not pitches:
                continue

            x = staff_left + 8 + (float(el.offset) / bar_ql) * note_area_width
            pitch_text = ".".join(p.nameWithOctave for p in pitches)
            duration_ql = float(getattr(el.duration, "quarterLength", 1.0) or 1.0)
            for p_idx, p in enumerate(sorted(pitches, key=lambda pitch: pitch.midi, reverse=True)):
                y = center_y - (p.midi - center_midi) * 3.0 + p_idx * 3
                note_item = self.StaffNoteItem(
                    x=x,
                    y=y,
                    width=12,
                    height=8,
                    part_label=part_label,
                    source_measure=measure,
                    event_obj=el,
                    pitch_obj=p,
                    measure_num=measure.number,
                    beat=float(el.offset),
                    duration_ql=duration_ql,
                    pitch_text=pitch_text,
                )
                self.scene.addItem(note_item)
                self.note_items.append(note_item)

                stem = QGraphicsLineItem(x + 10, y + 4, x + 10, y - 24)
                self.scene.addItem(stem)

    def _selected_note_items(self) -> List["OctaveEditorDialog.StaffNoteItem"]:
        selected = [item for item in self.note_items if item.isSelected()]
        unique = []
        seen = set()
        for item in selected:
            key = (id(item.event_obj), id(item.pitch_obj), item.measure_num, round(item.beat, 6))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _copy_event_metadata(self, source_event: Any, dest_event: Any, fallback_duration: float) -> None:
        try:
            dest_event.duration = copy.deepcopy(source_event.duration)
        except Exception:
            dest_event.duration.quarterLength = fallback_duration
        if hasattr(source_event, "tie") and getattr(source_event, "tie", None) is not None:
            try:
                dest_event.tie = copy.deepcopy(source_event.tie)
            except Exception:
                pass
        try:
            dest_event.articulations = [copy.deepcopy(a) for a in getattr(source_event, "articulations", [])]
        except Exception:
            pass
        try:
            dest_event.expressions = [copy.deepcopy(e) for e in getattr(source_event, "expressions", [])]
        except Exception:
            pass

    def _get_or_create_measure(
        self,
        part: stream.Part,
        measure_num: int,
        source_measure: Optional[stream.Measure] = None,
    ) -> stream.Measure:
        for measure in part.getElementsByClass(stream.Measure):
            if measure.number == measure_num:
                return measure

        new_measure = stream.Measure(number=measure_num)
        if source_measure is not None:
            for ts in source_measure.getElementsByClass("TimeSignature"):
                new_measure.insert(ts.offset, copy.deepcopy(ts))
            for ks in source_measure.getElementsByClass("KeySignature"):
                new_measure.insert(ks.offset, copy.deepcopy(ks))
        part.append(new_measure)
        return new_measure

    def _event_at_offset(self, measure: stream.Measure, offset: float) -> Optional[Any]:
        for el in measure.notesAndRests:
            if not isinstance(el, (note.Note, chord.Chord)):
                continue
            if abs(float(el.offset) - offset) <= 1e-4:
                return el
        return None

    def _insert_selected_pitch(self, item: "OctaveEditorDialog.StaffNoteItem", dest_part: stream.Part) -> bool:
        pitch_midi = int(item.pitch_obj.midi)
        dest_measure = self._get_or_create_measure(dest_part, item.measure_num, item.source_measure)
        existing = self._event_at_offset(dest_measure, item.beat)

        if isinstance(existing, note.Note):
            if existing.pitch.midi == pitch_midi:
                return False
            new_chord = chord.Chord([copy.deepcopy(existing.pitch), copy.deepcopy(item.pitch_obj)])
            self._copy_event_metadata(existing, new_chord, item.duration_ql)
            dest_measure.remove(existing)
            dest_measure.insert(item.beat, new_chord)
            return True

        if isinstance(existing, chord.Chord):
            existing_midis = [p.midi for p in existing.pitches]
            if pitch_midi in existing_midis:
                return False
            new_pitches = [copy.deepcopy(p) for p in existing.pitches] + [copy.deepcopy(item.pitch_obj)]
            new_chord = chord.Chord(new_pitches)
            self._copy_event_metadata(existing, new_chord, item.duration_ql)
            dest_measure.remove(existing)
            dest_measure.insert(item.beat, new_chord)
            return True

        new_note = note.Note(copy.deepcopy(item.pitch_obj))
        self._copy_event_metadata(item.event_obj, new_note, item.duration_ql)
        dest_measure.insert(item.beat, new_note)
        return True

    def _remove_pitch_group(
        self,
        source_measure: stream.Measure,
        source_event: Any,
        offset: float,
        midi_values: set,
    ) -> int:
        event = source_event
        if event not in source_measure.notesAndRests:
            event = self._event_at_offset(source_measure, offset)
            if event is None:
                return 0

        if isinstance(event, note.Note):
            if event.pitch.midi in midi_values:
                source_measure.remove(event)
                return 1
            return 0

        if isinstance(event, chord.Chord):
            old_pitches = list(event.pitches)
            remaining = [copy.deepcopy(p) for p in old_pitches if p.midi not in midi_values]
            removed = len(old_pitches) - len(remaining)
            if removed <= 0:
                return 0
            source_measure.remove(event)
            if len(remaining) == 1:
                new_note = note.Note(remaining[0])
                self._copy_event_metadata(event, new_note, float(event.duration.quarterLength or 1.0))
                source_measure.insert(offset, new_note)
            elif len(remaining) > 1:
                new_chord = chord.Chord(remaining)
                self._copy_event_metadata(event, new_chord, float(event.duration.quarterLength or 1.0))
                source_measure.insert(offset, new_chord)
            return removed
        return 0

    def _shift_selected(self, semitones: int) -> None:
        items = self._selected_note_items()
        if not items:
            QMessageBox.information(self, "No Selection", "Select one or more notes first.")
            return
        action = "+8va" if semitones > 0 else "-8va"
        self._push_undo_snapshot(action)
        changed = 0
        seen_pitches = set()
        for item in items:
            key = id(item.pitch_obj)
            if key in seen_pitches:
                continue
            seen_pitches.add(key)
            item.pitch_obj.midi = max(0, min(127, item.pitch_obj.midi + semitones))
            changed += 1
        current = self.part_combo.currentText()
        self._selection_by_part[current] = {self._note_item_key(item) for item in items}
        self._log(f"{action} applied to {changed} selected note(s)")
        self._refresh_note_list()

    def _raise_selected(self) -> None:
        self._shift_selected(12)

    def _lower_selected(self) -> None:
        self._shift_selected(-12)

    def _transfer_selected(self, move: bool) -> None:
        items = self._selected_note_items()
        if not items:
            QMessageBox.information(self, "No Selection", "Select one or more notes first.")
            return
        source_label = self.part_combo.currentText()
        dest_label = self.target_part_combo.currentText()
        if not dest_label:
            QMessageBox.information(self, "No Destination", "Select a destination part for voicing changes.")
            return
        if source_label == dest_label:
            QMessageBox.warning(self, "Invalid Destination", "Choose a different destination part.")
            return

        dest_part = self.part_map.get(dest_label)
        if dest_part is None:
            QMessageBox.warning(self, "Invalid Destination", "Could not resolve destination part.")
            return
        self._push_undo_snapshot(f"{'Move' if move else 'Copy'} to {dest_label}")

        inserted = 0
        grouped_for_removal: Dict[int, Dict[str, Any]] = {}
        for item in items:
            if self._insert_selected_pitch(item, dest_part):
                inserted += 1
                if move:
                    key = id(item.event_obj)
                    group = grouped_for_removal.setdefault(
                        key,
                        {
                            "measure": item.source_measure,
                            "event": item.event_obj,
                            "offset": item.beat,
                            "midis": set(),
                        },
                    )
                    group["midis"].add(int(item.pitch_obj.midi))

        removed = 0
        if move:
            for group in grouped_for_removal.values():
                removed += self._remove_pitch_group(
                    source_measure=group["measure"],
                    source_event=group["event"],
                    offset=group["offset"],
                    midi_values=group["midis"],
                )

        action = "Moved" if move else "Copied"
        self._log(f"{action} {inserted} selected note(s) from '{source_label}' to '{dest_label}'")
        if move:
            self._log(f"Removed {removed} source note(s) from '{source_label}'")
            self._selection_by_part[source_label] = set()
        else:
            self._selection_by_part[source_label] = {self._note_item_key(item) for item in items}
        moved_keys = {
            (item.measure_num, round(float(item.beat), 6), int(item.pitch_obj.midi))
            for item in items
        }
        existing_dest = set(self._selection_by_part.get(dest_label, set()))
        self._selection_by_part[dest_label] = existing_dest | moved_keys
        self._refresh_note_list()

    def _delete_selected(self) -> None:
        items = self._selected_note_items()
        if not items:
            QMessageBox.information(self, "No Selection", "Select one or more notes first.")
            return
        self._push_undo_snapshot("Delete selected notes")
        grouped: Dict[int, Dict[str, Any]] = {}
        for item in items:
            key = id(item.event_obj)
            group = grouped.setdefault(
                key,
                {"measure": item.source_measure, "event": item.event_obj, "offset": item.beat, "midis": set()},
            )
            group["midis"].add(int(item.pitch_obj.midi))

        removed = 0
        for group in grouped.values():
            removed += self._remove_pitch_group(
                source_measure=group["measure"],
                source_event=group["event"],
                offset=group["offset"],
                midi_values=group["midis"],
            )
        current = self.part_combo.currentText()
        self._selection_by_part[current] = set()
        self._log(f"Deleted {removed} selected note(s)")
        self._refresh_note_list()

    def _select_visible(self) -> None:
        for item in self.note_items:
            item.setSelected(True)
        self._update_selection_summary()

    def _clear_selection(self) -> None:
        self.scene.clearSelection()
        self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        if self._suspend_selection_updates:
            return
        selected = self._selected_note_items()
        current = self.part_combo.currentText()
        if current:
            self._selection_by_part[current] = {self._note_item_key(item) for item in selected}
        for item in self.note_items:
            item._apply_style(item.isSelected())
        if not selected:
            self.selection_label.setText("No notes selected")
            return
        preview = ", ".join(
            f"M{item.measure_num} beat {item.beat:.2f} {item.pitch_obj.nameWithOctave}"
            for item in selected[:6]
        )
        if len(selected) > 6:
            preview += f", ... ({len(selected)} selected)"
        self.selection_label.setText(preview)

    def _save(self) -> None:
        if not self.score:
            return
        self.score.write("musicxml", fp=self.musicxml_path)
        self._log(f"Saved: {Path(self.musicxml_path).name}")
        QMessageBox.information(self, "Saved", f"Saved changes to:\n{Path(self.musicxml_path).name}")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN GUI
# ═══════════════════════════════════════════════════════════════════════

class ScoreArranger(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.input_path: Optional[str] = None
        self.thread: Optional[ConversionThread] = None
        self.last_output_path: Optional[str] = None
        self.editor_btn: Optional[QPushButton] = None
        self.source_part_list: Optional[QListWidget] = None
        cfg = load_settings()
        self.audiveris_jar: Optional[str] = cfg.get("audiveris_jar")
        self.audiveris_java: Optional[str] = cfg.get("java_exe")
        self.musescore_exe: Optional[str] = cfg.get("musescore_exe")
        self.initUI()

    def initUI(self) -> None:
        self.setWindowTitle("🎺 Brass Ensemble Transcriber v6.0")
        screen = QApplication.primaryScreen().geometry()
        w, h = 720, 800
        self.setGeometry((screen.width() - w) // 2, (screen.height() - h) // 2, w, h)

        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; }
            QPushButton {
                background-color: #4CAF50; color: white; border: none;
                padding: 10px; border-radius: 5px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #ccc; color: #888; }
            QPushButton#goBtn { background-color: #2196F3; padding: 14px; font-size: 15px; }
            QPushButton#goBtn:hover { background-color: #0b7dda; }
            QGroupBox {
                font-weight: bold; border: 2px solid #ddd;
                border-radius: 5px; margin-top: 10px; padding-top: 10px;
            }
            QComboBox, QLineEdit { padding: 8px; font-size: 13px; }
            QListWidget { font-size: 12px; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        # Title
        title = QLabel("🎺 Brass Ensemble Transcriber")
        title.setStyleSheet("color: #2196F3; font-size: 22px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("Arrange any score for brass trio, quartet, quintet · trumpet quartet through septet")
        sub.setStyleSheet("color: #666; font-size: 11px; font-style: italic;")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        # 1. Input file
        g1 = QGroupBox("1. Input Score")
        g1l = QVBoxLayout()
        file_row = QHBoxLayout()
        self.select_btn = QPushButton("📁 Choose File")
        self.select_btn.clicked.connect(self.select_file)
        file_row.addWidget(self.select_btn)
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("color: #666; font-style: italic;")
        file_row.addWidget(self.file_label, 1)
        g1l.addLayout(file_row)

        pdf_row = QHBoxLayout()
        self.pdf_status_label = QLabel(self._pdf_status_text())
        self.pdf_status_label.setStyleSheet("color: #888; font-size: 10px;")
        pdf_row.addWidget(self.pdf_status_label, 1)
        self.pdf_setup_btn = QPushButton("⚙ PDF Setup")
        self.pdf_setup_btn.setStyleSheet("""
            QPushButton {
                background-color: #607D8B; color: white; border: none;
                padding: 4px 10px; border-radius: 4px; font-size: 11px;
            }
            QPushButton:hover { background-color: #455A64; }
        """)
        self.pdf_setup_btn.setFixedHeight(26)
        self.pdf_setup_btn.clicked.connect(self.open_audiveris_setup)
        pdf_row.addWidget(self.pdf_setup_btn)
        g1l.addLayout(pdf_row)
        g1.setLayout(g1l)
        layout.addWidget(g1)

        # 2. Target instruments
        g2 = QGroupBox("2. Target Arrangement")
        g2l = QVBoxLayout()

        # Mode tabs
        mode_row = QHBoxLayout()
        self.mode_tabs = QButtonGroup()
        for i, label in enumerate(["Presets", "Pick Instruments", "Type It"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet("""
                QPushButton { background-color: #e0e0e0; color: #333; padding: 8px 16px; }
                QPushButton:checked { background-color: #2196F3; color: white; }
                QPushButton:hover { background-color: #bbdefb; }
            """)
            self.mode_tabs.addButton(btn, i)
            mode_row.addWidget(btn)
        self.mode_tabs.button(0).setChecked(True)
        self.mode_tabs.idClicked.connect(self._switch_mode)
        g2l.addLayout(mode_row)

        # Mode stack
        self.mode_stack = QStackedWidget()

        # Mode 0: Presets
        preset_w = QWidget()
        preset_l = QVBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(ENSEMBLE_PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._update_preset_desc)
        preset_l.addWidget(self.preset_combo)
        self.preset_desc = QLabel()
        self.preset_desc.setStyleSheet("color: #555; font-size: 11px; font-style: italic;")
        self.preset_desc.setWordWrap(True)
        preset_l.addWidget(self.preset_desc)
        preset_w.setLayout(preset_l)
        self._update_preset_desc(self.preset_combo.currentText())
        self.mode_stack.addWidget(preset_w)

        # Mode 1: Pick
        pick_w = QWidget()
        pick_l = QHBoxLayout()
        avail_col = QVBoxLayout()
        avail_col.addWidget(QLabel("Available:"))
        self.avail_list = QListWidget()
        self.avail_list.setSelectionMode(QAbstractItemView.SingleSelection)
        for inst in INSTRUMENT_DB:
            self.avail_list.addItem(inst)
        avail_col.addWidget(self.avail_list)
        pick_l.addLayout(avail_col)

        btn_col = QVBoxLayout()
        btn_col.addStretch()
        add_btn = QPushButton("→ Add")
        add_btn.clicked.connect(self._pick_add)
        add_btn.setStyleSheet("padding: 8px 12px; font-size: 12px;")
        btn_col.addWidget(add_btn)
        rm_btn = QPushButton("← Remove")
        rm_btn.clicked.connect(self._pick_remove)
        rm_btn.setStyleSheet("padding: 8px 12px; font-size: 12px; background-color: #f44336;")
        btn_col.addWidget(rm_btn)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(lambda: self.target_list.clear())
        clear_btn.setStyleSheet("padding: 8px 12px; font-size: 12px; background-color: #ff9800;")
        btn_col.addWidget(clear_btn)
        btn_col.addStretch()
        pick_l.addLayout(btn_col)

        target_col = QVBoxLayout()
        target_col.addWidget(QLabel("Target parts:"))
        self.target_list = QListWidget()
        target_col.addWidget(self.target_list)
        pick_l.addLayout(target_col)
        pick_w.setLayout(pick_l)
        self.mode_stack.addWidget(pick_w)

        # Mode 2: Free text
        text_w = QWidget()
        text_l = QVBoxLayout()
        text_l.addWidget(QLabel("Describe your target arrangement:"))
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText('e.g. "brass quintet", "2 trumpets, trombone, tuba"')
        text_l.addWidget(self.text_input)
        self.text_preview = QLabel()
        self.text_preview.setStyleSheet("color: #555; font-size: 11px;")
        self.text_preview.setWordWrap(True)
        text_l.addWidget(self.text_preview)
        self.text_input.textChanged.connect(self._update_text_preview)
        text_w.setLayout(text_l)
        self.mode_stack.addWidget(text_w)

        g2l.addWidget(self.mode_stack)
        g2.setLayout(g2l)
        layout.addWidget(g2)

        g_parts = QGroupBox("3. Source Parts")
        g_parts_l = QVBoxLayout()
        parts_hint = QLabel("Uncheck any source part you want excluded from the arrangement.")
        parts_hint.setStyleSheet("color: #666; font-size: 11px;")
        g_parts_l.addWidget(parts_hint)

        parts_btn_row = QHBoxLayout()
        include_all_btn = QPushButton("Include All")
        include_all_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 6px 12px; font-size: 11px;")
        include_all_btn.clicked.connect(lambda: self._set_all_source_parts(Qt.Checked))
        parts_btn_row.addWidget(include_all_btn)

        exclude_voices_btn = QPushButton("Exclude All Voices")
        exclude_voices_btn.setStyleSheet("background-color: #E65100; color: white; padding: 6px 12px; font-size: 11px;")
        exclude_voices_btn.clicked.connect(self._exclude_voice_parts)
        parts_btn_row.addWidget(exclude_voices_btn)
        parts_btn_row.addStretch()
        g_parts_l.addLayout(parts_btn_row)

        self.source_part_list = QListWidget()
        self.source_part_list.setMinimumHeight(150)
        g_parts_l.addWidget(self.source_part_list)
        g_parts.setLayout(g_parts_l)
        layout.addWidget(g_parts)

        # 3. Go
        self.go_btn = QPushButton("▶ ARRANGE & SAVE")
        self.go_btn.setObjectName("goBtn")
        self.go_btn.clicked.connect(self.run_arrangement)
        self.go_btn.setEnabled(False)
        self.go_btn.setMinimumHeight(48)
        layout.addWidget(self.go_btn)

        # Export options
        export_row = QHBoxLayout()
        self.midi_check = QCheckBox("Also export MIDI (.mid)")
        self.midi_check.setStyleSheet("font-size: 12px; color: #444;")
        export_row.addWidget(self.midi_check)
        self.pdf_score_check = QCheckBox("Also export PDF (Score)")
        self.pdf_score_check.setStyleSheet("font-size: 12px; color: #444;")
        export_row.addWidget(self.pdf_score_check)
        export_row.addStretch()

        self.midi_btn = QPushButton("Save as MIDI...")
        self.midi_btn.setEnabled(False)
        self.midi_btn.setStyleSheet("background-color: #9C27B0; color: white; border: none; padding: 8px 16px; border-radius: 5px; font-size: 12px; font-weight: bold;")
        self.midi_btn.clicked.connect(self.save_as_midi)
        export_row.addWidget(self.midi_btn)

        self.pdf_score_btn = QPushButton("Save as PDF (Score)...")
        self.pdf_score_btn.setEnabled(False)
        self.pdf_score_btn.setStyleSheet("background-color: #E65100; color: white; border: none; padding: 8px 16px; border-radius: 5px; font-size: 12px; font-weight: bold;")
        self.pdf_score_btn.clicked.connect(self.save_as_pdf_score)
        export_row.addWidget(self.pdf_score_btn)

        self.pdf_parts_btn = QPushButton("Save as PDF (Parts)...")
        self.pdf_parts_btn.setEnabled(False)
        self.pdf_parts_btn.setStyleSheet("background-color: #1565C0; color: white; border: none; padding: 8px 16px; border-radius: 5px; font-size: 12px; font-weight: bold;")
        self.pdf_parts_btn.clicked.connect(self.save_as_pdf_parts)
        export_row.addWidget(self.pdf_parts_btn)

        self.open_editor_btn = QPushButton("Open Existing Score...")
        self.open_editor_btn.setStyleSheet("background-color: #00897B; color: white; border: none; padding: 8px 16px; border-radius: 5px; font-size: 12px; font-weight: bold;")
        self.open_editor_btn.clicked.connect(self.open_existing_for_editor)
        export_row.addWidget(self.open_editor_btn)

        self.editor_btn = QPushButton("Visual Editor...")
        self.editor_btn.setEnabled(False)
        self.editor_btn.setStyleSheet("background-color: #6A1B9A; color: white; border: none; padding: 8px 16px; border-radius: 5px; font-size: 12px; font-weight: bold;")
        self.editor_btn.clicked.connect(self.open_octave_editor)
        export_row.addWidget(self.editor_btn)

        layout.addLayout(export_row)

        # Log
        g3 = QGroupBox("Processing Log")
        g3l = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(170)
        self.log_text.setStyleSheet("background-color: #2b2b2b; color: #00ff00; font-family: monospace; padding: 5px; font-size: 11px;")
        g3l.addWidget(self.log_text)
        g3.setLayout(g3l)
        layout.addWidget(g3)

        info = QLabel("Supports: MusicXML (.xml .musicxml .mxl) · MIDI (.mid) · MuseScore (.mscz) · PDF (.pdf) via Audiveris")
        info.setStyleSheet("color: #999; font-size: 10px;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        central.setLayout(layout)

    # ── GUI helpers ─────────────────────────────────────────────────

    def _switch_mode(self, idx: int) -> None:
        self.mode_stack.setCurrentIndex(idx)

    def _update_preset_desc(self, name: str) -> None:
        instruments = ENSEMBLE_PRESETS.get(name, [])
        self.preset_desc.setText(f"→ {', '.join(instruments)}")

    def _pick_add(self) -> None:
        item = self.avail_list.currentItem()
        if item:
            self.target_list.addItem(item.text())

    def _pick_remove(self) -> None:
        row = self.target_list.currentRow()
        if row >= 0:
            self.target_list.takeItem(row)

    def _update_text_preview(self, text: str) -> None:
        result = parse_free_text(text)
        if result:
            self.text_preview.setText(f"→ {', '.join(result)}")
            self.text_preview.setStyleSheet("color: #4CAF50; font-size: 11px;")
        elif text.strip():
            self.text_preview.setText("⚠ Could not parse — try instrument names separated by commas")
            self.text_preview.setStyleSheet("color: #f44336; font-size: 11px;")
        else:
            self.text_preview.setText("")

    def _get_target_instruments(self) -> Tuple[List[str], Optional[str]]:
        """Return (instrument_list, ensemble_name_or_None)."""
        mode = self.mode_tabs.checkedId()
        if mode == 0:
            name = self.preset_combo.currentText()
            return ENSEMBLE_PRESETS.get(name, []), name
        elif mode == 1:
            instruments = [self.target_list.item(i).text() for i in range(self.target_list.count())]
            matched = next((n for n, insts in ENSEMBLE_PRESETS.items() if insts == instruments), None)
            return instruments, matched
        elif mode == 2:
            text = self.text_input.text().lower().strip()
            result = parse_free_text(text)
            matched = next((n for n, insts in ENSEMBLE_PRESETS.items() if insts == result), None)
            return result or [], matched
        return [], None

    # ── File selection ──────────────────────────────────────────────

    def _set_all_source_parts(self, state: Qt.CheckState) -> None:
        if not self.source_part_list:
            return
        for i in range(self.source_part_list.count()):
            item = self.source_part_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(state)

    def _exclude_voice_parts(self) -> None:
        if not self.source_part_list:
            return
        for i in range(self.source_part_list.count()):
            item = self.source_part_list.item(i)
            families = item.data(Qt.UserRole) or set()
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Unchecked if "voice" in families else Qt.Checked)

    def _populate_source_parts(self, path: str) -> None:
        if not self.source_part_list:
            return
        self.source_part_list.clear()
        if Path(path).suffix.lower() == ".pdf":
            item = QListWidgetItem("Source-part exclusion is unavailable for PDF until after OCR conversion.")
            item.setFlags(Qt.NoItemFlags)
            self.source_part_list.addItem(item)
            return
        try:
            score = converter.parse(path)
        except Exception as e:
            item = QListWidgetItem(f"Could not inspect source parts: {e}")
            item.setFlags(Qt.NoItemFlags)
            self.source_part_list.addItem(item)
            return
        for i, part in enumerate(score.parts):
            name = part.partName or f"Part {i + 1}"
            families = classify_source_part(part)
            label = f"{name} [{', '.join(sorted(families))}]"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, families)
            item.setData(Qt.UserRole + 1, name)
            self.source_part_list.addItem(item)

    def select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Music File", "",
            "Music Files (*.xml *.musicxml *.mxl *.mid *.midi *.mscz *.mscx *.pdf)"
            ";;PDF Scores (*.pdf)"
            ";;All Files (*)"
        )
        if path:
            self.input_path = path
            name = Path(path).name
            self.file_label.setText(f"✓ {name}")
            self.file_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.go_btn.setEnabled(True)
            self.log_msg(f"Selected: {name}")
            self._populate_source_parts(path)

            if Path(path).suffix.lower() == ".pdf" and not self.audiveris_jar:
                reply = QMessageBox.question(
                    self, "PDF Import — Setup Required",
                    "PDF conversion requires Audiveris and Java.\n\nOpen the setup dialog now?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self.open_audiveris_setup()

    def _pdf_status_text(self) -> str:
        if self.audiveris_jar and Path(self.audiveris_jar).exists():
            return f"PDF: Audiveris configured ✓ ({Path(self.audiveris_jar).name})"
        return "PDF: Audiveris not configured — click ⚙ PDF Setup to enable PDF import"

    def open_audiveris_setup(self) -> None:
        dlg = AudiverisSetupDialog(
            self, current_jar=self.audiveris_jar,
            current_java=self.audiveris_java, current_mscore=self.musescore_exe,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.audiveris_jar = dlg.selected_jar
            self.audiveris_java = dlg.selected_java
            self.musescore_exe = dlg.selected_mscore
            self.pdf_status_label.setText(self._pdf_status_text())

    # ── Run arrangement ─────────────────────────────────────────────

    def run_arrangement(self) -> None:
        if not self.input_path:
            return

        targets, ensemble_name = self._get_target_instruments()
        if not targets:
            QMessageBox.warning(self, "No Target", "Please specify at least one target instrument.")
            return

        ensemble_def = ENSEMBLE_DB.get(ensemble_name)

        default = Path(self.input_path).stem + "_arranged.musicxml"
        output, _ = QFileDialog.getSaveFileName(
            self, "Save Arranged Score", default,
            "MusicXML (*.musicxml);;MIDI (*.mid);;All Files (*)",
        )
        if not output:
            return

        label = ensemble_name or ", ".join(targets)
        excluded_part_names: List[str] = []
        if self.source_part_list:
            for i in range(self.source_part_list.count()):
                item = self.source_part_list.item(i)
                if not (item.flags() & Qt.ItemIsUserCheckable):
                    continue
                if item.checkState() != Qt.Checked:
                    excluded_part_names.append(item.data(Qt.UserRole + 1))
        self.log_msg(f"\n{'='*50}")
        self.log_msg(f"ARRANGING for: {label}")
        if ensemble_def:
            self.log_msg(f"Voicing: {ensemble_def.voicing} · crossing tolerance ±{ensemble_def.crossing_tolerance} st")
        if excluded_part_names:
            self.log_msg(f"Excluded source parts: {', '.join(excluded_part_names)}")
        self.log_msg(f"{'='*50}")
        self.go_btn.setEnabled(False)
        self.select_btn.setEnabled(False)

        also_midi = self.midi_check.isChecked()
        self.thread = ConversionThread(
            self.input_path, output, targets, ensemble_def,
            excluded_part_names=excluded_part_names,
            also_midi=also_midi,
            audiveris_jar=self.audiveris_jar,
            java_exe=self.audiveris_java,
        )
        self.thread.log.connect(self.log_msg)
        self.thread.finished.connect(self._finished)
        self.thread.start()

    def _finished(self, success: bool, message: str) -> None:
        self.go_btn.setEnabled(True)
        self.select_btn.setEnabled(True)
        if success:
            self.last_output_path = message
            self.midi_btn.setEnabled(True)
            self.pdf_score_btn.setEnabled(True)
            self.pdf_parts_btn.setEnabled(True)
            if self.editor_btn is not None:
                self.editor_btn.setEnabled(True)
            extra = ""
            if self.midi_check.isChecked():
                midi_name = Path(message).with_suffix(".mid").name
                extra += f"\n{midi_name}"
            if self.pdf_score_check.isChecked():
                pdf_path = str(Path(message).with_suffix(".pdf"))
                try:
                    self._render_pdf_score(pdf_path)
                    extra += f"\n{Path(pdf_path).name}"
                except Exception as e:
                    self.log_msg(f"\nAuto PDF export failed: {e}")
            QMessageBox.information(self, "Success!", f"Saved:\n{Path(message).name}{extra}")
        else:
            QMessageBox.critical(self, "Error", f"Arrangement failed:\n\n{message}")

    def open_octave_editor(self) -> None:
        if not self.last_output_path:
            QMessageBox.information(self, "No Score", "Arrange and save a score first.")
            return
        try:
            dlg = OctaveEditorDialog(self.last_output_path, self)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Editor Error", f"Could not open visual editor:\n\n{e}")

    def open_existing_for_editor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Existing Arranged Score",
            "",
            "MusicXML (*.musicxml *.xml *.mxl);;All Files (*)",
        )
        if not path:
            return
        self.last_output_path = path
        if self.editor_btn is not None:
            self.editor_btn.setEnabled(True)
        self.midi_btn.setEnabled(True)
        self.pdf_score_btn.setEnabled(True)
        self.pdf_parts_btn.setEnabled(True)
        self.log_msg(f"Opened existing score for editing: {Path(path).name}")
        self.open_octave_editor()

    def save_as_midi(self) -> None:
        if not self.last_output_path:
            return
        default = str(Path(self.last_output_path).with_suffix(".mid"))
        midi_path, _ = QFileDialog.getSaveFileName(self, "Save as MIDI", default, "MIDI (*.mid);;All Files (*)")
        if not midi_path:
            return
        try:
            self.log_msg(f"\nExporting MIDI: {Path(midi_path).name}...")
            score = converter.parse(self.last_output_path)
            score = score.toSoundingPitch()
            score.write("midi", fp=midi_path)
            self.log_msg("  ✓ Saved")
            QMessageBox.information(self, "MIDI Saved", f"Saved:\n{midi_path}")
        except Exception as e:
            self.log_msg(f"\n❌ MIDI export failed: {e}")
            QMessageBox.critical(self, "Export Error", f"MIDI export failed:\n\n{e}")

    # ── PDF export helpers ──────────────────────────────────────────

    def _resolve_mscore(self) -> str:
        mscore = self.musescore_exe or find_musescore_executable()
        if not mscore:
            raise RuntimeError("MuseScore not found. Install MuseScore 3 or 4 from musescore.org.")
        return mscore

    def save_as_pdf_score(self) -> None:
        if not self.last_output_path:
            return
        default = str(Path(self.last_output_path).with_suffix(".pdf"))
        pdf_path, _ = QFileDialog.getSaveFileName(self, "Save as PDF (Score)", default, "PDF (*.pdf);;All Files (*)")
        if not pdf_path:
            return
        try:
            self._render_pdf_score(pdf_path)
            QMessageBox.information(self, "PDF Saved", f"Saved:\n{pdf_path}")
        except Exception as e:
            self.log_msg(f"\nPDF export failed: {e}")
            QMessageBox.critical(self, "Export Error", f"PDF export failed:\n\n{e}")

    def _render_pdf_score(self, pdf_path: str) -> None:
        """Export arranged score to PDF."""
        if not self.last_output_path:
            raise RuntimeError("No arranged score to export")
        mscore = self._resolve_mscore()
        self.log_msg(f"\nExporting PDF score: {Path(pdf_path).name}...")
        tmp_dir = tempfile.mkdtemp(prefix="utrans_score_")
        try:
            tmp_xml = str(Path(tmp_dir) / Path(self.last_output_path).name)
            shutil.copy2(self.last_output_path, tmp_xml)
            title_str, composer_str = self._read_title_composer(self.last_output_path)
            self._postprocess_part_xml(tmp_xml, title=title_str, composer=composer_str, log_fn=self.log_msg)
            convert_to_pdf(tmp_xml, pdf_path, mscore, log_fn=self.log_msg)
            self.log_msg("  Done")
        finally:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    def _read_title_composer(self, arranged_path: str, score: Optional[stream.Score] = None) -> Tuple[str, str]:
        """Extract (title, composer) for PDF export."""
        def _from_meta(md):
            if md is None:
                return "", ""
            t = (getattr(md, "title", None) or getattr(md, "movementName", None) or "")
            c = getattr(md, "composer", None) or ""
            if isinstance(c, (list, tuple)):
                c = c[0] if c else ""
            return (t or "").strip(), (c or "").strip()

        title, composer = "", ""
        if score is not None:
            title, composer = _from_meta(getattr(score, "metadata", None))

        if not (title and composer):
            try:
                with open(arranged_path, "r", encoding="utf-8") as f:
                    blob = f.read()
                if not title:
                    m = re.search(r"<work-title>([^<]+)</work-title>", blob) or re.search(r"<movement-title>([^<]+)</movement-title>", blob)
                    if m:
                        title = m.group(1).strip()
                if not composer:
                    m = re.search(r'<creator\b[^>]*type="composer"[^>]*>([^<]+)</creator>', blob)
                    if m:
                        composer = m.group(1).strip()
            except Exception:
                pass

        if not (title and composer) and self.input_path:
            try:
                ext = Path(self.input_path).suffix.lower()
                if ext in (".xml", ".musicxml", ".mxl", ".mid", ".midi", ".mscz", ".mscx"):
                    src_score = converter.parse(self.input_path)
                    t2, c2 = _from_meta(getattr(src_score, "metadata", None))
                    if not title:
                        title = t2
                    if not composer:
                        composer = c2
            except Exception:
                pass

        return title, composer

    def save_as_pdf_parts(self) -> None:
        """Export each part as a separate PDF."""
        if not self.last_output_path:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Select folder for individual part PDFs", str(Path(self.last_output_path).parent))
        if not out_dir:
            return

        import xml.etree.ElementTree as ET

        try:
            mscore = self._resolve_mscore()
            self.log_msg(f"\nExporting individual part PDFs to: {out_dir}")
            tree = ET.parse(self.last_output_path)
            root = tree.getroot()

            parts_info = []
            for sp in root.iter("score-part"):
                pid = sp.get("id", "")
                pname_el = sp.find("part-name")
                name = (pname_el.text or "").strip() if pname_el is not None else ""
                if not name:
                    abbr = sp.find("part-abbreviation")
                    name = (abbr.text or "").strip() if abbr is not None else pid
                parts_info.append((pid, name or pid))

            if not parts_info:
                raise RuntimeError("No <score-part> entries found.")

            title_str, composer_str = self._read_title_composer(self.last_output_path)
            self.log_msg(f"  Metadata: title={title_str!r} composer={composer_str!r}")

            tmp_dir = tempfile.mkdtemp(prefix="utrans_parts_")
            try:
                saved = []
                for idx, (pid, part_name) in enumerate(parts_info):
                    tree_i = ET.parse(self.last_output_path)
                    root_i = tree_i.getroot()

                    pl = root_i.find("part-list")
                    if pl is not None:
                        for sp in list(pl):
                            if sp.tag == "score-part" and sp.get("id") != pid:
                                pl.remove(sp)
                            elif sp.tag.startswith("part-group"):
                                pl.remove(sp)

                    for p in list(root_i.findall("part")):
                        if p.get("id") != pid:
                            root_i.remove(p)

                    for mp in root_i.iter("midi-program"):
                        try:
                            n = int((mp.text or "").strip())
                        except ValueError:
                            continue
                        if 53 <= n <= 55:
                            mp.text = str(DEFAULT_INSTRUMENTAL_MIDI)

                    for pn in root_i.iter("part-name"):
                        pn.set("print-object", "yes")
                        if not (pn.text and pn.text.strip()):
                            pn.text = part_name

                    safe_name = re.sub(r'[\\/:*?"<>|]', "_", part_name)
                    tmp_xml = str(Path(tmp_dir) / f"{Path(self.last_output_path).stem}_{safe_name}.musicxml")
                    tree_i.write(tmp_xml, encoding="utf-8", xml_declaration=True)

                    self._postprocess_part_xml(tmp_xml, part_name=part_name, title=title_str, composer=composer_str, log_fn=self.log_msg)

                    pdf_out = str(Path(out_dir) / f"{Path(self.last_output_path).stem}_{safe_name}.pdf")
                    self.log_msg(f"  Converting: {safe_name}...")
                    convert_to_pdf(tmp_xml, pdf_out, mscore)
                    saved.append(pdf_out)

                self.log_msg(f"  Done — {len(saved)} PDF(s) saved.")
                QMessageBox.information(self, "Parts Saved", f"Saved {len(saved)} PDF file(s) to:\n{out_dir}")
            finally:
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass
        except Exception as e:
            import traceback
            self.log_msg(f"\nPDF parts export failed: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Export Error", f"PDF parts export failed:\n\n{e}")

    @staticmethod
    def _postprocess_part_xml(xml_path: str, part_name: Optional[str] = None, title: Optional[str] = None,
                              composer: Optional[str] = None, log_fn: Optional = None) -> None:
        """Post-process MusicXML to inject credits and fix part visibility."""
        import html
        try:
            with open(xml_path, "r", encoding="utf-8") as f:
                content = f.read()

            if part_name is not None:
                safe = html.escape(part_name)
                content = re.sub(
                    r'<part-name\b[^/]*/\s*>|<part-name\b[^>]*>[^<]*</part-name>',
                    f'<part-name print-object="yes">{safe}</part-name>',
                    content,
                )

            content = re.sub(r'<credit\b[^>]*>.*?</credit>\s*', '', content, flags=re.DOTALL)

            _pre_title = re.search(r'<work-title>([^<]+)</work-title>', content)
            _pre_title = _pre_title.group(1).strip() if _pre_title else ""
            if not _pre_title:
                _mv = re.search(r'<movement-title>([^<]+)</movement-title>', content)
                _pre_title = _mv.group(1).strip() if _mv else ""
            _pre_comp = re.search(r'<creator\b[^>]*type="composer"[^>]*>([^<]+)</creator>', content)
            _pre_comp = _pre_comp.group(1).strip() if _pre_comp else ""

            content = re.sub(r'<work>.*?</work>\s*', '', content, flags=re.DOTALL)
            content = re.sub(r'<movement-title>[^<]*</movement-title>\s*', '', content)
            content = re.sub(r'<creator\b[^>]*>.*?</creator>\s*', '', content, flags=re.DOTALL)

            title_text = (title or "").strip() or _pre_title
            composer_text = (composer or "").strip() or _pre_comp

            injected = ""
            if title_text:
                injected += f'<credit page="1"><credit-type>title</credit-type><credit-words font-size="{DEFAULT_TITLE_FONT_SIZE}" font-weight="bold">{html.escape(title_text)}</credit-words></credit>\n  '
            if composer_text:
                injected += f'<credit page="1"><credit-type>composer</credit-type><credit-words font-size="12">{html.escape(composer_text)}</credit-words></credit>\n  '

            if injected:
                content = re.sub(r'(<part-list\b)', injected + r"\1", content, count=1)

            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as _e:
            if log_fn:
                log_fn(f"    _postprocess_part_xml failed: {_e}")

    def log_msg(self, text: str) -> None:
        """Append to log text area and scroll to bottom."""
        self.log_text.append(text)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event) -> None:
        if self.thread and self.thread.isRunning():
            self.thread.terminate()
            self.thread.wait(3000)
        event.accept()
