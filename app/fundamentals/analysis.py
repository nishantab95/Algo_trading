from __future__ import annotations

import math
from datetime import date


RULE_PROFILE = {
    "id": "general_corporate_v1", "minimum_annual_periods": 2,
    "max_financial_period_age_days": 550, "green_debt_to_equity": 1.5,
    "caution_debt_to_equity": 2.5, "green_interest_coverage": 3.0,
    "caution_interest_coverage": 1.0, "green_cash_conversion": 0.8,
}


def _valid(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _ratio(numerator, denominator):
    if not _valid(numerator) or not _valid(denominator) or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _growth(current, previous):
    if not _valid(current) or not _valid(previous): return None, "missing"
    if previous <= 0 or current <= 0:
        return None, "sign_or_zero_change"
    return current / previous - 1, "comparable"


def _period_age_days(period):
    """Return the age of an annual report period without guessing a filing date."""
    if not period:
        return None
    try:
        return (date.today() - date.fromisoformat(str(period)[:10])).days
    except (TypeError, ValueError):
        return None


def calculate(snapshot: dict) -> dict:
    annual = snapshot.get("annual", [])
    current = annual[0] if annual else {"metrics": {}, "period_end": None}
    prior = annual[1] if len(annual) > 1 else {"metrics": {}, "period_end": None}
    metrics, old = current.get("metrics", {}), prior.get("metrics", {})
    values = {"current_period": current.get("period_end"), "prior_period": prior.get("period_end"), "currency": snapshot.get("identity", {}).get("statement_currency")}
    for key in ("revenue", "gross_profit", "operating_income", "net_income", "total_assets", "equity", "total_debt", "cash", "current_assets", "current_liabilities", "interest_expense", "operating_cash_flow", "capital_expenditure"):
        values[key] = metrics.get(key)
    values.update({
        "gross_margin": _ratio(metrics.get("gross_profit"), metrics.get("revenue")),
        "operating_margin": _ratio(metrics.get("operating_income"), metrics.get("revenue")),
        "net_margin": _ratio(metrics.get("net_income"), metrics.get("revenue")),
        "roe": _ratio(metrics.get("net_income"), ((metrics.get("equity") or 0) + (old.get("equity") or 0)) / 2) if _valid(metrics.get("equity")) and _valid(old.get("equity")) else None,
        "roa": _ratio(metrics.get("net_income"), ((metrics.get("total_assets") or 0) + (old.get("total_assets") or 0)) / 2) if _valid(metrics.get("total_assets")) and _valid(old.get("total_assets")) else None,
        "roce": _ratio(metrics.get("operating_income"), metrics.get("total_assets") - metrics.get("current_liabilities")) if _valid(metrics.get("total_assets")) and _valid(metrics.get("current_liabilities")) else None,
        "net_debt": metrics.get("total_debt") - metrics.get("cash") if _valid(metrics.get("total_debt")) and _valid(metrics.get("cash")) else None,
        "current_ratio": _ratio(metrics.get("current_assets"), metrics.get("current_liabilities")),
        "interest_coverage": _ratio(metrics.get("operating_income"), abs(metrics.get("interest_expense"))) if _valid(metrics.get("interest_expense")) and metrics.get("interest_expense") != 0 else None,
        "revenue_growth": None, "net_income_growth": None,
        "cash_conversion": _ratio(metrics.get("operating_cash_flow"), metrics.get("net_income")),
    })
    values["debt_to_equity"] = _ratio(metrics.get("total_debt"), metrics.get("equity")) if _valid(metrics.get("equity")) and metrics.get("equity") > 0 else None
    values["revenue_growth"], values["revenue_growth_status"] = _growth(metrics.get("revenue"), old.get("revenue"))
    values["net_income_growth"], values["net_income_growth_status"] = _growth(metrics.get("net_income"), old.get("net_income"))
    old_operating_margin = _ratio(old.get("operating_income"), old.get("revenue"))
    values["prior_operating_margin"] = old_operating_margin
    values["operating_margin_change"] = values["operating_margin"] - old_operating_margin if _valid(values["operating_margin"]) and _valid(old_operating_margin) else None
    values["debt_change"] = metrics.get("total_debt") - old.get("total_debt") if _valid(metrics.get("total_debt")) and _valid(old.get("total_debt")) else None
    values["operating_cash_flow_change"] = metrics.get("operating_cash_flow") - old.get("operating_cash_flow") if _valid(metrics.get("operating_cash_flow")) and _valid(old.get("operating_cash_flow")) else None
    capex = metrics.get("capital_expenditure")
    values["free_cash_flow"] = metrics.get("operating_cash_flow") + capex if _valid(metrics.get("operating_cash_flow")) and _valid(capex) and capex < 0 else (metrics.get("operating_cash_flow") - capex if _valid(metrics.get("operating_cash_flow")) and _valid(capex) else None)
    if len(annual) >= 3:
        earliest = annual[-1].get("metrics", {}).get("revenue")
        latest = metrics.get("revenue")
        values["revenue_cagr"] = (latest / earliest) ** (1 / (len(annual) - 1)) - 1 if _valid(latest) and _valid(earliest) and latest > 0 and earliest > 0 else None
    else:
        values["revenue_cagr"] = None
    valuation = dict(snapshot.get("valuation", {}))
    pe = valuation.get("pe")
    valuation["earnings_yield"] = 1 / pe if _valid(pe) and pe > 0 else None
    return {"values": values, "valuation": valuation, "annual_periods": [row.get("period_end") for row in annual]}


def sector_type(identity: dict) -> str:
    quote_type = str(identity.get("quote_type") or "").upper()
    sector = str(identity.get("sector") or "").lower()
    industry = str(identity.get("industry") or "").lower()
    if quote_type in {"ETF", "MUTUALFUND", "FUND"}: return "fund_or_instrument"
    if "insurance" in industry: return "insurer"
    if "bank" in industry or "bank" in sector: return "bank"
    if any(word in industry for word in ("credit", "lending", "financial services", "capital markets")): return "lender_or_nbfc"
    if "reit" in industry or "real estate investment trust" in industry: return "reit_or_specialised"
    return "operating_company" if identity.get("sector") else "unknown"


def _check(key, status, value, threshold, period, text):
    return {"id": key, "status": status, "value": value, "threshold": threshold, "period": period, "explanation": text}


def assess(snapshot: dict) -> dict:
    computed = calculate(snapshot); values = computed["values"]; identity = snapshot.get("identity", {}); sector = sector_type(identity); warnings = list(snapshot.get("data_quality_warnings", [])); period = values["current_period"]
    valuation = {"classification": "UNKNOWN", "reason": "No peer or intrinsic-value benchmark is configured; raw Yahoo multiples are displayed only.", "raw_multiples": computed["valuation"]}
    if sector != "operating_company":
        return {"health": "UNKNOWN", "rule_profile": RULE_PROFILE["id"], "sector_type": sector, "checks": [_check("sector_scope", "NOT_APPLICABLE", None, None, period, "Specialised financial-sector or fund assessment is not implemented; industrial-company ratios were not applied.")], "reasons": ["Financial health is UNKNOWN because this entity requires sector-specific rules."], "warnings": warnings, "completeness": "insufficient", "metrics": computed, "valuation": valuation}
    essential = ("revenue", "net_income", "total_assets", "equity", "operating_cash_flow")
    checks = []
    missing = [key for key in essential if not _valid(values.get(key))]
    checks.append(_check("data_completeness", "MISSING" if missing or len(computed["annual_periods"]) < RULE_PROFILE["minimum_annual_periods"] else "PASS", {"missing": missing, "annual_periods": computed["annual_periods"]}, f"{RULE_PROFILE['minimum_annual_periods']} comparable annual periods", period, "Essential annual statement fields and comparable history are required for GREEN."))
    period_age = _period_age_days(period)
    report_status = "MISSING" if period_age is None else "PASS" if 0 <= period_age <= RULE_PROFILE["max_financial_period_age_days"] else "CAUTION"
    checks.append(_check("report_freshness", report_status, period_age, f"<= {RULE_PROFILE['max_financial_period_age_days']} days", period, "Report freshness is based on the latest statement period; Yahoo does not reliably expose filing dates."))
    checks.append(_check("profitability", "PASS" if _valid(values.get("net_margin")) and values["net_margin"] > 0 and _valid(values.get("operating_margin")) and values["operating_margin"] > 0 else ("FAIL" if _valid(values.get("net_income")) and values["net_income"] < 0 else "MISSING"), {"net_margin": values.get("net_margin"), "operating_margin": values.get("operating_margin")}, "> 0", period, "Positive operating and net margins are favourable."))
    leverage = values.get("debt_to_equity")
    leverage_status = "MISSING" if leverage is None else "PASS" if leverage <= RULE_PROFILE["green_debt_to_equity"] else "CAUTION" if leverage <= RULE_PROFILE["caution_debt_to_equity"] else "FAIL"
    checks.append(_check("leverage", leverage_status, leverage, {"pass": RULE_PROFILE["green_debt_to_equity"], "fail_above": RULE_PROFILE["caution_debt_to_equity"]}, period, "Debt/equity is not calculated for zero or negative equity."))
    coverage = values.get("interest_coverage")
    debt = values.get("total_debt")
    coverage_status = "NOT_APPLICABLE" if _valid(debt) and debt == 0 else "MISSING" if coverage is None else "PASS" if coverage >= RULE_PROFILE["green_interest_coverage"] else "CAUTION" if coverage > RULE_PROFILE["caution_interest_coverage"] else "FAIL"
    checks.append(_check("interest_coverage", coverage_status, coverage, {"pass": RULE_PROFILE["green_interest_coverage"], "fail_at_or_below": RULE_PROFILE["caution_interest_coverage"]}, period, "Interest coverage uses operating income divided by absolute reported interest expense; it is not required for a reported debt-free company."))
    fcf, cfo = values.get("free_cash_flow"), values.get("operating_cash_flow")
    conversion = values.get("cash_conversion")
    cash_status = "MISSING" if not _valid(cfo) else "FAIL" if cfo < 0 or (_valid(fcf) and fcf < 0) else "CAUTION" if not _valid(fcf) or not _valid(conversion) or conversion < RULE_PROFILE["green_cash_conversion"] else "PASS"
    checks.append(_check("cash_flow", cash_status, {"operating_cash_flow": cfo, "free_cash_flow": fcf, "cash_conversion": conversion}, {"positive_cash_flow": True, "minimum_cash_conversion": RULE_PROFILE["green_cash_conversion"]}, period, "Free cash flow treats negative reported capital expenditure as cash invested; operating cash flow is compared with net income."))
    growth = values.get("revenue_growth")
    margin_change = values.get("operating_margin_change")
    growth_status = "MISSING" if growth is None else "CAUTION" if growth < 0 or (_valid(margin_change) and margin_change < 0) else "PASS"
    checks.append(_check("growth", growth_status, {"revenue_growth": growth, "net_income_growth": values.get("net_income_growth"), "operating_margin_change": margin_change, "revenue_cagr": values.get("revenue_cagr")}, {"revenue_growth": ">= 0", "operating_margin_change": ">= 0"}, period, "Revenue, earnings, margin and multi-year revenue changes use comparable annual periods; sign changes and zero denominators are not converted into misleading percentages."))
    severe = any(check["status"] == "FAIL" for check in checks if check["id"] in {"profitability", "leverage", "interest_coverage", "cash_flow"})
    complete = not missing and len(computed["annual_periods"]) >= RULE_PROFILE["minimum_annual_periods"] and report_status == "PASS"
    health = "RISKY" if severe else "UNKNOWN" if not complete else "GREEN" if all(check["status"] in {"PASS", "NOT_APPLICABLE"} for check in checks if check["id"] not in {"growth"}) and checks[-1]["status"] == "PASS" else "AMBER"
    reasons = [check["explanation"] for check in checks if check["status"] in {"FAIL", "CAUTION", "MISSING"}]
    if health == "GREEN": reasons = ["Comparable annual revenue, profitability, leverage, coverage and cash-flow checks meet the configured screening conditions."]
    return {"health": health, "rule_profile": RULE_PROFILE["id"], "sector_type": sector, "checks": checks, "reasons": reasons, "warnings": warnings, "completeness": "complete" if complete else "insufficient", "metrics": computed, "valuation": valuation}
