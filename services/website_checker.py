"""
Website Availability & SSL Security Checker
Performs asynchronous HTTP/HTTPS reachability, TLS verification,
and detects parked or broken domains using httpx.
"""

from typing import List, Tuple
from urllib.parse import urlparse
import httpx
from utils.logger import logger
from utils.security import validate_url

PARKED_DOMAIN_KEYWORDS = [
    "domain is for sale",
    "buy this domain",
    "parked free",
    "godaddy",
    "namecheap parking",
    "under construction",
    "domain registration",
    "this website is for sale",
]


class WebsiteCheckResult:
    def __init__(
        self,
        is_reachable: bool,
        has_https: bool,
        status_code: int = 0,
        final_url: str = "",
        flags: List[str] = None,
        risk_points: float = 0.0,
    ):
        self.is_reachable = is_reachable
        self.has_https = has_https
        self.status_code = status_code
        self.final_url = final_url
        self.flags = flags or []
        self.risk_points = risk_points

    def to_dict(self) -> dict:
        return {
            "is_reachable": self.is_reachable,
            "has_https": self.has_https,
            "status_code": self.status_code,
            "final_url": self.final_url,
            "flags": self.flags,
            "risk_points": self.risk_points,
        }


async def check_website(url: str, timeout: float = 6.0) -> WebsiteCheckResult:
    """
    Validates company website reachability, HTTPS enforcement, and content signals.
    """
    flags: List[str] = []
    risk_points = 0.0

    # Use centralized security validation
    valid, error = validate_url(url)
    if not valid:
        return WebsiteCheckResult(
            is_reachable=False,
            has_https=False,
            flags=[error],
            risk_points=100.0,
        )

    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    has_https = clean_url.startswith("https://")
    if not has_https:
        flags.append("Company website uses unencrypted HTTP instead of secure HTTPS")
        risk_points += 15.0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RealFreelanceJobs-Bot/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Use global client for connection reuse
    from .ai_analyzer import get_http_client
    client = await get_http_client()
    try:
        resp = await client.get(clean_url, timeout=timeout)
        final_url = str(resp.url)
        status_code = resp.status_code

        if status_code >= 400:
            flags.append(f"Company website returned HTTP error status: {status_code}")
            risk_points += 20.0
            return WebsiteCheckResult(
                is_reachable=False,
                has_https=final_url.startswith("https://"),
                status_code=status_code,
                final_url=final_url,
                flags=flags,
                risk_points=risk_points,
            )

        # Check for parked domain or sales placeholders
        body_sample = resp.text[:4000].lower()
        for kw in PARKED_DOMAIN_KEYWORDS:
            if kw in body_sample:
                flags.append(f"Website appears to be an inactive or parked placeholder ('{kw}')")
                risk_points += 30.0
                break

        return WebsiteCheckResult(
            is_reachable=True,
            has_https=final_url.startswith("https://"),
            status_code=status_code,
            final_url=final_url,
            flags=flags,
            risk_points=risk_points,
        )

    except httpx.ConnectTimeout:
        logger.warning(f"Connection timed out when checking website: {clean_url}")
        flags.append("Company website connection timed out (server unreachable)")
        return WebsiteCheckResult(is_reachable=False, has_https=has_https, flags=flags, risk_points=20.0)

    except httpx.ConnectError:
        logger.warning(f"Failed to connect to website: {clean_url}")
        flags.append("Company website is offline or domain does not resolve")
        return WebsiteCheckResult(is_reachable=False, has_https=has_https, flags=flags, risk_points=25.0)

    except httpx.InvalidURL:
        flags.append("Invalid website URL provided")
        return WebsiteCheckResult(is_reachable=False, has_https=has_https, flags=flags, risk_points=20.0)

    except Exception as exc:
        logger.warning(f"SSL/TLS or protocol error checking website {clean_url}: {exc}")
        flags.append("SSL/TLS certificate invalid or connection failed")
        return WebsiteCheckResult(is_reachable=False, has_https=has_https, flags=flags, risk_points=20.0)
