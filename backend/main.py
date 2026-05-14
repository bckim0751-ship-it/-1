import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
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

# ── 후보 종목 (줄여서 속도 확보) ───────────────────────────────────────────
KR_CANDIDATES = [(t, n) for t, n in KR_BUILTIN[:20]]
US_CANDIDATES = [
    ("AAPL","Apple"), ("MSFT","Microsoft"), ("NVDA","NVIDIA"), ("GOOGL","Alphabet"),
    ("META","Meta"), ("AMZN","Amazon"), ("TSLA","Tesla"), ("AMD","AMD"),
    ("NFLX","Netflix"), ("JPM","JPMorgan"), ("V","Visa"), ("AVGO","Broadcom"),
    ("ORCL","Oracle"), ("MU","Micron"), ("PLTR","Palantir"),
    ("QCOM","Qualcomm"), ("ADBE","Adobe"), ("CRM","Salesforce"),
    ("UBER","Uber"), ("ARM","Arm Holdings"),
]

_cache: dict = {"kr": [], "us": [], "ts": 0, "computing": False}
_CACHE_TTL = 10800


def _score_stock(ticker: str, market: str, name: str) -> Optional[dict]:
    try:
        data = get_us_stock_data(ticker) if market == "US" else get_kr_stock_data(ticker)
        if "error" in data or len(data.get("history", [])) < 60:
            return None
        tech = analyze_technical(data["history"])
        fund = analyze_fundamental(data["info"], market)
        pc = tech.get("price_changes", {})
        ind = tech.get("indicators", {})
        rsi = ind.get("rsi") or 50
        macd = ind.get("macd") or 0
        macd_sig = ind.get("macd_signal") or 0
        m1 = pc.get("1m") or 0
        m3 = pc.get("3m") or 0
        bonus = 0
        if 30 <= rsi <= 50: bonus += 15
        elif rsi < 30: bonus += 10
        if macd > macd_sig: bonus += 10 if macd > 0 else 5
        if -20 <= m1 <= -5: bonus += 10
        elif -5 < m1 <= 5: bonus += 5
        if -30 <= m3 <= -10: bonus += 8
        score = max(0, min(100, round((tech["score"] + fund["score"]) / 2 + bonus * 0.3)))
        return {
            "ticker": data["ticker"], "name": name or data["name"],
            "market": market, "current_price": data["current_price"],
            "currency": data["currency"], "combined_score": score,
            "recommendation": "BUY" if score >= 62 else ("SELL" if score <= 38 else "HOLD"),
            "price_change_1d": round(pc.get("1d") or 0, 2),
            "price_change_1w": round(pc.get("1w") or 0, 2),
            "price_change_1m": round(m1, 2),
            "price_change_3m": round(m3, 2),
            "rsi": round(rsi, 1),
        }
    except Exception:
        return None


def _compute_top10():
    """백그라운드에서 실행 — 완료되면 캐시에 저장."""
    if _cache["computing"]:
        return
    _cache["computing"] = True
    try:
        kr_results, us_results = [], []
        # KR: 워커 3개
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(_score_stock, t, "KR", n): t for t, n in KR_CANDIDATES}
            for f in as_completed(futures):
                r = f.result()
                if r: kr_results.append(r)
        # US: 워커 4개
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(_score_stock, t, "US", n): t for t, n in US_CANDIDATES}
            for f in as_completed(futures):
                r = f.result()
                if r: us_results.append(r)
        _cache["kr"] = sorted(kr_results, key=lambda x: x["combined_score"], reverse=True)[:10]
        _cache["us"] = sorted(us_results, key=lambda x: x["combined_score"], reverse=True)[:10]
        _cache["ts"] = time.time()
    finally:
        _cache["computing"] = False


@asynccontextmanager
async def lifespan(app):
    # 서버 시작 시 백그라운드에서 TOP10 미리 계산
    threading.Thread(target=_compute_top10, daemon=True).start()
    yield


app = FastAPI(title="BC_STOCK", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    idx = os.path.join(frontend_path, "index.html")
    return FileResponse(idx) if os.path.exists(idx) else {"message": "BC_STOCK"}


@app.get("/api/top10")
async def get_top10(refresh: bool = False):
    """캐시된 TOP10 즉시 반환. 만료됐거나 refresh=true면 백그라운드 재계산 트리거."""
    now = time.time()
    expired = now - _cache["ts"] > _CACHE_TTL

    if (expired or refresh) and not _cache["computing"]:
        threading.Thread(target=_compute_top10, daemon=True).start()

    return {
        "kr": _cache["kr"],
        "us": _cache["us"],
        "computing": _cache["computing"],
        "cached": bool(_cache["ts"]),
    }


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
