"""
AI Scam Analysis Service
Connects to an external AI provider (Google Gemini or OpenAI) via async HTTP
to conduct deep semantic scam analysis on job postings.
Returns structured JSON with risk score, level, flags, reasons, and recommendations.
Provides offline fallback if API key is not configured or network call fails.
"""

import json
import re
from typing import Dict, Any, List, Optional
import httpx
from config import settings
from utils.logger import logger

SYSTEM_PROMPT = """You are a specialized fraud detection AI analyzing freelance job postings.
Your task is to screen the job posting for scam signals, deception, phishing, upfront fee requests,
credential harvesting, or unrealistic claims.

Screen specifically for:
1. Upfront fee demands (registration, interview, training materials, security deposits, software license fees).
2. Credential phishing (requests for OTP, SMS codes, passwords, private keys, crypto seed phrases, bank logins, unredacted government IDs).
3. Untraceable payments (crypto-only, USDT TRC20, BNB, gift cards).
4. Suspicious contact/application methods (Telegram-only secret chats, WhatsApp-only redirections, refusal of standard contract).
5. Unrealistic promises (e.g. $500/day for basic retyping or copy-pasting).
6. Urgency manipulation ("urgent hiring", "only 2 spots", "guaranteed wealth").

Output MUST BE strict, valid JSON matching this schema:
{
  "risk_score": <integer from 0 to 100>,
  "risk_level": "<low|review|high|very_high>",
  "flags": ["<specific flag 1>", "<specific flag 2>"],
  "reasons": ["<reason 1>", "<reason 2>"],
  "recommendation": "<approve|review|reject>"
}

Risk scoring guidelines:
- 0 to 20 = "low", recommendation "approve"
- 21 to 50 = "review", recommendation "review"
- 51 to 75 = "high", recommendation "reject" or "review"
- 76 to 100 = "very_high", recommendation "reject"

DO NOT output markdown code fences, backticks, or any additional text outside the JSON object.
"""


class AIAnalyzerResult:
    def __init__(
        self,
        risk_score: float,
        risk_level: str,
        flags: List[str],
        reasons: List[str],
        recommendation: str,
        raw_response: Optional[str] = None
    ):
        self.risk_score = risk_score
        self.risk_level = risk_level
        self.flags = flags
        self.reasons = reasons
        self.recommendation = recommendation
        self.raw_response = raw_response

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "flags": self.flags,
            "reasons": self.reasons,
            "recommendation": self.recommendation,
        }


def extract_json_from_text(text: str) -> Optional[dict]:
    """Extracts and parses JSON from raw LLM output, handling markdown blocks if present."""
    clean = text.strip()
    # Remove markdown code fences if model included them
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Try finding JSON object boundaries
        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(clean[start : end + 1])
            except Exception:
                pass
    return None


async def verify_ai_connection() -> Dict[str, Any]:
    """
    Verifies AI API connectivity without exposing secret keys.
    Returns status dictionary indicating provider, model, and connectivity.
    """
    api_key = settings.AI_API_KEY.strip().strip("'\"")
    if not api_key:
        return {
            "status": "fallback",
            "provider": "offline_heuristic",
            "model": "rule_based_engine",
            "message": "AI_API_KEY not configured. Multi-tiered heuristic scam engine is active."
        }

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
                    {"role": "system", "content": "Return valid JSON."},
                    {"role": "user", "content": "Respond with {\"status\": \"ok\"}"}
                ],
                "max_tokens": 15,
                "response_format": {"type": "json_object"}
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code == 200:
                    return {
                        "status": "connected",
                        "provider": "openai",
                        "model": model,
                        "message": f"OpenAI connection verified ({model})"
                    }
                elif resp.status_code == 429:
                    return {
                        "status": "quota_exhausted",
                        "provider": "openai",
                        "model": model,
                        "message": f"OpenAI reachable ({model}), but quota is exhausted (HTTP 429). Automated heuristic fallback active."
                    }
                elif resp.status_code == 401:
                    return {
                        "status": "unauthorized",
                        "provider": "openai",
                        "model": model,
                        "message": "OpenAI API returned HTTP 401 (Invalid API key)."
                    }
                else:
                    return {
                        "status": "error",
                        "provider": "openai",
                        "model": model,
                        "message": f"OpenAI returned HTTP {resp.status_code}."
                    }
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            body = {
                "contents": [{"parts": [{"text": "Respond with {\"status\": \"ok\"}"}]}],
                "generationConfig": {"responseMimeType": "application/json"}
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, json=body)
                if resp.status_code == 200:
                    return {
                        "status": "connected",
                        "provider": "gemini",
                        "model": model,
                        "message": f"Gemini connection verified ({model})"
                    }
                else:
                    return {
                        "status": "error",
                        "provider": "gemini",
                        "model": model,
                        "message": f"Gemini API returned HTTP {resp.status_code}."
                    }
    except Exception as exc:
        return {
            "status": "network_error",
            "provider": provider,
            "model": model,
            "message": f"AI connection test failed: {exc}"
        }


async def call_gemini_api(payload_text: str) -> Optional[dict]:
    """Queries Google Gemini API."""
    api_key = settings.AI_API_KEY.strip().strip("'\"")
    model = settings.effective_ai_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT},
                    {"text": f"Analyze this job posting:\n\n{payload_text}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=body)
        if resp.status_code == 200:
            data = resp.json()
            try:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return extract_json_from_text(content)
            except (KeyError, IndexError):
                logger.error(f"Unexpected Gemini response structure: {data}")
        else:
            logger.warning(f"Gemini API returned HTTP {resp.status_code}: {resp.text}")
    return None


async def call_openai_api(payload_text: str) -> Optional[dict]:
    """Queries OpenAI compatible endpoint."""
    api_key = settings.AI_API_KEY.strip().strip("'\"")
    model = settings.effective_ai_model
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this job posting:\n\n{payload_text}"}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return extract_json_from_text(content)
        else:
            logger.warning(f"OpenAI API returned HTTP {resp.status_code}: {resp.text}")
    return None


async def analyze_job_with_ai(
    company_name: str,
    job_title: str,
    job_description: str,
    payment_rate: str,
    expected_work: str,
    application_method: str,
    company_website: str,
    contact_email: str,
    heuristic_flags: List[str]
) -> AIAnalyzerResult:
    """
    Coordinates AI analysis of job posting.
    If AI API key is missing or fails, provides deterministic fallback.
    """
    job_payload = (
        f"Company Name: {company_name}\n"
        f"Job Title: {job_title}\n"
        f"Website: {company_website}\n"
        f"Contact Email: {contact_email}\n"
        f"Compensation: {payment_rate}\n"
        f"Application Method: {application_method}\n"
        f"Pre-screening Flags: {', '.join(heuristic_flags) if heuristic_flags else 'None'}\n\n"
        f"Expected Work:\n{expected_work}\n\n"
        f"Job Description:\n{job_description}"
    )

    # If no API key configured, use fallback
    if not settings.AI_API_KEY:
        logger.info("AI API key not configured; using heuristic analysis fallback.")
        return _build_fallback_result(heuristic_flags)

    parsed_result: Optional[dict] = None
    try:
        provider = settings.effective_ai_provider
        if provider == "openai":
            parsed_result = await call_openai_api(job_payload)
        else:
            parsed_result = await call_gemini_api(job_payload)
    except Exception as exc:
        logger.error(f"Error calling AI analyzer provider: {exc}", exc_info=True)

    if parsed_result:
        try:
            score = float(parsed_result.get("risk_score", 0))
            level = str(parsed_result.get("risk_level", "low")).lower()
            flags = list(parsed_result.get("flags", []))
            reasons = list(parsed_result.get("reasons", []))
            rec = str(parsed_result.get("recommendation", "approve")).lower()

            return AIAnalyzerResult(
                risk_score=min(max(score, 0.0), 100.0),
                risk_level=level if level in ("low", "review", "high", "very_high") else "review",
                flags=flags,
                reasons=reasons,
                recommendation=rec if rec in ("approve", "review", "reject") else "review",
            )
        except Exception as exc:
            logger.error(f"Error parsing AI response fields: {exc}")

    # Fallback if AI response failed to parse
    return _build_fallback_result(heuristic_flags)


def _build_fallback_result(heuristic_flags: List[str]) -> AIAnalyzerResult:
    """Builds a structured result when AI API is not active or unavailable."""
    if not heuristic_flags:
        return AIAnalyzerResult(
            risk_score=5.0,
            risk_level="low",
            flags=[],
            reasons=["Standard job formatting with no suspicious keywords identified."],
            recommendation="approve"
        )

    score = min(len(heuristic_flags) * 25.0, 95.0)
    level = "review" if score <= 50 else ("high" if score <= 75 else "very_high")
    recommendation = "review" if score <= 50 else "reject"

    return AIAnalyzerResult(
        risk_score=score,
        risk_level=level,
        flags=heuristic_flags,
        reasons=[f"Automated risk detection identified {len(heuristic_flags)} suspicious signal(s)."],
        recommendation=recommendation
    )
