import os
import json
import anthropic
import pandas as pd
from typing import Optional


def _extract_json(text: str) -> dict:
    """Claude 응답에서 JSON 추출 — 여러 포맷 대응."""
    text = text.strip()
    # 코드블록 제거
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("{"):
                text = part
                break
    # 첫 번째 { ... } 추출
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


def _score_based_fallback(technical: dict, fundamental: dict, error_detail: str = "") -> dict:
    """AI 호출 실패 시 지표·셋업 기반 분석으로 대체."""
    tech_score = technical.get("score", 50)
    fund_score = fundamental.get("score", 50)
    combined = (tech_score + fund_score) / 2
    setup = technical.get("trade_setup", {}) or {}
    grade = setup.get("setup_grade", "D")
    rr = setup.get("risk_reward") or 0

    # 셋업 등급 + 손익비 기반 추천
    if grade == "F":
        rec = "회피"
    elif grade == "A" and combined >= 58 and rr >= 1.8:
        rec = "적극매수"
    elif grade in ("A", "B") and combined >= 55:
        rec = "매수"
    elif grade in ("B", "C") and combined >= 48:
        rec = "분할매수"
    elif combined <= 38:
        rec = "회피"
    else:
        rec = "관망"

    ind = technical.get("indicators", {})
    rsi = ind.get("rsi") or 50

    strengths, risks = [], []
    for s in technical.get("signals", []) + fundamental.get("signals", []):
        if s.get("type") == "bullish":
            strengths.append(s.get("message", ""))
        elif s.get("type") == "bearish":
            risks.append(s.get("message", ""))

    # 셋업 기반 액션 플랜
    action = setup.get("setup_desc", "")
    if setup.get("entry_low") and setup.get("target") and setup.get("stop"):
        action += (f" 진입 {setup['entry_low']:,.0f}~{setup['entry_high']:,.0f}, "
                   f"목표 {setup['target']:,.0f}(+{setup.get('upside_pct')}%), "
                   f"손절 {setup['stop']:,.0f}(-{setup.get('downside_pct')}%), "
                   f"손익비 {rr}.")

    note = " (AI 일시 오류로 지표 기반 자동 분석)" if error_detail else ""

    return {
        "recommendation": rec,
        "confidence": min(90, int(abs(combined - 50) * 2 + 30)),
        "summary": f"{setup.get('setup_label', '관망')} · 종합 {combined:.0f}점 → {rec}",
        "action_plan": (action or "뚜렷한 셋업 없음 — 방향성 확인 후 진입.") + note,
        "reasoning": f"기술 {tech_score}점/펀더 {fund_score}점, RSI {rsi:.0f}, "
                     f"셋업등급 {grade}, 손익비 {rr}.",
        "strengths": strengths[:3],
        "risks": risks[:2],
        "risk_level": "낮음" if combined >= 65 else "높음" if combined <= 40 else "중간",
        "investment_horizon": "단기(1-3개월)",
        "data_source": "매매셋업 + 기술·펀더멘털 지표 (AI 없음)",
    }


def get_ai_recommendation(
    ticker: str,
    name: str,
    market: str,
    current_price: float,
    currency: str,
    technical: dict,
    fundamental: dict,
    price_changes: dict,
    history: Optional[pd.DataFrame] = None,
    market_context: Optional[dict] = None,
    trade_setup: Optional[dict] = None,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _score_based_fallback(technical, fundamental, "API 키 미설정")

    # ── 52주 고저가 계산 ───────────────────────────────────────────────────
    w52_high = w52_low = None
    if history is not None and not history.empty and "Close" in history.columns:
        recent = history.tail(252)
        w52_high = float(recent["Close"].max())
        w52_low = float(recent["Close"].min())
        w52_pos = (current_price - w52_low) / (w52_high - w52_low) * 100 if w52_high != w52_low else 50

    # ── 컨텍스트 조합 ────────────────────────────────────────────────────
    ind = technical.get("indicators", {})
    metrics = fundamental.get("metrics", {})
    tech_signals = "\n".join(
        f"  [{s['type'].upper()}] {s['indicator']}: {s['message']}"
        for s in technical.get("signals", [])
    )
    fund_signals = "\n".join(
        f"  [{s['type'].upper()}] {s['indicator']}: {s['message']}"
        for s in fundamental.get("signals", [])
    )

    w52_section = ""
    if w52_high:
        fmt = lambda v: f"{v:,.0f}" if currency == "KRW" else f"{v:,.2f}"
        w52_section = f"""
## 52주 가격 위치
- 52주 고가: {fmt(w52_high)} {currency}
- 52주 저가: {fmt(w52_low)} {currency}
- 현재 위치: 52주 범위의 {w52_pos:.0f}% 지점 (0%=저점, 100%=고점)"""

    ctx_section = ""
    if market_context:
        ctx_section = f"""
## 시장 환경 (참고 데이터)
{chr(10).join(f'- {k}: {v}' for k, v in market_context.items() if v)}"""

    setup_section = ""
    if trade_setup and trade_setup.get("setup_label"):
        fmt = lambda v: (f"{v:,.0f}" if currency == "KRW" else f"{v:,.2f}") if v else "-"
        setup_section = f"""
## 매매 셋업 (시스템 자동 산출 — 이 수치를 참고해 조언하세요)
- 셋업 유형: {trade_setup.get('setup_label')} (등급 {trade_setup.get('setup_grade')})
- 셋업 설명: {trade_setup.get('setup_desc')}
- 권장 진입가: {fmt(trade_setup.get('entry_low'))} ~ {fmt(trade_setup.get('entry_high'))}
- 목표가: {fmt(trade_setup.get('target'))} (기대수익 {trade_setup.get('upside_pct')}%)
- 손절가: {fmt(trade_setup.get('stop'))} (손실 {trade_setup.get('downside_pct')}%)
- 손익비(R/R): {trade_setup.get('risk_reward')} (2 이상이면 유리)
- 변동성(ATR): 일평균 {trade_setup.get('atr_pct')}%"""

    prompt = f"""당신은 실전 자금을 운용하는 스윙 트레이더입니다. 당신의 돈이 실제로 들어간다는 전제로
{name}({ticker}, {market})를 1~3개월 관점에서 분석하세요. 교과서적 설명이 아니라,
"지금 사야 하나, 산다면 얼마에 사고 어디서 손절하나"에 답하세요.

## 가격 현황
- 현재가: {current_price:,.2f} {currency}
- 1일: {price_changes.get('1d', 0):+.2f}% / 1주: {price_changes.get('1w', 0):+.2f}% / 1개월: {price_changes.get('1m', 0):+.2f}% / 3개월: {price_changes.get('3m', 0):+.2f}%
{w52_section}
{ctx_section}
{setup_section}

## 기술적 지표 (점수: {technical.get('score', 50)}/100)
- RSI(14): {ind.get('rsi', 'N/A')} | MACD: {ind.get('macd', 'N/A')} (Signal: {ind.get('macd_signal', 'N/A')})
- 볼린저밴드 상단: {ind.get('bb_upper', 'N/A')} / 하단: {ind.get('bb_lower', 'N/A')}
- MA20: {ind.get('ma20', 'N/A')} / MA60: {ind.get('ma60', 'N/A')} / MA120: {ind.get('ma120', 'N/A')}
신호:
{tech_signals or '  없음'}

## 펀더멘털 (점수: {fundamental.get('score', 50)}/100)
- PER: {metrics.get('per', 'N/A')} / PBR: {metrics.get('pbr', 'N/A')} / ROE: {f"{metrics.get('roe')}%" if metrics.get('roe') else 'N/A'}
- 배당수익률: {f"{metrics.get('dividend_yield')}%" if metrics.get('dividend_yield') else 'N/A'} / 순이익률: {f"{metrics.get('profit_margin')}%" if metrics.get('profit_margin') else 'N/A'}
- 섹터: {metrics.get('sector', 'N/A')}
신호:
{fund_signals or '  없음'}

## 응답 형식 (JSON만, 다른 텍스트 없이)
{{
  "recommendation": "적극매수 또는 매수 또는 분할매수 또는 관망 또는 회피",
  "confidence": 75,
  "summary": "지금 어떻게 행동할지 한 줄 (60자 이내, 예: '20일선 눌림목 분할 매수, 손절은 직전 저점')",
  "action_plan": "구체적 매매 시나리오 2-3문장 — 진입 타이밍·조건, 목표 도달 시 대응, 손절 조건을 실전 표현으로",
  "reasoning": "위 판단의 근거 — 기술적 셋업·펀더멘털·시장 환경을 엮어서 (200자 내외)",
  "strengths": ["매수 논리1", "매수 논리2"],
  "risks": ["이 시나리오가 깨지는 조건1", "리스크2"],
  "risk_level": "낮음 또는 중간 또는 높음",
  "investment_horizon": "단기(1-3개월) 또는 중기(3-6개월) 또는 장기(1년+)",
  "data_source": "매매셋업 + 기술적·펀더멘털 + 시장환경"
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _extract_json(message.content[0].text)
        result.setdefault("data_source", "Claude AI + 기술·펀더멘털 분석")
        return result
    except Exception as e:
        return _score_based_fallback(technical, fundamental, str(e)[:80])
