import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
import yfinance as yf

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

# Top5 종목 풀 — 한국 + 미국 주요 종목 30개
TOP5_CANDIDATES = [
    ("US", "AAPL"), ("US", "MSFT"), ("US", "NVDA"), ("US", "TSLA"), ("US", "GOOGL"),
    ("US", "META"), ("US", "AMZN"), ("US", "AMD"), ("US", "NFLX"), ("US", "JPM"),
    ("US", "V"), ("US", "MA"), ("US", "AVGO"), ("US", "ORCL"), ("US", "CRM"),
    ("KR", "005930"), ("KR", "000660"), ("KR", "035420"), ("KR", "005380"), ("KR", "051910"),
    ("KR", "035720"), ("KR", "000270"), ("KR", "068270"), ("KR", "373220"), ("KR", "086520"),
    ("KR", "042700"), ("KR", "009540"), ("KR", "105560"), ("KR", "055550"), ("KR", "003550"),
]

KR_NAME_MAP = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
    "005380": "현대차", "051910": "LG화학", "035720": "카카오",
    "000270": "기아", "068270": "셀트리온", "207940": "삼성바이오로직스",
    "006400": "삼성SDI", "028260": "삼성물산", "105560": "KB금융",
    "055550": "신한지주", "032830": "삼성생명", "003550": "LG",
    "017670": "SK텔레콤", "030200": "KT", "096770": "SK이노베이션",
    "373220": "LG에너지솔루션", "086520": "에코프로", "042700": "한미반도체",
    "009540": "HD한국조선해양", "247540": "에코프로비엠", "091990": "셀트리온헬스케어",
}

# 3시간 캐시
_top5_cache: dict = {"data": None, "ts": 0}
_CACHE_TTL = 10800

US_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "META", "AMZN", "AMD", "NFLX", "JPM", "V", "AVGO", "ORCL", "CRM", "MA"]
KR_TICKERS = ["005930", "000660", "035420", "005380", "051910", "035720", "000270", "068270", "373220", "086520", "042700", "009540", "105560", "055550", "003550"]

US_NAME_MAP = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "TSLA": "Tesla",
    "GOOGL": "Alphabet", "META": "Meta", "AMZN": "Amazon", "AMD": "AMD",
    "NFLX": "Netflix", "JPM": "JPMorgan", "V": "Visa", "AVGO": "Broadcom",
    "ORCL": "Oracle", "CRM": "Salesforce", "MA": "Mastercard",
}


def _fetch_us_batch() -> list[dict]:
    """미국 종목 전체를 yf.download 단일 호출로 가져와 429 회피."""
    try:
        raw = yf.download(
            US_TICKERS, period="1y", auto_adjust=True,
            group_by="ticker", progress=False, threads=False
        )
        results = []
        for ticker in US_TICKERS:
            try:
                if len(US_TICKERS) == 1:
                    hist = raw
                else:
                    hist = raw[ticker].dropna()
                if hist.empty or len(hist) < 30:
                    continue
                hist.columns = [c if isinstance(c, str) else c[0] for c in hist.columns]
                technical = analyze_technical(hist)
                score = technical["score"]
                price_changes = technical.get("price_changes", {})
                results.append({
                    "ticker": ticker,
                    "name": US_NAME_MAP.get(ticker, ticker),
                    "market": "US",
                    "current_price": round(float(hist["Close"].iloc[-1]), 2),
                    "currency": "USD",
                    "combined_score": score,
                    "recommendation": "BUY" if score >= 60 else ("SELL" if score <= 40 else "HOLD"),
                    "price_change_1d": price_changes.get("1d", 0),
                    "price_change_1m": price_changes.get("1m", 0),
                })
            except Exception:
                continue
        return results
    except Exception:
        return []


def _analyze_kr_one(ticker: str) -> Optional[dict]:
    try:
        data = get_kr_stock_data(ticker)
        if "error" in data:
            return None
        name = KR_NAME_MAP.get(ticker, data["name"])
        technical = analyze_technical(data["history"])
        fundamental = analyze_fundamental(data["info"], "KR")
        combined_score = round((technical["score"] + fundamental["score"]) / 2)
        price_changes = technical.get("price_changes", {})
        return {
            "ticker": ticker,
            "name": name,
            "market": "KR",
            "current_price": data["current_price"],
            "currency": "KRW",
            "combined_score": combined_score,
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
    """미국은 batch 다운로드, 한국은 순차 분석 후 TOP5 반환 (3시간 캐시)."""
    now = time.time()
    if _top5_cache["data"] and now - _top5_cache["ts"] < _CACHE_TTL:
        return {"stocks": _top5_cache["data"], "cached": True}

    # 미국: 단일 batch 요청 (429 방지)
    us_results = _fetch_us_batch()

    # 한국: 순차 처리 (pykrx rate limit 고려)
    kr_results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_analyze_kr_one, t): t for t in KR_TICKERS}
        for future in as_completed(futures):
            result = future.result()
            if result:
                kr_results.append(result)

    all_results = us_results + kr_results
    top5 = sorted(all_results, key=lambda x: x["combined_score"], reverse=True)[:5]
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
