import yfinance as yf
import pandas as pd
try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False
from pykrx import stock as krx_stock
from datetime import datetime, timedelta


def _normalize_hist(hist: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to Open/High/Low/Close/Volume."""
    hist = hist.copy()
    hist.columns = [str(c).strip().capitalize() for c in hist.columns]
    rename = {}
    for c in hist.columns:
        cl = c.lower()
        if cl in ("open", "시가"):      rename[c] = "Open"
        elif cl in ("high", "고가"):    rename[c] = "High"
        elif cl in ("low", "저가"):     rename[c] = "Low"
        elif cl in ("close", "종가"):   rename[c] = "Close"
        elif cl in ("volume", "거래량"): rename[c] = "Volume"
    hist = hist.rename(columns=rename)
    needed = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in hist.columns]
    hist = hist[needed].copy()
    hist.index = pd.to_datetime(hist.index)
    hist = hist.sort_index().dropna()
    return hist


def _get_fdr(ticker: str, period_days: int = 400) -> pd.DataFrame:
    if not FDR_AVAILABLE:
        return pd.DataFrame()
    end = datetime.today()
    start = end - timedelta(days=period_days)
    try:
        hist = fdr.DataReader(ticker, start, end)
        if hist.empty:
            return pd.DataFrame()
        return _normalize_hist(hist)
    except Exception:
        return pd.DataFrame()


def get_us_stock_data(ticker: str, period: str = "1y") -> dict:
    ticker = ticker.upper()
    # Try FinanceDataReader first (stooq source, no rate limit)
    hist = _get_fdr(ticker)
    if hist.empty:
        # Fallback: yfinance
        try:
            t = yf.Ticker(ticker)
            raw = t.history(period=period)
            if not raw.empty:
                hist = _normalize_hist(raw)
        except Exception:
            pass

    if hist.empty or len(hist) < 20:
        return {"error": f"No price data for {ticker}"}

    # Fundamental data via yfinance (best-effort)
    info = {}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        pass

    name = info.get("longName") or info.get("shortName") or ticker
    current_price = float(hist["Close"].iloc[-1])

    return {
        "ticker": ticker, "market": "US", "name": name,
        "history": hist, "info": info,
        "current_price": current_price, "currency": "USD",
    }


def get_kr_stock_data(ticker: str, period_days: int = 400) -> dict:
    # Try FinanceDataReader first
    hist = _get_fdr(ticker, period_days)

    if hist.empty:
        # Fallback: pykrx
        try:
            end_date = datetime.today().strftime("%Y%m%d")
            start_date = (datetime.today() - timedelta(days=period_days)).strftime("%Y%m%d")
            raw = krx_stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
            if not raw.empty:
                col_map = {raw.columns[i]: n for i, n in enumerate(["Open","High","Low","Close","Volume"]) if i < len(raw.columns)}
                raw = raw.rename(columns=col_map)[["Open","High","Low","Close","Volume"]]
                raw.index = pd.to_datetime(raw.index)
                hist = raw.sort_index().dropna()
        except Exception:
            pass

    if hist.empty or len(hist) < 20:
        return {"error": f"No price data for KR {ticker}"}

    # Name
    name = ticker
    try:
        raw_name = krx_stock.get_market_ticker_name(ticker)
        if isinstance(raw_name, str) and raw_name.strip():
            name = raw_name.strip()
    except Exception:
        pass

    # Fundamental
    fundamental = {}
    try:
        today = datetime.today().strftime("%Y%m%d")
        df = krx_stock.get_market_fundamental_by_ticker(today, market="ALL")
        if ticker in df.index:
            row = df.loc[ticker]
            fundamental = {
                "trailingPE":   float(row.get("PER", 0)) or None,
                "priceToBook":  float(row.get("PBR", 0)) or None,
                "dividendYield": (float(row.get("DIV", 0)) / 100) or None,
                "eps": float(row.get("EPS", 0)) or None,
            }
    except Exception:
        pass

    return {
        "ticker": ticker, "market": "KR", "name": name,
        "history": hist, "info": fundamental,
        "current_price": float(hist["Close"].iloc[-1]), "currency": "KRW",
    }


# ── Search ──────────────────────────────────────────────────────────────────

KR_BUILTIN = [
    ("005930","삼성전자"),("000660","SK하이닉스"),("035420","NAVER"),("005380","현대차"),
    ("051910","LG화학"),("035720","카카오"),("000270","기아"),("068270","셀트리온"),
    ("207940","삼성바이오로직스"),("006400","삼성SDI"),("028260","삼성물산"),("105560","KB금융"),
    ("055550","신한지주"),("032830","삼성생명"),("003550","LG"),("017670","SK텔레콤"),
    ("030200","KT"),("096770","SK이노베이션"),("009150","삼성전기"),("003490","대한항공"),
    ("000810","삼성화재"),("012330","현대모비스"),("316140","우리금융지주"),("086790","하나금융지주"),
    ("373220","LG에너지솔루션"),("086520","에코프로"),("042700","한미반도체"),("009540","HD한국조선해양"),
    ("247540","에코프로비엠"),("091990","셀트리온헬스케어"),("033780","KT&G"),("010950","S-Oil"),
    ("015760","한국전력"),("011200","HMM"),("000720","현대건설"),("010140","삼성중공업"),
]

US_BUILTIN = [
    ("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("GOOGL","Alphabet"),
    ("AMZN","Amazon"),("META","Meta"),("TSLA","Tesla"),("BRK-B","Berkshire Hathaway"),
    ("UNH","UnitedHealth"),("LLY","Eli Lilly"),("JPM","JPMorgan"),("V","Visa"),
    ("XOM","Exxon Mobil"),("MA","Mastercard"),("AVGO","Broadcom"),("PG","P&G"),
    ("JNJ","Johnson & Johnson"),("HD","Home Depot"),("MRK","Merck"),("CVX","Chevron"),
    ("COST","Costco"),("ABBV","AbbVie"),("AMD","AMD"),("NFLX","Netflix"),
    ("KO","Coca-Cola"),("PEP","PepsiCo"),("BAC","Bank of America"),("ADBE","Adobe"),
    ("WMT","Walmart"),("MCD","McDonald's"),("CRM","Salesforce"),("ORCL","Oracle"),
    ("ACN","Accenture"),("CSCO","Cisco"),("IBM","IBM"),("INTC","Intel"),
    ("QCOM","Qualcomm"),("TXN","Texas Instruments"),("PYPL","PayPal"),("UBER","Uber"),
    ("ABNB","Airbnb"),("DIS","Disney"),("NKE","Nike"),("SBUX","Starbucks"),
    ("BA","Boeing"),("GE","GE Aerospace"),("CAT","Caterpillar"),("GS","Goldman Sachs"),
    ("MS","Morgan Stanley"),("MRNA","Moderna"),("AMGN","Amgen"),("PLTR","Palantir"),
    ("ARM","Arm Holdings"),("SMCI","Super Micro"),("MU","Micron"),("SNOW","Snowflake"),
    ("SHOP","Shopify"),("SQ","Block"),("COIN","Coinbase"),("MSTR","MicroStrategy"),
]


def search_kr_tickers(keyword: str) -> list[dict]:
    kl = keyword.lower()
    results = [{"ticker": t, "name": n, "market": "KR"} for t, n in KR_BUILTIN
               if kl in n.lower() or keyword in t]
    if results:
        return results[:10]
    try:
        for t in krx_stock.get_market_ticker_list(market="ALL"):
            try:
                n = krx_stock.get_market_ticker_name(t)
                if isinstance(n, str) and (kl in n.lower() or keyword in t):
                    results.append({"ticker": t, "name": n, "market": "KR"})
                    if len(results) >= 10:
                        break
            except Exception:
                continue
    except Exception:
        pass
    return results


def search_us_tickers(keyword: str) -> list[dict]:
    ku, kl = keyword.upper(), keyword.lower()
    results = [{"ticker": t, "name": n, "market": "US"} for t, n in US_BUILTIN
               if ku in t or kl in n.lower()]
    if results:
        return results[:10]
    try:
        import json as _j
        s = yf.Search(keyword, max_results=8)
        for q in (s.quotes if hasattr(s, "quotes") else []):
            sym = q.get("symbol", "")
            if q.get("exchange", "") in ("NMS","NYQ","NGM","PCX","NAS") and sym:
                results.append({"ticker": sym, "name": q.get("shortname") or sym, "market": "US"})
        if results:
            return results[:10]
    except Exception:
        pass
    return [{"ticker": ku, "name": ku, "market": "US"}]
