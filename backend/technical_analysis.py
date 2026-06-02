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


def compute_atr(history: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — 변동성 측정 (손절폭 산정용)."""
    high = history["High"] if "High" in history.columns else history["Close"]
    low = history["Low"] if "Low" in history.columns else history["Close"]
    close = history["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_trade_setup(history: pd.DataFrame, ind: dict) -> dict:
    """실전 매매 셋업 — 진입가/목표가/손절가/손익비 계산.
    1~3개월 스윙 관점. 추세 안에서의 진입 타이밍을 판단한다.
    """
    close = history["Close"]
    high = history["High"] if "High" in history.columns else close
    low = history["Low"] if "Low" in history.columns else close
    price = float(close.iloc[-1])

    ma20 = ind.get("ma20")
    ma60 = ind.get("ma60")
    ma120 = ind.get("ma120")
    rsi = ind.get("rsi") or 50

    atr_series = compute_atr(history)
    atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else price * 0.02
    atr_pct = atr / price * 100 if price else 2.0

    # 최근 60일 구조적 지지/저항
    recent = history.tail(60)
    swing_high = float(recent["High"].max()) if "High" in recent.columns else float(recent["Close"].max())
    swing_low = float(recent["Low"].min()) if "Low" in recent.columns else float(recent["Close"].min())

    # 추세 판정
    uptrend = bool(ma20 and ma60 and ma20 > ma60 and price > ma60)
    strong_uptrend = bool(ma20 and ma60 and ma120 and ma20 > ma60 > ma120)
    downtrend = bool(ma20 and ma60 and ma20 < ma60 and price < ma60)

    dist_ma20 = ((price - ma20) / ma20 * 100) if ma20 else 0

    # 거래량 확인
    vol_surge = False
    if "Volume" in history.columns:
        v = history["Volume"]
        avg_v = float(v.rolling(20).mean().iloc[-1]) if not pd.isna(v.rolling(20).mean().iloc[-1]) else 0
        cur_v = float(v.iloc[-1])
        vol_surge = avg_v > 0 and cur_v > avg_v * 1.3

    # ── 셋업 분류 ──────────────────────────────────────────────────────
    # setup: 코드 / 라벨 / 설명 / 등급(A~D, F=회피)
    if downtrend:
        setup = {"code": "avoid", "label": "회피", "grade": "F",
                 "desc": "하락 추세 — 60일선 아래. 추세 전환 확인 전까지 신규 진입 보류"}
    elif uptrend and -2 <= dist_ma20 <= 6 and 40 <= rsi <= 62:
        setup = {"code": "pullback", "label": "눌림목 매수", "grade": "A",
                 "desc": "상승 추세 중 20일선 부근 조정 — 가장 유리한 진입 구간"}
    elif price >= swing_high * 0.99 and vol_surge and rsi < 72:
        setup = {"code": "breakout", "label": "돌파 매수", "grade": "B",
                 "desc": f"최근 고점({swing_high:,.0f}) 돌파 + 거래량 증가 — 신고가 추세"}
    elif rsi < 35 and (not ma120 or price > ma120):
        setup = {"code": "rebound", "label": "반등 매수", "grade": "C",
                 "desc": "과매도 반등 시도 — 장기 추세는 살아있음. 분할 진입 권장"}
    elif strong_uptrend and rsi < 70:
        setup = {"code": "trend", "label": "추세 추종", "grade": "B",
                 "desc": "정배열 강세 지속 — 추세 유지 시 보유, 조정 시 추가 매수"}
    elif rsi >= 75:
        setup = {"code": "overheat", "label": "과열 관망", "grade": "D",
                 "desc": f"RSI {rsi:.0f} 과열 — 추격 매수 위험. 조정 후 재진입 대기"}
    else:
        setup = {"code": "wait", "label": "관망", "grade": "D",
                 "desc": "뚜렷한 매수 셋업 없음 — 방향성 확인까지 대기"}

    # ── 진입/목표/손절 가격 산정 ──────────────────────────────────────
    entry_low = entry_high = target = stop = None
    if setup["code"] in ("pullback", "trend", "rebound"):
        # 지지선 부근 매수: 현재가~20일선
        support = max(ma20 or price * 0.97, swing_low + atr)
        entry_low = round(min(price, support), 2)
        entry_high = round(price * 1.01, 2)
        # 손절: 구조적 지지 아래, 단 변동성 2.5배 이내로 캡 (과도한 손실 방지)
        struct_stop = swing_low - 0.5 * atr
        vol_cap = entry_low - 2.5 * atr
        stop = round(max(struct_stop, vol_cap), 2)
        # 목표: 직전 고점 회복 또는 측정 상승폭(3 ATR) 중 큰 값
        target = round(max(swing_high, price + 3 * atr), 2)
    elif setup["code"] == "breakout":
        entry_low = round(price * 0.995, 2)
        entry_high = round(price * 1.015, 2)
        # 돌파 실패 = 손절. 돌파레벨 약간 아래, 2.5 ATR 캡
        stop = round(max(swing_high * 0.97, price - 2.5 * atr), 2)
        target = round(price + 3.5 * atr, 2)
    # avoid / overheat / wait → 가격 미산정

    rr = None
    upside = downside = None
    if entry_low and target and stop:
        entry_ref = (entry_low + entry_high) / 2
        upside = round((target - entry_ref) / entry_ref * 100, 1)
        downside = round((entry_ref - stop) / entry_ref * 100, 1)
        if downside and downside > 0:
            rr = round(upside / downside, 1)

    return {
        "setup_code": setup["code"],
        "setup_label": setup["label"],
        "setup_grade": setup["grade"],
        "setup_desc": setup["desc"],
        "entry_low": entry_low,
        "entry_high": entry_high,
        "target": target,
        "stop": stop,
        "risk_reward": rr,
        "upside_pct": upside,
        "downside_pct": downside,
        "atr_pct": round(atr_pct, 1),
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
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

    # ── RSI: 과매도=매수기회, 과매수=주의, 단 강한 추세에서는 완화 ──────
    if current_rsi < 30:
        signals.append({"type": "bullish", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 과매도 구간 (강한 매수 기회)"})
        score += 15
    elif current_rsi < 50:
        signals.append({"type": "bullish", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 중립 하단 (추가 상승 여력)"})
        score += 5
    elif current_rsi <= 65:
        signals.append({"type": "neutral", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 건강한 상승 구간"})
        # 65 이하면 패널티 없음 — 모멘텀 인정
    elif current_rsi <= 75:
        signals.append({"type": "neutral", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 과열 주의, 단기 조정 가능"})
        score -= 5
    else:
        signals.append({"type": "bearish", "indicator": "RSI", "message": f"RSI {current_rsi:.1f} — 과매수 구간 (고점 주의)"})
        score -= 15

    # ── MACD ────────────────────────────────────────────────────────────
    if current_macd > current_signal and current_hist > 0:
        signals.append({"type": "bullish", "indicator": "MACD", "message": "MACD 골든크로스 — 상승 추세 확인"})
        score += 10
    elif current_macd < current_signal and current_hist < 0:
        signals.append({"type": "bearish", "indicator": "MACD", "message": "MACD 데드크로스 — 하락 추세"})
        score -= 10

    # ── 이동평균선 ───────────────────────────────────────────────────────
    ma20_val = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else None
    ma60_val = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else None
    ma120_val = float(ma120.iloc[-1]) if not pd.isna(ma120.iloc[-1]) else None

    if ma20_val and current_price > ma20_val:
        signals.append({"type": "bullish", "indicator": "MA20", "message": f"현재가 20일선({ma20_val:,.0f}) 위 — 단기 상승"})
        score += 5
    elif ma20_val:
        signals.append({"type": "bearish", "indicator": "MA20", "message": f"현재가 20일선({ma20_val:,.0f}) 아래 — 단기 약세"})
        score -= 5

    if ma60_val and current_price > ma60_val:
        signals.append({"type": "bullish", "indicator": "MA60", "message": "60일선 위 — 중기 상승 추세"})
        score += 5
    elif ma60_val:
        signals.append({"type": "bearish", "indicator": "MA60", "message": "60일선 아래 — 중기 약세"})
        score -= 5

    # ── 모멘텀: MA 정배열 (단기>중기>장기) = 추세 지속 신호 ──────────
    if ma20_val and ma60_val and ma120_val:
        if ma20_val > ma60_val > ma120_val and current_price > ma20_val:
            signals.append({"type": "bullish", "indicator": "추세", "message": "이동평균 정배열 — 강한 상승 추세 지속 중"})
            score += 12
        elif ma20_val < ma60_val < ma120_val and current_price < ma20_val:
            signals.append({"type": "bearish", "indicator": "추세", "message": "이동평균 역배열 — 하락 추세 지속"})
            score -= 12

    # ── 볼린저 밴드 ──────────────────────────────────────────────────────
    if current_price <= bb_lower:
        signals.append({"type": "bullish", "indicator": "BB", "message": "볼린저 밴드 하단 터치 — 반등 가능성"})
        score += 10
    elif current_price >= bb_upper:
        # 강한 모멘텀이면 BB 상단 돌파도 추세 신호 (패널티 완화)
        if current_macd > current_signal:
            signals.append({"type": "neutral", "indicator": "BB", "message": "볼린저 상단 돌파 + MACD 양호 — 강한 추세 (단기 과열 주의)"})
            score -= 3
        else:
            signals.append({"type": "bearish", "indicator": "BB", "message": "볼린저 밴드 상단 — 과매수, 조정 가능성"})
            score -= 10
    avg_vol = float(volume.rolling(20).mean().iloc[-1]) if not pd.isna(volume.rolling(20).mean().iloc[-1]) else 0
    current_vol = float(volume.iloc[-1])
    if avg_vol > 0 and current_vol > avg_vol * 1.5:
        signals.append({"type": "bullish", "indicator": "Volume", "message": f"거래량 급증 ({current_vol/avg_vol:.1f}x 평균)"})
        score += 5

    # ── 매매 셋업 계산 + 등급 반영 ──────────────────────────────────────
    _ind_for_setup = {
        "ma20": ma20_val, "ma60": ma60_val, "ma120": ma120_val, "rsi": current_rsi,
    }
    setup = compute_trade_setup(history, _ind_for_setup)
    grade_adj = {"A": 12, "B": 7, "C": 2, "D": -5, "F": -20}.get(setup["setup_grade"], 0)
    score += grade_adj
    # 손익비가 좋으면 가산점 (실전 핵심 지표)
    if setup.get("risk_reward"):
        if setup["risk_reward"] >= 3:   score += 6
        elif setup["risk_reward"] >= 2: score += 3
        elif setup["risk_reward"] < 1:  score -= 4

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
        "trade_setup": setup,
        "chart_data": chart_data,
    }
