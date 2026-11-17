"""Interactive candlestick chart with tradlab-style navigation."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout



class MarketChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.widget = pg.GraphicsLayoutWidget()
        layout.addWidget(self.widget)
        self.price = self.widget.addPlot(row=0, col=0)
        self.price.setLabel('left', 'Price (USD)')
        self.price.setLabel('bottom', 'Bars')
        self.price.showGrid(x=True, y=True, alpha=.2)
        self.price.setMouseEnabled(x=True, y=True)
        self.price.setMenuEnabled(True)
        self.price.setClipToView(True)
        self.rows = []

    def render(self, rows, title):
        self.rows = list(rows)
        self.price.clear()
        self.price.setTitle(title + ' (drag to pan, wheel to zoom)')
        self.price.setLabel('bottom', 'Bars')
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
        self.price.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)
        self.price.setLabel('bottom', f"Bars · {rows[0]['time']} → {rows[-1]['time']} (UTC / session dates)")
