"""Gold-only tradlab desktop shell with goldenboy's compact controls and log pump."""
import logging
import queue
import sys
from datetime import datetime, timezone
from logging.handlers import QueueHandler

from PySide6.QtCore import QDate, QObject, QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QHBoxLayout, QLabel,
    QMainWindow, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from config.settings import GOLD_SYMBOL, TIMEFRAME_NAMES, ACTIVE_ACCOUNT_PROFILE, DB_PATH
from core.gold_session import GoldSession
from core.logging_setup import configure_logging
from gui.chart import MarketChart

logger = logging.getLogger('goldenboy.gui')


class LogPump(QObject):
    def __init__(self, output, parent=None):
        super().__init__(parent)
        self.output = output
        self.queue = queue.Queue(maxsize=10000)
        self.handler = QueueHandler(self.queue)
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s', '%H:%M:%S'))
        logging.getLogger('goldenboy').addHandler(self.handler)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain)
        self.timer.start(100)

    def drain(self):
        lines = []
        for _ in range(250):
            try:
                lines.append(self.queue.get_nowait().getMessage())
            except queue.Empty:
                break
        if lines:
            self.output.appendPlainText('\n'.join(lines))

    def close(self):
        self.timer.stop()
        logging.getLogger('goldenboy').removeHandler(self.handler)
        self.drain()


class Job(QObject):
    finished = Signal(bool, object)

    def __init__(self, session, operation, options):
        super().__init__()
        self.session, self.operation, self.options = session, operation, options

    def run(self):
        try:
            result = getattr(self.session, self.operation)(**self.options)
            self.finished.emit(True, result)
        except Exception as exc:
            # Keyring/terminal internals may contain account details; keep UI error concise.
            logger.error('%s failed (%s). Check terminal, keyring profile and broker history.', self.operation, type(exc).__name__)
            self.finished.emit(False, f'{self.operation} failed ({type(exc).__name__}); check terminal, keyring profile and logs')
        finally:
            self.session.db.close_thread_connection()


class Window(QMainWindow):
    def __init__(self, session=None):
        super().__init__()
        self.setWindowTitle('Goldenboy · Gold trading workspace')
        self.resize(1250, 900)
        self.session = session or GoldSession()
        self.thread = None
        self.last_snapshot = None
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        header = QHBoxLayout()
        header.addWidget(QLabel(f'<b>GOLDENBOY</b> · {GOLD_SYMBOL} · M5 / H1 / D1'))
        header.addStretch()
        self.profile = QComboBox()
        self.profile.addItems(['DEMO', 'LIVE'])
        self.profile.setCurrentText(ACTIVE_ACCOUNT_PROFILE)
        header.addWidget(self.profile)
        self.initialize = QPushButton('Initialize MetaTrader')
        self.initialize.clicked.connect(lambda: self.launch('initialize', profile=self.profile.currentText()))
        header.addWidget(self.initialize)
        self.connection = QLabel('Disconnected')
        header.addWidget(self.connection)
        layout.addLayout(header)
        split = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)
        self.dashboard = self.page('Dashboard')
        self.quote = QLabel('Initialize MetaTrader to load the gold quote and account.')
        self.dashboard.addWidget(self.quote)
        self.strategy_status = QLabel('Strategy: awaiting your gold strategy. Trading is unavailable.')
        self.dashboard.addWidget(self.strategy_status)
        start_bot = QPushButton('Start trading · strategy required')
        start_bot.setEnabled(False)
        self.dashboard.addWidget(start_bot)
        self.coverage = QTableWidget(0, 4)
        self.coverage.setHorizontalHeaderLabels(['Interval', 'Stored candles', 'First UTC open', 'Latest UTC open'])
        self.coverage.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.coverage.horizontalHeader().setStretchLastSection(True)
        self.dashboard.addWidget(self.coverage)
        self.dashboard.addStretch()
        data = self.page('Data')
        date_controls = QHBoxLayout()
        self.start = QDateEdit(QDate.currentDate().addMonths(-1))
        self.end = QDateEdit(QDate.currentDate())
        for field in (self.start, self.end):
            field.setCalendarPopup(True)
            field.setDisplayFormat('yyyy-MM-dd')
        date_controls.addWidget(QLabel('From UTC'))
        date_controls.addWidget(self.start)
        date_controls.addWidget(QLabel('Until UTC (exclusive)'))
        date_controls.addWidget(self.end)
        self.backfill = QPushButton('Backfill M5 / H1 / D1')
        self.backfill.clicked.connect(self.backfill_range)
        date_controls.addWidget(self.backfill)
        data.addLayout(date_controls)
        collect_controls = QHBoxLayout()
        self.sync = QPushButton('Sync all intervals')
        self.sync.clicked.connect(lambda: self.launch('collect'))
        self.auto = QPushButton('Start collection every 5 minutes')
        self.auto.setCheckable(True)
        self.auto.toggled.connect(self.set_auto)
        collect_controls.addWidget(self.sync)
        collect_controls.addWidget(self.auto)
        data.addLayout(collect_controls)
        data.addWidget(QLabel('Only closed gold candles are stored. Broker history availability limits backfill coverage.'))
        data.addStretch()
        portfolio = self.page('Portfolio')
        self.account = QLabel('Account summary unavailable until connected')
        portfolio.addWidget(self.account)
        self.refresh_account = QPushButton('Refresh account and gold positions')
        self.refresh_account.clicked.connect(lambda: self.launch('snapshot'))
        portfolio.addWidget(self.refresh_account)
        self.positions = QTableWidget(0, 7)
        self.positions.setHorizontalHeaderLabels(['Ticket', 'Symbol', 'Side', 'Volume', 'Open price', 'Current price', 'Profit'])
        self.positions.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.positions.horizontalHeader().setStretchLastSection(True)
        portfolio.addWidget(self.positions)
        backtest = self.page('Backtesting')
        backtest.addWidget(QLabel('Strategy: not installed. Candle inspection is available; backtest execution awaits your strategy.'))
        self.run_backtest = QPushButton('Run backtest · strategy required')
        self.run_backtest.setEnabled(False)
        backtest.addWidget(self.run_backtest)
        chart_controls = QHBoxLayout()
        self.chart_frame = QComboBox()
        for tf, name in TIMEFRAME_NAMES.items():
            self.chart_frame.addItem(name, tf)
        self.display_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.display_from.setCalendarPopup(True)
        self.display_from.setDisplayFormat('yyyy-MM-dd')
        self.limit = QSpinBox()
        self.limit.setRange(10, 20000)
        self.limit.setValue(1000)
        chart_controls.addWidget(QLabel('Interval'))
        chart_controls.addWidget(self.chart_frame)
        chart_controls.addWidget(QLabel('Display from UTC'))
        chart_controls.addWidget(self.display_from)
        chart_controls.addWidget(QLabel('Latest bars'))
        chart_controls.addWidget(self.limit)
        refresh_chart = QPushButton('Refresh chart')
        refresh_chart.clicked.connect(self.refresh)
        chart_controls.addWidget(refresh_chart)
        backtest.addLayout(chart_controls)
        self.chart = MarketChart()
        backtest.addWidget(self.chart)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(3000)
        split.addWidget(self.logs)
        split.setSizes([650, 160])
        layout.addWidget(split)
        logs_tab = self.page('Logs')
        logs_tab.addWidget(QLabel('The live log panel below stays visible across all tabs. Rotating files: logs/goldenboy.log'))
        clear = QPushButton('Clear visible logs')
        clear.clicked.connect(self.logs.clear)
        logs_tab.addWidget(clear)
        logs_tab.addStretch()
        self.pump = LogPump(self.logs, self)
        self.timer = QTimer(self)
        self.timer.setInterval(300000)
        self.timer.timeout.connect(self.auto_collect)
        self.chart_frame.currentIndexChanged.connect(self.refresh)
        self.display_from.dateChanged.connect(self.refresh)
        self.limit.valueChanged.connect(self.refresh)
        self.set_controls()
        self.refresh()
        self.statusBar().showMessage('Ready · no strategy installed')
        logger.info('Gold workspace ready. Database: %s', self.session.db.db_path)

    def page(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tabs.addTab(page, title)
        return layout

    def set_controls(self):
        idle = self.thread is None
        connected = self.session.client is not None
        for control in (self.initialize, self.profile):
            control.setEnabled(idle)
        for control in (self.backfill, self.sync, self.refresh_account, self.auto):
            control.setEnabled(idle and connected)

    def launch(self, operation, **options):
        if self.thread is not None:
            return
        self.thread = QThread(self)
        self.job = Job(self.session, operation, options)
        self.job.moveToThread(self.thread)
        self.thread.started.connect(self.job.run)
        self.job.finished.connect(self.completed)
        self.job.finished.connect(self.thread.quit)
        self.job.finished.connect(self.job.deleteLater)
        self.thread.finished.connect(self.job_done)
        self.set_controls()
        self.statusBar().showMessage(f'{operation} in progress…')
        self.thread.start()

    def completed(self, success, payload):
        if success:
            self.last_snapshot = payload
            self.show_snapshot(payload)
            self.statusBar().showMessage('Operation complete')
        else:
            self.statusBar().showMessage(str(payload))
            if self.session.client is None:
                self.connection.setText('Disconnected · initialization failed')
                self.auto.setChecked(False)
        self.refresh()

    def job_done(self):
        self.thread.deleteLater()
        self.thread = None
        self.job = None
        self.set_controls()

    def show_snapshot(self, payload):
        account = payload['account']
        self.connection.setText(f'Connected · {self.session.client.profile}')
        self.account.setText(' · '.join(f'{k}: {account.get(k)}' for k in ('login','currency','balance','equity','profit','margin_free')))
        tick = payload['tick']
        self.quote.setText(f'{GOLD_SYMBOL} · Bid {getattr(tick,"bid", "—")} · Ask {getattr(tick,"ask", "—")}')
        positions = payload['positions']
        self.positions.setRowCount(len(positions))
        for i, position in enumerate(positions):
            values = [position.ticket, position.symbol, 'BUY' if position.type == 0 else 'SELL', position.volume,
                      position.price_open, getattr(position,'price_current',''), position.profit]
            for j, value in enumerate(values):
                self.positions.setItem(i, j, QTableWidgetItem(str(value)))

    def backfill_range(self):
        start = datetime.combine(self.start.date().toPython(), datetime.min.time(), timezone.utc)
        end = datetime.combine(self.end.date().toPython(), datetime.min.time(), timezone.utc)
        if not start < end <= datetime.now(timezone.utc):
            self.statusBar().showMessage('Choose start < end, with end no later than today (UTC)')
            return
        self.launch('collect', start=start, end=end)

    def set_auto(self, enabled):
        self.auto.setText('Stop scheduled collection' if enabled else 'Start collection every 5 minutes')
        if enabled:
            self.timer.start()
            self.auto_collect()
        else:
            self.timer.stop()

    def auto_collect(self):
        if self.thread is None and self.session.client is not None:
            self.launch('collect')

    def refresh(self, *_):
        from datetime import datetime, timezone
        self.coverage.setRowCount(3)
        for i, (tf, name) in enumerate(TIMEFRAME_NAMES.items()):
            row = self.session.db.conn.execute('SELECT COUNT(*),MIN(time),MAX(time) FROM bars WHERE symbol=? AND timeframe=?', (GOLD_SYMBOL,tf)).fetchone()
            values = [name, row[0], *[datetime.fromtimestamp(v,timezone.utc).isoformat() if v else '—' for v in row[1:]]]
            for j, value in enumerate(values):
                self.coverage.setItem(i,j,QTableWidgetItem(str(value)))
        frame = self.session.db.load_bars(GOLD_SYMBOL, self.chart_frame.currentData(), limit=self.limit.value())
        rows = []
        if not frame.empty:
            start = datetime.combine(self.display_from.date().toPython(), datetime.min.time(), timezone.utc).timestamp()
            for row in frame[frame['time'] >= start].to_dict('records'):
                row['time'] = datetime.fromtimestamp(row['time'],timezone.utc).isoformat()
                rows.append(row)
        self.chart.render(rows, f'{GOLD_SYMBOL} · {self.chart_frame.currentText()} · closed candles')

    def closeEvent(self, event):
        if self.thread is not None:
            self.statusBar().showMessage('Wait for the current operation to finish before closing')
            event.ignore()
            return
        self.timer.stop()
        self.session.close()
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
