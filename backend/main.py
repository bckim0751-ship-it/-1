import os
import time
import threading
import pandas as pd
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
    _get_yahoo_direct, _get_fdr,
    search_kr_tickers, search_us_tickers,
    KR_BUILTIN, US_BUILTIN,
)
from technical_analysis import analyze_technical
from fundamental_analysis import analyze_fundamental
from ai_recommendation import get_ai_recommendation

# ── 후보 종목 ─────────────────────────────────────────────────────────────
KR_CANDIDATES = [
    ("005930", "삼성전자"),   ("000660", "SK하이닉스"),  ("035420", "NAVER"),
    ("005380", "현대차"),     ("000270", "기아"),         ("051910", "LG화학"),
    ("035720", "카카오"),     ("105560", "KB금융"),       ("055550", "신한지주"),
    ("373220", "LG에너지솔루션"),
]

_cache: dict = {
    "kr": [], "us": [], "ts": 0, "computing": False,
    "progress": "", "error": "", "done": 0, "total": 0,
}
_CACHE_TTL = 10800


def _fetch_kr_ohlcv(ticker: str) -> pd.DataFrame:
    """세 가지 소스를 순서대로 시도해 OHLCV DataFrame 반환.
    순서: pykrx(Render에서 검증됨) → Yahoo .KS(curl_cffi) → FDR(8s 타임아웃)
    """

    # 1) pykrx — Render 싱가포르에서 KRX 직접 접속 가능, 검증된 소스
    try:
        from pykrx import stock as krx_stock
        end = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=120)).strftime("%Y%m%d")
        raw = krx_stock.get_market_ohlcv_by_date(start, end, ticker)
        if raw is not None and not raw.empty:
            rename = {}
            for c in raw.columns:
                s = str(c)
                if "시가" in s:    rename[c] = "Open"
                elif "고가" in s:  rename[c] = "High"
                elif "저가" in s:  rename[c] = "Low"
                elif "종가" in s:  rename[c] = "Close"
                elif "거래량" in s: rename[c] = "Volume"
            raw = raw.rename(columns=rename)
            if "Close" in raw.columns:
                raw.index = pd.to_datetime(raw.index)
                h = raw[["Close"] + [c for c in ["Open","High","Low","Volume"] if c in raw.columns]].dropna()
                if len(h) >= 20:
                    return h
    except Exception:
        pass

    # 2) Yahoo Finance .KS (curl_cffi Chrome 위장 — 글로벌 접속 가능)
    try:
        h = _get_yahoo_direct(ticker + ".KS", period="6mo")
        if not h.empty and len(h) >= 20:
            return h
    except Exception:
        pass

    # 3) FDR — 짧은 별도 스레드로 타임아웃 제어
    try:
        result = [pd.DataFrame()]
        def _fdr_fetch():
            try:
                result[0] = _get_fdr(ticker, period_days=90)
            except Exception:
                pass
        t = threading.Thread(target=_fdr_fetch, daemon=True)
        t.start()
        t.join(timeout=8)  # 8초 이내에 응답 없으면 포기
        if not result[0].empty and len(result[0]) >= 20:
            return result[0]
    except Exception:
        pass

    return pd.DataFrame()


def _quick_score_kr(ticker: str, name: str) -> Optional[dict]:
    try:
        hist = _fetch_kr_ohlcv(ticker)
        if hist.empty:
            return None

        close = hist["Close"].astype(float)
        current_price = float(close.iloc[-1])
        if current_price <= 0:
            return None

        # RSI 14
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi_series = 100 - 100 / (1 + rs)
        rsi = float(rsi_series.iloc[-1])
        if rsi != rsi:  # NaN guard
            rsi = 50.0

        def pct(n: int) -> float:
            return float(close.pct_change(n).iloc[-1] * 100) if len(close) > n else 0.0

        p1d = pct(1)
        p1w = pct(5)
        p1m = pct(21) if len(close) > 21 else 0.0
        p3m = pct(63) if len(close) > 63 else 0.0

        # 간단 스코어
        score = 50
        if rsi < 30:         score += 20
        elif rsi < 45:       score += 10
        elif rsi > 70:       score -= 15

        if -15 <= p1m <= -3: score += 10
        elif -3 < p1m <= 5:  score += 5
        elif p1m < -20:      score -= 8

        if -20 <= p3m <= -5: score += 8

        if len(close) >= 20:
            ma20 = float(close.rolling(20).mean().iloc[-1])
            score += 5 if current_price > ma20 else -5

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
            futures = {
                pool.submit(_quick_score_kr, t, n): (t, n)
                for t, n in KR_CANDIDATES
            }
            for fut in as_completed(futures):
                t, n = futures[fut]
                try:
                    r = fut.result(timeout=25)
                    if r:
                        kr_results.append(r)
                except Exception:
                    pass
                _cache["done"] += 1
                _cache["progress"] = f"{_cache['done']}/{_cache['total']} 완료"
                if kr_results:
                    _cache["kr"] = sorted(
                        kr_results, key=lambda x: x["combined_score"], reverse=True
                    )[:10]

        if kr_results:
            _cache["kr"] = sorted(
                kr_results, key=lambda x: x["combined_score"], reverse=True
            )[:10]
            _cache["us"] = []
            _cache["ts"] = time.time()          # 결과 있을 때만 타임스탬프 업데이트
            _cache["progress"] = f"완료 ({len(kr_results)}개 분석)"
        else:
            _cache["error"] = "데이터를 가져오지 못했습니다. 잠시 후 새로고침 해주세요."
            _cache["progress"] = "데이터 없음"
            # ts를 업데이트하지 않아 다음 폴링에서 자동 재시도됨

    except Exception as e:
        _cache["error"] = str(e)
        _cache["progress"] = "오류 발생"
        if kr_results:
            _cache["kr"] = sorted(
                kr_results, key=lambda x: x["combined_score"], reverse=True
            )[:10]
            _cache["ts"] = time.time()
    finally:
        _cache["computing"] = False


def _keep_alive():
    """Render 무료 플랜 슬립 방지 — 10분마다 자기 자신에게 헬스체크."""
    import requests as _req
    port = os.environ.get("PORT", "10000")
    url = f"http://localhost:{port}/api/health"
    while True:
        time.sleep(600)  # 10분
        try:
            _req.get(url, timeout=5)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    # 서버 시작 시 즉시 계산
    threading.Thread(target=_compute_top10, daemon=True).start()

    # 매일 오전 8:00 KST (= 23:00 UTC) 에 자동 갱신 — 장 개장(9시) 전 준비
    kst = pytz.timezone("Asia/Seoul")
    scheduler = BackgroundScheduler(timezone=kst)
    scheduler.add_job(
        _compute_top10,
        CronTrigger(hour=8, minute=0, timezone=kst),
        id="daily_refresh",
        replace_existing=True,
    )
    scheduler.start()

    # Render 무료 플랜 슬립 방지
    threading.Thread(target=_keep_alive, daemon=True).start()

    yield
    scheduler.shutdown(wait=False)


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
    expired = (now - _cache["ts"] > _CACHE_TTL) or (_cache["ts"] == 0)
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
    """디버그용: 현재 캐시/계산 상태 확인."""
    return {
        "computing": _cache["computing"],
        "progress": _cache.get("progress", ""),
        "done": _cache.get("done", 0),
        "total": _cache.get("total", 0),
        "kr_count": len(_cache["kr"]),
        "cached": bool(_cache["ts"]),
        "error": _cache.get("error", ""),
        "cache_age_sec": round(time.time() - _cache["ts"]) if _cache["ts"] else None,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "ai_enabled": bool(os.environ.get("ANTHROPIC_API_KEY"))}
