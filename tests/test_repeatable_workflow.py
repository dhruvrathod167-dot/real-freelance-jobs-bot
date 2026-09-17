"""
Unit Tests for Repeatable Job-Posting Workflow
Targets "Legally Freelancing Working" group (-1004335696952).
Verifies:
1. Repeated submissions by the same user (no permanent/hourly lockout).
2. Unique auto-incremented Job IDs for every submission.
3. Admin Approve: broadcast directly to Legally Freelancing Working with verified send_message.
4. Admin Reject: marked REJECTED, no publication to group.
5. Auto-deletion of old pending moderation message from admin chat upon approval/rejection.
6. Approved job post in Legally Freelancing Working is never deleted.
7. Duplicate approval / duplicate broadcast prevention.
8. Failed broadcast handling: kept in retryable state (PENDING_REVIEW), actual error displayed.
"""

from contextlib import asynccontextmanager
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from telegram.error import TelegramError

from database.models import Base
from database.crud import get_or_create_user, create_job_submission, get_job_by_id
from handlers.admin import (
    _execute_approval,
    _execute_rejection,
    record_pending_moderation_message,
    delete_pending_moderation_messages,
    PENDING_MODERATION_MESSAGES,
)
from handlers.group import group_message_moderation_handler
from utils.rate_limiter import rate_limiter_manager
from config import settings


class TestRepeatableJobPostingWorkflow(unittest.IsolatedAsyncioTestCase):

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

        # Clean up any state in PENDING_MODERATION_MESSAGES
        PENDING_MODERATION_MESSAGES.clear()

    async def asyncTearDown(self):
        self.db_patcher.stop()
        await self.engine.dispose()
        PENDING_MODERATION_MESSAGES.clear()

    async def test_repeated_submissions_and_unique_job_ids(self):
        """
        Verifies requirement 1 & 2:
        User submits Job #1 -> approved -> user submits Job #2 -> rejected -> user submits Job #3.
        Each job receives a unique integer ID and user is never locked out.
        """
        user_id = 100200300
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=user_id, first_name="DevAlice", username="devalice")

            # Submission #1
            job1 = await create_job_submission(
                session=session,
                user_id=user_id,
                company_name="Corp Alpha",
                company_website="https://corpalpha.example.com",
                contact_email="jobs@corpalpha.example.com",
                job_title="Fullstack React Engineer",
                job_description="Build modern reactive dashboards.",
                payment_rate="$50/hr",
                expected_work="Deliver dashboard components.",
                country_region="Remote",
                application_method="Apply via jobs@corpalpha.example.com",
                original_source=None,
                risk_score=5.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job1_id = job1.id
            await session.commit()

        # Approve Job #1
        mock_context = MagicMock()
        mock_published = MagicMock()
        mock_published.message_id = 1001
        mock_context.bot.send_message = AsyncMock(return_value=mock_published)
        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        await _execute_approval(job_id=job1_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # Rate limiter is cleared for user
        self.assertTrue(rate_limiter_manager.limiters["submissions"].is_allowed(user_id))

        # Submission #2 immediately after
        async with self.session_factory() as session:
            job2 = await create_job_submission(
                session=session,
                user_id=user_id,
                company_name="Corp Beta",
                company_website="https://corpbeta.example.com",
                contact_email="jobs@corpbeta.example.com",
                job_title="DevOps Engineer",
                job_description="Maintain AWS and Docker clusters.",
                payment_rate="$70/hr",
                expected_work="CI/CD pipelines.",
                country_region="Remote",
                application_method="Apply via email",
                original_source=None,
                risk_score=8.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job2_id = job2.id
            await session.commit()

        # Unique Job ID check
        self.assertNotEqual(job1_id, job2_id)
        self.assertEqual(job2_id, job1_id + 1)

        # Reject Job #2
        await _execute_rejection(job_id=job2_id, admin_id=5952301026, reason="Duplicate role", context=mock_context, reply_target=mock_reply_target)

        # Rate limiter remains cleared and user can submit Job #3
        self.assertTrue(asyncio.run(rate_limiter_manager.limiters["submissions"].is_allowed)(user_id))

        async with self.session_factory() as session:
            job3 = await create_job_submission(
                session=session,
                user_id=user_id,
                company_name="Corp Gamma",
                company_website="https://corpgamma.example.com",
                contact_email="jobs@corpgamma.example.com",
                job_title="Python Data Engineer",
                job_description="Build ETL pipelines.",
                payment_rate="$65/hr",
                expected_work="Deliver pipelines.",
                country_region="Remote Worldwide",
                application_method="Apply online",
                original_source=None,
                risk_score=10.0,
                risk_level="low",
                detected_flags=[],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job3_id = job3.id
            await session.commit()

        self.assertEqual(job3_id, job2_id + 1)

    async def test_admin_approve_and_broadcast_verification(self):
        """
        Verifies requirement 3 & 4:
        Admin approve publishes directly to 'Legally Freelancing Working' (-1004335696952),
        verifies send_message succeeds, and records channel_message_id.
        """
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=2001, first_name="HiringManager")
            job = await create_job_submission(
                session=session,
                user_id=2001,
                company_name="Delta Innovations",
                company_website="https://deltainnovations.example.com",
                contact_email="contact@deltainnovations.example.com",
                job_title="Mobile Flutter Developer",
                job_description="Create high performance cross-platform iOS and Android apps.",
                payment_rate="$55/hr",
                expected_work="Build Flutter apps.",
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
        published_msg = MagicMock()
        published_msg.message_id = 98765
        mock_context.bot.send_message = AsyncMock(return_value=published_msg)
        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # Telegram send_message called for target group -1004335696952
        group_calls = [c for c in mock_context.bot.send_message.call_args_list if c[1].get("chat_id") == -1004335696952]
        self.assertEqual(len(group_calls), 1)
        self.assertIn("Delta Innovations", group_calls[0][1]["text"])

        # DB updated to APPROVED with channel_message_id
        async with self.session_factory() as session:
            db_job = await get_job_by_id(session, job_id)
            self.assertEqual(db_job.status, "APPROVED")
            self.assertEqual(db_job.channel_message_id, 98765)

    async def test_admin_reject_flow(self):
        """
        Verifies requirement 5:
        Admin reject marks job as REJECTED and does NOT publish it to the group.
        """
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=3001, first_name="BadActor")
            job = await create_job_submission(
                session=session,
                user_id=3001,
                company_name="Vague Inc",
                company_website="https://vague.example.com",
                contact_email="vague@example.com",
                job_title="Mystery Job",
                job_description="Do tasks for money.",
                payment_rate="$1000/day",
                expected_work="Unknown",
                country_region="Remote",
                application_method="DM me",
                original_source=None,
                risk_score=40.0,
                risk_level="review",
                detected_flags=["Unrealistic compensation"],
                ai_analysis={},
                status="PENDING_REVIEW"
            )
            job_id = job.id
            await session.commit()

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        await _execute_rejection(job_id=job_id, admin_id=5952301026, reason="Vague description and unrealistic rate", context=mock_context, reply_target=mock_reply_target)

        # Verify NO message was sent to Legally Freelancing Working (-1004335696952)
        group_sends = [c for c in mock_context.bot.send_message.call_args_list if c[1].get("chat_id") == -1004335696952]
        self.assertEqual(len(group_sends), 0)

        # Verify DB status is REJECTED
        async with self.session_factory() as session:
            db_job = await get_job_by_id(session, job_id)
            self.assertEqual(db_job.status, "REJECTED")
            self.assertIsNone(db_job.channel_message_id)

    async def test_auto_deletion_of_pending_moderation_message(self):
        """
        Verifies requirement 6:
        Automatically delete the old PENDING MODERATION message from the admin chat
        when approved or rejected.
        """
        job_id = 99
        admin_chat_id = 5952301026
        pending_msg_id = 5555

        record_pending_moderation_message(job_id=job_id, chat_id=admin_chat_id, message_id=pending_msg_id)

        mock_bot = MagicMock()
        mock_bot.delete_message = AsyncMock()

        mock_current_msg = MagicMock()
        mock_current_msg.chat_id = admin_chat_id
        mock_current_msg.message_id = pending_msg_id
        mock_current_msg.delete = AsyncMock()

        # Delete pending moderation messages
        await delete_pending_moderation_messages(job_id=job_id, bot=mock_bot, current_msg=mock_current_msg)

        # Current callback message deleted
        mock_current_msg.delete.assert_awaited_once()

    async def test_prevent_duplicate_approval_and_broadcast(self):
        """
        Verifies requirement 9:
        Prevent duplicate approval/broadcast if admin presses Approve more than once.
        """
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=4001, first_name="Dave")
            job = await create_job_submission(
                session=session,
                user_id=4001,
                company_name="Echo Services",
                company_website="https://echo.example.com",
                contact_email="jobs@echo.example.com",
                job_title="QA Engineer",
                job_description="Automate integration tests.",
                payment_rate="$45/hr",
                expected_work="Write tests.",
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
        published_msg = MagicMock()
        published_msg.message_id = 12345
        mock_context.bot.send_message = AsyncMock(return_value=published_msg)
        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        # 1st Approval: Executes broadcast
        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)
        self.assertEqual(len([c for c in mock_context.bot.send_message.call_args_list if c[1].get("chat_id") == -1004335696952]), 1)

        # 2nd Approval click (duplicate): MUST NOT broadcast again!
        mock_context.bot.send_message.reset_mock()
        mock_reply_target.reply_text.reset_mock()

        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # Group send_message was NOT called again
        group_sends = [c for c in mock_context.bot.send_message.call_args_list if c[1].get("chat_id") == -1004335696952]
        self.assertEqual(len(group_sends), 0)

        # Admin notified that job is already approved
        admin_call = mock_reply_target.reply_text.call_args[0][0]
        self.assertIn("already approved and published", admin_call)

    async def test_failed_broadcast_handling_and_retryable_state(self):
        """
        Verifies requirement 10:
        If Telegram broadcast fails, do NOT report 'completed', show actual error,
        and keep the job in a retryable state (PENDING_REVIEW).
        """
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=5001, first_name="Eve")
            job = await create_job_submission(
                session=session,
                user_id=5001,
                company_name="Foxtrot Systems",
                company_website="https://foxtrot.example.com",
                contact_email="jobs@foxtrot.example.com",
                job_title="Security Analyst",
                job_description="Analyze audit logs.",
                payment_rate="$50/hr",
                expected_work="Log analysis.",
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
        # Simulate Telegram API error on group broadcast
        mock_context.bot.send_message = AsyncMock(side_effect=TelegramError("Chat not found or bot lacks permission"))
        mock_reply_target = MagicMock()
        mock_reply_target.reply_text = AsyncMock()

        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # 1. Admin notified of actual error, NOT completion
        admin_reply = mock_reply_target.reply_text.call_args[0][0]
        self.assertIn("Broadcast FAILED!", admin_reply)
        self.assertIn("Chat not found or bot lacks permission", admin_reply)
        self.assertNotIn("Broadcast to Legally Freelancing Working completed", admin_reply)

        # 2. Database reflects retryable PENDING_REVIEW state
        async with self.session_factory() as session:
            db_job = await get_job_by_id(session, job_id)
            self.assertEqual(db_job.status, "PENDING_REVIEW")
            self.assertIsNone(db_job.channel_message_id)

        # 3. Now simulate that permissions/network are fixed and retry succeeds
        mock_published = MagicMock()
        mock_published.message_id = 99999
        mock_context.bot.send_message = AsyncMock(return_value=mock_published)
        mock_reply_target.reply_text.reset_mock()

        await _execute_approval(job_id=job_id, admin_id=5952301026, context=mock_context, reply_target=mock_reply_target)

        # Broadcast succeeds on retry!
        async with self.session_factory() as session:
            updated_job = await get_job_by_id(session, job_id)
            self.assertEqual(updated_job.status, "APPROVED")
            self.assertEqual(updated_job.channel_message_id, 99999)

    async def test_bot_group_broadcast_never_deleted_by_moderation(self):
        """
        Verifies requirement 8:
        Do NOT delete the final approved job post from Legally Freelancing Working.
        The bot itself or admin posts are exempt from message deletion.
        """
        mock_update = MagicMock()
        mock_update.effective_chat.type = "supergroup"
        mock_update.effective_chat.id = -1004335696952
        mock_update.effective_chat.title = "Legally Freelancing Working"

        # Message is from the bot itself
        mock_update.effective_user.is_bot = True
        mock_update.effective_user.id = 987654321
        mock_update.effective_message.text = "Job #1 Approved: Senior Python Developer at Acme Corp."
        mock_update.effective_message.delete = AsyncMock()

        mock_context = MagicMock()

        await group_message_moderation_handler(mock_update, mock_context)

        # Message must NOT be deleted
        mock_update.effective_message.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
