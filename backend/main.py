import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional

from stock_data import (
    get_us_stock_data, get_kr_stock_data,
    search_kr_tickers, search_us_tickers,
    KR_BUILTIN, US_BUILTIN,
)
from technical_analysis import analyze_technical
from fundamental_analysis import analyze_fundamental
from ai_recommendation import get_ai_recommendation

app = FastAPI(title="BC_STOCK", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# ── 후보 종목 ────────────────────────────────────────────────────────────────
KR_CANDIDATES = [t for t, _ in KR_BUILTIN[:30]]
US_CANDIDATES = [
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AMD","NFLX","JPM",
    "V","MA","AVGO","ORCL","CRM","ADBE","QCOM","MU","UBER","PLTR",
    "ARM","SMCI","SHOP","COIN","BAC","GS","XOM","LLY","UNH","COST",
]

_cache: dict = {"kr": None, "us": None, "ts": 0}
_CACHE_TTL = 10800  # 3시간


def _score_stock(ticker: str, market: str, name: str) -> Optional[dict]:
    """종목 하나를 분석하고 1~3개월 상승 가능성 점수와 함께 반환."""
    try:
        data = get_us_stock_data(ticker) if market == "US" else get_kr_stock_data(ticker)
        if "error" in data:
            return None

        hist = data["history"]
        if len(hist) < 60:
            return None

        tech = analyze_technical(hist)
        fund = analyze_fundamental(data["info"], market)
        price_changes = tech.get("price_changes", {})
        ind = tech.get("indicators", {})

        # 1~3개월 상승 가능성 보너스 점수
        bonus = 0
        rsi = ind.get("rsi", 50) or 50
        macd = ind.get("macd", 0) or 0
        macd_sig = ind.get("macd_signal", 0) or 0
        change_1m = price_changes.get("1m", 0) or 0
        change_3m = price_changes.get("3m", 0) or 0

        # RSI 과매도 회복 구간 (매수 타이밍)
        if 30 <= rsi <= 50:
            bonus += 15
        elif rsi < 30:
            bonus += 10

        # MACD 상향 돌파
        if macd > macd_sig and macd > 0:
            bonus += 10
        elif macd > macd_sig and macd < 0:
            bonus += 5  # 바닥에서 회복 중

        # 1개월 하락 후 반등 가능성 (역발상 투자)
        if -20 <= change_1m <= -5:
            bonus += 10
        elif -5 < change_1m <= 5:
            bonus += 5  # 횡보 후 돌파 대기

        # 3개월 기준 저점 회복 중
        if -30 <= change_3m <= -10:
            bonus += 8

        combined = round((tech["score"] + fund["score"]) / 2 + bonus * 0.3)
        combined = max(0, min(100, combined))

        rec = "BUY" if combined >= 62 else ("SELL" if combined <= 38 else "HOLD")

        return {
            "ticker": data["ticker"],
            "name": name or data["name"],
            "market": market,
            "current_price": data["current_price"],
            "currency": data["currency"],
            "combined_score": combined,
            "tech_score": tech["score"],
            "fund_score": fund["score"],
            "recommendation": rec,
            "price_change_1d": round(price_changes.get("1d", 0), 2),
            "price_change_1w": round(price_changes.get("1w", 0), 2),
            "price_change_1m": round(price_changes.get("1m", 0), 2),
            "price_change_3m": round(price_changes.get("3m", 0), 2),
            "rsi": round(rsi, 1),
        }
    except Exception:
        return None


def _build_top10(candidates: list[tuple], market: str, workers: int = 4) -> list[dict]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_score_stock, t, market, n): t for t, n in candidates}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)
    return sorted(results, key=lambda x: x["combined_score"], reverse=True)[:10]


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    idx = os.path.join(frontend_path, "index.html")
    return FileResponse(idx) if os.path.exists(idx) else {"message": "BC_STOCK"}


@app.get("/api/top10")
async def get_top10():
    """KR TOP10 + US TOP10 반환 (3시간 캐시)."""
    now = time.time()
    if _cache["kr"] and _cache["us"] and now - _cache["ts"] < _CACHE_TTL:
        return {"kr": _cache["kr"], "us": _cache["us"], "cached": True}

    kr_candidates = [(t, n) for t, n in KR_BUILTIN if t in KR_CANDIDATES]
    us_name_map = {t: n for t, n in __import__("stock_data").US_BUILTIN}
    us_candidates = [(t, us_name_map.get(t, t)) for t in US_CANDIDATES]

    # KR: 순차 처리(pykrx), US: 병렬(FDR/stooq)
    kr_top10 = _build_top10(kr_candidates, "KR", workers=3)
    us_top10 = _build_top10(us_candidates, "US", workers=5)

    _cache["kr"] = kr_top10
    _cache["us"] = us_top10
    _cache["ts"] = now
    return {"kr": kr_top10, "us": us_top10, "cached": False}


@app.get("/api/search")
async def search_stocks(query: str, market: Optional[str] = None):
    results = []
    if not market or market == "KR":
        results.extend(search_kr_tickers(query))
    if not market or market == "US":
        results.extend(search_us_tickers(query))
    return {"results": results}


@app.get("/api/analyze/{market}/{ticker}")
async def analyze_stock(market: str, ticker: str):
    market = market.upper()
    if market == "US":
        data = get_us_stock_data(ticker)
    elif market == "KR":
        data = get_kr_stock_data(ticker)
    else:
        raise HTTPException(400, "Market must be 'US' or 'KR'")

    if "error" in data:
        raise HTTPException(404, data["error"])

    tech = analyze_technical(data["history"])
    fund = analyze_fundamental(data["info"], market)
    ai = get_ai_recommendation(
        ticker=data["ticker"], name=data["name"], market=market,
        current_price=data["current_price"], currency=data["currency"],
        technical=tech, fundamental=fund,
        price_changes=tech.get("price_changes", {}),
    )
    combined_score = round((tech["score"] + fund["score"]) / 2)

    return {
        "ticker": data["ticker"], "name": data["name"],
        "market": market, "current_price": data["current_price"],
        "currency": data["currency"], "combined_score": combined_score,
        "technical": {
            "score": tech["score"], "signals": tech["signals"],
            "indicators": tech["indicators"], "price_changes": tech["price_changes"],
            "chart_data": tech["chart_data"],
        },
        "fundamental": {
            "score": fund["score"], "signals": fund["signals"],
            "metrics": fund["metrics"],
        },
        "ai_recommendation": ai,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "ai_enabled": bool(os.environ.get("ANTHROPIC_API_KEY"))}
