from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QEvent, QItemSelectionModel, QModelIndex, QObject, QRectF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPen, QTextOption
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QAbstractItemView,
    QStyledItemDelegate,
    QSplitter,
    QStyle,
    QTableView,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


FILM_STYLE = """
QMainWindow {
    background: #17110e;
}
QToolBar {
    background: #211711;
    border: 0;
    border-bottom: 1px solid #7c5a34;
    padding: 7px;
    spacing: 6px;
}
QToolButton {
    background: #332318;
    color: #f4dfb5;
    border: 1px solid #9c7442;
    border-radius: 4px;
    padding: 7px 10px;
    font-weight: 600;
}
QToolButton:hover {
    background: #4b301d;
    border-color: #d9ad63;
}
QToolButton:pressed {
    background: #6f2f25;
}
QToolButton:disabled {
    background: #211a16;
    color: #6f6256;
    border-color: #3b3028;
}
QFrame#dropFrame {
    background: #18110e;
}
QWidget#leftPanel, QWidget#rightPanel {
    background: #1d1511;
}
QVideoWidget {
    background: #050403;
    border: 2px solid #8b6538;
    border-radius: 5px;
}
QLabel#subtitlePreview {
    padding: 14px;
    background: #0d0a08;
    color: #ffe0a3;
    border: 2px solid #b88a4a;
    border-radius: 5px;
    font-weight: 700;
}
QTableView {
    background: #1a130f;
    alternate-background-color: #241811;
    color: #f1dfbf;
    gridline-color: #5f4529;
    border: 1px solid #8b6538;
    border-radius: 5px;
    selection-background-color: #9a3d2f;
    selection-color: #fff4d2;
}
QTableView::item {
    padding: 7px;
}
QHeaderView::section {
    background: #302016;
    color: #dcb978;
    border: 0;
    border-right: 1px solid #5f4529;
    border-bottom: 1px solid #8b6538;
    padding: 7px;
    font-weight: 700;
}
QTextEdit {
    background: #fff0c8;
    color: #1d1511;
    border: 2px solid #d0a04f;
    selection-background-color: #9a3d2f;
}
QSplitter::handle {
    background: #3b2a1d;
}
QStatusBar {
    background: #130e0b;
    color: #dcb978;
    border-top: 1px solid #5f4529;
}
QLabel#shortcutFooter {
    padding: 8px 12px;
    color: #d6bd8c;
    background: #130e0b;
    border-top: 1px solid #5f4529;
}
"""


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
SNAP_SECONDS = 0.2


def resource_path(relative_path: str) -> Path:
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path:
        return Path(base_path) / relative_path
    return Path(relative_path)


DEFAULT_MODEL_PATH = resource_path("models/small")


@dataclass(frozen=True)
class ShortcutSpec:
    action_id: str
    label: str
    sequence: str
    display: str


SHORTCUTS = [
    ShortcutSpec("open", "导入", "Ctrl+O", "Cmd/Ctrl+O"),
    ShortcutSpec("export", "导出 SRT", "Ctrl+E", "Cmd/Ctrl+E"),
    ShortcutSpec("undo", "撤销", "Ctrl+Z", "Cmd/Ctrl+Z"),
    ShortcutSpec("redo", "反撤销", "Ctrl+Shift+Z", "Cmd/Ctrl+Shift+Z"),
    ShortcutSpec("play", "播放/暂停", "Space", "Space"),
    ShortcutSpec("mark", "标记", "M", "M"),
    ShortcutSpec("split", "分割字幕", "Alt+C", "Option/Alt+C"),
    ShortcutSpec("merge", "合并", "Alt+M", "Option/Alt+M"),
    ShortcutSpec("edit", "编辑当前行", "Return", "Enter/单击当前行"),
    ShortcutSpec("newline", "输入中换行", "Ctrl+Return", "Cmd/Ctrl+Enter"),
    ShortcutSpec("cancel", "处理中撤销", "Esc", "Esc"),
]


@dataclass
class Subtitle:
    start: float
    end: float
    text: str


@dataclass
class AppState:
    subtitles: list[Subtitle]
    markers: list[float]
    selected_row: int


def clone_subtitles(subtitles: list[Subtitle]) -> list[Subtitle]:
    return [Subtitle(sub.start, sub.end, sub.text) for sub in subtitles]


def clone_state(state: AppState) -> AppState:
    return AppState(clone_subtitles(state.subtitles), list(state.markers), state.selected_row)


class HistoryStack:
    def __init__(self, limit: int = 100) -> None:
        self.limit = limit
        self.states: list[AppState] = []
        self.index = -1

    def push(self, state: AppState) -> None:
        snapshot = clone_state(state)
        if self.index >= 0 and self._same_state(self.states[self.index], snapshot):
            return
        del self.states[self.index + 1 :]
        self.states.append(snapshot)
        if len(self.states) > self.limit:
            self.states.pop(0)
        self.index = len(self.states) - 1

    def undo(self) -> AppState | None:
        if self.index <= 0:
            return None
        self.index -= 1
        return clone_state(self.states[self.index])

    def redo(self) -> AppState | None:
        if self.index >= len(self.states) - 1:
            return None
        self.index += 1
        return clone_state(self.states[self.index])

    @staticmethod
    def _same_state(left: AppState, right: AppState) -> bool:
        if left.markers != right.markers or left.selected_row != right.selected_row:
            return False
        if len(left.subtitles) != len(right.subtitles):
            return False
        return all(
            a.start == b.start and a.end == b.end and a.text == b.text
            for a, b in zip(left.subtitles, right.subtitles)
        )


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def fmt_srt_time(seconds: float) -> str:
    return fmt_time(seconds).replace(".", ",")


def write_srt(path: Path, subtitles: list[Subtitle]) -> None:
    lines: list[str] = []
    for index, sub in enumerate(subtitles, 1):
        lines.append(str(index))
        lines.append(f"{fmt_srt_time(sub.start)} --> {fmt_srt_time(sub.end)}")
        lines.append(sub.text.strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def resolve_model_ref() -> str:
    model_ref = os.environ.get("EASYSUB_MODEL")
    if model_ref:
        model_path = Path(model_ref).expanduser()
        if model_ref.startswith("/") or model_ref.startswith("~") or "/" in model_ref:
            if not model_path.exists():
                raise RuntimeError(f"EASYSUB_MODEL 指向的模型路径不存在：{model_path}")
            return str(model_path)
        return model_ref
    if DEFAULT_MODEL_PATH.exists():
        return str(DEFAULT_MODEL_PATH)
    raise RuntimeError(f"没有设置 EASYSUB_MODEL，也未找到项目内 {DEFAULT_MODEL_PATH} 本地模型。")


def media_duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return max(0.0, float(out.strip()))
    except Exception:
        return 0.0


def extract_wav(path: Path, temp_dir: Path) -> Path | None:
    wav_path = temp_dir / f"{path.stem}.16k.wav"
    try:
        subprocess.check_call(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(wav_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return wav_path
    except Exception:
        return path if path.suffix.lower() == ".wav" else None


def waveform_peaks(wav_path: Path, buckets: int = 1200) -> np.ndarray:
    try:
        with wave.open(str(wav_path), "rb") as src:
            frames = src.readframes(src.getnframes())
            channels = src.getnchannels()
            sample_width = src.getsampwidth()
        dtype = np.int16 if sample_width == 2 else np.uint8
        samples = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        if samples.size == 0:
            return np.array([], dtype=float)
        samples = samples.astype(float)
        if dtype == np.uint8:
            samples -= 128
        step = max(1, samples.size // buckets)
        trimmed = samples[: step * (samples.size // step)]
        if trimmed.size == 0:
            return np.array([], dtype=float)
        peaks = np.abs(trimmed.reshape(-1, step)).max(axis=1)
        max_peak = peaks.max(initial=1.0)
        return peaks / max_peak
    except Exception:
        return np.array([], dtype=float)


class SubtitleModel(QAbstractTableModel):
    changed = Signal()
    textEdited = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.subtitles: list[Subtitle] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.subtitles)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else 3

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        sub = self.subtitles[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            if index.column() == 0:
                return fmt_time(sub.start)
            if index.column() == 1:
                return fmt_time(sub.end)
            return sub.text
        if role == Qt.TextAlignmentRole and index.column() < 2:
            return Qt.AlignCenter
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return ["开始", "结束", "字幕"][section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        base = super().flags(index)
        if index.isValid() and index.column() == 2:
            return base | Qt.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role == Qt.EditRole and index.isValid() and index.column() == 2:
            new_text = str(value)
            if self.subtitles[index.row()].text == new_text:
                return False
            self.subtitles[index.row()].text = new_text
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            self.changed.emit()
            self.textEdited.emit(index.row())
            return True
        return False

    def set_subtitles(self, subtitles: list[Subtitle]) -> None:
        self.beginResetModel()
        self.subtitles = subtitles
        self.endResetModel()
        self.changed.emit()

    def update_timing(self, row: int, start: float, end: float) -> None:
        if 0 <= row < len(self.subtitles):
            sub = self.subtitles[row]
            sub.start = max(0.0, min(start, end - 0.1))
            sub.end = max(sub.start + 0.1, end)
            left = self.index(row, 0)
            right = self.index(row, 1)
            self.dataChanged.emit(left, right, [Qt.DisplayRole])
            self.changed.emit()


class SubtitleTextDelegate(QStyledItemDelegate):
    editingStarted = Signal()
    editingFinished = Signal()
    splitRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.current_editor: QTextEdit | None = None

    def createEditor(self, parent, option, index):
        editor = QTextEdit(parent)
        editor.setAcceptRichText(False)
        editor.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        editor.installEventFilter(self)
        editor.destroyed.connect(lambda _=None: self.on_editor_destroyed(editor))
        self.current_editor = editor
        self.editingStarted.emit()
        return editor

    def setEditorData(self, editor, index: QModelIndex) -> None:
        editor.setPlainText(index.data(Qt.EditRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index: QModelIndex) -> None:
        model.setData(index, editor.toPlainText(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)

    def eventFilter(self, watched: QObject, event) -> bool:
        if isinstance(watched, QTextEdit) and event.type() == QEvent.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            if key == Qt.Key_C and modifiers & Qt.AltModifier:
                self.splitRequested.emit()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if modifiers & (Qt.ControlModifier | Qt.MetaModifier):
                    watched.insertPlainText("\n")
                    return True
                self.commitData.emit(watched)
                self.closeEditor.emit(watched, QStyledItemDelegate.NoHint)
                self.editingFinished.emit()
                return True
            if key == Qt.Key_Escape:
                self.closeEditor.emit(watched, QStyledItemDelegate.RevertModelCache)
                self.editingFinished.emit()
                return True
        return super().eventFilter(watched, event)

    def on_editor_destroyed(self, editor: QTextEdit) -> None:
        if self.current_editor is editor:
            self.current_editor = None
        self.editingFinished.emit()

    def edited_text_and_cursor(self) -> tuple[str, int] | None:
        if self.current_editor is None:
            return None
        cursor = self.current_editor.textCursor()
        return self.current_editor.toPlainText(), cursor.position()

    def close_current_editor_without_commit(self) -> None:
        if self.current_editor is not None:
            self.closeEditor.emit(self.current_editor, QStyledItemDelegate.RevertModelCache)


class TranscriptionWorker(QObject):
    finished = Signal(list, float, object, str)

    def __init__(self, media_path: Path) -> None:
        super().__init__()
        self.media_path = media_path

    def run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="easysubtitles-") as temp_name:
            temp_root = Path(temp_name)
            wav_path = extract_wav(self.media_path, temp_root)
            duration = media_duration(self.media_path)
            peaks = waveform_peaks(wav_path) if wav_path else np.array([], dtype=float)
            subtitles: list[Subtitle]
            message = ""
            try:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError("当前 Python 环境没有安装 faster-whisper。请确认使用项目 .venv 运行。") from exc

                model = WhisperModel(resolve_model_ref(), device="cpu", compute_type="int8")
                segments, _info = model.transcribe(str(wav_path or self.media_path), vad_filter=True)
                subtitles = [
                    Subtitle(float(seg.start), max(float(seg.end), float(seg.start) + 0.1), seg.text.strip())
                    for seg in segments
                    if seg.text.strip()
                ]
                if not subtitles:
                    subtitles = [Subtitle(0.0, max(1.0, duration), "")]
            except Exception as exc:
                duration = duration or 5.0
                subtitles = [Subtitle(0.0, min(duration, 4.0), f"未生成字幕：{exc}")]
                message = str(exc)
        self.finished.emit(subtitles, duration, peaks, message)


class DropFrame(QFrame):
    dropped = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() in VIDEO_SUFFIXES | AUDIO_SUFFIXES:
            self.dropped.emit(path)


class WaveformWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.peaks = np.array([], dtype=float)
        self.position = 0.0
        self.duration = 0.0
        self.setMinimumHeight(260)

    def set_waveform(self, peaks, duration: float) -> None:
        self.peaks = peaks if isinstance(peaks, np.ndarray) else np.array([], dtype=float)
        self.duration = duration
        self.update()

    def set_position(self, position: float) -> None:
        self.position = position
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#100c0a"))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#4f3926"), 1))
        for x in range(10, self.width(), 28):
            painter.drawLine(x, 0, x, self.height())
        if self.peaks.size == 0:
            painter.setPen(QColor("#a89062"))
            painter.drawText(self.rect(), Qt.AlignCenter, "音频波形将在处理后显示")
            return
        mid = self.height() / 2
        width = max(1, self.width())
        step = max(1, self.peaks.size // width)
        visible = self.peaks[::step][:width]
        painter.setPen(QPen(QColor("#d6a756"), 1))
        for x, peak in enumerate(visible):
            h = float(peak) * (self.height() * 0.42)
            painter.drawLine(x, int(mid - h), x, int(mid + h))
        if self.duration > 0:
            x = int((self.position / self.duration) * self.width())
            painter.setPen(QPen(QColor("#b53a2d"), 2))
            painter.drawLine(x, 0, x, self.height())


class TimelineWidget(QWidget):
    seekRequested = Signal(float)
    rowSelected = Signal(int)
    subtitleTimingChanged = Signal(int, float, float)
    timingEditStarted = Signal()
    timingEditFinished = Signal()

    def __init__(self, model: SubtitleModel) -> None:
        super().__init__()
        self.model = model
        self.duration = 1.0
        self.position = 0.0
        self.selected_row = -1
        self.markers: list[float] = []
        self.drag: tuple[int, str] | None = None
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        model.changed.connect(self.update)

    def set_duration(self, duration: float) -> None:
        self.duration = max(1.0, duration)
        self.update()

    def set_position(self, position: float) -> None:
        self.position = position
        self.update()

    def set_selected_row(self, row: int) -> None:
        self.selected_row = row
        self.update()

    def add_marker(self, time_value: float) -> None:
        self.markers.append(max(0.0, min(time_value, self.duration)))
        self.markers = sorted(set(round(m, 3) for m in self.markers))
        self.update()

    def x_for_time(self, value: float) -> float:
        duration = max(0.001, self.duration)
        return 12 + (max(0.0, min(value, duration)) / duration) * max(1, self.width() - 24)

    def time_for_x(self, x: float) -> float:
        duration = max(0.001, self.duration)
        return max(0.0, min(duration, ((x - 12) / max(1, self.width() - 24)) * duration))

    def snapped(self, value: float, current_row: int | None = None) -> float:
        for marker in self.markers:
            if abs(marker - value) <= SNAP_SECONDS:
                return marker
        for row, sub in enumerate(self.model.subtitles):
            if current_row is not None and row == current_row:
                continue
            for anchor in (sub.start, sub.end):
                if abs(anchor - value) <= SNAP_SECONDS:
                    return anchor
        return value

    def subtitle_rect(self, row: int) -> QRectF:
        sub = self.model.subtitles[row]
        x1 = self.x_for_time(sub.start)
        x2 = self.x_for_time(sub.end)
        y = 52 + (row % 2) * 28
        return QRectF(x1, y, max(4.0, x2 - x1), 22)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#211711"))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#3d2a1d"), 1))
        for x in range(18, self.width(), 34):
            painter.drawEllipse(x, 7, 8, 8)
            painter.drawEllipse(x, self.height() - 16, 8, 8)
        painter.setPen(QColor("#b9965a"))
        axis_y = 28
        painter.drawLine(12, axis_y, self.width() - 12, axis_y)
        tick_count = 8
        for i in range(tick_count + 1):
            t = self.duration * i / tick_count
            x = self.x_for_time(t)
            painter.drawLine(int(x), axis_y - 5, int(x), axis_y + 5)
            painter.drawText(int(x - 30), 4, 60, 18, Qt.AlignCenter, fmt_time(t)[3:8])
        painter.setPen(QPen(QColor("#d2a24f"), 2))
        for marker in self.markers:
            x = int(self.x_for_time(marker))
            painter.drawLine(x, 18, x, self.height() - 8)
        subtitles = self.model.subtitles
        draw_text = len(subtitles) <= 300
        for row, sub in enumerate(subtitles):
            rect = self.subtitle_rect(row)
            active = row == self.selected_row
            painter.setBrush(QColor("#b54a36") if active else QColor("#6b4a2e"))
            painter.setPen(QPen(QColor("#f1c776") if active else QColor("#a67a45"), 1))
            painter.drawRoundedRect(rect, 4, 4)
            if draw_text and rect.width() > 24:
                painter.setPen(QColor("#fff0c8") if active else QColor("#e2c899"))
                painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, sub.text)
        x = int(self.x_for_time(self.position))
        painter.setPen(QPen(QColor("#e8d2a0"), 2))
        painter.drawLine(x, 0, x, self.height())

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        for row in range(len(self.model.subtitles)):
            rect = self.subtitle_rect(row)
            if rect.adjusted(-6, -4, 6, 4).contains(pos):
                if abs(pos.x() - rect.left()) < 8:
                    self.drag = (row, "start")
                    self.timingEditStarted.emit()
                elif abs(pos.x() - rect.right()) < 8:
                    self.drag = (row, "end")
                    self.timingEditStarted.emit()
                else:
                    self.rowSelected.emit(row)
                    self.seekRequested.emit(self.model.subtitles[row].start)
                return
        self.seekRequested.emit(self.time_for_x(pos.x()))

    def mouseMoveEvent(self, event) -> None:
        if self.drag is None:
            return
        row, edge = self.drag
        sub = self.model.subtitles[row]
        value = self.snapped(self.time_for_x(event.position().x()), row)
        if edge == "start":
            self.subtitleTimingChanged.emit(row, min(value, sub.end - 0.1), sub.end)
        else:
            self.subtitleTimingChanged.emit(row, sub.start, max(value, sub.start + 0.1))

    def mouseReleaseEvent(self, event) -> None:
        if self.drag is not None:
            self.timingEditFinished.emit()
        self.drag = None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EasySubtitles MVP")
        self.resize(1280, 760)
        self.media_path: Path | None = None
        self.duration = 1.0
        self.selected_row = -1
        self.is_editing = False
        self.is_processing = False
        self.processing_cancelled = False
        self.first_frame_primed = False
        self.last_position_update_ms = -1
        self.drag_started_state: AppState | None = None
        self.history = HistoryStack()
        self.model = SubtitleModel()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.worker_thread: QThread | None = None
        self.worker: TranscriptionWorker | None = None
        self._build_ui()
        self._wire()
        self.apply_film_theme()
        self.push_history()
        self.refresh_action_states()

    def _build_ui(self) -> None:
        toolbar = QToolBar("主工具栏")
        self.toolbar = toolbar
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DialogOpenButton), "打开", self)
        self.process_action = QAction("重新处理", self)
        self.play_action = QAction(self.style().standardIcon(QStyle.SP_MediaPlay), "播放/暂停", self)
        self.mark_action = QAction("标记当前时间点", self)
        self.split_action = QAction("分割字幕", self)
        self.merge_action = QAction("合并", self)
        self.export_action = QAction("导出 SRT", self)
        self.undo_action = QAction("撤销", self)
        self.redo_action = QAction("反撤销", self)
        self.cancel_action = QAction("撤销处理", self)
        self.cancel_action.setEnabled(False)
        for action in [self.open_action, self.process_action, self.play_action, self.mark_action, self.split_action, self.merge_action, self.export_action]:
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in [self.undo_action, self.redo_action]:
            toolbar.addAction(action)

        self.drop_frame = DropFrame()
        self.drop_frame.setObjectName("dropFrame")
        self.setCentralWidget(self.drop_frame)
        root = QVBoxLayout(self.drop_frame)
        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter
        root.addWidget(splitter)

        left = QWidget()
        left.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(320)
        self.waveform = WaveformWidget()
        self.waveform.setObjectName("waveform")
        self.subtitle_preview = QLabel("拖拽视频/音频文件到窗口，或点击打开。")
        self.subtitle_preview.setObjectName("subtitlePreview")
        self.subtitle_preview.setAlignment(Qt.AlignCenter)
        self.subtitle_preview.setWordWrap(True)
        self.subtitle_preview.setFont(QFont("Georgia", 19, QFont.Bold))
        self.timeline = TimelineWidget(self.model)
        left_layout.addWidget(self.video)
        left_layout.addWidget(self.waveform)
        left_layout.addWidget(self.subtitle_preview)
        left_layout.addWidget(self.timeline)

        right = QWidget()
        right.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.text_delegate = SubtitleTextDelegate(self)
        self.table.setItemDelegateForColumn(2, self.text_delegate)
        right_layout.addWidget(self.table)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([720, 560])
        self.player.setVideoOutput(self.video)
        self.shortcut_footer = QLabel(self.shortcut_help_text())
        self.shortcut_footer.setObjectName("shortcutFooter")
        self.shortcut_footer.setWordWrap(True)
        root.addWidget(self.shortcut_footer)
        self.setAcceptDrops(True)
        self.drop_frame.setAcceptDrops(True)
        for widget in [self.drop_frame, splitter, left, right, self.video, self.waveform, self.timeline, self.table, self.table.viewport()]:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def _wire(self) -> None:
        self.apply_shortcuts()
        self.open_action.triggered.connect(self.open_file)
        self.process_action.triggered.connect(self.start_processing)
        self.play_action.triggered.connect(self.toggle_playback)
        self.mark_action.triggered.connect(self.add_marker)
        self.split_action.triggered.connect(self.split_current_subtitle)
        self.merge_action.triggered.connect(self.merge_selected_subtitles)
        self.export_action.triggered.connect(self.export_srt)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.cancel_action.triggered.connect(self.cancel_processing)
        self.drop_frame.dropped.connect(self.load_media)
        self.timeline.seekRequested.connect(self.seek)
        self.timeline.rowSelected.connect(lambda row: self.select_row(row, do_seek=False))
        self.timeline.subtitleTimingChanged.connect(self.model.update_timing)
        self.timeline.timingEditStarted.connect(self.on_timing_edit_started)
        self.timeline.timingEditFinished.connect(self.on_timing_edit_finished)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.refresh_action_states())
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_player_duration)
        self.player.mediaStatusChanged.connect(self.on_media_status)
        self.model.changed.connect(self.refresh_preview)
        self.model.textEdited.connect(self.on_text_edited)
        self.text_delegate.editingStarted.connect(self.on_editing_started)
        self.text_delegate.editingFinished.connect(self.on_editing_finished)
        self.text_delegate.splitRequested.connect(self.split_current_subtitle)
        self.table.installEventFilter(self)

    def apply_film_theme(self) -> None:
        self.setStyleSheet(FILM_STYLE)
        self.toolbar.setIconSize(self.toolbar.iconSize())
        self.table.setShowGrid(True)
        self.table.setFont(QFont("Georgia", 13))
        self.table.horizontalHeader().setFont(QFont("Georgia", 13, QFont.Bold))
        self.statusBar().setFont(QFont("Georgia", 12))

    def eventFilter(self, watched: QObject, event) -> bool:
        if event.type() == QEvent.DragEnter and self.has_media_urls(event):
            event.acceptProposedAction()
            return True
        if event.type() == QEvent.Drop:
            path = self.first_media_path(event)
            if path:
                self.load_media(path)
                event.acceptProposedAction()
                return True
        if watched == self.table and event.type() == QEvent.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            if self.is_editing:
                return False
            if modifiers & (Qt.ControlModifier | Qt.MetaModifier):
                return False
            row = self.selected_row
            if key in (Qt.Key_Up, Qt.Key_Down):
                delta = -1 if key == Qt.Key_Up else 1
                self.select_row(max(0, min(len(self.model.subtitles) - 1, row + delta)))
                return True
            if key in (Qt.Key_Left, Qt.Key_Right):
                self.seek_current_boundary(to_end=key == Qt.Key_Right)
                return True
            if key == Qt.Key_Space:
                self.toggle_playback()
                return True
            if key == Qt.Key_M:
                self.add_marker()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.begin_edit_current_row()
                return True
        if watched == self.table.viewport() and event.type() == QEvent.MouseButtonRelease:
            index = self.table.indexAt(event.position().toPoint())
            if index.isValid():
                self.handle_table_click(index, event.modifiers())
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:
        if self.has_media_urls(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        path = self.first_media_path(event)
        if path:
            self.load_media(path)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    @staticmethod
    def first_media_path(event) -> Path | None:
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in VIDEO_SUFFIXES | AUDIO_SUFFIXES:
                return path
        return None

    @classmethod
    def has_media_urls(cls, event) -> bool:
        return cls.first_media_path(event) is not None

    def shortcut_help_text(self) -> str:
        return "    ".join(f"{item.label}: {item.display}" for item in SHORTCUTS)

    def apply_shortcuts(self) -> None:
        action_map = {
            "open": self.open_action,
            "export": self.export_action,
            "undo": self.undo_action,
            "redo": self.redo_action,
            "play": self.play_action,
            "mark": self.mark_action,
            "split": self.split_action,
            "merge": self.merge_action,
            "cancel": self.cancel_action,
        }
        for spec in SHORTCUTS:
            if spec.action_id in {"play", "mark", "edit", "newline"}:
                continue
            action = action_map.get(spec.action_id)
            if not action:
                continue
            if spec.action_id in {"open", "export", "undo", "redo"}:
                action.setShortcuts(self.shortcut_sequences(spec.sequence))
            elif spec.action_id == "split":
                action.setShortcuts([QKeySequence(spec.sequence), QKeySequence("Meta+Alt+C")])
            elif spec.action_id == "merge":
                action.setShortcuts([QKeySequence(spec.sequence), QKeySequence("Meta+Alt+M")])
            else:
                action.setShortcut(self.shortcut_sequence(spec.sequence))
            action.setShortcutContext(Qt.WindowShortcut)
            self.addAction(action)

    @staticmethod
    def shortcut_sequence(value: str) -> QKeySequence:
        return QKeySequence(value)

    @staticmethod
    def shortcut_sequences(value: str) -> list[QKeySequence]:
        sequences = [QKeySequence(value)]
        if value.startswith("Ctrl+"):
            sequences.append(QKeySequence(value.replace("Ctrl+", "Meta+", 1)))
        return sequences

    def set_toolbar_action_enabled(self, action: QAction, enabled: bool) -> None:
        action.setEnabled(enabled)
        widget = self.toolbar.widgetForAction(action)
        if widget:
            if enabled:
                widget.unsetCursor()
            else:
                widget.setCursor(Qt.ForbiddenCursor)

    def refresh_action_states(self) -> None:
        has_media = self.media_path is not None
        has_subtitles = bool(self.model.subtitles)
        can_work = has_media and not self.is_processing
        self.set_toolbar_action_enabled(self.open_action, not self.is_processing)
        self.set_toolbar_action_enabled(self.process_action, can_work)
        self.set_toolbar_action_enabled(self.play_action, has_media and not self.is_processing)
        self.set_toolbar_action_enabled(self.mark_action, has_media and not self.is_processing)
        self.set_toolbar_action_enabled(self.split_action, self.is_editing and not self.is_processing)
        self.set_toolbar_action_enabled(self.merge_action, self.can_merge_selection() and not self.is_editing and not self.is_processing)
        self.set_toolbar_action_enabled(self.export_action, has_subtitles and not self.is_processing)
        self.set_toolbar_action_enabled(self.undo_action, self.history.index > 0 and not self.is_processing)
        self.set_toolbar_action_enabled(self.redo_action, self.history.index < len(self.history.states) - 1 and not self.is_processing)
        self.set_toolbar_action_enabled(self.cancel_action, self.is_processing and not self.processing_cancelled)

    def keyPressEvent(self, event) -> None:
        if self.is_editing or event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            delta = -1 if key == Qt.Key_Up else 1
            self.select_row(max(0, min(len(self.model.subtitles) - 1, self.selected_row + delta)))
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Right):
            self.seek_current_boundary(to_end=key == Qt.Key_Right)
            event.accept()
            return
        if key == Qt.Key_Space:
            self.toggle_playback()
            event.accept()
            return
        if key == Qt.Key_M:
            self.add_marker()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.begin_edit_current_row()
            event.accept()
            return
        super().keyPressEvent(event)

    def snapshot(self) -> AppState:
        return AppState(clone_subtitles(self.model.subtitles), list(self.timeline.markers), self.selected_row)

    def push_history(self) -> None:
        self.history.push(self.snapshot())
        self.refresh_action_states()

    def apply_state(self, state: AppState) -> None:
        self.model.set_subtitles(clone_subtitles(state.subtitles))
        self.timeline.markers = list(state.markers)
        self.timeline.update()
        if state.subtitles:
            self.select_row(max(0, min(len(state.subtitles) - 1, state.selected_row)), do_seek=True)
        else:
            self.selected_row = -1
            self.timeline.set_selected_row(-1)
            self.table.clearSelection()
            self.refresh_preview()

    def undo(self) -> None:
        if self.is_editing:
            return
        state = self.history.undo()
        if state is None:
            self.statusBar().showMessage("没有可撤销的操作。", 3000)
            return
        self.apply_state(state)
        self.refresh_action_states()

    def redo(self) -> None:
        if self.is_editing:
            return
        state = self.history.redo()
        if state is None:
            self.statusBar().showMessage("没有可反撤销的操作。", 3000)
            return
        self.apply_state(state)
        self.refresh_action_states()

    def add_marker(self) -> None:
        if self.is_editing or self.is_processing or not self.media_path:
            return
        self.timeline.add_marker(self.current_seconds())
        self.push_history()

    def selected_rows(self) -> list[int]:
        if self.table.selectionModel() is None:
            return []
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def can_merge_selection(self) -> bool:
        rows = self.selected_rows()
        return len(rows) >= 2 and rows == list(range(rows[0], rows[-1] + 1))

    def begin_edit_current_row(self) -> None:
        if self.selected_row < 0 or self.is_editing or self.is_processing:
            return
        index = self.model.index(self.selected_row, 2)
        self.table.setCurrentIndex(index)
        self.table.edit(index)

    def seek_current_boundary(self, to_end: bool) -> None:
        if self.is_editing or not (0 <= self.selected_row < len(self.model.subtitles)):
            return
        sub = self.model.subtitles[self.selected_row]
        self.seek(sub.end if to_end else sub.start)

    def split_current_subtitle(self) -> None:
        if not self.is_editing or not (0 <= self.selected_row < len(self.model.subtitles)):
            return
        edit_state = self.text_delegate.edited_text_and_cursor()
        if edit_state is None:
            return
        text, cursor_pos = edit_state
        left_text = text[:cursor_pos]
        right_text = text[cursor_pos:]
        original = self.model.subtitles[self.selected_row]
        if original.end - original.start <= 0.2:
            self.statusBar().showMessage("当前字幕块太短，无法分割。", 4000)
            return
        split_time = max(original.start + 0.1, min(self.current_seconds(), original.end - 0.1))
        if not left_text and not right_text:
            return
        self.text_delegate.close_current_editor_without_commit()
        self.is_editing = False
        updated = clone_subtitles(self.model.subtitles)
        updated[self.selected_row] = Subtitle(original.start, split_time, left_text)
        updated.insert(self.selected_row + 1, Subtitle(split_time, original.end, right_text))
        self.model.set_subtitles(updated)
        self.select_row(self.selected_row + 1, do_seek=False)
        self.push_history()
        self.refresh_preview()
        self.statusBar().showMessage("已按光标位置分割字幕。", 4000)

    def merge_selected_subtitles(self) -> None:
        if self.is_editing or self.is_processing or not self.can_merge_selection():
            return
        rows = self.selected_rows()
        subtitles = self.model.subtitles
        selected = [subtitles[row] for row in rows]
        merged = Subtitle(
            min(sub.start for sub in selected),
            max(sub.end for sub in selected),
            " ".join(sub.text.strip() for sub in selected if sub.text.strip()),
        )
        updated = clone_subtitles(subtitles)
        first, last = rows[0], rows[-1]
        updated[first : last + 1] = [merged]
        self.model.set_subtitles(updated)
        self.select_row(first, do_seek=True)
        self.push_history()
        self.refresh_preview()
        self.statusBar().showMessage(f"已合并 {len(rows)} 条字幕。", 4000)

    def on_editing_started(self) -> None:
        self.is_editing = True
        self.refresh_action_states()

    def on_editing_finished(self) -> None:
        self.is_editing = False
        self.refresh_action_states()

    def on_text_edited(self, row: int) -> None:
        self.selected_row = row
        self.push_history()

    def on_timing_edit_started(self) -> None:
        self.drag_started_state = self.snapshot()

    def on_timing_edit_finished(self) -> None:
        if self.drag_started_state and not HistoryStack._same_state(self.drag_started_state, self.snapshot()):
            self.push_history()
        self.drag_started_state = None

    def open_file(self) -> None:
        if self.is_editing or self.is_processing:
            return
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频或音频",
            str(Path.home()),
            "Media files (*.mp4 *.mov *.m4v *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus)",
        )
        if file_name:
            self.load_media(Path(file_name))

    def load_media(self, path: Path) -> None:
        if self.is_editing or self.is_processing:
            return
        self.media_path = path
        self.first_frame_primed = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.video.setVisible(path.suffix.lower() in VIDEO_SUFFIXES)
        self.waveform.setVisible(path.suffix.lower() in AUDIO_SUFFIXES)
        self.subtitle_preview.setText(f"已载入：{path.name}")
        self.duration = media_duration(path) or 1.0
        self.timeline.set_duration(self.duration)
        self.waveform.set_waveform(np.array([], dtype=float), self.duration)
        self.prime_video_frame()
        self.refresh_action_states()
        self.start_processing()

    def prime_video_frame(self) -> None:
        if not self.media_path or self.media_path.suffix.lower() not in VIDEO_SUFFIXES:
            return
        if self.first_frame_primed:
            return
        self.first_frame_primed = True

        def show_first_frame() -> None:
            if self.player.playbackState() != QMediaPlayer.PlayingState:
                self.player.setPosition(1)

        QTimer.singleShot(100, show_first_frame)

    def start_processing(self) -> None:
        if self.is_editing or self.is_processing:
            return
        if not self.media_path:
            self.open_file()
            if not self.media_path:
                return
        self.is_processing = True
        self.processing_cancelled = False
        self.process_action.setText("处理中...")
        self.refresh_action_states()
        self.subtitle_preview.setText("正在本地处理音频并生成字幕...")
        self.worker_thread = QThread(self)
        self.worker = TranscriptionWorker(self.media_path)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_transcribed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.on_worker_thread_finished)
        self.worker_thread.start()

    def on_worker_thread_finished(self) -> None:
        self.worker_thread = None
        self.worker = None

    def on_transcribed(self, subtitles: list[Subtitle], duration: float, peaks, message: str) -> None:
        self.is_processing = False
        self.process_action.setText("重新处理")
        if self.processing_cancelled:
            self.processing_cancelled = False
            self.refresh_action_states()
            self.statusBar().showMessage("已撤销本次重新处理，保留旧字幕。", 6000)
            self.refresh_preview()
            return
        self.duration = max(duration, subtitles[-1].end if subtitles else 1.0, 1.0)
        self.model.set_subtitles(subtitles)
        self.timeline.set_duration(self.duration)
        self.waveform.set_waveform(peaks, self.duration)
        self.waveform.setVisible(bool(self.media_path and self.media_path.suffix.lower() in AUDIO_SUFFIXES))
        self.select_row(0)
        self.push_history()
        self.refresh_action_states()
        if message:
            self.statusBar().showMessage(f"转写未完成，已进入占位校对模式：{message}", 12000)
        else:
            self.statusBar().showMessage("字幕生成完成，可以开始校对。", 6000)

    def cancel_processing(self) -> None:
        if not self.is_processing:
            return
        self.processing_cancelled = True
        self.refresh_action_states()
        self.subtitle_preview.setText("正在撤销本次重新处理，等待当前任务结束...")
        self.statusBar().showMessage("已请求撤销本次重新处理，旧字幕会保留。", 6000)

    def current_seconds(self) -> float:
        return self.player.position() / 1000.0

    def on_position(self, ms: int) -> None:
        if self.last_position_update_ms >= 0 and abs(ms - self.last_position_update_ms) < 40:
            return
        self.last_position_update_ms = ms
        pos = ms / 1000.0
        self.timeline.set_position(pos)
        self.waveform.set_position(pos)
        self.refresh_preview()

    def on_player_duration(self, ms: int) -> None:
        if ms > 0:
            self.duration = max(self.duration, ms / 1000.0)
            self.timeline.set_duration(self.duration)

    def on_media_status(self, status) -> None:
        ready = {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }
        if status in ready and self.player.playbackState() != QMediaPlayer.PlayingState:
            self.prime_video_frame()

    def refresh_preview(self) -> None:
        if 0 <= self.selected_row < len(self.model.subtitles):
            self.subtitle_preview.setText(self.model.subtitles[self.selected_row].text)
        elif self.media_path:
            self.subtitle_preview.setText(self.media_path.name)

    def toggle_playback(self) -> None:
        if self.is_editing:
            return
        if not self.media_path:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, seconds: float) -> None:
        self.player.setPosition(int(seconds * 1000))

    def seek_to_row(self, index: QModelIndex) -> None:
        row = index.row()
        if row == self.selected_row and not self.is_editing:
            self.begin_edit_current_row()
            return
        self.select_row(row)

    def handle_table_click(self, index: QModelIndex, modifiers: Qt.KeyboardModifiers) -> None:
        row = index.row()
        multi_selecting = bool(modifiers & (Qt.ShiftModifier | Qt.ControlModifier | Qt.MetaModifier))
        if row == self.selected_row and not self.is_editing and not multi_selecting:
            self.begin_edit_current_row()
            return
        if multi_selecting:
            self.selected_row = row
            self.timeline.set_selected_row(row)
            self.table.selectionModel().setCurrentIndex(self.model.index(row, 2), QItemSelectionModel.NoUpdate)
            self.seek(self.model.subtitles[row].start)
            self.refresh_preview()
            self.refresh_action_states()
            return
        self.select_row(row)

    def select_row(self, row: int, do_seek: bool = True) -> None:
        if not (0 <= row < len(self.model.subtitles)):
            return
        if self.is_editing:
            self.table.closePersistentEditor(self.table.currentIndex())
            self.is_editing = False
        self.selected_row = row
        self.timeline.set_selected_row(row)
        index = self.model.index(row, 2)
        self.table.selectRow(row)
        self.table.setCurrentIndex(index)
        if do_seek:
            self.seek(self.model.subtitles[row].start)

    def export_srt(self) -> None:
        if self.is_editing:
            return
        if not self.model.subtitles:
            QMessageBox.information(self, "没有字幕", "请先生成或编辑字幕。")
            return
        default = str((self.media_path or Path("subtitles")).with_suffix(".srt"))
        file_name, _ = QFileDialog.getSaveFileName(self, "导出 SRT", default, "SubRip (*.srt)")
        if file_name:
            write_srt(Path(file_name), self.model.subtitles)
            self.statusBar().showMessage(f"已导出：{file_name}", 6000)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("EasySubtitles")
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.open_file)
    sys.exit(app.exec())
