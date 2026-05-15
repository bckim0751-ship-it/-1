import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
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

# ── 후보 종목 — 유동성 높은 핵심 10개 ────────────────────────────────────
KR_CANDIDATES = [
    ("005930","삼성전자"), ("000660","SK하이닉스"), ("035420","NAVER"),
    ("005380","현대차"), ("000270","기아"), ("051910","LG화학"),
    ("035720","카카오"), ("105560","KB금융"), ("055550","신한지주"),
    ("373220","LG에너지솔루션"),
]

_cache: dict = {"kr": [], "us": [], "ts": 0, "computing": False,
                "progress": "", "error": "", "done": 0, "total": 0}
_CACHE_TTL = 10800


def _quick_score_kr(ticker: str, name: str) -> Optional[dict]:
    """pykrx만 직접 사용 — FDR/stooq 완전 우회, 펀더멘털 생략."""
    try:
        from pykrx import stock as krx_stock

        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=90)).strftime("%Y%m%d")

        raw = krx_stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        if raw is None or raw.empty or len(raw) < 20:
            return None

        # 컬럼 정규화 (시가/고가/저가/종가/거래량)
        cols = list(raw.columns)
        rename = {}
        for c in cols:
            cl = str(c)
            if "시가" in cl:   rename[c] = "Open"
            elif "고가" in cl: rename[c] = "High"
            elif "저가" in cl: rename[c] = "Low"
            elif "종가" in cl: rename[c] = "Close"
            elif "거래량" in cl: rename[c] = "Volume"
        raw = raw.rename(columns=rename)
        if "Close" not in raw.columns:
            return None

        close = raw["Close"].astype(float)
        current_price = float(close.iloc[-1])
        if current_price <= 0:
            return None

        # RSI 14
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        if rsi != rsi:  # NaN
            rsi = 50.0

        # 가격 변동률
        def pct(n):
            return float(close.pct_change(n).iloc[-1] * 100) if len(close) > n else 0.0

        p1d = pct(1)
        p1w = pct(5)
        p1m = pct(21) if len(close) > 21 else 0.0
        p3m = pct(63) if len(close) > 63 else 0.0

        # 간단 스코어링
        score = 50
        if rsi < 30:       score += 20
        elif rsi < 45:     score += 10
        elif rsi > 70:     score -= 15

        if -15 <= p1m <= -3:  score += 10   # 건전한 조정
        elif -3 < p1m <= 5:   score += 5    # 횡보/소폭 상승
        elif p1m < -20:       score -= 8    # 급락

        if -20 <= p3m <= -5:  score += 8

        if len(close) >= 20:
            ma20 = float(close.rolling(20).mean().iloc[-1])
            if current_price > ma20:  score += 5
            else:                     score -= 5

        score = max(0, min(100, score))
        rec = "BUY" if score >= 60 else ("SELL" if score <= 40 else "HOLD")

        return {
            "ticker": ticker, "name": name, "market": "KR",
            "current_price": current_price, "currency": "KRW",
            "combined_score": score, "recommendation": rec,
            "price_change_1d": round(p1d, 2),
            "price_change_1w": round(p1w, 2),
            "price_change_1m": round(p1m, 2),
            "price_change_3m": round(p3m, 2),
            "rsi": round(rsi, 1),
        }
    except Exception:
        return None


def _compute_top10():
    if _cache["computing"]:
        return
    _cache["computing"] = True
    _cache["error"] = ""
    _cache["done"] = 0
    _cache["total"] = len(KR_CANDIDATES)
    _cache["progress"] = "분석 시작..."
    kr_results = []
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_quick_score_kr, t, n): (t, n) for t, n in KR_CANDIDATES}
            for fut in as_completed(futures):
                try:
                    r = fut.result(timeout=20)
                    if r:
                        kr_results.append(r)
                except Exception:
                    pass
                _cache["done"] += 1
                _cache["progress"] = f"{_cache['done']}/{_cache['total']} 완료"
                if kr_results:
                    _cache["kr"] = sorted(kr_results, key=lambda x: x["combined_score"], reverse=True)[:10]

        _cache["kr"] = sorted(kr_results, key=lambda x: x["combined_score"], reverse=True)[:10]
        _cache["us"] = []
        _cache["ts"] = time.time()
        _cache["progress"] = f"완료 ({len(kr_results)}개 분석)"
    except Exception as e:
        _cache["error"] = str(e)
        _cache["progress"] = "오류 발생"
        if kr_results:
            _cache["kr"] = sorted(kr_results, key=lambda x: x["combined_score"], reverse=True)[:10]
            _cache["ts"] = time.time()
    finally:
        _cache["computing"] = False


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=_compute_top10, daemon=True).start()
    yield


app = FastAPI(title="BC_STOCK", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    idx = os.path.join(frontend_path, "index.html")
    return FileResponse(idx) if os.path.exists(idx) else {"message": "BC_STOCK"}


@app.get("/api/top10")
async def get_top10(refresh: bool = False):
    now = time.time()
    expired = now - _cache["ts"] > _CACHE_TTL
    if (expired or refresh) and not _cache["computing"]:
        threading.Thread(target=_compute_top10, daemon=True).start()
    return {
        "kr": _cache["kr"],
        "us": _cache["us"],
        "computing": _cache["computing"],
        "cached": bool(_cache["ts"]),
        "progress": _cache.get("progress", ""),
        "done": _cache.get("done", 0),
        "total": _cache.get("total", 0),
        "error": _cache.get("error", ""),
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


@app.get("/api/status")
async def status():
    return {
        "computing": _cache["computing"],
        "progress": _cache.get("progress", ""),
        "done": _cache.get("done", 0),
        "total": _cache.get("total", 0),
        "kr_count": len(_cache["kr"]),
        "cached": bool(_cache["ts"]),
        "error": _cache.get("error", ""),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "ai_enabled": bool(os.environ.get("ANTHROPIC_API_KEY"))}
