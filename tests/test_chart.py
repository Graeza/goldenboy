import unittest
import numpy as np
import talib
from gui.chart import indicators


class IndicatorTests(unittest.TestCase):
    def test_matches_tradlab_ema_macd_and_rsi_formula(self):
        close = np.array([2000 + i * .5 + 5 * np.sin(i) for i in range(80)])
        result = indicators(close)
        np.testing.assert_allclose(result['EMA10'], talib.EMA(close, timeperiod=10), equal_nan=True)
        np.testing.assert_allclose(result['EMA21'], talib.EMA(close, timeperiod=21), equal_nan=True)
        expected_macd = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        for name, expected in zip(('MACD', 'MACD Signal', 'MACD Hist'), expected_macd):
            np.testing.assert_allclose(result[name], expected, equal_nan=True)
        delta = np.diff(close, prepend=close[0])
        for i in range(13, len(close)):
            sample = delta[i-13:i+1]
            gain = np.maximum(sample, 0).mean()
            loss = np.maximum(-sample, 0).mean()
            self.assertAlmostEqual(result['RSI'][i], 100 - 100 / (1 + gain / loss))
        self.assertTrue(np.isnan(result['RSI'][:13]).all())

    def test_short_and_flat_history_do_not_create_false_signals(self):
        for close in ([], [2000], [2000] * 40):
            result = indicators(close)
            self.assertEqual(len(result['EMA10']), len(close))
            self.assertTrue(np.isnan(result['RSI']).all())
