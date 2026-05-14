import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from stock_data import get_us_stock_data, get_kr_stock_data, search_kr_tickers, search_us_tickers
from technical_analysis import analyze_technical
from fundamental_analysis import analyze_fundamental
from ai_recommendation import get_ai_recommendation

app = FastAPI(title="Stock Recommendation System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/")
async def root():
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Stock Recommendation API", "docs": "/docs"}


@app.get("/api/search")
async def search_stocks(query: str, market: Optional[str] = None):
    """Search for stocks by ticker or name."""
    results = []
    if not market or market == "KR":
        results.extend(search_kr_tickers(query))
    if not market or market == "US":
        results.extend(search_us_tickers(query))
    return {"results": results}


@app.get("/api/analyze/{market}/{ticker}")
async def analyze_stock(market: str, ticker: str):
    """Full analysis: technical + fundamental + AI recommendation."""
    market = market.upper()

    if market == "US":
        data = get_us_stock_data(ticker)
    elif market == "KR":
        data = get_kr_stock_data(ticker)
    else:
        raise HTTPException(status_code=400, detail="Market must be 'US' or 'KR'")

    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])

    history = data["history"]
    info = data["info"]

    technical = analyze_technical(history)
    fundamental = analyze_fundamental(info, market)

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
