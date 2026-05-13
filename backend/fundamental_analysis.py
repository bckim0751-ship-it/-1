from typing import Optional


def analyze_fundamental(info: dict, market: str = "US") -> dict:
    """Analyze fundamental data and return score + signals."""
    signals = []
    score = 50

    # PER (Price-to-Earnings Ratio)
    per = info.get("trailingPE") or info.get("forwardPE")
    if per and per > 0:
        if market == "KR":
            if per < 10:
                signals.append({"type": "bullish", "indicator": "PER", "message": f"PER {per:.1f} — 저평가 (시장 평균 대비 낮음)"})
                score += 10
            elif per < 20:
                signals.append({"type": "neutral", "indicator": "PER", "message": f"PER {per:.1f} — 적정 수준"})
            else:
                signals.append({"type": "bearish", "indicator": "PER", "message": f"PER {per:.1f} — 고평가 가능성"})
                score -= 10
        else:  # US
            if per < 15:
                signals.append({"type": "bullish", "indicator": "PER", "message": f"PER {per:.1f} — 저평가 (S&P500 평균 대비 낮음)"})
                score += 10
            elif per < 30:
                signals.append({"type": "neutral", "indicator": "PER", "message": f"PER {per:.1f} — 적정 수준"})
            else:
                signals.append({"type": "bearish", "indicator": "PER", "message": f"PER {per:.1f} — 고평가 가능성"})
                score -= 10

    # PBR (Price-to-Book Ratio)
    pbr = info.get("priceToBook")
    if pbr and pbr > 0:
        if pbr < 1:
            signals.append({"type": "bullish", "indicator": "PBR", "message": f"PBR {pbr:.2f} — 장부가 이하 거래 (저평가)"})
            score += 15
        elif pbr < 3:
            signals.append({"type": "neutral", "indicator": "PBR", "message": f"PBR {pbr:.2f} — 적정 수준"})
        else:
            signals.append({"type": "bearish", "indicator": "PBR", "message": f"PBR {pbr:.2f} — 장부가 대비 고평가"})
            score -= 5

    # ROE (Return on Equity) — US only from yfinance
    roe = info.get("returnOnEquity")
    if roe and roe > 0:
        roe_pct = roe * 100
        if roe_pct > 15:
            signals.append({"type": "bullish", "indicator": "ROE", "message": f"ROE {roe_pct:.1f}% — 우수한 자기자본이익률"})
            score += 10
        elif roe_pct > 8:
            signals.append({"type": "neutral", "indicator": "ROE", "message": f"ROE {roe_pct:.1f}% — 양호한 수준"})
        else:
            signals.append({"type": "bearish", "indicator": "ROE", "message": f"ROE {roe_pct:.1f}% — 낮은 자본효율"})
            score -= 5

    # Dividend yield
    div_yield = info.get("dividendYield")
    if div_yield and div_yield > 0:
        div_pct = div_yield * 100
        if div_pct > 3:
            signals.append({"type": "bullish", "indicator": "배당", "message": f"배당수익률 {div_pct:.2f}% — 높은 배당"})
            score += 5
        elif div_pct > 1:
            signals.append({"type": "neutral", "indicator": "배당", "message": f"배당수익률 {div_pct:.2f}%"})

    # Profit margins (US)
    profit_margin = info.get("profitMargins")
    if profit_margin:
        pm_pct = profit_margin * 100
        if pm_pct > 20:
            signals.append({"type": "bullish", "indicator": "순이익률", "message": f"순이익률 {pm_pct:.1f}% — 높은 수익성"})
            score += 10
        elif pm_pct > 10:
            signals.append({"type": "neutral", "indicator": "순이익률", "message": f"순이익률 {pm_pct:.1f}% — 양호"})
        elif pm_pct < 0:
            signals.append({"type": "bearish", "indicator": "순이익률", "message": f"순이익률 {pm_pct:.1f}% — 적자"})
            score -= 15

    # Debt to equity (US)
    debt_to_equity = info.get("debtToEquity")
    if debt_to_equity is not None:
        if debt_to_equity < 50:
            signals.append({"type": "bullish", "indicator": "부채비율", "message": f"부채비율 {debt_to_equity:.0f}% — 낮은 부채"})
            score += 5
        elif debt_to_equity > 200:
            signals.append({"type": "bearish", "indicator": "부채비율", "message": f"부채비율 {debt_to_equity:.0f}% — 높은 부채 부담"})
            score -= 10

    # Revenue growth (US)
    rev_growth = info.get("revenueGrowth")
    if rev_growth is not None:
        rg_pct = rev_growth * 100
        if rg_pct > 15:
            signals.append({"type": "bullish", "indicator": "매출성장률", "message": f"매출성장률 {rg_pct:.1f}% — 강한 성장"})
            score += 10
        elif rg_pct > 5:
            signals.append({"type": "neutral", "indicator": "매출성장률", "message": f"매출성장률 {rg_pct:.1f}% — 안정적 성장"})
        elif rg_pct < 0:
            signals.append({"type": "bearish", "indicator": "매출성장률", "message": f"매출성장률 {rg_pct:.1f}% — 매출 감소"})
            score -= 10

    score = max(0, min(100, score))

    return {
        "score": round(score),
        "signals": signals,
        "metrics": {
            "per": round(per, 2) if per else None,
            "pbr": round(pbr, 2) if pbr else None,
            "roe": round(roe * 100, 2) if roe else None,
            "dividend_yield": round(div_yield * 100, 2) if div_yield else None,
            "profit_margin": round(profit_margin * 100, 2) if profit_margin else None,
            "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity is not None else None,
            "revenue_growth": round(rev_growth * 100, 2) if rev_growth is not None else None,
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        },
    }
