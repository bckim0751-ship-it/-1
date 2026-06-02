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
    """AI 호출 실패 시 지표 기반 분석으로 대체."""
    tech_score = technical.get("score", 50)
    fund_score = fundamental.get("score", 50)
    combined = (tech_score + fund_score) / 2
    rec = "BUY" if combined >= 60 else ("SELL" if combined <= 40 else "HOLD")

    ind = technical.get("indicators", {})
    pc = technical.get("price_changes", {})
    rsi = ind.get("rsi") or 50

    # 지표 기반 강점/위험 자동 도출
    strengths, risks = [], []
    signals = technical.get("signals", []) + fundamental.get("signals", [])
    for s in signals:
        if s.get("type") == "bullish":
            strengths.append(s.get("message", ""))
        elif s.get("type") == "bearish":
            risks.append(s.get("message", ""))

    reasoning_parts = [
        f"기술적 분석 점수 {tech_score}/100, 펀더멘털 점수 {fund_score}/100.",
        f"RSI {rsi:.1f}({'과매도' if rsi < 30 else '과매수' if rsi > 70 else '중립'} 구간).",
    ]
    p1m = pc.get("1m") or 0
    p3m = pc.get("3m") or 0
    if p1m: reasoning_parts.append(f"최근 1개월 {p1m:+.1f}%, 3개월 {p3m:+.1f}%.")
    if error_detail:
        reasoning_parts.append(f"(AI 서비스 일시 오류로 지표 기반 분석 제공)")

    return {
        "recommendation": rec,
        "confidence": min(90, int(abs(combined - 50) * 2 + 30)),
        "summary": f"기술·펀더멘털 종합 {combined:.0f}점 → {rec}",
        "reasoning": " ".join(reasoning_parts),
        "strengths": strengths[:3],
        "risks": risks[:2],
        "target_price": None,
        "risk_level": "낮음" if combined >= 65 else "높음" if combined <= 40 else "중간",
        "investment_horizon": "단기(1-3개월)",
        "data_source": "기술적+펀더멘털 지표 (AI 없음)",
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

    prompt = f"""당신은 CFA 자격증을 보유한 시니어 주식 애널리스트입니다.
아래 실제 시장 데이터를 바탕으로 {name}({ticker}, {market}) 투자 분석을 해주세요.
단순히 데이터를 반복하지 말고, 데이터 간 관계에서 나오는 **인사이트**를 제공하세요.

## 가격 현황
- 현재가: {current_price:,.2f} {currency}
- 1일: {price_changes.get('1d', 0):+.2f}% / 1주: {price_changes.get('1w', 0):+.2f}% / 1개월: {price_changes.get('1m', 0):+.2f}% / 3개월: {price_changes.get('3m', 0):+.2f}%
{w52_section}
{ctx_section}

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
  "recommendation": "BUY 또는 HOLD 또는 SELL",
  "confidence": 75,
  "summary": "핵심 판단 한 줄 (60자 이내)",
  "reasoning": "데이터 기반 분석 근거 — 지표들의 상호작용과 현재 시장 맥락 포함 (250자 내외)",
  "strengths": ["구체적 강점1", "구체적 강점2"],
  "risks": ["구체적 리스크1", "구체적 리스크2"],
  "target_price": null,
  "risk_level": "낮음 또는 중간 또는 높음",
  "investment_horizon": "단기(1-3개월) 또는 중기(3-6개월) 또는 장기(1년+)",
  "data_source": "기술적 지표 + 펀더멘털 + 52주 가격 위치"
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
