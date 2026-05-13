import os
import anthropic
from typing import Optional


def get_ai_recommendation(
    ticker: str,
    name: str,
    market: str,
    current_price: float,
    currency: str,
    technical: dict,
    fundamental: dict,
    price_changes: dict,
) -> dict:
    """Generate AI-powered investment recommendation using Claude."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "recommendation": "HOLD",
            "summary": "AI 분석을 사용하려면 ANTHROPIC_API_KEY 환경변수를 설정해주세요.",
            "reasoning": "",
            "risk_level": "중간",
            "target_price": None,
        }

    client = anthropic.Anthropic(api_key=api_key)

    tech_signals = "\n".join([f"- [{s['type'].upper()}] {s['indicator']}: {s['message']}" for s in technical.get("signals", [])])
    fund_signals = "\n".join([f"- [{s['type'].upper()}] {s['indicator']}: {s['message']}" for s in fundamental.get("signals", [])])

    indicators = technical.get("indicators", {})
    metrics = fundamental.get("metrics", {})

    prompt = f"""당신은 전문 주식 애널리스트입니다. 다음 데이터를 바탕으로 {name} ({ticker}, {market} 시장)에 대한 투자 분석을 해주세요.

## 현재 상황
- 현재가: {current_price:,.2f} {currency}
- 1일 등락: {price_changes.get('1d', 0):+.2f}%
- 1주 등락: {price_changes.get('1w', 0):+.2f}%
- 1개월 등락: {price_changes.get('1m', 0):+.2f}%
- 3개월 등락: {price_changes.get('3m', 0):+.2f}%

## 기술적 분석 (점수: {technical.get('score', 50)}/100)
- RSI: {indicators.get('rsi', 'N/A')}
- MACD: {indicators.get('macd', 'N/A')} (Signal: {indicators.get('macd_signal', 'N/A')})
- 볼린저밴드: 상단 {indicators.get('bb_upper', 'N/A')}, 하단 {indicators.get('bb_lower', 'N/A')}
- MA20: {indicators.get('ma20', 'N/A')}, MA60: {indicators.get('ma60', 'N/A')}

기술적 신호:
{tech_signals if tech_signals else "- 신호 없음"}

## 펀더멘털 분석 (점수: {fundamental.get('score', 50)}/100)
- PER: {metrics.get('per', 'N/A')}
- PBR: {metrics.get('pbr', 'N/A')}
- ROE: {f"{metrics.get('roe', 'N/A')}%" if metrics.get('roe') else 'N/A'}
- 배당수익률: {f"{metrics.get('dividend_yield', 'N/A')}%" if metrics.get('dividend_yield') else 'N/A'}
- 순이익률: {f"{metrics.get('profit_margin', 'N/A')}%" if metrics.get('profit_margin') else 'N/A'}
- 부채비율: {f"{metrics.get('debt_to_equity', 'N/A')}%" if metrics.get('debt_to_equity') is not None else 'N/A'}
- 섹터: {metrics.get('sector', 'N/A')}

펀더멘털 신호:
{fund_signals if fund_signals else "- 신호 없음"}

## 요청 사항
다음 JSON 형식으로 응답해주세요 (다른 텍스트 없이 JSON만):
{{
  "recommendation": "BUY 또는 HOLD 또는 SELL 중 하나",
  "confidence": 70,
  "summary": "한 줄 요약 (50자 이내)",
  "reasoning": "상세 분석 이유 (200-300자)",
  "strengths": ["강점1", "강점2", "강점3"],
  "risks": ["위험요인1", "위험요인2"],
  "target_price": null 또는 숫자,
  "risk_level": "낮음 또는 중간 또는 높음",
  "investment_horizon": "단기(1-3개월) 또는 중기(3-6개월) 또는 장기(1년+)"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        response_text = message.content[0].text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        result = json.loads(response_text.strip())
        return result
    except Exception as e:
        tech_score = technical.get("score", 50)
        fund_score = fundamental.get("score", 50)
        combined = (tech_score + fund_score) / 2
        rec = "BUY" if combined >= 60 else ("SELL" if combined <= 40 else "HOLD")
        return {
            "recommendation": rec,
            "confidence": int(abs(combined - 50) * 2),
            "summary": f"기술+펀더멘털 종합 점수 {combined:.0f}/100",
            "reasoning": f"AI 분석 오류로 점수 기반 추천: 기술적 분석 {tech_score}점, 펀더멘털 분석 {fund_score}점",
            "strengths": [],
            "risks": [],
            "target_price": None,
            "risk_level": "중간",
            "investment_horizon": "중기(3-6개월)",
        }
