import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional

from stock_data import get_us_stock_data, get_kr_stock_data, search_kr_tickers, search_us_tickers
from technical_analysis import analyze_technical
from fundamental_analysis import analyze_fundamental
from ai_recommendation import get_ai_recommendation

app = FastAPI(title="BC_STOCK", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# Top5 종목 풀 (한국 + 미국 인기 종목)
TOP5_CANDIDATES = [
    ("US", "AAPL"), ("US", "MSFT"), ("US", "NVDA"), ("US", "TSLA"), ("US", "GOOGL"),
    ("US", "META"), ("US", "AMZN"), ("US", "AMD"),
    ("KR", "005930"), ("KR", "000660"), ("KR", "035420"), ("KR", "005380"), ("KR", "051910"),
]

# 1시간 캐시
_top5_cache: dict = {"data": None, "ts": 0}
_CACHE_TTL = 3600


def _analyze_one(market: str, ticker: str) -> Optional[dict]:
    try:
        data = get_us_stock_data(ticker) if market == "US" else get_kr_stock_data(ticker)
        if "error" in data:
            return None
        technical = analyze_technical(data["history"])
        fundamental = analyze_fundamental(data["info"], market)
        combined_score = round((technical["score"] + fundamental["score"]) / 2)
        price_changes = technical.get("price_changes", {})
        return {
            "ticker": data["ticker"],
            "name": data["name"],
            "market": market,
            "current_price": data["current_price"],
            "currency": data["currency"],
            "combined_score": combined_score,
            "technical_score": technical["score"],
            "fundamental_score": fundamental["score"],
            "recommendation": "BUY" if combined_score >= 60 else ("SELL" if combined_score <= 40 else "HOLD"),
            "price_change_1d": price_changes.get("1d", 0),
            "price_change_1m": price_changes.get("1m", 0),
        }
    except Exception:
        return None


@app.get("/")
async def root():
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "BC_STOCK API", "docs": "/docs"}


@app.get("/api/top5")
async def get_top5():
    """병렬로 후보 종목 분석 후 종합점수 상위 5개 반환 (1시간 캐시)."""
    now = time.time()
    if _top5_cache["data"] and now - _top5_cache["ts"] < _CACHE_TTL:
        return {"stocks": _top5_cache["data"], "cached": True}

    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_analyze_one, m, t): (m, t) for m, t in TOP5_CANDIDATES}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    top5 = sorted(results, key=lambda x: x["combined_score"], reverse=True)[:5]
    _top5_cache["data"] = top5
    _top5_cache["ts"] = now
    return {"stocks": top5, "cached": False}


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
        raise HTTPException(status_code=400, detail="Market must be 'US' or 'KR'")

    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])

    technical = analyze_technical(data["history"])
    fundamental = analyze_fundamental(data["info"], market)

    ai = get_ai_recommendation(
        ticker=data["ticker"],
        name=data["name"],
        market=market,
        current_price=data["current_price"],
        currency=data["currency"],
        technical=technical,
        fundamental=fundamental,
        price_changes=technical.get("price_changes", {}),
    )

    combined_score = round((technical["score"] + fundamental["score"]) / 2)

    return {
        "ticker": data["ticker"],
        "name": data["name"],
        "market": market,
        "current_price": data["current_price"],
        "currency": data["currency"],
        "combined_score": combined_score,
        "technical": {
            "score": technical["score"],
            "signals": technical["signals"],
            "indicators": technical["indicators"],
            "price_changes": technical["price_changes"],
            "chart_data": technical["chart_data"],
        },
        "fundamental": {
            "score": fundamental["score"],
            "signals": fundamental["signals"],
            "metrics": fundamental["metrics"],
        },
        "ai_recommendation": ai,
    }


@app.get("/api/health")
async def health():
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {"status": "ok", "ai_enabled": has_api_key}
