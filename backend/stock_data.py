import yfinance as yf
import pandas as pd
from pykrx import stock as krx_stock
from datetime import datetime, timedelta
from typing import Optional


def get_us_stock_data(ticker: str, period: str = "1y") -> dict:
    """Fetch US stock data using yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        hist = ticker_obj.history(period=period)
        info = ticker_obj.info

        if hist.empty:
            return {"error": f"No data found for ticker {ticker}"}

        return {
            "ticker": ticker.upper(),
            "market": "US",
            "name": info.get("longName", ticker.upper()),
            "history": hist,
            "info": info,
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice") or float(hist["Close"].iloc[-1]),
            "currency": info.get("currency", "USD"),
        }
    except Exception as e:
        return {"error": str(e)}


def get_kr_stock_data(ticker: str, period_days: int = 365) -> dict:
    """Fetch Korean stock data using pykrx."""
    try:
        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=period_days)).strftime("%Y%m%d")

        # Try to get ticker name
        try:
            name = str(krx_stock.get_market_ticker_name(ticker))
        except Exception:
            name = ticker

        hist = krx_stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        if hist.empty:
            return {"error": f"No data found for KR ticker {ticker}"}

        hist.index = pd.to_datetime(hist.index)
        col_map = {hist.columns[0]: "Open", hist.columns[1]: "High", hist.columns[2]: "Low", hist.columns[3]: "Close", hist.columns[4]: "Volume"}
        hist = hist.rename(columns=col_map)[["Open", "High", "Low", "Close", "Volume"]]

        # Fundamental data
        fundamental = _get_kr_fundamental(ticker)

        current_price = float(hist["Close"].iloc[-1])

        return {
            "ticker": ticker,
            "market": "KR",
            "name": name,
            "history": hist,
            "info": fundamental,
            "current_price": current_price,
            "currency": "KRW",
        }
    except Exception as e:
        return {"error": str(e)}


def _get_kr_fundamental(ticker: str) -> dict:
    """Fetch Korean stock fundamental data."""
    try:
        today = datetime.today().strftime("%Y%m%d")
        df = krx_stock.get_market_fundamental_by_ticker(today, market="ALL")
        if ticker in df.index:
            row = df.loc[ticker]
            return {
                "trailingPE": float(row.get("PER", 0)) if row.get("PER", 0) != 0 else None,
                "priceToBook": float(row.get("PBR", 0)) if row.get("PBR", 0) != 0 else None,
                "dividendYield": float(row.get("DIV", 0)) / 100 if row.get("DIV", 0) != 0 else None,
                "eps": float(row.get("EPS", 0)) if row.get("EPS", 0) != 0 else None,
                "bps": float(row.get("BPS", 0)) if row.get("BPS", 0) != 0 else None,
            }
    except Exception:
        pass
    return {}


def search_kr_tickers(keyword: str) -> list[dict]:
    """Search Korean stock tickers by name."""
    try:
        tickers = krx_stock.get_market_ticker_list(market="ALL")
        results = []
        for t in tickers:
            try:
                name = krx_stock.get_market_ticker_name(t)
                if keyword.lower() in name.lower() or keyword in t:
                    results.append({"ticker": t, "name": name, "market": "KR"})
                    if len(results) >= 10:
                        break
            except Exception:
                continue
        return results
    except Exception as e:
        return []


def search_us_tickers(keyword: str) -> list[dict]:
    """Search US stock tickers using yfinance."""
    try:
        ticker_obj = yf.Ticker(keyword.upper())
        info = ticker_obj.info
        if info.get("longName"):
            return [{"ticker": keyword.upper(), "name": info["longName"], "market": "US"}]
    except Exception:
        pass
    return [{"ticker": keyword.upper(), "name": keyword.upper(), "market": "US"}]
