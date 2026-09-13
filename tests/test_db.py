"""
Async Database and ORM Unit Tests
Tests database initialization, user verification workflow, job submission persistence,
status updates, reports, and audit logging.
"""

import asyncio
import unittest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database.models import Base
from database.crud import (
    get_or_create_user,
    confirm_user_rules,
    set_user_status,
    create_job_submission,
    get_job_by_id,
    update_job_status,
    create_report,
    create_audit_entry,
    get_system_stats,
)


class TestDatabaseOperations(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # In-memory SQLite for test isolation
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        # Initialize schema
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_user_creation_and_verification(self):
        async with self.session_factory() as session:
            # 1. Create initial user
            user = await get_or_create_user(
                session=session,
                user_id=123456789,
                first_name="Alice",
                username="alice_dev"
            )
            await session.commit()
            self.assertEqual(user.status, "PENDING")
            self.assertFalse(user.rules_accepted)

            # 2. Confirm rules / verify
            verified_user = await confirm_user_rules(session=session, user_id=123456789)
            await session.commit()
            self.assertEqual(verified_user.status, "VERIFIED")
            self.assertTrue(verified_user.rules_accepted)

    async def test_job_submission_and_approval(self):
        async with self.session_factory() as session:
            # Create poster user
            await get_or_create_user(session, user_id=999, first_name="Bob")
            await session.commit()

            # Submit job
            job = await create_job_submission(
                session=session,
                user_id=999,
                company_name="Tech Solutions Ltd",
                company_website="https://techsolutions.com",
                contact_email="jobs@techsolutions.com",
                job_title="Fullstack Engineer",
                job_description="Build modern web apps with Python and Vue.",
                payment_rate="$60/hr",
                expected_work="Build features and APIs",
                country_region="Remote Worldwide",
                application_method="Email resume",
                original_source="Direct",
                risk_score=5.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={"recommendation": "approve"},
                status="PENDING_REVIEW"
            )
            await session.commit()
            self.assertEqual(job.status, "PENDING_REVIEW")
            job_id = job.id

            # Approve job
            approved_job = await update_job_status(
                session=session,
                job_id=job_id,
                status="APPROVED",
                admin_notes="Approved clean listing",
                actor_id=1001
            )
            await session.commit()
            self.assertEqual(approved_job.status, "APPROVED")

    async def test_report_and_audit_logging(self):
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=111, first_name="Charlie")
            await session.commit()

            # Create report
            report = await create_report(
                session=session,
                reporter_id=111,
                reason="User asked for upfront deposit fee",
                target_user_id=222
            )
            await session.commit()
            self.assertEqual(report.status, "OPEN")
            self.assertEqual(report.reporter_user_id, 111)

            # Create audit log
            audit = await create_audit_entry(
                session=session,
                actor_id=1001,
                action="USER_BANNED",
                target_type="USER",
                target_id="222",
                details="Scam upfront fee verified"
            )
            await session.commit()
            self.assertEqual(audit.action, "USER_BANNED")

            # Check stats
            stats = await get_system_stats(session)
            self.assertEqual(stats["open_reports"], 1)


if __name__ == "__main__":
    unittest.main()
