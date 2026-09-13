"""
Unit Tests for Approved Job Broadcast Flow.
Verifies target group resolution (-1004335696952 / Legally Freelancing Working),
successful send verification, failure error reporting, and prevention of false completion claims.
"""

from contextlib import asynccontextmanager
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from telegram.error import TelegramError

from database.models import Base
from database.crud import get_or_create_user, create_job_submission, get_job_by_id
from handlers.admin import _execute_approval, broadcast_job_handler
from config import settings


class TestApprovedJobBroadcast(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        @asynccontextmanager
        async def mock_get_db_session():
            async with self.session_factory() as session:
                yield session
                await session.commit()

        self.db_patcher = patch("handlers.admin.get_db_session", side_effect=mock_get_db_session)
        self.mock_db = self.db_patcher.start()

    async def asyncTearDown(self):
        self.db_patcher.stop()
        await self.engine.dispose()

    async def test_broadcast_success_to_legally_freelancing_working(self):
        """Verifies approved job sends message to target group and confirms only upon success."""
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=12345, first_name="Alice", username="alice_hiring")
            job = await create_job_submission(
                session=session,
                user_id=12345,
                company_name="Tech Solutions Ltd.",
                company_website="https://techsolutions.example.com",
                contact_email="hiring@techsolutions.example.com",
                job_title="Senior Python Backend Engineer",
                job_description="Developing microservices and database pipelines.",
                payment_rate="$60/hr",
                expected_work="Build APIs and unit tests.",
                country_region="Remote",
                application_method="Apply via email",
                original_source=None,
                risk_score=5.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job_id = job.id
            await session.commit()

        mock_context = MagicMock()
        mock_published = MagicMock()
        mock_published.message_id = 777
        mock_context.bot.send_message = AsyncMock(return_value=mock_published)

        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        # Execute approval
        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # 1. Verified Telegram send called with target group ID -1004335696952
        send_calls = [c for c in mock_context.bot.send_message.call_args_list if c[1].get("chat_id") == -1004335696952]
        self.assertEqual(len(send_calls), 1)
        sent_kwargs = send_calls[0][1]
        self.assertIn("Tech Solutions Ltd.", sent_kwargs["text"])
        self.assertIn("Senior Python Backend Engineer", sent_kwargs["text"])

        # 2. Admin received confirmation with exact group name and message ID
        mock_reply_target.reply_text.assert_awaited_once()
        admin_reply = mock_reply_target.reply_text.call_args[0][0]
        self.assertIn("Approved!", admin_reply)
        self.assertIn("Legally Freelancing Working", admin_reply)
        self.assertIn("777", admin_reply)

        # 3. Database status updated to APPROVED with channel_message_id
        async with self.session_factory() as session:
            updated_job = await get_job_by_id(session, job_id)
            self.assertEqual(updated_job.status, "APPROVED")
            self.assertEqual(updated_job.channel_message_id, 777)

    async def test_broadcast_failure_reports_error_and_does_not_claim_completion(self):
        """Verifies that if Telegram send fails, actual error is shown and completion is NOT claimed."""
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=67890, first_name="Bob", username="bob_recruiter")
            job = await create_job_submission(
                session=session,
                user_id=67890,
                company_name="Alpha Corp",
                company_website="https://alpha.example.com",
                contact_email="jobs@alpha.example.com",
                job_title="Data Analyst",
                job_description="Analyze operational metrics.",
                payment_rate="$40/hr",
                expected_work="Build reports.",
                country_region="Remote",
                application_method="Apply via jobs@alpha.example.com",
                original_source=None,
                risk_score=10.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job_id = job.id
            await session.commit()

        mock_context = MagicMock()
        # Simulate Telegram API error (e.g. permission error or network drop)
        mock_context.bot.send_message = AsyncMock(side_effect=TelegramError("Chat not found or bot lacks permission"))

        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # Admin notified of FAILURE with exact error, NOT false completion
        mock_reply_target.reply_text.assert_awaited_once()
        admin_reply = mock_reply_target.reply_text.call_args[0][0]
        self.assertIn("Broadcast FAILED!", admin_reply)
        self.assertIn("Chat not found or bot lacks permission", admin_reply)
        self.assertNotIn("Broadcast to verified community completed", admin_reply)

        # Database reflects failure
        async with self.session_factory() as session:
            updated_job = await get_job_by_id(session, job_id)
            self.assertIsNone(updated_job.channel_message_id)
            self.assertIn("Broadcast Failed", updated_job.admin_notes)

    async def test_broadcast_unconfigured_group_warns_admin(self):
        """Verifies that if target group ID is unset, admin is warned and send is not blindly claimed."""
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=11111, first_name="Carol", username="carol")
            job = await create_job_submission(
                session=session,
                user_id=11111,
                company_name="Beta Inc",
                company_website="https://beta.example.com",
                contact_email="jobs@beta.example.com",
                job_title="Copywriter",
                job_description="Write blog posts.",
                payment_rate="$30/hr",
                expected_work="Content creation.",
                country_region="Remote",
                application_method="Email us",
                original_source=None,
                risk_score=5.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job_id = job.id
            await session.commit()

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()

        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        with patch.object(settings, "TELEGRAM_GROUP_ID", ""):
            await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        admin_reply = mock_reply_target.reply_text.call_args[0][0]
        self.assertIn("Broadcast FAILED!", admin_reply)
        self.assertIn("Target group chat ID is not configured", admin_reply)


if __name__ == "__main__":
    unittest.main()
