import pandas as pd
import numpy as np
from typing import Optional


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def compute_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    return {
        "upper": sma + (std * std_dev),
        "middle": sma,
        "lower": sma - (std * std_dev),
    }


def analyze_technical(history: pd.DataFrame) -> dict:
    """Run full technical analysis and return scores + signals."""
    close = history["Close"]
    volume = history["Volume"]

    # Moving averages
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()

    rsi = compute_rsi(close)
    macd_data = compute_macd(close)
    bb = compute_bollinger_bands(close)

    current_price = float(close.iloc[-1])
    current_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
    current_macd = float(macd_data["macd"].iloc[-1]) if not pd.isna(macd_data["macd"].iloc[-1]) else 0.0
    current_signal = float(macd_data["signal"].iloc[-1]) if not pd.isna(macd_data["signal"].iloc[-1]) else 0.0
    current_hist = float(macd_data["histogram"].iloc[-1]) if not pd.isna(macd_data["histogram"].iloc[-1]) else 0.0
    bb_upper = float(bb["upper"].iloc[-1]) if not pd.isna(bb["upper"].iloc[-1]) else current_price
    bb_lower = float(bb["lower"].iloc[-1]) if not pd.isna(bb["lower"].iloc[-1]) else current_price
    bb_middle = float(bb["middle"].iloc[-1]) if not pd.isna(bb["middle"].iloc[-1]) else current_price

    signals = []
    score = 50  # neutral starting point

    # RSI signals
    if current_rsi < 30:
        signals.append({"type": "bullish", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 과매도 구간 (매수 기회)"})
        score += 15
    elif current_rsi > 70:
        signals.append({"type": "bearish", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 과매수 구간 (주의 필요)"})
        score -= 15
    else:
        signals.append({"type": "neutral", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 중립 구간"})

    # MACD signals
    if current_macd > current_signal and current_hist > 0:
        signals.append({"type": "bullish", "indicator": "MACD", "message": "MACD 골든크로스 — 상승 추세"})
        score += 10
    elif current_macd < current_signal and current_hist < 0:
        signals.append({"type": "bearish", "indicator": "MACD", "message": "MACD 데드크로스 — 하락 추세"})
        score -= 10

    # Moving average signals
    ma20_val = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else None
    ma60_val = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else None
    ma120_val = float(ma120.iloc[-1]) if not pd.isna(ma120.iloc[-1]) else None

    if ma20_val and current_price > ma20_val:
        signals.append({"type": "bullish", "indicator": "MA20", "message": f"현재가({current_price:,.0f})가 20일 이평선({ma20_val:,.0f}) 위"})
        score += 5
    elif ma20_val:
        signals.append({"type": "bearish", "indicator": "MA20", "message": f"현재가({current_price:,.0f})가 20일 이평선({ma20_val:,.0f}) 아래"})
        score -= 5

    if ma60_val and current_price > ma60_val:
        signals.append({"type": "bullish", "indicator": "MA60", "message": f"60일 이평선 위 — 중기 상승 추세"})
        score += 5
    elif ma60_val:
        signals.append({"type": "bearish", "indicator": "MA60", "message": f"60일 이평선 아래 — 중기 하락 추세"})
        score -= 5

    # Bollinger Band signals
    if current_price <= bb_lower:
        signals.append({"type": "bullish", "indicator": "BB", "message": "볼린저 밴드 하단 터치 — 반등 가능성"})
        score += 10
    elif current_price >= bb_upper:
        signals.append({"type": "bearish", "indicator": "BB", "message": "볼린저 밴드 상단 터치 — 과매수 주의"})
        score -= 10

    # Volume trend
    avg_vol = float(volume.rolling(20).mean().iloc[-1]) if not pd.isna(volume.rolling(20).mean().iloc[-1]) else 0
    current_vol = float(volume.iloc[-1])
    if avg_vol > 0 and current_vol > avg_vol * 1.5:
        signals.append({"type": "bullish", "indicator": "Volume", "message": f"거래량 급증 ({current_vol/avg_vol:.1f}x 평균)"})
        score += 5

    score = max(0, min(100, score))

    # Chart data (last 60 days)
    recent = history.tail(60)
    chart_data = {
        "dates": [d.strftime("%Y-%m-%d") for d in recent.index],
        "close": [round(float(v), 2) for v in recent["Close"]],
        "ma5": [round(float(v), 2) if not pd.isna(v) else None for v in ma5.tail(60)],
        "ma20": [round(float(v), 2) if not pd.isna(v) else None for v in ma20.tail(60)],
        "ma60": [round(float(v), 2) if not pd.isna(v) else None for v in ma60.tail(60)],
        "bb_upper": [round(float(v), 2) if not pd.isna(v) else None for v in bb["upper"].tail(60)],
        "bb_lower": [round(float(v), 2) if not pd.isna(v) else None for v in bb["lower"].tail(60)],
        "volume": [int(v) for v in recent["Volume"]],
        "rsi": [round(float(v), 2) if not pd.isna(v) else None for v in rsi.tail(60)],
        "macd": [round(float(v), 4) if not pd.isna(v) else None for v in macd_data["macd"].tail(60)],
        "macd_signal": [round(float(v), 4) if not pd.isna(v) else None for v in macd_data["signal"].tail(60)],
        "macd_hist": [round(float(v), 4) if not pd.isna(v) else None for v in macd_data["histogram"].tail(60)],
    }

    # Price change stats
    price_1d = float(close.pct_change(1).iloc[-1] * 100) if len(close) > 1 else 0
    price_1w = float(close.pct_change(5).iloc[-1] * 100) if len(close) > 5 else 0
    price_1m = float(close.pct_change(21).iloc[-1] * 100) if len(close) > 21 else 0
    price_3m = float(close.pct_change(63).iloc[-1] * 100) if len(close) > 63 else 0

    return {
        "score": round(score),
        "signals": signals,
        "indicators": {
            "rsi": round(current_rsi, 2),
            "macd": round(current_macd, 4),
            "macd_signal": round(current_signal, 4),
            "bb_upper": round(bb_upper, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_middle": round(bb_middle, 2),
            "ma5": round(float(ma5.iloc[-1]), 2) if not pd.isna(ma5.iloc[-1]) else None,
            "ma20": round(ma20_val, 2) if ma20_val else None,
            "ma60": round(ma60_val, 2) if ma60_val else None,
            "ma120": round(ma120_val, 2) if ma120_val else None,
        },
        "price_changes": {
            "1d": round(price_1d, 2),
            "1w": round(price_1w, 2),
            "1m": round(price_1m, 2),
            "3m": round(price_3m, 2),
        },
        "chart_data": chart_data,
    }
