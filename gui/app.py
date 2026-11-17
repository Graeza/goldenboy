import logging
import queue
import sys
from datetime import datetime, timezone
from logging.handlers import QueueHandler

from PySide6.QtCore import QDate, QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QHBoxLayout, QLabel,
    QMainWindow, QPlainTextEdit, QPushButton, QSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates

from config.settings import API_KEY, SYMBOL, TIMEFRAMES
from core.database import connect, stats
from core.logging_setup import configure_logging
from core.pipeline import backfill, sync
from core.sources import SOURCES, create_provider, close_provider, database_path
from config.settings import DATA_SOURCE

logger = logging.getLogger('goldenboy.gui')


class LogPump(QObject):
    """Drain a bounded log queue on the UI thread; never touch Qt from a worker."""
    def __init__(self, output, parent=None):
        super().__init__(parent)
        self.output = output
        self.records = queue.Queue(maxsize=10000)
        self.handler = QueueHandler(self.records)
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s', '%H:%M:%S'))
        logging.getLogger('goldenboy').addHandler(self.handler)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain)
        self.timer.start(100)

    def drain(self):
        lines = []
        for _ in range(250):
            try:
                lines.append(self.records.get_nowait().getMessage())
            except queue.Empty:
                break
        if lines:
            self.output.appendPlainText('\n'.join(lines))

    def close(self):
        self.timer.stop()
        logging.getLogger('goldenboy').removeHandler(self.handler)
        self.drain()


class Collector(QObject):
    finished = Signal(str)

    def __init__(self, command, key, frames, start, end, source="twelvedata"):
        self.source = source
        super().__init__()
        self.command, self.key, self.frames = command, key, frames
        self.start, self.end = start, end

    def run(self):
        con = None
        provider = None
        message = 'Collection complete'
        try:
            con = connect(database_path(self.source))  # SQLite connection belongs to this worker thread.
            provider = create_provider(self.source, self.key)
            now = datetime.now(timezone.utc)
            for timeframe in self.frames:
                if self.command == 'backfill':
                    backfill(provider, con, SYMBOL, timeframe, self.start, self.end, now=now)
                else:
                    sync(provider, con, SYMBOL, timeframe, now=now)
            logger.info(message)
        except Exception:
            message = 'Collection failed — see logs'
            logger.exception('Collection failed')
        finally:
            try:
                if provider is not None:
                    close_provider(provider)
            except Exception:
                message = 'Source cleanup failed — see logs'
                logger.exception('Source cleanup failed')
            finally:
                if con is not None:
                    con.close()
                self.finished.emit(message)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Goldenboy · Gold market data')
        self.resize(1200, 850)
        self.thread = None
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.addWidget(QLabel(f'{SYMBOL} · Stored market candles · UTC'))
        controls = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItems(SOURCES)
        self.source.setCurrentText(DATA_SOURCE)
        controls.addWidget(QLabel("Source"))
        controls.addWidget(self.source)
        self.frames = QComboBox()
        self.frames.addItems(['all', *TIMEFRAMES])
        self.start = QDateEdit(QDate.currentDate().addDays(-30))
        self.end = QDateEdit(QDate.currentDate())
        for field in (self.start, self.end):
            field.setCalendarPopup(True)
            field.setDisplayFormat('yyyy-MM-dd')
        controls.addWidget(QLabel('Collect'))
        controls.addWidget(self.frames)
        controls.addWidget(QLabel('From UTC'))
        controls.addWidget(self.start)
        controls.addWidget(QLabel('Until UTC (exclusive)'))
        controls.addWidget(self.end)
        self.backfill_button = QPushButton('Backfill')
        self.sync_button = QPushButton('Sync')
        self.backfill_button.clicked.connect(lambda: self.collect('backfill'))
        self.sync_button.clicked.connect(lambda: self.collect('sync'))
        controls.addWidget(self.backfill_button)
        controls.addWidget(self.sync_button)
        layout.addLayout(controls)
        chart_controls = QHBoxLayout()
        self.chart_frame = QComboBox()
        self.chart_frame.addItems(TIMEFRAMES)
        self.limit = QSpinBox()
        self.limit.setRange(10, 5000)
        self.limit.setValue(300)
        refresh = QPushButton('Refresh chart')
        refresh.clicked.connect(self.refresh)
        self.chart_frame.currentTextChanged.connect(self.refresh)
        chart_controls.addWidget(QLabel('Chart interval'))
        chart_controls.addWidget(self.chart_frame)
        chart_controls.addWidget(QLabel('Latest bars'))
        chart_controls.addWidget(self.limit)
        chart_controls.addWidget(refresh)
        chart_controls.addStretch()
        layout.addLayout(chart_controls)
        splitter = QSplitter()
        from PySide6.QtCore import Qt
        splitter.setOrientation(Qt.Orientation.Vertical)
        chart = QWidget()
        chart_layout = QVBoxLayout(chart)
        self.figure = Figure(layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.figure)
        chart_layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        chart_layout.addWidget(self.canvas)
        splitter.addWidget(chart)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(3000)
        splitter.addWidget(self.logs)
        splitter.setSizes([550, 180])
        layout.addWidget(splitter)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.pump = LogPump(self.logs, self)
        self.statusBar().showMessage('Ready · Backfill before first sync')
        self.source.currentTextChanged.connect(self.refresh)
        self.refresh()
        logger.info('Ready. Source: %s', self.source.currentText())

    def collect(self, command):
        if self.thread is not None:
            return
        start = datetime.combine(self.start.date().toPython(), datetime.min.time(), timezone.utc)
        end = datetime.combine(self.end.date().toPython(), datetime.min.time(), timezone.utc)
        if command == 'backfill' and (start >= end or end > datetime.now(timezone.utc)):
            self.statusBar().showMessage('Choose start < end, with end no later than now (UTC)')
            return
        if self.source.currentText() == "twelvedata" and (not API_KEY.strip() or API_KEY.strip() == "your_api_key_here"):
            self.statusBar().showMessage('Set TWELVE_DATA_API_KEY in .env and restart the app')
            return
        frames = TIMEFRAMES if self.frames.currentText() == 'all' else (self.frames.currentText(),)
        self.thread = QThread(self)
        self.worker = Collector(command, API_KEY.strip(), frames, start, end, self.source.currentText())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.completed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread_finished)
        self.source.setEnabled(False)
        self.backfill_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.statusBar().showMessage('Collecting… API rate-limit waits are normal')
        logger.info('Starting %s for %s', command, ', '.join(frames))
        self.thread.start()

    def completed(self, message):
        self.statusBar().showMessage(message)
        self.refresh()

    def thread_finished(self):
        self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.source.setEnabled(True)
        self.backfill_button.setEnabled(True)
        self.sync_button.setEnabled(True)

    def refresh(self, *_):
        con = None
        try:
            con = connect(database_path(self.source.currentText()))
            rows = con.execute('''SELECT time, open, high, low, close FROM BARS
                WHERE symbol=? AND timeframe=? AND is_closed=1 ORDER BY time DESC LIMIT ?''',
                (SYMBOL, self.chart_frame.currentText(), self.limit.value())).fetchall()[::-1]
            summary = stats(con, SYMBOL)
            self.summary.setText(' · '.join(f"{r['timeframe']}: {r['bars']:,} bars (latest {r['last_bar']})" for r in summary)
                                 or 'No stored candles. Choose dates and run Backfill.')
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.set_title(f'{SYMBOL} · {self.source.currentText()} · {self.chart_frame.currentText()} · closed candles')
            ax.set_ylabel('Price (USD)')
            ax.set_xlabel('UTC / daily session date')
            if rows:
                width = {'5min': 5 / 1440, '1h': 1 / 24, '1day': 1}[self.chart_frame.currentText()] * .7
                for row in rows:
                    stamp = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    x = mdates.date2num(stamp)
                    color = '#148060' if row['close'] >= row['open'] else '#cb4242'
                    ax.vlines(x, row['low'], row['high'], color=color, linewidth=.8)
                    ax.add_patch(Rectangle((x - width / 2, min(row['open'], row['close'])),
                                           width, abs(row['close'] - row['open']), facecolor=color, edgecolor=color))
                    if row['open'] == row['close']:
                        ax.hlines(row['open'], x - width / 2, x + width / 2, color=color)
                ax.autoscale_view()
                locator = mdates.AutoDateLocator(tz=timezone.utc)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
            else:
                ax.text(.5, .5, 'No stored candles for this interval', transform=ax.transAxes, ha='center')
            ax.grid(alpha=.2)
            self.canvas.draw_idle()
        except Exception:
            logger.exception('Cannot refresh chart')
            self.statusBar().showMessage('Chart refresh failed — see logs')
        finally:
            if con is not None:
                con.close()

    def closeEvent(self, event):
        if self.thread is not None:
            self.statusBar().showMessage('Wait for collection to finish before closing')
            event.ignore()
            return
        self.pump.close()
        event.accept()


def main():
    configure_logging()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = Window()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
