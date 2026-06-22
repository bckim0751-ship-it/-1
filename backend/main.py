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
    _get_kr_investor_flow, analyze_investor_flow,
    search_kr_tickers, search_us_tickers,
    KR_BUILTIN, US_BUILTIN,
)
from technical_analysis import analyze_technical
from fundamental_analysis import analyze_fundamental
from ai_recommendation import get_ai_recommendation

# ── 후보 종목 — 섹터 대표 + 모멘텀 종목 포함 20개 ──────────────────────
KR_CANDIDATES = [
    # 반도체·전자
    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("009150", "삼성전기"),
    ("042700", "한미반도체"), ("086520", "에코프로"),
    # 자동차
    ("005380", "현대차"), ("000270", "기아"),
    # 인터넷·플랫폼
    ("035420", "NAVER"), ("035720", "카카오"),
    # 조선·방산
    ("009540", "HD한국조선해양"), ("012330", "현대모비스"),
    # 금융
    ("105560", "KB금융"), ("055550", "신한지주"), ("086790", "하나금융지주"),
    # 화학·배터리
    ("051910", "LG화학"), ("373220", "LG에너지솔루션"), ("247540", "에코프로비엠"),
    # 헬스케어
    ("068270", "셀트리온"), ("207940", "삼성바이오로직스"),
    # 통신
    ("017670", "SK텔레콤"),
]

_cache: dict = {
    "kr": [], "us": [], "ts": 0, "computing": False,
    "progress": "", "error": "", "done": 0, "total": 0,
    "briefing": {},
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

        # Volume 컬럼 없으면 dummy 추가 (analyze_technical 요구사항)
        if "Volume" not in hist.columns:
            hist = hist.copy()
            hist["Volume"] = 0

        # 상세 분석과 동일한 로직 사용 → 점수 일관성 보장
        tech = analyze_technical(hist)
        fund_score = 50  # TOP10 경로는 펀더멘털 생략 → 중립값

        # 외국인·기관 수급 반영 (국내 매매 방향 핵심 변수)
        flow_res = analyze_investor_flow(_get_kr_investor_flow(ticker))
        tech_score = max(0, min(100, tech["score"] + flow_res["score_adj"]))

        pc = tech.get("price_changes", {})
        ind = tech.get("indicators", {})
        setup = tech.get("trade_setup", {})
        rsi = ind.get("rsi") or 50
        combined_score = round((tech_score + fund_score) / 2)
        rec = _decide_recommendation(combined_score, setup)

        return {
            "ticker": ticker, "name": name, "market": "KR",
            "current_price": float(hist["Close"].iloc[-1]), "currency": "KRW",
            "combined_score": combined_score, "recommendation": rec,
            "price_change_1d": round(pc.get("1d") or 0, 2),
            "price_change_1w": round(pc.get("1w") or 0, 2),
            "price_change_1m": round(pc.get("1m") or 0, 2),
            "price_change_3m": round(pc.get("3m") or 0, 2),
            "rsi": round(rsi, 1),
            "setup_label": setup.get("setup_label", ""),
            "setup_grade": setup.get("setup_grade", ""),
            "risk_reward": setup.get("risk_reward"),
            "target": setup.get("target"),
            "stop": setup.get("stop"),
            "entry_low": setup.get("entry_low"),
            "entry_high": setup.get("entry_high"),
            "upside_pct": setup.get("upside_pct"),
            "foreign_net_eok": flow_res["metrics"].get("foreign_net_eok"),
            "inst_net_eok": flow_res["metrics"].get("inst_net_eok"),
        }
    except Exception:
        return None


def _decide_recommendation(score: int, setup: dict) -> str:
    """점수 + 셋업 등급 + 손익비를 종합한 실전 추천.
    적극매수 / 매수 / 분할매수 / 관망 / 회피
    """
    grade = setup.get("setup_grade", "D")
    rr = setup.get("risk_reward") or 0
    if grade == "F":
        return "회피"
    if grade == "A" and score >= 58 and rr >= 1.8:
        return "적극매수"
    if grade in ("A", "B") and score >= 55:
        return "매수"
    if grade in ("B", "C") and score >= 48:
        return "분할매수"
    if score <= 38:
        return "회피"
    return "관망"


def _generate_briefing(kr_results: list) -> dict:
    """종목 데이터 기반 장 전 시장 브리핑 — Claude Haiku 사용."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not kr_results:
        return {}
    try:
        import anthropic, json as _json
        import pytz
        kst = pytz.timezone("Asia/Seoul")
        today = datetime.now(kst).strftime("%Y년 %m월 %d일")

        lines = "\n".join([
            f"- {r['name']}({r['ticker']}): 종합{r['combined_score']}점 / "
            f"RSI {r['rsi']} / 1일 {r['price_change_1d']:+.1f}% / 1개월 {r['price_change_1m']:+.1f}%"
            for r in sorted(kr_results, key=lambda x: x["combined_score"], reverse=True)
        ])

        prompt = f"""{today} 기준 국내 주요 종목 기술적 분석 데이터입니다.

{lines}

위 데이터를 바탕으로 오늘 장 개장 전 시장 브리핑을 아래 JSON 형식으로만 답하세요:
{{
  "mood": "긍정적 또는 중립 또는 부정적",
  "mood_reason": "시장 심리 한 줄 요약",
  "key_issues": [
    "주목할 이슈 1 (종목명 포함, 구체적으로)",
    "주목할 이슈 2",
    "주목할 이슈 3"
  ],
  "top_pick": "오늘 가장 주목할 종목명과 이유 (1문장)",
  "caution": "오늘 주의해야 할 리스크 요인 (1문장)"
}}"""

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return _json.loads(text.strip())
    except Exception:
        return {}


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
            _cache["ts"] = time.time()
            _cache["progress"] = f"완료 ({len(kr_results)}개 분석)"
            # 브리핑 생성 (별도 스레드로 — 실패해도 TOP10 결과에 영향 없음)
            threading.Thread(
                target=lambda: _cache.update({"briefing": _generate_briefing(kr_results)}),
                daemon=True,
            ).start()
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
    threading.Thread(target=_compute_market_outlook, daemon=True).start()

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
        "briefing": _cache.get("briefing", {}),
    }


@app.get("/api/search")
async def search_stocks(query: str, market: Optional[str] = None):
    results = []
    if not market or market == "KR":
        results.extend(search_kr_tickers(query))
    if not market or market == "US":
        results.extend(search_us_tickers(query))
    return {"results": results}


_mkt_ctx_cache: dict = {"data": {}, "ts": 0}

def _get_market_context(market: str) -> dict:
    """KOSPI/S&P500·환율 등 시장 컨텍스트 — 1시간 캐시."""
    now = time.time()
    if now - _mkt_ctx_cache["ts"] < 3600 and _mkt_ctx_cache["data"].get(market):
        return _mkt_ctx_cache["data"][market]

    ctx = {}
    try:
        if market == "KR":
            from pykrx import stock as krx_stock
            end = datetime.today().strftime("%Y%m%d")
            start = (datetime.today() - timedelta(days=10)).strftime("%Y%m%d")
            idx = krx_stock.get_index_ohlcv_by_date(start, end, "1001")  # KOSPI
            if idx is not None and not idx.empty and len(idx) >= 2:
                kospi_now = float(idx["종가"].iloc[-1])
                kospi_prev = float(idx["종가"].iloc[-2])
                kospi_chg = (kospi_now - kospi_prev) / kospi_prev * 100
                ctx["KOSPI 지수"] = f"{kospi_now:,.2f} ({kospi_chg:+.2f}%)"
        else:
            sp = _get_yahoo_direct("^GSPC", period="5d")
            if not sp.empty and len(sp) >= 2:
                sp_chg = float(sp["Close"].pct_change().iloc[-1] * 100)
                ctx["S&P500"] = f"{float(sp['Close'].iloc[-1]):,.2f} ({sp_chg:+.2f}%)"

        # USD/KRW 환율
        fx = _get_yahoo_direct("KRW=X", period="5d")
        if not fx.empty:
            ctx["USD/KRW"] = f"{float(fx['Close'].iloc[-1]):,.0f}원"

    except Exception:
        pass

    _mkt_ctx_cache["data"][market] = ctx
    _mkt_ctx_cache["ts"] = now
    return ctx


# ── 글로벌 증시 → 국내 증시 전망 ──────────────────────────────────────────────
_outlook_cache: dict = {"data": {}, "ts": 0, "computing": False}
_OUTLOOK_TTL = 3600  # 1시간


def _get_global_indices() -> dict:
    """미국·글로벌 핵심 지표 — 국내장 방향 예측 재료."""
    out = {}
    pairs = [
        ("^GSPC", "S&P500"), ("^IXIC", "나스닥"),
        ("^SOX", "필라델피아 반도체"), ("^VIX", "VIX 변동성"),
    ]
    for sym, label in pairs:
        try:
            # 별도 스레드로 타임아웃 제어 (8초)
            result = [pd.DataFrame()]
            def _fetch(s=sym, r=result):
                r[0] = _get_yahoo_direct(s, period="5d")
            t = threading.Thread(target=_fetch, daemon=True)
            t.start(); t.join(timeout=8)
            h = result[0]
            if not h.empty and len(h) >= 2:
                chg = float(h["Close"].pct_change().iloc[-1] * 100)
                out[label] = {"value": round(float(h["Close"].iloc[-1]), 2), "change": round(chg, 2)}
        except Exception:
            pass
    try:
        result = [pd.DataFrame()]
        def _fx():
            result[0] = _get_yahoo_direct("KRW=X", period="5d")
        t = threading.Thread(target=_fx, daemon=True)
        t.start(); t.join(timeout=8)
        fx = result[0]
        if not fx.empty and len(fx) >= 2:
            chg = float(fx["Close"].pct_change().iloc[-1] * 100)
            out["USD/KRW"] = {"value": round(float(fx["Close"].iloc[-1]), 1), "change": round(chg, 2)}
    except Exception:
        pass
    try:
        from pykrx import stock as ks
        end = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=10)).strftime("%Y%m%d")
        idx = ks.get_index_ohlcv_by_date(start, end, "1001")  # KOSPI
        if idx is not None and not idx.empty and len(idx) >= 2:
            now_v = float(idx["종가"].iloc[-1]); prev = float(idx["종가"].iloc[-2])
            out["KOSPI"] = {"value": round(now_v, 2), "change": round((now_v - prev) / prev * 100, 2)}
    except Exception:
        pass
    return out


def _generate_market_outlook() -> dict:
    """미국 증시 흐름 기반 국내 증시 전망 — Claude Haiku."""
    indices = _get_global_indices()
    base = {"indices": indices}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not indices:
        return base
    try:
        import anthropic, json as _json, pytz
        kst = pytz.timezone("Asia/Seoul")
        today = datetime.now(kst).strftime("%Y년 %m월 %d일")
        lines = "\n".join(
            f"- {k}: {v['value']:,} ({v['change']:+.2f}%)" for k, v in indices.items()
        )
        prompt = f"""{today} 기준 글로벌 증시 지표입니다.

{lines}

당신은 국내 증시 전략가입니다. 위 미국 증시(S&P500/나스닥/필라델피아 반도체지수/VIX)와
환율 흐름을 바탕으로, 오늘 한국 증시가 어떻게 움직일지 예측하세요.
특히 ① 미국장 마감 흐름이 국내 개장에 미칠 영향, ② 반도체지수(SOX)와 삼성전자·SK하이닉스 연동,
③ 환율이 외국인 수급에 미칠 영향, ④ VIX로 본 위험선호도를 짚어주세요.
아래 JSON으로만 답하세요:
{{
  "us_summary": "미국 증시 마감 흐름 한 줄 요약",
  "kr_outlook": "오늘 국내 증시 예상 흐름 2-3문장 (미국장과 연관지어 구체적으로)",
  "direction": "강세 또는 약세 또는 혼조",
  "watch_sectors": ["주목 섹터1 (이유 포함)", "섹터2 (이유 포함)"],
  "special_notes": ["오늘의 특이사항/리스크1", "특이사항2"],
  "fx_note": "환율이 외국인 수급에 미칠 영향 한 줄"
}}"""
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = _json.loads(text.strip())
        data["indices"] = indices
        return data
    except Exception:
        return base


def _compute_market_outlook():
    """백그라운드 스레드에서 전망 생성 — 이벤트 루프 블로킹 방지."""
    if _outlook_cache["computing"]:
        return
    _outlook_cache["computing"] = True
    try:
        result = _generate_market_outlook()
        if result:
            _outlook_cache["data"] = result
            _outlook_cache["ts"] = time.time()
    except Exception:
        pass
    finally:
        _outlook_cache["computing"] = False


@app.get("/api/market-outlook")
async def market_outlook(refresh: bool = False):
    now = time.time()
    expired = (_outlook_cache["ts"] == 0) or (now - _outlook_cache["ts"] > _OUTLOOK_TTL)
    if (expired or refresh) and not _outlook_cache["computing"]:
        threading.Thread(target=_compute_market_outlook, daemon=True).start()
    return {
        **_outlook_cache["data"],
        "computing": _outlook_cache["computing"],
        "ready": bool(_outlook_cache["ts"]),
    }


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

    # 외국인·기관 수급 (KR 전용) — 기술점수에 반영 + 신호 추가
    flow_res = {"score_adj": 0, "signals": [], "metrics": {}}
    if market == "KR":
        try:
            flow_res = analyze_investor_flow(_get_kr_investor_flow(data["ticker"]))
        except Exception:
            pass
    if flow_res["signals"]:
        tech["signals"] = tech["signals"] + flow_res["signals"]
    tech["score"] = max(0, min(100, tech["score"] + flow_res["score_adj"]))

    # 시장 컨텍스트 수집 (실패해도 분석 계속)
    try:
        mkt_ctx = _get_market_context(market)
    except Exception:
        mkt_ctx = {}

    ai = get_ai_recommendation(
        ticker=data["ticker"], name=data["name"], market=market,
        current_price=data["current_price"], currency=data["currency"],
        technical=tech, fundamental=fund,
        price_changes=tech.get("price_changes", {}),
        history=data["history"],
        market_context=mkt_ctx,
        trade_setup=tech.get("trade_setup", {}),
    )
    combined_score = round((tech["score"] + fund["score"]) / 2)
    setup = tech.get("trade_setup", {})

    return {
        "ticker": data["ticker"], "name": data["name"],
        "market": market, "current_price": data["current_price"],
        "currency": data["currency"], "combined_score": combined_score,
        "recommendation": _decide_recommendation(combined_score, setup),
        "trade_setup": setup,
        "investor_flow": flow_res,
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
