"""
Unified Moderation & Risk Assessment Pipeline
Orchestrates website checks, domain integrity, heuristic pattern detection,
and AI analysis to produce the final calibrated Risk Score and automatic action.
"""

from typing import Dict, Any, List
from services.website_checker import check_website
from services.domain_checker import check_domain_integrity
from services.scam_detector import scan_job_heuristics
from services.ai_analyzer import analyze_job_with_ai
from utils.logger import logger


class ModerationDecision:
    def __init__(
        self,
        final_score: float,
        risk_level: str,
        action: str,  # "queue", "hold_review", "block_review"
        all_flags: List[str],
        reasons: List[str],
        ai_data: Dict[str, Any],
        website_data: Dict[str, Any],
    ):
        self.final_score = final_score
        self.risk_level = risk_level
        self.action = action
        self.all_flags = all_flags
        self.reasons = reasons
        self.ai_data = ai_data
        self.website_data = website_data

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_score": self.final_score,
            "risk_level": self.risk_level,
            "action": self.action,
            "all_flags": self.all_flags,
            "reasons": self.reasons,
            "ai_data": self.ai_data,
            "website_data": self.website_data,
        }


async def run_full_security_screening(
    company_name: str,
    company_website: str,
    contact_email: str,
    job_title: str,
    job_description: str,
    payment_rate: str,
    expected_work: str,
    country_region: str,
    application_method: str,
) -> ModerationDecision:
    """
    Runs complete automated screening across:
    1. Website availability & HTTPS check
    2. Domain integrity & email mismatch
    3. Content heuristic pattern detection
    4. AI contextual scam evaluation
    """
    logger.info(f"Starting automated security screening for job: '{job_title}' at '{company_name}'")
    all_flags: List[str] = []
    reasons: List[str] = []
    total_score = 0.0

    # 1. Website reachability & HTTPS check
    web_res = await check_website(company_website)
    if web_res.flags:
        all_flags.extend(web_res.flags)
        total_score += web_res.risk_points

    # 2. Domain & Email integrity check
    dom_flags, dom_risk = check_domain_integrity(company_website, contact_email, company_name)
    if dom_flags:
        all_flags.extend(dom_flags)
        total_score += dom_risk

    # 3. Content heuristic scan
    heuristic_res = scan_job_heuristics(
        job_title=job_title,
        job_description=job_description,
        payment_rate=payment_rate,
        expected_work=expected_work,
        application_method=application_method,
    )
    if heuristic_res.flags:
        all_flags.extend(heuristic_res.flags)
        total_score += heuristic_res.risk_score
        reasons.extend(heuristic_res.reasons)

    # 4. AI contextual analysis
    ai_res = await analyze_job_with_ai(
        company_name=company_name,
        job_title=job_title,
        job_description=job_description,
        payment_rate=payment_rate,
        expected_work=expected_work,
        application_method=application_method,
        company_website=company_website,
        contact_email=contact_email,
        heuristic_flags=all_flags
    )
    if ai_res.flags:
        for f in ai_res.flags:
            if f not in all_flags:
                all_flags.append(f)
    if ai_res.reasons:
        reasons.extend(ai_res.reasons)

    # Weight synthesized final score (blend heuristics + website + AI)
    # If heuristics found strong fraud indicators or combinations, ensure score is not diluted
    ai_weight = 0.4
    rule_weight = 0.6
    blended_score = (total_score * rule_weight) + (ai_res.risk_score * ai_weight)

    # If heuristic scanning detected strong indicators or combinations, preserve the high score
    if heuristic_res.strong_indicator_count >= 1 or heuristic_res.risk_score >= 50.0:
        final_score = max(blended_score, heuristic_res.risk_score)
    else:
        final_score = blended_score

    final_score = min(max(final_score, 0.0), 100.0)

    # Determine Risk Tier & Action:
    # If multiple strong scam indicators are present or score >= 50.0,
    # the job is classified as HIGH RISK / VERY HIGH RISK and blocked for admin review.
    if final_score <= 20.0 and heuristic_res.strong_indicator_count == 0 and heuristic_res.medium_indicator_count < 2:
        risk_level = "low"
        action = "queue"
    elif final_score <= 50.0 and heuristic_res.strong_indicator_count == 0 and heuristic_res.medium_indicator_count < 2:
        risk_level = "review"
        action = "hold_review"
    elif final_score <= 75.0:
        risk_level = "high"
        action = "block_review"
    else:
        risk_level = "very_high"
        action = "block_review"

    # Deduplicate flags
    unique_flags = list(dict.fromkeys(all_flags))

    logger.info(
        f"Screening complete: Score={final_score:.1f}, Level={risk_level}, Flags={len(unique_flags)}, Action={action}"
    )

    return ModerationDecision(
        final_score=round(final_score, 1),
        risk_level=risk_level,
        action=action,
        all_flags=unique_flags,
        reasons=reasons,
        ai_data=ai_res.to_dict(),
        website_data=web_res.to_dict(),
    )
