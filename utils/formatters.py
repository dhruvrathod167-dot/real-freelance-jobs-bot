"""
Message Formatting Utility
Provides clean HTML formatting for Telegram messages, verified job cards,
admin alerts, risk breakdown summaries, and legal safety disclaimers.
"""

import html
from typing import List, Optional, Dict, Any

# Mandatory community legal and safety disclaimer
COMMUNITY_SAFETY_DISCLAIMER = (
    "<b>⚠️ SAFETY ADVISORY</b>\n"
    "<i>Real Freelance Jobs screens submissions using automated risk indicators. "
    "We are NOT an escrow, employer, or legal certifier. Never pay upfront fees "
    "(training, equipment, registration), never deposit crypto, and never share "
    "OTPs, passwords, or bank credentials. Verify every client independently.</i>"
)


def get_risk_badge(score: float, level: str) -> str:
    """Returns a visual emoji badge based on risk tier using non-defamatory HIGH RISK / REVIEW REQUIRED terminology."""
    lvl = level.lower()
    if lvl == "low" or score <= 20:
        return f"🟢 <b>LOW RISK</b> ({score:.0f}/100)"
    elif lvl == "review" or score <= 50:
        return f"🟡 <b>REVIEW REQUIRED</b> ({score:.0f}/100)"
    elif lvl == "high" or score <= 75:
        return f"🟠 <b>HIGH RISK / REVIEW REQUIRED</b> ({score:.0f}/100)"
    else:
        return f"🔴 <b>HIGH RISK / BLOCKED FOR REVIEW</b> ({score:.0f}/100)"


def format_job_card(
    job_id: int,
    company_name: str,
    job_title: str,
    payment_rate: str,
    country_region: str,
    expected_work: str,
    job_description: str,
    application_method: str,
    company_website: Optional[str] = None,
    contact_email: Optional[str] = None,
    risk_score: Optional[float] = None,
    risk_level: Optional[str] = None,
    show_risk: bool = False,
    is_featured: bool = False,
    is_sponsored: bool = False,
) -> str:
    """Formats a verified job post card for publishing to the group/channel."""
    c_name = html.escape(company_name)
    title = html.escape(job_title)
    rate = html.escape(payment_rate)
    region = html.escape(country_region)
    work = html.escape(expected_work)
    app = html.escape(application_method)
    desc = html.escape(job_description[:600] + ("..." if len(job_description) > 600 else ""))

    # Header with optional sponsorship badge
    if is_sponsored:
        header = f"💎 <b>[SPONSORED LISTING] JOB #{job_id}</b>"
    elif is_featured:
        header = f"⭐ <b>[FEATURED OPPORTUNITY] JOB #{job_id}</b>"
    else:
        header = f"💼 <b>VERIFIED JOB OPPORTUNITY #{job_id}</b>"

    lines = [
        header,
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"🏢 <b>Company/Client:</b> {c_name}",
        f"📌 <b>Role:</b> {title}",
        f"💰 <b>Compensation:</b> {rate}",
        f"🌍 <b>Location/Scope:</b> {region}",
        f"",
        f"📝 <b>Key Deliverables:</b>\n{work}",
        f"",
        f"📄 <b>Description:</b>\n{desc}",
        f"",
        f"📬 <b>How to Apply:</b>\n{app}",
    ]

    if company_website:
        clean_web = html.escape(company_website)
        lines.append(f"🌐 <b>Website:</b> {clean_web}")

    if contact_email:
        clean_email = html.escape(contact_email)
        lines.append(f"✉️ <b>Email:</b> {clean_email}")

    if show_risk and risk_score is not None and risk_level:
        lines.append(f"\n🛡️ <b>Automated Risk Rating:</b> {get_risk_badge(risk_score, risk_level)}")

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━━\n{COMMUNITY_SAFETY_DISCLAIMER}")
    return "\n".join(lines)


def format_admin_job_review(
    job_id: int,
    user_id: int,
    username: Optional[str],
    company_name: str,
    job_title: str,
    payment_rate: str,
    country_region: str,
    company_website: str,
    contact_email: str,
    application_method: str,
    expected_work: str,
    job_description: str,
    risk_score: float,
    risk_level: str,
    detected_flags: List[str],
    ai_reasons: List[str]
) -> str:
    """Formats an exhaustive inspection card for administrators."""
    user_str = f"@{username}" if username else f"ID: <code>{user_id}</code>"
    c_name = html.escape(company_name)
    title = html.escape(job_title)
    rate = html.escape(payment_rate)
    region = html.escape(country_region)
    web = html.escape(company_website)
    email = html.escape(contact_email)
    app = html.escape(application_method)
    work = html.escape(expected_work)
    desc = html.escape(job_description)

    flags_text = "\n".join([f"  • {html.escape(f)}" for f in detected_flags]) if detected_flags else "  • No critical flags detected"
    reasons_text = "\n".join([f"  • {html.escape(r)}" for r in ai_reasons]) if ai_reasons else "  • Heuristic scan clear"

    badge = get_risk_badge(risk_score, risk_level)

    text = (
        f"🚨 <b>PENDING MODERATION: Job #{job_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Submitted by:</b> {user_str} (<code>{user_id}</code>)\n"
        f"🏢 <b>Company:</b> {c_name}\n"
        f"🌐 <b>Website:</b> {web}\n"
        f"✉️ <b>Email:</b> {email}\n"
        f"📌 <b>Title:</b> {title}\n"
        f"💰 <b>Rate:</b> {rate}\n"
        f"🌍 <b>Region:</b> {region}\n"
        f"📬 <b>Apply:</b> {app}\n\n"
        f"🛡️ <b>Risk Assessment:</b> {badge}\n\n"
        f"⚠️ <b>Detected Flags:</b>\n{flags_text}\n\n"
        f"🧠 <b>AI & Security Analysis:</b>\n{reasons_text}\n\n"
        f"📝 <b>Deliverables:</b>\n{work}\n\n"
        f"📄 <b>Full Description:</b>\n{desc}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Use the buttons below to approve or reject this submission.</i>"
    )
    return text


def format_user_verification_status(
    user_id: int,
    status: str,
    risk_score: float,
    submission_count: int,
    flag_notes: Optional[str] = None
) -> str:
    """Formats user status card for /status command."""
    status_emojis = {
        "VERIFIED": "✅ <b>Verified Member</b>",
        "PENDING": "⏳ <b>Pending Verification</b>",
        "SUSPICIOUS": "⚠️ <b>Suspicious Account (Elevated Risk)</b>",
        "RESTRICTED": "🚫 <b>Restricted Account</b>",
        "BANNED": "⛔ <b>Banned from Submitting</b>"
    }
    status_text = status_emojis.get(status.upper(), status)

    lines = [
        f"📋 <b>YOUR VERIFICATION PROFILE</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"🆔 <b>User ID:</b> <code>{user_id}</code>",
        f"🛡️ <b>Status:</b> {status_text}",
        f"📊 <b>Account Risk Rating:</b> {risk_score:.0f}/100",
        f"💼 <b>Jobs Submitted:</b> {submission_count}",
    ]

    if flag_notes:
        lines.append(f"📌 <b>Notes:</b> {html.escape(flag_notes)}")

    if status.upper() == "PENDING":
        lines.append("\n👉 <i>Please complete your verification checklist using /verify.</i>")
    elif status.upper() == "VERIFIED":
        lines.append("\n👉 <i>You are verified to submit job postings using /submit.</i>")
    elif status.upper() == "SUSPICIOUS":
        lines.append("\n👉 <i>Your profile was flagged for elevated risk indicators. New job submissions will be held for administrative review.</i>")
    elif status.upper() in ("RESTRICTED", "BANNED"):
        lines.append("\n👉 <i>Your account was flagged for safety violations. If you believe this is an error, contact community admins.</i>")

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━━\n{COMMUNITY_SAFETY_DISCLAIMER}")
    return "\n".join(lines)


def format_my_id_card(
    user_id: int,
    first_name: str,
    last_name: Optional[str],
    username: Optional[str],
    status: str,
    risk_score: float,
    is_admin: bool,
    chat_id: int,
    chat_type: str,
) -> str:
    """Formats the /myid response with Telegram user identifiers."""
    full_name = html.escape(f"{first_name} {last_name or ''}".strip())
    user_handle = f"@{username}" if username else "<i>No username set</i>"
    admin_badge = "👑 <b>Authorized Administrator</b>" if is_admin else "👤 <b>Standard Member</b>"

    status_badge = {
        "VERIFIED": "✅ Verified",
        "PENDING": "⏳ Pending",
        "SUSPICIOUS": "⚠️ Suspicious",
        "RESTRICTED": "🚫 Restricted",
        "BANNED": "⛔ Banned"
    }.get(status.upper(), status)

    text = (
        "🆔 <b>YOUR TELEGRAM IDENTITY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Name:</b> {full_name}\n"
        f"📎 <b>Username:</b> {user_handle}\n"
        f"🆔 <b>Telegram User ID:</b> <code>{user_id}</code>\n"
        f"💬 <b>Current Chat ID:</b> <code>{chat_id}</code> ({chat_type})\n"
        f"🛡️ <b>Verification:</b> {status_badge} ({risk_score:.0f}/100)\n"
        f"🔑 <b>Role:</b> {admin_badge}\n\n"
        "💡 <i>Tip: To grant admin permissions, copy your User ID <code>{user_id}</code> into the <code>ADMIN_IDS=</code> field of your <code>.env</code> file.</i>"
    )
    return text


def format_monetization_card() -> str:
    """Formats voluntary employer monetization and sponsorship options."""
    text = (
        "⭐ <b>EMPLOYER SPONSORSHIPS & SERVICES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Zero Fee Policy for Freelancers:</b>\n"
        "All basic job screenings, community verification, and job applications are "
        "<b>100% free forever</b>. We NEVER charge users for unlocking jobs, VAT, taxes, "
        "or withdrawal fees.\n\n"
        "<b>Voluntary Employer Promotion Options:</b>\n\n"
        "1. <b>Free Standard Screening (Free)</b>\n"
        "• Automated AI & security screening\n"
        "• Standard broadcast to community channel\n\n"
        "2. <b>⭐ Featured Job Placement</b>\n"
        "• Pinned in the community channel for 48 hours\n"
        "• Highlighted 'Featured' visual badge\n"
        "• Priority moderation queueing\n\n"
        "3. <b>💎 Sponsored Employer Listing</b>\n"
        "• Promoted listing in daily community digests\n"
        "• Direct link to company career portal\n"
        "• Verified company badge\n\n"
        "4. <b>🏢 Employer Business Verification</b>\n"
        "• Dedicated verification of corporate domain and credentials\n"
        "• 'Verified Employer' trust seal on all postings\n\n"
        "5. <b>🤝 Voluntary Community Support</b>\n"
        "• Support platform server and AI screening costs\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>To inquire about featured or sponsored listings, contact community administrators.</i>\n\n"
        f"{COMMUNITY_SAFETY_DISCLAIMER}"
    )
    return text
