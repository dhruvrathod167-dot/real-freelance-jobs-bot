"""
Domain and Email Integrity Checker
Analyzes domain validity, URL shorteners, high-risk TLDs,
and verifies company website domain against contact email address.
"""

from typing import List, Tuple, Optional
from urllib.parse import urlparse
import re

URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "cutt.ly", "is.gd", "rb.gy",
    "ow.ly", "goo.gl", "v.gd", "shorturl.at", "bl.ink", "tiny.cc",
    "buff.ly", "rebrand.ly", "t.ly", "s.id", "soo.gd", "clck.ru"
}

FREE_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "mail.ru", "yandex.ru", "yandex.com", "proton.me", "protonmail.com",
    "aol.com", "icloud.com", "zoho.com", "gmx.com", "gmx.net", "tutanota.com"
}

HIGH_RISK_TLDS = {
    ".top", ".loan", ".click", ".work", ".gq", ".cf", ".ml", ".ga",
    ".tk", ".buzz", ".rest", ".fit", ".icu", ".monster", ".bar"
}


def extract_root_domain(netloc_or_email_domain: str) -> str:
    """Strips scheme, path, port, www prefix, and returns root domain."""
    cleaned = netloc_or_email_domain.strip().lower()
    if "://" in cleaned or "/" in cleaned:
        parsed = urlparse(cleaned if "://" in cleaned else "https://" + cleaned)
        cleaned = parsed.netloc
    cleaned = cleaned.split(":")[0].strip()
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned


def is_url_shortener(url: str) -> bool:
    """Checks if a URL points to a known link shortener."""
    parsed = urlparse(url if "://" in url else "https://" + url)
    domain = extract_root_domain(parsed.netloc)
    return domain in URL_SHORTENERS


def check_domain_integrity(
    company_website: str,
    contact_email: str,
    company_name: str
) -> Tuple[List[str], float]:
    """
    Checks for:
    1. URL shorteners masking destination
    2. High-risk / spammy TLDs
    3. Free email providers for claimed corporate entities
    4. Domain mismatch between website and contact email
    """
    flags: List[str] = []
    risk_points = 0.0

    # 1. Inspect Company Website Domain
    clean_web = company_website.strip()
    if not clean_web.startswith(("http://", "https://")):
        clean_web = "https://" + clean_web

    parsed_web = urlparse(clean_web)
    web_domain = extract_root_domain(parsed_web.netloc)

    if not web_domain:
        flags.append("Company website domain is missing or malformed")
        risk_points += 20.0
        return flags, risk_points

    if is_url_shortener(clean_web):
        flags.append(f"Company website uses a URL shortener ({web_domain}) to conceal final destination")
        risk_points += 35.0

    for tld in HIGH_RISK_TLDS:
        if web_domain.endswith(tld):
            flags.append(f"Company website uses high-risk / low-reputation TLD '{tld}'")
            risk_points += 15.0
            break

    # 2. Inspect Contact Email Domain
    email_clean = contact_email.strip().lower()
    email_parts = email_clean.split("@")
    if len(email_parts) != 2 or not email_parts[1]:
        flags.append("Contact email format is invalid")
        risk_points += 20.0
        return flags, risk_points

    email_domain = extract_root_domain(email_parts[1])

    # 3. Check for Free Email Provider on Corporate Claims
    is_free_email = email_domain in FREE_EMAIL_PROVIDERS
    if is_free_email:
        flags.append(
            f"Contact email uses free/public provider (@{email_domain}) instead of an official company domain"
        )
        risk_points += 15.0

    # 4. Check for Mismatch between Website Domain and Email Domain
    # (If email is not a free provider and doesn't match the website)
    if not is_free_email and web_domain:
        # Compare base domain parts (e.g. acme.com vs mail.acme.com)
        web_parts = web_domain.split(".")
        email_base_parts = email_domain.split(".")

        web_base = ".".join(web_parts[-2:]) if len(web_parts) >= 2 else web_domain
        email_base = ".".join(email_base_parts[-2:]) if len(email_base_parts) >= 2 else email_domain

        if web_base != email_base:
            flags.append(
                f"Domain mismatch: Website is '{web_domain}' but contact email is '@{email_domain}'"
            )
            risk_points += 20.0

    return flags, risk_points
