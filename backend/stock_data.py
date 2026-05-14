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
            raw_name = krx_stock.get_market_ticker_name(ticker)
            name = raw_name if isinstance(raw_name, str) and raw_name.strip() else ticker
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
    """Search Korean stock tickers by name or ticker code."""
    # 빠른 검색을 위한 주요 KR 종목 내장 리스트
    KR_STOCKS = [
        ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035420", "NAVER"),
        ("005380", "현대차"), ("051910", "LG화학"), ("035720", "카카오"),
        ("000270", "기아"), ("068270", "셀트리온"), ("207940", "삼성바이오로직스"),
        ("006400", "삼성SDI"), ("028260", "삼성물산"), ("105560", "KB금융"),
        ("055550", "신한지주"), ("032830", "삼성생명"), ("003550", "LG"),
        ("017670", "SK텔레콤"), ("030200", "KT"), ("096770", "SK이노베이션"),
        ("009150", "삼성전기"), ("018260", "삼성에스디에스"), ("011200", "HMM"),
        ("033780", "KT&G"), ("010950", "S-Oil"), ("015760", "한국전력"),
        ("086790", "하나금융지주"), ("316140", "우리금융지주"), ("000810", "삼성화재"),
        ("012330", "현대모비스"), ("011170", "롯데케미칼"), ("051600", "한전KPS"),
        ("034730", "SK"), ("003490", "대한항공"), ("020150", "롯데케미칼"),
        ("009540", "HD한국조선해양"), ("042700", "한미반도체"), ("373220", "LG에너지솔루션"),
        ("247540", "에코프로비엠"), ("086520", "에코프로"), ("091990", "셀트리온헬스케어"),
    ]
    kw_lower = keyword.lower()
    results = [
        {"ticker": t, "name": n, "market": "KR"}
        for t, n in KR_STOCKS
        if kw_lower in n.lower() or keyword in t
    ]
    if results:
        return results[:10]

    # 내장 리스트에 없으면 pykrx로 검색
    try:
        tickers = krx_stock.get_market_ticker_list(market="ALL")
        for t in tickers:
            try:
                name = krx_stock.get_market_ticker_name(t)
                if isinstance(name, str) and (kw_lower in name.lower() or keyword in t):
                    results.append({"ticker": t, "name": name, "market": "KR"})
                    if len(results) >= 10:
                        break
            except Exception:
                continue
    except Exception:
        pass
    return results


def search_us_tickers(keyword: str) -> list[dict]:
    """Search US stock tickers using yfinance Search API + built-in list."""
    # 주요 US 종목 내장 리스트
    US_STOCKS = [
        ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corporation"), ("NVDA", "NVIDIA Corporation"),
        ("GOOGL", "Alphabet Inc."), ("AMZN", "Amazon.com Inc."), ("META", "Meta Platforms Inc."),
        ("TSLA", "Tesla Inc."), ("BRK-B", "Berkshire Hathaway"), ("UNH", "UnitedHealth Group"),
        ("LLY", "Eli Lilly and Company"), ("JPM", "JPMorgan Chase & Co."), ("V", "Visa Inc."),
        ("XOM", "Exxon Mobil Corporation"), ("MA", "Mastercard Inc."), ("AVGO", "Broadcom Inc."),
        ("PG", "Procter & Gamble Co."), ("JNJ", "Johnson & Johnson"), ("HD", "The Home Depot"),
        ("MRK", "Merck & Co."), ("CVX", "Chevron Corporation"), ("COST", "Costco Wholesale"),
        ("ABBV", "AbbVie Inc."), ("AMD", "Advanced Micro Devices"), ("NFLX", "Netflix Inc."),
        ("KO", "The Coca-Cola Company"), ("PEP", "PepsiCo Inc."), ("BAC", "Bank of America"),
        ("TMO", "Thermo Fisher Scientific"), ("ADBE", "Adobe Inc."), ("WMT", "Walmart Inc."),
        ("MCD", "McDonald's Corporation"), ("CRM", "Salesforce Inc."), ("ORCL", "Oracle Corporation"),
        ("ACN", "Accenture plc"), ("CSCO", "Cisco Systems"), ("IBM", "International Business Machines"),
        ("INTC", "Intel Corporation"), ("QCOM", "Qualcomm Inc."), ("TXN", "Texas Instruments"),
        ("PYPL", "PayPal Holdings"), ("UBER", "Uber Technologies"), ("ABNB", "Airbnb Inc."),
        ("DIS", "The Walt Disney Company"), ("NKE", "Nike Inc."), ("SBUX", "Starbucks Corporation"),
        ("BA", "Boeing Company"), ("GE", "GE Aerospace"), ("CAT", "Caterpillar Inc."),
        ("GS", "Goldman Sachs"), ("MS", "Morgan Stanley"), ("C", "Citigroup Inc."),
        ("PFE", "Pfizer Inc."), ("MRNA", "Moderna Inc."), ("AMGN", "Amgen Inc."),
        ("SPOT", "Spotify Technology"), ("SNOW", "Snowflake Inc."), ("PLTR", "Palantir Technologies"),
        ("ARM", "Arm Holdings"), ("SMCI", "Super Micro Computer"), ("MU", "Micron Technology"),
    ]
    kw_upper = keyword.upper()
    kw_lower = keyword.lower()
    results = [
        {"ticker": t, "name": n, "market": "US"}
        for t, n in US_STOCKS
        if kw_upper in t or kw_lower in n.lower()
    ]
    if results:
        return results[:10]

    # 내장 리스트에 없으면 yfinance Search 시도
    try:
        search = yf.Search(keyword, max_results=8)
        quotes = search.quotes if hasattr(search, "quotes") else []
        for q in quotes:
            symbol = q.get("symbol", "")
            name = q.get("shortname") or q.get("longname") or symbol
            exchange = q.get("exchange", "")
            # 미국 주식만 필터 (나스닥/NYSE)
            if exchange in ("NMS", "NYQ", "NGM", "PCX", "BTS") and symbol:
                results.append({"ticker": symbol, "name": name, "market": "US"})
        if results:
            return results[:10]
    except Exception:
        pass

    # 정확한 티커로 직접 조회
    try:
        info = yf.Ticker(kw_upper).info
        if info.get("longName"):
            return [{"ticker": kw_upper, "name": info["longName"], "market": "US"}]
    except Exception:
        pass

    return [{"ticker": kw_upper, "name": kw_upper, "market": "US"}]

