"""Tradlab-style linked candlestick and indicator panels."""
import numpy as np
import pyqtgraph as pg
import talib
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout


def indicators(close):
    """Match tradlab: TA-Lib EMA/MACD and simple rolling-average RSI(14)."""
    close = np.asarray(close, dtype=float)
    delta = np.diff(close, prepend=close[0]) if len(close) else close
    rsi = np.full(len(close), np.nan)
    if len(close) >= 14:
        gains = np.convolve(np.maximum(delta, 0), np.ones(14) / 14, 'valid')
        losses = np.convolve(np.maximum(-delta, 0), np.ones(14) / 14, 'valid')
        with np.errstate(divide='ignore', invalid='ignore'):
            rsi[13:] = 100 - 100 / (1 + gains / losses)
    macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    return {'EMA10': talib.EMA(close, timeperiod=10), 'EMA21': talib.EMA(close, timeperiod=21),
            'RSI': rsi, 'MACD': macd, 'MACD Signal': signal, 'MACD Hist': hist}


class MarketChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.widget = pg.GraphicsLayoutWidget()
        layout.addWidget(self.widget)
        self.price = self.widget.addPlot(row=0, col=0)
        self.lower = self.widget.addPlot(row=1, col=0)
        self.price.setLabel('left', 'Price (USD)')
        self.lower.setLabel('left', 'Indicators')
        self.lower.setLabel('bottom', 'Bars')
        for plot in (self.price, self.lower):
            plot.showGrid(x=True, y=True, alpha=.2)
            plot.setMouseEnabled(x=True, y=True)
            plot.setMenuEnabled(True)
            plot.setClipToView(True)
            plot.addLegend(offset=(10, 10))
        self.lower.setXLink(self.price)
        self.widget.ci.layout.setRowStretchFactor(0, 3)
        self.widget.ci.layout.setRowStretchFactor(1, 2)
        self.rows = []
        self.curves = {}

    def render(self, rows, title, selected):
        self.rows = list(rows)
        self.price.clear()
        self.lower.clear()
        self.curves = {}
        self.price.setTitle(title + ' (drag to pan, wheel to zoom)')
        self.lower.setTitle('Selected indicators')
        if not rows:
            self.price.setTitle(title + ' · No bars found for selected range')
            return
        x = np.arange(len(rows), dtype=float)
        op, high, low, close = (np.array([r[key] for r in rows], dtype=float)
                                for key in ('open', 'high', 'low', 'close'))
        wick_x = np.column_stack((x, x, np.full(len(x), np.nan))).ravel()
        wick_y = np.column_stack((low, high, np.full(len(x), np.nan))).ravel()
        self.price.plot(wick_x, wick_y, pen=pg.mkPen((200, 200, 200), width=1))
        for mask, color in ((close >= op, (30, 170, 80)), (close < op, (210, 60, 60))):
            if np.any(mask):
                self.price.addItem(pg.BarGraphItem(x=x[mask], y0=op[mask], y1=close[mask], width=.65,
                                                  brush=pg.mkBrush(*color, 180), pen=pg.mkPen(*color, 220)))
        doji = close == op
        if np.any(doji):
            # Flat candle bodies remain visible.
            dx = np.column_stack((x[doji] - .325, x[doji] + .325, np.full(sum(doji), np.nan))).ravel()
            dy = np.column_stack((op[doji], op[doji], np.full(sum(doji), np.nan))).ravel()
            self.price.plot(dx, dy, pen=pg.mkPen(30, 170, 80))
        values = indicators(close)
        colors = {'EMA10': '#f5c542', 'EMA21': '#3fa7ff', 'RSI': '#b182ff',
                  'MACD': '#00d1b2', 'MACD Signal': '#ff8c42'}
        for name in selected:
            plot = self.price if name.startswith('EMA') else self.lower
            if name == 'MACD Hist':
                item = pg.BarGraphItem(x=x, y0=np.zeros_like(x), y1=np.nan_to_num(values[name]), width=.65,
                                       brush=pg.mkBrush(120, 120, 255, 120), pen=pg.mkPen(120, 120, 255, 180))
                plot.addItem(item)
            else:
                item = plot.plot(x, values[name], pen=pg.mkPen(colors[name], width=1.5), name=name)
            self.curves[name] = item
        if 'RSI' in selected:
            for level in (30, 70):
                self.lower.addLine(y=level, pen=pg.mkPen((150, 150, 150), style=Qt.PenStyle.DashLine))
        self.price.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)
        self.lower.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)
        self.lower.setLabel('bottom', f"Bars · {rows[0]['time']} → {rows[-1]['time']} (UTC / session dates)")
