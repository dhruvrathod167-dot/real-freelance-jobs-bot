"""
Heuristic Scam & Fraud Detection Engine
Analyzes job submissions for known fraud indicators, upfront fee extortion,
credential harvesting, crypto payment schemes, and manipulation language.
Produces a transparent risk score (0-100) and specific, non-defamatory flag descriptions.
Uses HIGH RISK / REVIEW REQUIRED terminology (never claims 100% scam or 100% genuine).
Detects combinations of multiple medium-risk indicators as well as strong scam signals.
"""

import hashlib
import re
from typing import List, Tuple, Dict, Any, Optional

# =====================================================================
# 1. STRONG SCAM INDICATORS (Substantial Risk: 65 - 75 points each)
# Clear indicators that immediately escalate a job to HIGH RISK / REVIEW REQUIRED
# =====================================================================

# 1.1 Pay-First Scam / Advance Fee Fraud
PAY_FIRST_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(pay[- ]first|must[- ]pay[- ]first|pay[- ]before[- ]starting|pay[- ]before[- ]you[- ]can[- ]work|pay[- ]upfront[- ]to[- ]receive|pay[- ]advance[- ]to[- ]secure|pay[- ]fee[- ]before[- ]getting|pay[- ]to[- ]receive[- ](the[- ])?job|pay[- ]to[- ]unlock[- ]tasks?)\b",
        "Demands applicant pay first before receiving job or tasks (Advance Fee Trap / Review Required)",
    ),
    (
        r"\b(transfer[- ]fee[- ]before|pay[- ]deposit[- ]before|send[- ]money[- ]first|pay[- ]to[- ]get[- ]hired|pay[- ]before[- ]we[- ]send[- ]work)\b",
        "Requires advance money transfer before hiring (Advance Fee Trap / Review Required)",
    ),
]

# 1.2 Upfront Registration & Deposit Fees
UPFRONT_FEE_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(registration[- ]fee|application[- ]fee|enrollment[- ]fee|interview[- ]fee)\b",
        "Requires upfront registration or application fee (High Risk / Review Required)",
    ),
    (
        r"\b(security[- ]deposit|refundable[- ]deposit|deposit[- ]required|starter[- ]deposit|deposit[- ]fee)\b",
        "Requires upfront security or refundable deposit (High Risk / Review Required)",
    ),
    (
        r"\b(purchase[- ]equipment|buy[- ]laptop|buy[- ]software|pay[- ]for[- ]tools|buy[- ]materials)\b",
        "Directs applicant to purchase equipment or software from a designated vendor (High Risk / Review Required)",
    ),
    (
        r"\b(activation[- ]fee|clearance[- ]fee|release[- ]fee|dispatch[- ]fee|processing[- ]fee)\b",
        "Demands fee to release payout or activate salary (High Risk / Review Required)",
    ),
    (
        r"\b(tax[- ]fee|vat[- ]payment|advance[- ]tax|customs[- ]clearance[- ]fee)\b",
        "Demands advance tax or clearance fee before payout (High Risk / Review Required)",
    ),
    (
        r"\b(training[- ]fee|certification[- ]fee|badge[- ]fee|id[- ]card[- ]fee)\b",
        "Charges worker for training materials or worker badge (High Risk / Review Required)",
    ),
]

# 1.3 Critical Credential / Identity Harvesting
CREDENTIAL_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(otp|one[- ]time[- ]password|verification[- ]code|sms[- ]code)\b",
        "Requests OTP or SMS verification code (Credential Harvesting / High Risk)",
    ),
    (
        r"\b(seed[- ]phrase|secret[- ]recovery[- ]phrase|private[- ]key|wallet[- ]mnemonic|12[- ]words|24[- ]words)\b",
        "Requests cryptocurrency wallet seed phrase or private key (Credential Harvesting / High Risk)",
    ),
    (
        r"\b(password|passcode|bank[- ]pin|cvv|cvc|card[- ]security[- ]code)\b",
        "Requests passwords, PINs, or credit card security codes (Credential Harvesting / High Risk)",
    ),
    (
        r"\b(online[- ]banking[- ]login|bank[- ]login|bank[- ]account[- ]access)\b",
        "Demands access to personal online banking credentials (Credential Harvesting / High Risk)",
    ),
    (
        r"\b(send[- ]passport[- ]copy|national[- ]id[- ]card|id[- ]front[- ]back)\b",
        "Demands unredacted sensitive government ID documents before hiring (High Risk / Review Required)",
    ),
]

# 1.4 Crypto Deposit Schemes & Untraceable Settlement
CRYPTO_DEPOSIT_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(crypto[- ]deposit|deposit[- ]crypto|deposit.*wallet|send[- ]bitcoin|wallet[- ]address.*deposit|send[- ]usdt|deposit.*trc20|transfer[- ]crypto)\b",
        "Instructs applicant to deposit or transfer cryptocurrency into a wallet (High Risk / Review Required)",
    ),
    (
        r"\b(gift[- ]card|steam[- ]card|apple[- ]card|google[- ]play[- ]card|razer[- ]gold)\b",
        "Requests payment or deposit via retail gift cards (High Risk / Review Required)",
    ),
]

# 1.5 Extremely Unrealistic Compensation for Simple Tasks
UNREALISTIC_SALARY_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(typing[- ]jobs?|retyping|copy[- ]paste|data[- ]entry)\b.*\b(\$[4-9]\d{2,}|\$[1-9]\d{3,}|\$500|\$1000)\b",
        "Promises exorbitant pay ($400-$1000+) for basic typing or copy-paste tasks (Unrealistic Compensation / High Risk)",
    ),
    (
        r"\b(\$[4-9]\d{2,3}\s*(per|/)\s*(day|hour)|[1-9]\d{3,}\s*(per|/)\s*day)\b",
        "Promotes suspiciously high daily or hourly compensation for non-specialized tasks (Unrealistic Compensation / High Risk)",
    ),
    (
        r"\b(guaranteed[- ]income|earn[- ]easy[- ]money|get[- ]rich|100%[- ]guaranteed[- ](income|payout)|instant[- ]wealth)\b",
        "Uses deceptive guaranteed easy money or instant wealth claims (High Risk / Review Required)",
    ),
]

# =====================================================================
# 2. MEDIUM-RISK INDICATORS (20 - 25 points each)
# Individual flags indicate caution; COMBINATIONS trigger HIGH RISK
# =====================================================================

# 2.1 Telegram-only / Off-Platform Escrow Schemes
TELEGRAM_SCHEME_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(telegram[- ]escrow|send[- ]to[- ]admin[- ]first|contact[- ]manager[- ]telegram[- ]only|chat[- ]on[- ]telegram[- ]secret|dm[- ]on[- ]telegram[- ]only)\b",
        "Directs communications exclusively through unofficial Telegram-only channels (Review Required)",
    ),
    (
        r"\b(no[- ]interview[- ]needed|direct[- ]hire[- ]without[- ]interview|immediate[- ]start[- ]today)\b",
        "Promises instant employment with zero interview or screening (Review Required)",
    ),
]

# 2.2 Artificial Urgency & Psychological Manipulation
URGENCY_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(urgent[- ]hiring|limited[- ]slots?[- ]left|only[- ]\d+[- ]spots?[- ]remaining|act[- ]now|hurry[- ]up)\b",
        "Employs high-pressure artificial scarcity language (Review Required)",
    ),
    (
        r"\b(strictly[- ]confidential|do[- ]not[- ]tell[- ]anyone|secret[- ]task)\b",
        "Instructs worker to keep communications secret (Review Required)",
    ),
]

# 2.3 General Crypto Currency Mention (without explicit deposit command)
CRYPTO_MENTION_PATTERNS: List[Tuple[str, str]] = [
    (
        r"\b(usdt|tether|trc20|erc20|bep20|binance[- ]smart[- ]chain|bnb)\b",
        "Specifies payment exclusively in cryptocurrency without standard payroll terms (Review Required)",
    ),
]

# 2.4 Suspicious Links & Shorteners
SUSPICIOUS_LINK_PATTERNS: List[Tuple[str, str, str]] = [
    (
        r"(bit\.ly|tinyurl\.com|t\.co|goo\.gl|is\.gd|cutt\.ly|ow\.ly|buff\.ly|rebrand\.ly|shorte\.st)/[a-zA-Z0-9_\-]+",
        "Uses masked URL shortener hiding true destination (Review Required)",
        "medium",
    ),
    (
        r"https?://[^\s]*(free[-_]?crypto|claim[-_]?airdrop|claim[-_]?reward|crypto[-_]?bonus|bonus[-_]?payout|instant[-_]?payout|login[-_]?verify|account[-_]?update)[^\s]*",
        "Contains known phishing / fraudulent reward link (High Risk / Review Required)",
        "strong",
    ),
    (
        r"\b(t\.me/\+[a-zA-Z0-9_\-]+|t\.me/joinchat/[a-zA-Z0-9_\-]+)\b",
        "Redirects to private invite link / channel redirect trap (Review Required)",
        "medium",
    ),
]


class HeuristicScanResult:
    def __init__(
        self,
        risk_score: float,
        risk_level: str,
        flags: List[str],
        reasons: List[str],
        content_hash: str,
        strong_indicator_count: int = 0,
        medium_indicator_count: int = 0,
        classification: str = "LOW RISK",
        auto_publish_allowed: bool = True,
    ):
        self.risk_score = risk_score
        self.risk_level = risk_level
        self.flags = flags
        self.reasons = reasons
        self.content_hash = content_hash
        self.strong_indicator_count = strong_indicator_count
        self.medium_indicator_count = medium_indicator_count
        self.classification = classification
        self.auto_publish_allowed = auto_publish_allowed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "flags": self.flags,
            "reasons": self.reasons,
            "content_hash": self.content_hash,
            "strong_indicator_count": self.strong_indicator_count,
            "medium_indicator_count": self.medium_indicator_count,
            "classification": self.classification,
            "auto_publish_allowed": self.auto_publish_allowed,
        }


def compute_content_hash(text: str) -> str:
    """Creates a normalized SHA256 hash of job text for duplicate detection."""
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def scan_job_heuristics(
    job_title: str,
    job_description: str,
    payment_rate: str,
    expected_work: str,
    application_method: str,
) -> HeuristicScanResult:
    """
    Executes advanced rule-based scam analysis on submitted job content.
    Substantially increases risk score for clear scam indicators:
    - Upfront registration/application fees
    - Security / refundable deposits
    - "Pay first to receive the job" advance fee schemes
    - Crypto deposits / gift cards
    - OTP / password / credential requests
    - Extremely unrealistic compensation
    Detects combinations of multiple medium-risk indicators (composite amplification).
    If multiple strong indicators are present, classifies as HIGH RISK / VERY HIGH RISK
    and prohibits auto-publishing.
    Uses HIGH RISK / REVIEW REQUIRED terminology (never claims 100% scam or 100% genuine).
    """
    full_text = f"{job_title} {job_description} {payment_rate} {expected_work} {application_method}".lower()
    strong_indicators: List[str] = []
    medium_indicators: List[str] = []
    flags: List[str] = []
    reasons: List[str] = []
    raw_score = 0.0

    # 1. Pay-First Scam / Advance Fee Fraud (Strong: 75 points)
    for pattern, description in PAY_FIRST_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Advance Fee Trap (High Risk / Review Required): '{description}'")
            strong_indicators.append(description)
            raw_score += 75.0

    # 2. Upfront Registration & Deposit Fees (Strong: 70 points)
    for pattern, description in UPFRONT_FEE_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Financial safety flag (High Risk / Review Required): '{description}'")
            strong_indicators.append(description)
            raw_score += 70.0

    # 3. Credential Harvesting / OTP / Password / PIN (Strong: 75 points)
    for pattern, description in CREDENTIAL_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Credential Harvesting (High Risk / Review Required): '{description}'")
            strong_indicators.append(description)
            raw_score += 75.0

    # 4. Crypto Deposit / Gift Card Schemes (Strong: 70 points)
    for pattern, description in CRYPTO_DEPOSIT_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Payment safety flag (High Risk / Review Required): '{description}'")
            strong_indicators.append(description)
            raw_score += 70.0

    # 5. Extremely Unrealistic Compensation for Simple Work (Strong: 65 points)
    for pattern, description in UNREALISTIC_SALARY_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Compensation flag (High Risk / Review Required): '{description}'")
            strong_indicators.append(description)
            raw_score += 65.0

    # 6. Medium Risk: Crypto Mention (25 points) - only if not already flagged as crypto deposit
    if not any("crypto" in s.lower() or "deposit" in s.lower() or "wallet" in s.lower() for s in strong_indicators):
        for pattern, description in CRYPTO_MENTION_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                flags.append(description)
                reasons.append(f"Payment channel flag (Review Required): '{description}'")
                medium_indicators.append(description)
                raw_score += 25.0

    # 7. Medium Risk: Telegram-Only / Off-Platform Escrow (25 points)
    for pattern, description in TELEGRAM_SCHEME_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Communication channel flag (Review Required): '{description}'")
            medium_indicators.append(description)
            raw_score += 25.0

    # 8. Medium Risk: Urgency / Scarcity Manipulation (20 points)
    for pattern, description in URGENCY_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Behavioral indicator (Review Required): '{description}'")
            medium_indicators.append(description)
            raw_score += 20.0

    # 9. Suspicious Links & Shorteners
    for pattern, description, tier in SUSPICIOUS_LINK_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append(description)
            reasons.append(f"Link safety flag: '{description}'")
            if tier == "strong":
                strong_indicators.append(description)
                raw_score += 70.0
            else:
                medium_indicators.append(description)
                raw_score += 25.0

    # =====================================================================
    # COMBINATION DETECTION & COMPOSITE RISK AMPLIFICATION
    # =====================================================================

    # A. Multiple Strong Scam Indicators:
    # If multiple strong scam indicators are present, classify as HIGH RISK / VERY HIGH RISK
    # and strictly block auto-publication.
    if len(strong_indicators) >= 2:
        raw_score = max(raw_score + 25.0, 85.0)
        combo_flag = f"MULTIPLE STRONG FRAUD INDICATORS DETECTED ({len(strong_indicators)} strong signals: High Risk / Review Required)"
        flags.insert(0, combo_flag)
        reasons.append(
            f"Composite Alert: Listing presents {len(strong_indicators)} distinct strong scam indicators simultaneously. "
            f"Auto-publication is strictly blocked; manual administrator review required."
        )

    # B. Combinations of Multiple Medium-Risk Indicators:
    # Detects combinations of medium-risk indicators (e.g. Telegram-only + Urgency + Link Shortener)
    # and amplifies the risk score into High Risk / Review Required.
    elif len(medium_indicators) >= 2:
        amplification = 20.0 if len(medium_indicators) == 2 else 35.0
        raw_score += amplification
        combo_flag = f"COMBINATION RISK: {len(medium_indicators)} medium-risk indicators detected in combination (High Risk / Review Required)"
        flags.insert(0, combo_flag)
        reasons.append(
            f"Composite Alert: Combined detection of {len(medium_indicators)} medium-risk factors "
            f"elevates listing to High Risk / Review Required."
        )

    # Bound risk score between 0 and 100
    final_score = min(max(raw_score, 0.0), 100.0)

    # Classify Risk Level & Terminology (HIGH RISK / REVIEW REQUIRED)
    if final_score <= 20.0:
        risk_level = "low"
        classification = "LOW RISK"
        auto_publish_allowed = True
    elif final_score <= 50.0 and len(strong_indicators) == 0 and len(medium_indicators) < 2:
        risk_level = "review"
        classification = "REVIEW REQUIRED"
        auto_publish_allowed = False
    elif final_score <= 75.0:
        risk_level = "high"
        classification = "HIGH RISK / REVIEW REQUIRED"
        auto_publish_allowed = False
    else:
        risk_level = "very_high"
        classification = "HIGH RISK / REVIEW REQUIRED"
        auto_publish_allowed = False

    content_hash = compute_content_hash(full_text)

    return HeuristicScanResult(
        risk_score=final_score,
        risk_level=risk_level,
        flags=flags,
        reasons=reasons,
        content_hash=content_hash,
        strong_indicator_count=len(strong_indicators),
        medium_indicator_count=len(medium_indicators),
        classification=classification,
        auto_publish_allowed=auto_publish_allowed,
    )
