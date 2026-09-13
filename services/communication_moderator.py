"""
Community Communication Moderation Service (Multilingual & Language-Independent)
Analyzes public group text messages in "Legally Freelancing Working" for:
- Abusive language, personal insults, derogatory slurs (English, Hindi, Gujarati, Hinglish, Gujlish, mixed)
- Threatening statements, violent intent, physical harm, doxxing
- Harassment, sexual vulgarity, degrading obscenity
- Unsolicited spam, online casino, pump-and-dump fraud

Architecture:
1. Advanced Normalization: Unicode NFKC, diacritic stripping, leetspeak unmasking,
   repeated character collapsing, and whitespace normalization.
2. Deterministic Multilingual Fast-Path: Zero-latency detection of clear insults,
   obscenity, violent threats, and harassment across English, Hindi, and Gujarati.
3. AI Semantic Classification: Contextual LLM evaluation for subtle, mixed, or idiomatic expressions.
4. Severity Threshold:
   - CRITICAL / SERIOUS -> Message deletion + 4-day restriction + audit log.
   - MILD / NONE -> NO ACTION (normal conversations, opinions, tech debates, harmless words).
"""

import json
import re
import unicodedata
from typing import List, Optional, Tuple, Dict, Any
import httpx

from config import settings
from utils.logger import logger


class CommunicationScanResult:
    def __init__(
        self,
        is_violation: bool,
        violation_type: str = "NONE",  # ABUSE, THREAT, HARASSMENT, SPAM, NONE
        severity: str = "NONE",        # SERIOUS, CRITICAL, MILD, NONE
        details: str = "",
        matched_flags: Optional[List[str]] = None,
        language: str = "Unknown",
    ):
        self.is_violation = is_violation
        self.violation_type = violation_type
        self.severity = severity
        self.details = details
        self.matched_flags = matched_flags or []
        self.language = language

    def __repr__(self) -> str:
        return (
            f"<CommunicationScanResult violation={self.is_violation} "
            f"type={self.violation_type} severity={self.severity} details='{self.details}'>"
        )


def normalize_text_for_moderation(text: str) -> str:
    """
    Normalizes Unicode, case, spacing, repeated characters, leetspeak,
    and common obfuscation techniques across scripts (Latin, Devanagari, Gujarati).
    """
    if not text:
        return ""

    # 1. Unicode NFKC normalization
    norm = unicodedata.normalize("NFKC", text)

    # 2. Strip zero-width and invisible control characters
    norm = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad\u2060\u200e\u200f]", "", norm)

    # 3. Lowercase
    norm = norm.lower()

    # 4. Leetspeak / symbol substitutions commonly used to evade filters
    leetspeak_map = str.maketrans({
        "@": "a",
        "$": "s",
        "0": "o",
        "1": "i",
        "!": "i",
        "3": "e",
        "5": "s",
        "7": "t",
        "+": "t",
    })
    norm = norm.translate(leetspeak_map)

    # 5. Collapse excessive character repetitions (e.g. "kiiiillll" -> "kill", "stuuuupid" -> "stupid", "kuttaaaa" -> "kutta")
    norm = re.sub(r"(.)\1{2,}", r"\1", norm)

    # 6. Normalize multiple spaces/newlines to single space
    norm = re.sub(r"\s+", " ", norm).strip()

    return norm


# =====================================================================
# DETERMINISTIC MULTILINGUAL PATTERNS (English, Hindi, Gujarati, Hinglish, Gujlish)
# =====================================================================

# 1. Critical Violent Threats & Doxxing (Always CRITICAL severity -> 4-day / perm restriction)
THREAT_PATTERNS: List[Tuple[str, str]] = [
    # English
    (r"\b(i\s*(will|'ll)?\s*|gonna\s+|going to\s+)?(k+i+l+|murder|beat|hurt|destroy|strangle)\s+(you|u)\b", "Violent physical threat"),
    (r"\b(go\s+)?(k+i+l+\s+yourself|kys|hope\s+you\s+die|go\s+die)\b", "Severe suicide/death encouragement"),
    (r"\b(i will dox you|leak your address|track down your family|find where you live)\b", "Doxxing and physical stalking threat"),
    (r"\b(watch your back|you will pay for this|you're dead meat)\b", "Intimidating personal threat"),
    (r"\b(i('ll| will)|gonna) (smash|break) your (face|head|teeth)\b", "Violent physical threat"),
    (r"\b(say that to my face|i'll beat your ass|fight me)\b", "Aggressive fighting challenge"),

    # Hindi / Hinglish (Latin & Devanagari)
    (r"\b(jaan se (mar|maar) (dunga|denge)|mar dalunga|maar daalunga|mar dunga|maar dunga)\b", "Severe death threat (Hindi/Hinglish)"),
    (r"\b(tujhe zinda nahi chhodunga|tera khoon pi jaunga|tere ghar aake marunga)\b", "Violent physical threat (Hindi/Hinglish)"),
    (r"\b(haath pair tod dunga|goli mar dunga|jaan le lunga)\b", "Violent physical threat (Hindi/Hinglish)"),
    (r"(मार डालूंगा|जान से मार दूंगा|तुझे जिंदा नहीं छोड़ूंगा|खून पी जाऊंगा|गोली मार दूंगा)", "Severe violent threat (Hindi Devanagari)"),

    # Gujarati / Gujlish (Latin & Gujarati script)
    (r"\b(mari nakis|mari nakhu|jaan thi mari nakis|tane mari nakis|tane pati dais)\b", "Severe death threat (Gujarati/Gujlish)"),
    (r"\b(puro kari dais|tara ghar aavi ne maris|haath pag bhaangi nakis)\b", "Violent physical threat (Gujarati/Gujlish)"),
    (r"(મારી નાખીશ|પૂરો કરી નાખીશ|જાન થી મારી નાખીશ|હાથ પગ ભાંગી નાખીશ)", "Severe violent threat (Gujarati script)"),
]

# 2. Severe Sexual Harassment & Degrading Vulgarity (Always CRITICAL severity)
HARASSMENT_PATTERNS: List[Tuple[str, str]] = [
    # English
    (r"\b(send (nudes|bobs|boobs|naked pic)|show (tits|dick)|wanna fuck)\b", "Unsolicited sexual harassment"),
    (r"\b(bitch|slut|whore)\b", "Gendered harassment / abusive slurs"),

    # Hindi / Hinglish
    (r"\b(nudes bhej|nangi photo bhej|chut dikha|boobs dikha|chudwa le)\b", "Severe sexual harassment (Hindi/Hinglish)"),
    (r"\b(randi|chudakad|bhen ki chut|teri maa ki chut)\b", "Degrading vulgar obscenity (Hindi/Hinglish)"),
    (r"(रंडी|रांडी|छिनाल|चूत दिखा|नंगी फोटो)", "Severe sexual harassment / obscenity (Hindi Devanagari)"),

    # Gujarati / Gujlish
    (r"\b(nanga photo mokal|chodvu che|chhinal|dhandho kare che)\b", "Severe sexual harassment (Gujarati/Gujlish)"),
    (r"(નગ્ન ફોટો|રાંડ|છિનાળ)", "Severe sexual harassment / obscenity (Gujarati script)"),
]

# 3. Targeted Serious Abuse, Personal Insults & Hostile Fighting (SERIOUS severity -> 4-day restriction)
ABUSE_PATTERNS: List[Tuple[str, str]] = [
    # English Targeted Insults & Profanity
    (r"\b(you('re| are|r)?|u (are|r)?)\s+(a\s+|an\s+)?([a-z]+\s+)*(stupid|idiot|moron|retard|retarded|clown|scumbag|bastard|as+hole|dumbass|dumb|loser|useless|pathetic|trash|garbage|toxic|disgusting|scum)\b", "Targeted derogatory personal insult"),
    (r"\b(you\s+)?(shut up|stfu|shut your (mouth|face)|fuck off|get lost|go to hell)\b", "Hostile harassment and abusive dismissal"),
    (r"\b(you('re| are|r)?|u (are|r)?)\s+(a\s+)?(piece of (shit|trash|garbage|crap))\b", "Targeted derogatory insult"),
    (r"\b(stupid|dumb)\s+(bitch|bastard|idiot|moron|cunt|asshole|scumbag)\b", "Aggressive abusive language"),
    (r"\b(motherfucker|cunt|dickhead|asswipe|dipshit|cocksucker)\b", "Severe vulgar profanity"),
    (r"\b(you|u)\s+(suck|blow)\b", "Targeted derogatory insult"),
    (r"\b(fuck\s+(you|u))\b", "Direct vulgar profanity"),

    # Hindi / Hinglish Insults & Degrading Abuse
    (r"\b(madarchod|behenchod|bhosdike|bhosadike|bhosadiwale|chutiya|chutiye|kutta|kutte|kutti|kamina|kamine|harami|haramkhor|suar|bhadwe|bhadwa|saale|gandu|gaand mara|teri aisi taisi)\b", "Severe abusive insult (Hindi/Hinglish)"),
    (r"\b(tu|tum)\s+([a-z]+\s+)*(chutiya|kutta|kamina|harami|gadha|bhosdike|gandu|saale)\b", "Targeted abusive insult (Hindi/Hinglish)"),
    (r"\b(bhonk mat|chup kar saale|apni aukaat me reh|bakwaas band kar saale)\b", "Aggressive hostile fighting (Hindi/Hinglish)"),
    (r"(मादरचोद|बहनचोद|भोसड़ीके|चूतिया|कुत्ता|कमीना|हरामी|गांडू|भाड़वे|सूअर|गधा|भोंक मत|कुत्ते)", "Severe abusive insult (Hindi Devanagari)"),

    # Gujarati / Gujlish Insults & Degrading Abuse
    (r"\b(gadhedo|gadheda|gadhedi|kutro|kutri|lodu|loda|chodina|chodino|bhosdina|tapori|bhonk ma|thoth|nalayak)\b", "Severe abusive insult (Gujarati/Gujlish)"),
    (r"\b(tu|tame)\s+([a-z]+\s+)*(gadhedo|gadheda|kutro|lodu|chodina|gando|gandi|nalayak)\b", "Targeted abusive insult (Gujarati/Gujlish)"),
    (r"\b(bhonk ma|chup mar baka|tari ma ne|su kare che lodu|tari aisi taisi)\b", "Aggressive hostile fighting (Gujarati/Gujlish)"),
    (r"(ગધેડો|ગધેડા|કૂતરો|કૂતરા|લોડુ|ચોદીના|ભોસડીના|હરામી|નાલાયક|ભોંક મા|ચૂપ મર)", "Severe abusive insult (Gujarati script)"),

    # Mixed / Code-switched Insults (English + Hindi/Gujarati)
    (r"\b(you('re| are|r)?|u (are|r)?)\s+(a\s+)?([a-z]+\s+)*(chutiya|gadhedo|kutta|kamina|harami|lodu|bhosdike)\b", "Mixed code-switched targeted insult"),
    (r"\b(shut up you)\s+(chutiya|gadhedo|kutta|idiot|moron)\b", "Mixed code-switched hostile abuse"),
]

# 4. Inappropriate Commercial Spam / Gambling / Adult Flooding (SERIOUS severity)
SPAM_PATTERNS: List[Tuple[str, str]] = [
    (r"\b(online casino|crypto casino|free spins|win slots|poker bonus)\b", "Unsolicited gambling / casino spam"),
    (r"\b(free porn|adult cam|live girls webcam|xxx video)\b", "Inappropriate adult content promotion"),
    (r"\b(pump and dump|1000x crypto signal|guaranteed 100x return|forex robot)\b", "Deceptive financial pump spam"),
]

# 5. Mild / Ambiguous Colloquial Expressions (MILD severity -> NO ACTION, never penalized)
MILD_FRUSTRATION_PATTERNS: List[str] = [
    r"\b(damn|dammit|crap|sucks|annoying|wtf|what the hell|bullshit|lame|hell)\b",
    r"\b(yaar|dimaag kharab|bakwaas|bekar|dimag ki dahi)\b",
    r"\b(aa (code|bug|library|approach|work) bau (kharab|bakwas|slow) che)\b",
    r"\b(this (code|bug|library|tool|project|task|api|server|pc|laptop|work) is (garbage|trash|crap|bad|terrible|broken|stupid))\b",
]

# 6. Protected Professional Communication Signals (Context Guard in EN, HI, GU)
PROFESSIONAL_CONTEXT_KEYWORDS: List[str] = [
    # English
    "code", "react", "python", "javascript", "backend", "frontend", "database",
    "api", "contract", "client", "rate", "hourly", "milestone", "invoice", "deliverable",
    "scope", "review", "bug", "feature", "framework", "library", "design", "portfolio", "developer",
    # Hindi / Hinglish
    "kaam", "paisa", "daam", "namaste", "madad", "chahiye", "bhai", "project", "budget", "discuss",
    # Gujarati / Gujlish
    "kaam", "paisa", "bhav", "samay", "kem cho", "jaroor che", "madad", "joiye", "karsho", "nathi"
]


def scan_communication_message(text: str) -> CommunicationScanResult:
    """
    Deterministic multilingual scan for abusive, insulting, threatening, or spam text.
    Handles English, Hindi, Gujarati, Hinglish, Gujlish, and mixed code-switching.
    Returns CommunicationScanResult indicating whether a clear violation exists.
    """
    if not text or not text.strip():
        return CommunicationScanResult(is_violation=False, severity="NONE")

    normalized = normalize_text_for_moderation(text)
    flags: List[str] = []

    # 1. Critical Threats & Violent Intent (CRITICAL -> Action required)
    for pattern, reason in THREAT_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            flags.append(reason)
            return CommunicationScanResult(
                is_violation=True,
                violation_type="THREAT",
                severity="CRITICAL",
                details=f"Severe threat detected: {reason}",
                matched_flags=flags,
            )

    # 2. Severe Harassment & Sexual Misconduct (CRITICAL -> Action required)
    for pattern, reason in HARASSMENT_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            flags.append(reason)
            return CommunicationScanResult(
                is_violation=True,
                violation_type="HARASSMENT",
                severity="CRITICAL",
                details=f"Harassment detected: {reason}",
                matched_flags=flags,
            )

    # 3. Targeted Serious Abuse & Aggressive Fighting (SERIOUS -> Action required)
    for pattern, reason in ABUSE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            flags.append(reason)
            return CommunicationScanResult(
                is_violation=True,
                violation_type="ABUSE",
                severity="SERIOUS",
                details=f"Abusive communication detected: {reason}",
                matched_flags=flags,
            )

    # 4. Inappropriate Commercial Spam / Gambling (SERIOUS -> Action required)
    for pattern, reason in SPAM_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            flags.append(reason)
            return CommunicationScanResult(
                is_violation=True,
                violation_type="SPAM",
                severity="SERIOUS",
                details=f"Inappropriate spam detected: {reason}",
                matched_flags=flags,
            )

    # 5. Mild / Ambiguous Expressions (MILD -> NO ACTION, explicitly ignored)
    for pattern in MILD_FRUSTRATION_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return CommunicationScanResult(
                is_violation=False,
                violation_type="NONE",
                severity="MILD",
                details="Mild or non-targeted colloquial frustration; no personal attack.",
            )

    # Clean message: Normal professional conversation, debate, criticism, opinion, or greeting
    return CommunicationScanResult(is_violation=False, severity="NONE")


# =====================================================================
# AI SEMANTIC CLASSIFIER (Language-Independent LLM Semantic Analysis)
# =====================================================================

AI_COMMUNICATION_PROMPT = """You are an expert multilingual community safety moderator for a professional freelance group ("Legally Freelancing Working").
Your task is to analyze chat messages in ANY language or mixed language (English, Hindi, Gujarati, Hinglish, Gujlish, code-switched, transliterated).

Rules:
1. Normal professional conversation, freelance project discussion, rate negotiation, questions, opinions, disagreements, code reviews, greetings, and harmless words MUST be classified as "NONE" (is_violation: false).
2. Mild frustration about code, tools, or bugs (e.g., "damn this bug", "this library sucks", "yaar ye kya error hai", "aa approach bakwas che") MUST be classified as "MILD" (is_violation: false).
3. ONLY clear serious abuse, personal insults, obscenity, sexual vulgarity, degrading slurs, violent threats, doxxing, harassment, or aggressive fighting in any language (e.g., "you are stupid", "kutte kamine", "chutiya", "mar dalunga", "gadhedo lodu", "mari nakis", "fuck you") MUST be classified as "SERIOUS" or "CRITICAL" (is_violation: true).

Output MUST BE valid JSON matching this schema:
{
  "is_violation": <true|false>,
  "violation_type": "<ABUSE|THREAT|HARASSMENT|SPAM|NONE>",
  "severity": "<CRITICAL|SERIOUS|MILD|NONE>",
  "details": "<brief explanation>",
  "language_detected": "<English|Hindi|Gujarati|Hinglish|Gujlish|Mixed>"
}
"""


async def call_ai_for_communication_classification(text: str) -> Optional[dict]:
    """
    Asynchronously queries the configured AI provider (OpenAI or Gemini)
    for language-independent semantic classification of message content.
    """
    api_key = settings.AI_API_KEY.strip().strip("'\"")
    if not api_key:
        return None

    provider = settings.effective_ai_provider
    model = settings.effective_ai_model

    try:
        if provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": AI_COMMUNICATION_PROMPT},
                    {"role": "user", "content": f"Analyze this chat message:\n\n{text[:400]}"}
                ],
                "temperature": 0.1,
                "max_tokens": 120,
                "response_format": {"type": "json_object"}
            }
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
                elif resp.status_code == 429:
                    logger.warning("OpenAI API quota exhausted (429) during communication moderation; using deterministic engine.")
                else:
                    logger.warning(f"OpenAI moderation returned HTTP {resp.status_code}")
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            body = {
                "contents": [
                    {
                        "parts": [
                            {"text": AI_COMMUNICATION_PROMPT},
                            {"text": f"Analyze this chat message:\n\n{text[:400]}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json"
                }
            }
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(url, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(content)
                else:
                    logger.warning(f"Gemini moderation returned HTTP {resp.status_code}")
    except Exception as exc:
        logger.debug(f"AI communication moderation call skipped/failed ({exc}); deterministic result used.")

    return None


async def scan_communication_message_ai(text: str) -> CommunicationScanResult:
    """
    Main asynchronous communication moderation entrypoint.
    1. Runs fast deterministic multilingual check.
    2. If clear violation (CRITICAL or SERIOUS) detected: returns immediately.
    3. If clean or mild: optionally consults AI semantic classifier for nuance in any language.
    4. Applies strict severity threshold: only CRITICAL or SERIOUS trigger penalties.
    """
    # 1. Fast deterministic multilingual check
    det_result = scan_communication_message(text)
    if det_result.is_violation and det_result.severity in ("CRITICAL", "SERIOUS"):
        return det_result

    # 2. AI Semantic Classification for multilingual nuance
    ai_data = await call_ai_for_communication_classification(text)
    if ai_data and isinstance(ai_data, dict):
        is_violation = bool(ai_data.get("is_violation", False))
        severity = str(ai_data.get("severity", "NONE")).upper()
        violation_type = str(ai_data.get("violation_type", "NONE")).upper()
        details = str(ai_data.get("details", "AI semantic moderation alert"))
        lang = str(ai_data.get("language_detected", "Unknown"))

        # Strict severity threshold: only CRITICAL or SERIOUS trigger violation
        if is_violation and severity in ("CRITICAL", "SERIOUS"):
            return CommunicationScanResult(
                is_violation=True,
                violation_type=violation_type,
                severity=severity,
                details=f"AI Semantic detection ({lang}): {details}",
                matched_flags=[details],
                language=lang,
            )

    # 3. Fallback to deterministic result (NO ACTION for clean / mild)
    return det_result
