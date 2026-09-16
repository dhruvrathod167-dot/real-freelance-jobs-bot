"""
Database Models Module
Defines SQLAlchemy 2.0 ORM models for Users, Jobs, VerificationEvents, Reports, and AuditLogs.
Compatible with SQLite (aiosqlite) and PostgreSQL (asyncpg).
"""

from datetime import datetime, timezone
from typing import Optional, List
import json

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Helper for timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Stores Telegram user profile, verification state, and behavior metrics."""
    __tablename__ = "users"

    # Telegram user ID is unique and primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(256), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Status: PENDING, VERIFIED, SUSPICIOUS, RESTRICTED, BANNED
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Rules confirmation
    rules_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    rules_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Activity counters and moderation
    submission_count: Mapped[int] = mapped_column(Integer, default=0)
    reported_count: Mapped[int] = mapped_column(Integer, default=0)
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    flag_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Temporary restrictions (e.g. 4-day communication restrictions) & bans
    restricted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    restriction_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ban_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    verification_events: Mapped[List["VerificationEvent"]] = relationship(
        "VerificationEvent", back_populates="user", cascade="all, delete-orphan"
    )
    appeals: Mapped[List["Appeal"]] = relationship("Appeal", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username} status={self.status} risk={self.risk_score}>"


class Job(Base):
    """Stores job submissions, automatic scan results, AI analysis, and moderation status."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Collected Job Fields
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    company_website: Mapped[str] = mapped_column(String(512), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(256), nullable=False)
    job_title: Mapped[str] = mapped_column(String(256), nullable=False)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    payment_rate: Mapped[str] = mapped_column(String(256), nullable=False)
    expected_work: Mapped[str] = mapped_column(Text, nullable=False)
    country_region: Mapped[str] = mapped_column(String(256), nullable=False)
    application_method: Mapped[str] = mapped_column(String(512), nullable=False)
    original_source: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Monetization / Placement Tiers (Featured / Sponsored)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    listing_tier: Mapped[str] = mapped_column(String(32), default="standard")  # standard, featured, sponsored

    # Automated Risk Screening
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(32), default="low")  # low, review, high, very_high
    detected_flags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of flags
    ai_analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON AI analysis object

    # Moderation: PENDING_REVIEW, APPROVED, REJECTED, FLAGGED
    status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", index=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Telegram Group Broadcast tracking
    channel_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="jobs")
    reports: Mapped[List["Report"]] = relationship("Report", back_populates="job", cascade="all, delete-orphan")

    @property
    def detected_flags(self) -> List[str]:
        if not self.detected_flags_json:
            return []
        try:
            return json.loads(self.detected_flags_json)
        except Exception:
            return []

    @detected_flags.setter
    def detected_flags(self, flags: List[str]) -> None:
        self.detected_flags_json = json.dumps(flags)

    @property
    def ai_analysis(self) -> dict:
        if not self.ai_analysis_json:
            return {}
        try:
            return json.loads(self.ai_analysis_json)
        except Exception:
            return {}

    @ai_analysis.setter
    def ai_analysis(self, data: dict) -> None:
        self.ai_analysis_json = json.dumps(data)

    def __repr__(self) -> str:
        return f"<Job id={self.id} title={self.job_title!r} company={self.company_name!r} status={self.status}>"


class VerificationEvent(Base):
    """Audit log of user verification events."""
    __tablename__ = "verification_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped["User"] = relationship("User", back_populates="verification_events")


class Report(Base):
    """Community scam / suspicious job and user reports."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    target_job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    target_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)  # OPEN, RESOLVED, DISMISSED
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Optional["Job"]] = relationship("Job", back_populates="reports")


class AuditLog(Base):
    """Immutable audit trail for all admin actions and critical system decisions."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)  # JOB, USER, SYSTEM
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EmployerProfile(Base):
    """Stores optional verified employer business records and monetization tiers."""
    __tablename__ = "employer_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    official_domain: Mapped[str] = mapped_column(String(512), nullable=False)
    is_verified_business: Mapped[bool] = mapped_column(Boolean, default=False)
    tier: Mapped[str] = mapped_column(String(32), default="standard")  # standard, verified_employer, premium
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Appeal(Base):
    """Stores banned or restricted user appeals for administrator moderation."""
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    appeal_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)  # PENDING, APPROVED, REJECTED
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped["User"] = relationship("User", back_populates="appeals")


class VerificationMessage(Base):
    """Tracks monthly verification message count to prevent spam."""
    __tablename__ = "verification_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "welcome", "verification"
    calendar_month: Mapped[int] = mapped_column(Integer, nullable=False)  # Year (YYYY) * 100 + Month (1-12)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped["User"] = relationship("User")
