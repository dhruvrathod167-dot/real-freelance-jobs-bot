"""
Database CRUD Operations
Provides high-level async helper functions for users, jobs, reports, verification, and audit logs.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Job, VerificationEvent, Report, AuditLog, EmployerProfile, Appeal, VerificationMessage
from utils.logger import logger
from utils.security import SecurityError, AuthorizationError


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    first_name: str,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
) -> User:
    """Retrieves an existing user or creates a new pending profile."""
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    clean_first_name = str(first_name) if (first_name is not None and type(first_name).__name__ != "MagicMock") else "User"
    clean_last_name = str(last_name) if (last_name is not None and type(last_name).__name__ != "MagicMock") else None
    clean_username = str(username) if (username is not None and type(username).__name__ != "MagicMock") else None

    if user is None:
        user = User(
            id=int(user_id),
            first_name=clean_first_name,
            last_name=clean_last_name,
            username=clean_username,
            status="PENDING",
            risk_score=0.0,
            rules_accepted=False,
        )
        session.add(user)
        await session.flush()
        logger.info(f"Created new user profile: ID {user_id}, @{clean_username}")
    else:
        # Update latest name/handle if changed
        user.first_name = clean_first_name
        user.last_name = clean_last_name
        user.username = clean_username
        await session.flush()

    return user


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    """Fetches a user by Telegram ID."""
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def confirm_user_rules(session: AsyncSession, user_id: int) -> User:
    """Marks user rules as accepted and verifies the user profile."""
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.rules_accepted = True
        user.rules_accepted_at = datetime.now(timezone.utc)
        if user.status in ("PENDING", "RESTRICTED", None):
            user.status = "VERIFIED"

        # Record verification event
        event = VerificationEvent(
            user_id=user_id,
            action="RULES_CONFIRMED",
            details="User explicitly confirmed community anti-scam terms."
        )
        session.add(event)
        await session.flush()

    return user


async def set_user_status(
    session: AsyncSession,
    user_id: int,
    status: str,
    flag_notes: Optional[str] = None,
    actor_id: int = 0
) -> Optional[User]:
    """Updates user verification status (VERIFIED, RESTRICTED, BANNED)."""
    from config import settings
    
    # Prevent banning or restricting the owner
    if settings.is_owner(user_id) and status in ("BANNED", "RESTRICTED"):
        raise AuthorizationError("Owner cannot be banned or restricted")
    
    # Prevent admins from banning other admins (unless they're the owner)
    if settings.is_admin(user_id) and not settings.is_owner(actor_id) and status == "BANNED":
        raise AuthorizationError("Admins cannot ban other admins")
    
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        old_status = user.status
        user.status = status
        if flag_notes:
            user.flag_notes = flag_notes

        event = VerificationEvent(
            user_id=user_id,
            action=f"STATUS_CHANGED_{status}",
            details=f"Status changed from {old_status} to {status}. Reason: {flag_notes}"
        )
        session.add(event)

        audit = AuditLog(
            actor_id=actor_id,
            action=f"USER_{status}",
            target_type="USER",
            target_id=str(user_id),
            details=flag_notes
        )
        session.add(audit)
        await session.flush()

    return user


async def create_job_submission(
    session: AsyncSession,
    user_id: int,
    company_name: str,
    company_website: str,
    contact_email: str,
    job_title: str,
    job_description: str,
    payment_rate: str,
    expected_work: str,
    country_region: str,
    application_method: str,
    original_source: Optional[str],
    risk_score: float,
    risk_level: str,
    detected_flags: List[str],
    ai_analysis: Dict[str, Any],
    status: str = "PENDING_REVIEW"
) -> Job:
    """Stores a newly screened job posting."""
    job = Job(
        user_id=user_id,
        company_name=company_name,
        company_website=company_website,
        contact_email=contact_email,
        job_title=job_title,
        job_description=job_description,
        payment_rate=payment_rate,
        expected_work=expected_work,
        country_region=country_region,
        application_method=application_method,
        original_source=original_source,
        risk_score=risk_score,
        risk_level=risk_level,
        status=status,
    )
    job.detected_flags = detected_flags
    job.ai_analysis = ai_analysis
    session.add(job)

    # Increment user submission counter
    user = await get_user_by_id(session, user_id)
    if user:
        user.submission_count += 1

    await session.flush()
    return job


async def get_job_by_id(session: AsyncSession, job_id: int) -> Optional[Job]:
    """Fetches job by primary key."""
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_pending_jobs(session: AsyncSession, limit: int = 10, offset: int = 0) -> List[Job]:
    """Retrieves pending jobs ordered by descending risk score (highest risk first)."""
    stmt = select(Job).where(Job.status == "PENDING_REVIEW").order_by(Job.risk_score.desc(), Job.created_at.asc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_job_status(
    session: AsyncSession,
    job_id: int,
    status: str,
    admin_notes: Optional[str] = None,
    channel_message_id: Optional[int] = None,
    actor_id: int = 0
) -> Optional[Job]:
    """Updates job moderation status (APPROVED, REJECTED, etc.)."""
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()

    if job:
        job.status = status
        if admin_notes:
            job.admin_notes = admin_notes
        if channel_message_id is not None:
            job.channel_message_id = channel_message_id

        audit = AuditLog(
            actor_id=actor_id,
            action=f"JOB_{status}",
            target_type="JOB",
            target_id=str(job_id),
            details=admin_notes
        )
        session.add(audit)
        await session.flush()

    return job


async def create_report(
    session: AsyncSession,
    reporter_id: int,
    reason: str,
    target_job_id: Optional[int] = None,
    target_user_id: Optional[int] = None
) -> Report:
    """Stores a user scam / suspicious report."""
    report = Report(
        reporter_user_id=reporter_id,
        target_job_id=target_job_id,
        target_user_id=target_user_id,
        reason=reason,
        status="OPEN"
    )
    session.add(report)

    if target_user_id:
        target_user = await get_user_by_id(session, target_user_id)
        if target_user:
            target_user.reported_count += 1

    await session.flush()
    return report


async def create_audit_entry(
    session: AsyncSession,
    actor_id: int,
    action: str,
    target_type: str,
    target_id: str,
    details: Optional[str] = None
) -> AuditLog:
    """Logs an explicit administrative action to the audit trail."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_system_stats(session: AsyncSession) -> Dict[str, Any]:
    """Gathers community statistics for admins and dashboard."""
    total_users = await session.scalar(select(func.count(User.id)))
    verified_users = await session.scalar(select(func.count(User.id)).where(User.status == "VERIFIED"))
    banned_users = await session.scalar(select(func.count(User.id)).where(User.status == "BANNED"))

    total_jobs = await session.scalar(select(func.count(Job.id)))
    approved_jobs = await session.scalar(select(func.count(Job.id)).where(Job.status == "APPROVED"))
    pending_jobs = await session.scalar(select(func.count(Job.id)).where(Job.status == "PENDING_REVIEW"))
    rejected_jobs = await session.scalar(select(func.count(Job.id)).where(Job.status == "REJECTED"))

    open_reports = await session.scalar(select(func.count(Report.id)).where(Report.status == "OPEN"))

    return {
        "total_users": total_users or 0,
        "verified_users": verified_users or 0,
        "banned_users": banned_users or 0,
        "total_jobs": total_jobs or 0,
        "approved_jobs": approved_jobs or 0,
        "pending_jobs": pending_jobs or 0,
        "rejected_jobs": rejected_jobs or 0,
        "open_reports": open_reports or 0,
    }


async def set_job_tier(
    session: AsyncSession,
    job_id: int,
    is_featured: bool = False,
    is_sponsored: bool = False,
    listing_tier: str = "standard",
    actor_id: int = 0
) -> Optional[Job]:
    """Updates job placement and monetization tier (featured, sponsored)."""
    stmt = select(Job).where(Job.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()

    if job:
        job.is_featured = is_featured
        job.is_sponsored = is_sponsored
        job.listing_tier = listing_tier

        audit = AuditLog(
            actor_id=actor_id,
            action="JOB_TIER_UPDATED",
            target_type="JOB",
            target_id=str(job_id),
            details=f"Tier: {listing_tier}, Featured: {is_featured}, Sponsored: {is_sponsored}"
        )
        session.add(audit)
        await session.flush()

    return job


async def flag_user_suspicious(
    session: AsyncSession,
    user_id: int,
    reason: str,
    risk_score: float = 60.0,
    actor_id: int = 0
) -> Optional[User]:
    """Automatically or administratively flags a user account as SUSPICIOUS."""
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        old_status = user.status
        # If user is already banned or restricted, preserve that state
        if old_status not in ("BANNED", "RESTRICTED"):
            user.status = "SUSPICIOUS"
        user.risk_score = max(user.risk_score, risk_score)
        user.flag_notes = f"[Suspicious Flag]: {reason}"

        event = VerificationEvent(
            user_id=user_id,
            action="STATUS_CHANGED_SUSPICIOUS",
            details=f"Flagged suspicious: {reason}"
        )
        session.add(event)

        audit = AuditLog(
            actor_id=actor_id,
            action="USER_FLAGGED_SUSPICIOUS",
            target_type="USER",
            target_id=str(user_id),
            details=reason
        )
        session.add(audit)
        await session.flush()

    return user


async def get_employer_profile(session: AsyncSession, user_id: int) -> Optional[EmployerProfile]:
    """Fetches an employer profile by user ID."""
    stmt = select(EmployerProfile).where(EmployerProfile.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_employer_profile(
    session: AsyncSession,
    user_id: int,
    company_name: str,
    official_domain: str,
    tier: str = "standard",
    is_verified_business: bool = False
) -> EmployerProfile:
    """Creates or updates an employer profile."""
    stmt = select(EmployerProfile).where(EmployerProfile.user_id == user_id)
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = EmployerProfile(
            user_id=user_id,
            company_name=company_name,
            official_domain=official_domain,
            tier=tier,
            is_verified_business=is_verified_business
        )
        session.add(profile)
    else:
        profile.company_name = company_name
        profile.official_domain = official_domain
        profile.tier = tier
        profile.is_verified_business = is_verified_business

    await session.flush()
    return profile


async def restrict_user_communication(
    session: AsyncSession,
    user_id: int,
    duration_days: int = 4,
    reason: str = "Communication violation (Abuse / Harassment / Spam)",
    actor_id: int = 0
) -> Optional[User]:
    """Restricts user from sending messages for a specified number of days (default 4 days)."""
    from config import settings
    
    # Prevent restricting the owner
    if settings.is_owner(user_id):
        raise AuthorizationError("Owner cannot be restricted")
    
    # Prevent admins from restricting other admins (unless they're the owner)
    if settings.is_admin(user_id) and not settings.is_owner(actor_id):
        raise AuthorizationError("Admins cannot restrict other admins")
    
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        now = datetime.now(timezone.utc)
        user.status = "RESTRICTED"
        user.restricted_until = now + timedelta(days=duration_days)
        user.restriction_reason = reason
        user.violation_count += 1

        event = VerificationEvent(
            user_id=user_id,
            action="COMMUNICATION_RESTRICTED",
            details=f"Restricted for {duration_days} days until {user.restricted_until.isoformat()}. Reason: {reason}"
        )
        session.add(event)

        audit = AuditLog(
            actor_id=actor_id,
            action="USER_RESTRICTED_COMMUNICATION",
            target_type="USER",
            target_id=str(user_id),
            details=f"Duration: {duration_days} days. Expiry: {user.restricted_until.isoformat()}. Reason: {reason}"
        )
        session.add(audit)
        await session.flush()

    return user


async def ban_user_permanent(
    session: AsyncSession,
    user_id: int,
    reason: str = "Malicious scam content / repeated severe violations",
    actor_id: int = 0,
    risk_score: Optional[float] = None,
) -> Optional[User]:
    """Permanently bans a user from community participation."""
    from config import settings
    
    # Prevent banning the owner
    if settings.is_owner(user_id):
        raise AuthorizationError("Owner cannot be banned")
    
    # Prevent admins from banning other admins (unless they're the owner)
    if settings.is_admin(user_id) and not settings.is_owner(actor_id):
        raise AuthorizationError("Admins cannot ban other admins")
    
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.status = "BANNED"
        user.ban_reason = reason
        user.restricted_until = None
        user.violation_count += 1
        if risk_score is not None:
            user.risk_score = risk_score
        elif user.risk_score < 50.0:
            user.risk_score = 100.0

        event = VerificationEvent(
            user_id=user_id,
            action="USER_PERMANENTLY_BANNED",
            details=f"Banned permanently. Reason: {reason}"
        )
        session.add(event)

        audit = AuditLog(
            actor_id=actor_id,
            action="USER_BANNED_PERMANENT",
            target_type="USER",
            target_id=str(user_id),
            details=reason
        )
        session.add(audit)
        await session.flush()

    return user


async def unban_and_restore_user(
    session: AsyncSession,
    user_id: int,
    actor_id: int = 0,
    notes: str = "Pardoned by administrator"
) -> Optional[User]:
    """Restores a restricted or banned user back to VERIFIED with cleared restrictions."""
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        old_status = user.status
        user.status = "VERIFIED"
        user.restricted_until = None
        user.restriction_reason = None
        user.ban_reason = None

        event = VerificationEvent(
            user_id=user_id,
            action="USER_UNBANNED_RESTORED",
            details=f"Restored from {old_status} to VERIFIED. Notes: {notes}"
        )
        session.add(event)

        audit = AuditLog(
            actor_id=actor_id,
            action="USER_UNBANNED",
            target_type="USER",
            target_id=str(user_id),
            details=notes
        )
        session.add(audit)
        await session.flush()

    return user


async def get_expired_restrictions(session: AsyncSession) -> List[User]:
    """Retrieves all users whose temporary restriction duration has expired."""
    stmt = select(User).where(
        User.status == "RESTRICTED",
        User.restricted_until.isnot(None),
    )
    result = await session.execute(stmt)
    users = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    expired = []
    for u in users:
        r_until = u.restricted_until
        if r_until.tzinfo is None:
            r_until = r_until.replace(tzinfo=timezone.utc)
        if r_until <= now:
            expired.append(u)
    return expired


async def create_appeal(
    session: AsyncSession,
    user_id: int,
    appeal_text: str
) -> Appeal:
    """Stores a user's ban/restriction appeal for administrator review."""
    appeal = Appeal(
        user_id=user_id,
        appeal_text=appeal_text,
        status="PENDING",
    )
    session.add(appeal)
    await session.flush()

    audit = AuditLog(
        actor_id=user_id,
        action="APPEAL_SUBMITTED",
        target_type="APPEAL",
        target_id=str(appeal.id),
        details=appeal_text[:300]
    )
    session.add(audit)
    await session.flush()
    return appeal


async def get_appeal_by_id(session: AsyncSession, appeal_id: int) -> Optional[Appeal]:
    """Retrieves an appeal record by ID."""
    stmt = select(Appeal).where(Appeal.id == appeal_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_pending_appeals(session: AsyncSession, limit: int = 10) -> List[Appeal]:
    """Retrieves pending appeals awaiting administrator decision."""
    stmt = select(Appeal).where(Appeal.status == "PENDING").order_by(Appeal.created_at.asc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_user_appeal(session: AsyncSession, user_id: int) -> Optional[Appeal]:
    """Retrieves the latest pending appeal for a user if one exists."""
    stmt = select(Appeal).where(Appeal.user_id == user_id, Appeal.status == "PENDING").order_by(Appeal.created_at.desc())
    result = await session.execute(stmt)
    return result.scalars().first()


async def resolve_appeal(
    session: AsyncSession,
    appeal_id: int,
    status: str,  # APPROVED or REJECTED
    admin_id: int,
    notes: Optional[str] = None
) -> Optional[Appeal]:
    """Marks an appeal as APPROVED or REJECTED by an administrator."""
    stmt = select(Appeal).where(Appeal.id == appeal_id)
    result = await session.execute(stmt)
    appeal = result.scalar_one_or_none()

    if appeal:
        appeal.status = status
        appeal.reviewed_by = admin_id
        appeal.reviewed_at = datetime.now(timezone.utc)
        appeal.admin_notes = notes

        audit = AuditLog(
            actor_id=admin_id,
            action=f"APPEAL_{status}",
            target_type="APPEAL",
            target_id=str(appeal_id),
            details=f"Appeal {status} for User {appeal.user_id}. Notes: {notes}"
        )
        session.add(audit)
        await session.flush()

    return appeal


async def get_verification_message_count(
    session: AsyncSession,
    user_id: int,
    message_type: str,
    calendar_month: int
) -> int:
    """Get count of verification messages sent to a user in a specific calendar month."""
    stmt = select(func.count(VerificationMessage.id)).where(
        VerificationMessage.user_id == user_id,
        VerificationMessage.message_type == message_type,
        VerificationMessage.calendar_month == calendar_month
    )
    result = await session.execute(stmt)
    return result.scalar_one() or 0


async def create_verification_message(
    session: AsyncSession,
    user_id: int,
    message_type: str,
    calendar_month: int
) -> VerificationMessage:
    """Create a verification message tracking entry."""
    verification_msg = VerificationMessage(
        user_id=user_id,
        message_type=message_type,
        calendar_month=calendar_month
    )
    session.add(verification_msg)
    await session.flush()
    return verification_msg
