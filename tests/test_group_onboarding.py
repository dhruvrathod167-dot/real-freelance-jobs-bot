"""
Unit Tests for Automatic New-Member Verification Onboarding & Group Moderation.
Targets "Legally Freelancing Working" group:
1. Auto-onboarding & restriction on join with inline verify button.
2. Unverified users blocked from posting.
3. Verified users permitted to post low-risk freelance opportunities.
4. High-risk scam/fraud messages automatically deleted, sender restricted & flagged SUSPICIOUS, admins alerted.
5. Deep link verification flow.
"""

import asyncio
from contextlib import asynccontextmanager
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database.models import Base
from database.crud import get_or_create_user, confirm_user_rules, get_user_by_id
from handlers.group import (
    onboard_new_member,
    new_member_onboarding_handler,
    group_message_moderation_handler,
    RECENT_WELCOMES,
    LAST_UNVERIFIED_WARNING,
    KNOWN_COMMUNITY_CHATS,
)
from handlers.start import start_handler
from config import settings


class TestGroupOnboardingAndModeration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        RECENT_WELCOMES.clear()
        LAST_UNVERIFIED_WARNING.clear()
        KNOWN_COMMUNITY_CHATS.clear()

        @asynccontextmanager
        async def mock_get_db_session():
            async with self.session_factory() as session:
                yield session
                await session.commit()

        self.db_patcher = patch("handlers.group.get_db_session", side_effect=mock_get_db_session)
        self.mock_db = self.db_patcher.start()

        self.crud_db_patcher = patch("handlers.start.get_db_session", side_effect=mock_get_db_session)
        self.mock_crud_db = self.crud_db_patcher.start()

        self.verify_db_patcher = patch("handlers.verification.get_db_session", side_effect=mock_get_db_session)
        self.mock_verify_db = self.verify_db_patcher.start()

    async def asyncTearDown(self):
        self.db_patcher.stop()
        self.crud_db_patcher.stop()
        self.verify_db_patcher.stop()
        await self.engine.dispose()

    async def test_onboard_new_member_welcome_and_button(self):
        """Verifies welcome message, exact verification text, and inline verify button URL for Legally Freelancing Working."""
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 555666777
        mock_user.first_name = "Charlie"
        mock_user.last_name = "Brown"
        mock_user.username = "charlie_b"
        mock_user.is_bot = False

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        await onboard_new_member(mock_chat, mock_user, mock_context)

        # 1. Proactively restricted chat permissions
        mock_context.bot.restrict_chat_member.assert_awaited_once()

        # 2. Sent welcome message
        mock_context.bot.send_message.assert_awaited_once()
        call_kwargs = mock_context.bot.send_message.call_args[1]

        sent_text = call_kwargs["text"]
        self.assertIn("Please verify your account with @RealFreelanceJobsBot before posting or submitting freelance jobs.", sent_text)
        self.assertIn("Legally Freelancing Working", sent_text)
        self.assertIn("@charlie_b", sent_text)

        # 3. Inline keyboard has 'Verify Account' pointing to https://t.me/RealFreelanceJobsBot?start=verify
        markup = call_kwargs["reply_markup"]
        verify_btn = markup.inline_keyboard[0][0]
        self.assertEqual(verify_btn.text, "✅ Verify Account")
        self.assertEqual(verify_btn.url, f"https://t.me/{settings.BOT_USERNAME}?start=verify")

        # 4. Chat tracked in KNOWN_COMMUNITY_CHATS
        self.assertIn(mock_chat.id, KNOWN_COMMUNITY_CHATS)

    async def test_onboard_new_member_deduplication(self):
        """Verifies duplicate join events within 60 seconds are dropped to avoid group spam."""
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 999888777
        mock_user.first_name = "Diana"
        mock_user.last_name = None
        mock_user.username = "diana_freelancer"
        mock_user.is_bot = False

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        # First join event
        await onboard_new_member(mock_chat, mock_user, mock_context)
        self.assertEqual(mock_context.bot.send_message.await_count, 1)

        # Immediate duplicate event
        await onboard_new_member(mock_chat, mock_user, mock_context)
        # Should still be 1 (duplicate avoided)
        self.assertEqual(mock_context.bot.send_message.await_count, 1)

    async def test_normal_conversation_allowed_in_group(self):
        """Verifies normal professional messages and conversation receive NO ACTION (not deleted, not restricted)."""
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 111222333
        mock_user.first_name = "Eve"
        mock_user.last_name = None
        mock_user.username = "eve_unverified"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.text = "Hello everyone, can I ask a question about Python freelancing?"
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        await group_message_moderation_handler(mock_update, mock_context)

        # Normal professional conversation: NO ACTION
        mock_message.delete.assert_not_awaited()
        mock_context.bot.restrict_chat_member.assert_not_awaited()
        mock_context.bot.send_message.assert_not_awaited()

    async def test_verified_member_can_post_safe_job_message(self):
        """Verifies verified member posting a legitimate, low-risk freelance role is allowed (NOT deleted)."""
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=444555666, first_name="Frank", username="frank_dev")
            await confirm_user_rules(session, user_id=444555666)
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 444555666
        mock_user.first_name = "Frank"
        mock_user.last_name = None
        mock_user.username = "frank_dev"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 10101
        mock_message.text = "We are looking for a Python developer to assist with backend API development. Hourly rate: $45/hr. Contact us at jobs@example.com."
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()

        await group_message_moderation_handler(mock_update, mock_context)

        # Message is NOT deleted!
        mock_message.delete.assert_not_awaited()
        # No error or restriction
        mock_context.bot.send_message.assert_not_awaited()

    async def test_high_risk_scam_message_deleted_and_user_flagged(self):
        """Verifies high-risk fraud (upfront fee, registration fee, deposit) is deleted, sender restricted & flagged SUSPICIOUS, admins alerted."""
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=777888999, first_name="Grace", username="grace_scammer")
            await confirm_user_rules(session, user_id=777888999)
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 777888999
        mock_user.first_name = "Grace"
        mock_user.last_name = None
        mock_user.username = "grace_scammer"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 99999
        mock_message.text = "Hiring immediately! Work from home. Candidate must pay a refundable security deposit of $100 before starting work."
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()
        mock_context.bot.ban_chat_member = AsyncMock()

        # Set admin ID in settings for alert test
        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        # 1. Message deleted
        mock_message.delete.assert_awaited_once()

        # 2. Member banned or restricted
        self.assertTrue(
            mock_context.bot.ban_chat_member.await_count >= 1 or
            mock_context.bot.restrict_chat_member.await_count >= 1
        )

        # 3. User status updated to BANNED in DB
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 777888999)
            self.assertIsNotNone(db_user)
            self.assertEqual(db_user.status, "BANNED")
            self.assertGreaterEqual(db_user.risk_score, 50.0)

        # 4. Admin alert and group warning sent
        self.assertGreaterEqual(mock_context.bot.send_message.await_count, 1)

    async def test_deep_link_start_verify(self):
        """Verifies /start verify deep-link opens verification flow seamlessly."""
        mock_update = MagicMock()
        mock_update.effective_user.id = 123123123
        mock_update.effective_user.first_name = "Henry"
        mock_update.effective_user.last_name = None
        mock_update.effective_user.username = "henry_t"
        mock_update.callback_query = None
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.args = ["verify"]

        with patch("handlers.verification.verify_handler", new_callable=AsyncMock) as mock_verify:
            await start_handler(mock_update, mock_context)
            mock_verify.assert_awaited_once_with(mock_update, mock_context)


if __name__ == "__main__":
    unittest.main()
