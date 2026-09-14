"""
Unit Tests for Strict Community Moderation and Ban/Appeal System
Targets "Legally Freelancing Working" community group (-1004335696952).

Verifies:
1. Professional discussion allowed (rates, code reviews, technical debates, constructive critique).
2. 1st serious communication violation (abuse, threats, harassment, spam) -> 4-day sending restriction.
3. Database records restriction reason, timestamp, and expiry.
4. Auto-restoration of expired 4-day restrictions restores permissions and sets status to VERIFIED.
5. Repeated communication violations escalate to 14-day restriction and permanent ban.
6. Malicious scam post in group -> immediate deletion and permanent ban.
7. /appeal workflow in DM: submission, rate-limiting, status verification.
8. Admin review of appeals: Reject maintains ban, Unban restores Telegram permissions and VERIFIED status.
9. /appeals command lists pending appeals.
10. /rules displays the 10 professional community rules.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database.models import Base, User
from database.crud import (
    get_or_create_user,
    get_user_by_id,
    restrict_user_communication,
    ban_user_permanent,
    unban_and_restore_user,
    get_expired_restrictions,
    create_appeal,
    get_appeal_by_id,
    get_pending_appeals,
    resolve_appeal,
)
from services.communication_moderator import scan_communication_message
from handlers.group import (
    group_message_moderation_handler,
    auto_restore_expired_restrictions,
)
from handlers.appeal import appeal_handler
from handlers.admin import (
    list_appeals_handler,
    admin_callback_dispatcher,
    unrestrict_user_handler,
)
from handlers.start import rules_handler
from config import settings


class TestCommunityModerationAndAppeals(unittest.IsolatedAsyncioTestCase):

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

        self.db_patches = [
            patch("handlers.group.get_db_session", side_effect=mock_get_db_session),
            patch("handlers.appeal.get_db_session", side_effect=mock_get_db_session),
            patch("handlers.admin.get_db_session", side_effect=mock_get_db_session),
            patch("handlers.start.get_db_session", side_effect=mock_get_db_session),
        ]
        for p in self.db_patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.db_patches:
            p.stop()
        await self.engine.dispose()

    async def test_professional_discussion_allowed(self):
        """Verifies normal professional conversations about freelance work, rates, tech are NOT blocked."""
        test_messages = [
            "What is the average hourly rate for a Senior Python / React developer in Europe?",
            "I disagree with using MongoDB for this project, PostgreSQL with ACID transactions is much better suited.",
            "Can someone review my Upwork portfolio and give constructive criticism on my copy?",
            "Make sure you get a 50% deposit before handing over source code to new freelance clients.",
            "Hey team, does anyone have experience integrating Stripe Webhooks with FastAPI?",
        ]

        for text in test_messages:
            scan = scan_communication_message(text)
            self.assertFalse(scan.is_violation, f"Message was falsely flagged as violation: '{text}' (Type: {scan.violation_type})")

    async def test_first_serious_communication_violation_triggers_4_day_restriction(self):
        """Verifies 1st serious violation (abusive/threat) deletes message, applies 4-day mute, records in DB."""
        # 1. Setup verified user in DB
        async with self.session_factory() as session:
            await get_or_create_user(
                session=session,
                user_id=1001,
                first_name="ToxicUser",
                username="toxic_guy",
            )
            user = await get_user_by_id(session, 1001)
            user.status = "VERIFIED"
            user.rules_accepted = True
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 1001
        mock_user.first_name = "ToxicUser"
        mock_user.username = "toxic_guy"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 555
        mock_message.text = "You are an absolute idiot scammer piece of trash, I will find where you live and kill you!"
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        # 1. Message deleted
        mock_message.delete.assert_awaited_once()

        # 2. Telegram restrict_chat_member called with until_date ~ 4 days
        mock_context.bot.restrict_chat_member.assert_awaited_once()
        _, kwargs = mock_context.bot.restrict_chat_member.call_args
        until_date = kwargs.get("until_date")
        self.assertIsNotNone(until_date)
        # Expected around 4 days from now
        now = datetime.now(timezone.utc)
        self.assertGreater(until_date, now + timedelta(days=3))
        self.assertLessEqual(until_date, now + timedelta(days=5))

        # 3. User status in DB updated to RESTRICTED with 4-day expiry
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 1001)
            self.assertIsNotNone(db_user)
            self.assertEqual(db_user.status, "RESTRICTED")
            self.assertEqual(db_user.violation_count, 1)
            self.assertIsNotNone(db_user.restricted_until)
            self.assertIn("THREAT", db_user.restriction_reason.upper())

        # 4. DM sent to user with /appeal instructions
        dm_sent = any(
            call.kwargs.get("chat_id") == 1001 and "/appeal" in call.kwargs.get("text", "")
            for call in mock_context.bot.send_message.call_args_list
        )
        self.assertTrue(dm_sent, "User should have received DM with /appeal instructions")

    async def test_auto_restore_expired_4_day_restrictions(self):
        """Verifies background job automatically restores sending permissions after 4 days expire."""
        async with self.session_factory() as session:
            # Create user whose restriction expired 1 hour ago
            user = await get_or_create_user(
                session=session,
                user_id=2002,
                first_name="PardonedMember",
                username="pardoned",
            )
            user.status = "RESTRICTED"
            user.restricted_until = datetime.now(timezone.utc) - timedelta(hours=1)
            user.restriction_reason = "1st communication violation"
            user.violation_count = 1
            await session.commit()

        mock_bot = MagicMock()
        mock_bot.restrict_chat_member = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with patch.object(settings, "TELEGRAM_GROUP_ID", "-1004335696952"):
            restored = await auto_restore_expired_restrictions(mock_bot)

        self.assertIn(2002, restored)
        mock_bot.restrict_chat_member.assert_awaited_once()
        _, kwargs = mock_bot.restrict_chat_member.call_args
        perms = kwargs.get("permissions")
        self.assertTrue(perms.can_send_messages)

        # Check DB state
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 2002)
            self.assertEqual(db_user.status, "VERIFIED")
            self.assertIsNone(db_user.restricted_until)
            self.assertIsNone(db_user.restriction_reason)

    async def test_repeated_communication_violations_escalation(self):
        """Verifies repeated violations escalate to 14 days and permanent ban."""
        async with self.session_factory() as session:
            user = await get_or_create_user(
                session=session,
                user_id=3003,
                first_name="RepeatOffender",
                username="repeater",
            )
            user.status = "VERIFIED"
            user.rules_accepted = True
            user.violation_count = 1  # Already had 1 violation
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 3003
        mock_user.first_name = "RepeatOffender"
        mock_user.username = "repeater"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 777
        mock_message.text = "You are a complete useless idiot and piece of garbage, shut your face!"
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        # 2nd violation -> 14 days
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 3003)
            now = datetime.now(timezone.utc)
            restr = db_user.restricted_until if db_user.restricted_until.tzinfo else db_user.restricted_until.replace(tzinfo=timezone.utc)
            self.assertGreater(restr, now + timedelta(days=12))

        # Simulate that the 14-day restriction has completed and user is VERIFIED with violation_count=2
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 3003)
            db_user.status = "VERIFIED"
            db_user.restricted_until = None
            await session.commit()

        # 3rd violation -> permanent ban
        mock_message_3 = MagicMock()
        mock_message_3.message_id = 778
        mock_message_3.text = "Shut your mouth you stupid moron, get lost!"
        mock_message_3.delete = AsyncMock()
        mock_update.effective_message = mock_message_3
        mock_context.bot.ban_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 3003)
            self.assertEqual(db_user.status, "BANNED")
            self.assertEqual(db_user.violation_count, 3)

    async def test_malicious_scam_job_triggers_immediate_permanent_ban(self):
        """Verifies fraudulent job posts (upfront fee / crypto / OTP) immediately trigger permanent ban."""
        async with self.session_factory() as session:
            user = await get_or_create_user(
                session=session,
                user_id=4004,
                first_name="ScamBot",
                username="scammer",
            )
            user.status = "VERIFIED"
            user.rules_accepted = True
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 4004
        mock_user.first_name = "ScamBot"
        mock_user.username = "scammer"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 999
        mock_message.text = "URGENT JOB: Earn $1000/day copy typing! Pay 50 USDT registration fee to start. Send OTP code to verify."
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()
        mock_context.bot.ban_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        mock_message.delete.assert_awaited_once()
        mock_context.bot.ban_chat_member.assert_awaited_once_with(chat_id=-1004335696952, user_id=4004)

        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 4004)
            self.assertEqual(db_user.status, "BANNED")
            self.assertIn("Malicious scam post", db_user.ban_reason)

    async def test_appeal_submission_in_dm(self):
        """Verifies /appeal command in private bot chat submits an appeal to database."""
        async with self.session_factory() as session:
            user = await get_or_create_user(
                session=session,
                user_id=5005,
                first_name="BannedMember",
                username="banned_joe",
            )
            user.status = "BANNED"
            user.ban_reason = "Repeated abusive comments"
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.type = "private"

        mock_user = MagicMock()
        mock_user.id = 5005
        mock_user.first_name = "BannedMember"
        mock_user.username = "banned_joe"

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.args = ["My", "account", "was", "compromised", "and", "I", "have", "now", "secured", "it.", "Please", "reconsider."]
        mock_context.bot.send_message = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await appeal_handler(mock_update, mock_context)

        # Confirmation sent to user
        mock_update.message.reply_text.assert_awaited()
        user_reply = mock_update.message.reply_text.call_args[0][0]
        self.assertIn("Appeal Submitted Successfully", user_reply)

        # Appeal recorded in DB
        async with self.session_factory() as session:
            appeals = await get_pending_appeals(session)
            self.assertEqual(len(appeals), 1)
            self.assertEqual(appeals[0].user_id, 5005)
            self.assertEqual(appeals[0].status, "PENDING")

        # Admin notified with inline action buttons
        admin_call = mock_context.bot.send_message.call_args
        self.assertIsNotNone(admin_call)
        self.assertEqual(admin_call.kwargs.get("chat_id"), 5952301026)
        markup = admin_call.kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        button_callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("adm_appeal_unban_" in cb for cb in button_callbacks))
        self.assertTrue(any("adm_appeal_reject_" in cb for cb in button_callbacks))

    async def test_appeal_admin_approval_restores_user(self):
        """Verifies admin approving an appeal unbans the user in Telegram and restores VERIFIED status in DB."""
        async with self.session_factory() as session:
            user = await get_or_create_user(
                session=session,
                user_id=6006,
                first_name="ReformedUser",
                username="reformed",
            )
            user.status = "BANNED"
            user.ban_reason = "1st serious violation"
            appeal = await create_appeal(session, user_id=6006, appeal_text="I sincerely apologize and promise to uphold all community rules.")
            appeal_id = appeal.id
            await session.commit()

        mock_admin = MagicMock()
        mock_admin.id = 5952301026  # Admin

        mock_query = MagicMock()
        mock_query.data = f"adm_appeal_unban_{appeal_id}"
        mock_query.from_user = mock_admin
        mock_query.message.delete = AsyncMock()
        mock_query.answer = AsyncMock()

        mock_update = MagicMock()
        mock_update.callback_query = mock_query
        mock_update.effective_user = mock_admin

        mock_context = MagicMock()
        mock_context.bot.unban_chat_member = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()
        mock_context.bot.send_message = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"), \
             patch.object(settings, "TELEGRAM_GROUP_ID", "-1004335696952"):
            await admin_callback_dispatcher(mock_update, mock_context)

        # Telegram unban and unmute called for target group
        mock_context.bot.unban_chat_member.assert_awaited_once_with(
            chat_id=-1004335696952, user_id=6006, only_if_banned=False
        )
        mock_context.bot.restrict_chat_member.assert_awaited_once()

        # DB status restored to VERIFIED and appeal marked APPROVED
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 6006)
            self.assertEqual(db_user.status, "VERIFIED")
            self.assertIsNone(db_user.ban_reason)

            db_appeal = await get_appeal_by_id(session, appeal_id)
            self.assertEqual(db_appeal.status, "APPROVED")
            self.assertEqual(db_appeal.reviewed_by, 5952301026)

    async def test_appeal_admin_reject_maintains_ban(self):
        """Verifies admin rejecting an appeal maintains the permanent ban."""
        async with self.session_factory() as session:
            user = await get_or_create_user(
                session=session,
                user_id=7007,
                first_name="UnrepentantUser",
                username="bad_actor",
            )
            user.status = "BANNED"
            user.ban_reason = "Malicious phishing link"
            appeal = await create_appeal(session, user_id=7007, appeal_text="I don't care about your rules, unban me.")
            appeal_id = appeal.id
            await session.commit()

        mock_admin = MagicMock()
        mock_admin.id = 5952301026

        mock_query = MagicMock()
        mock_query.data = f"adm_appeal_reject_{appeal_id}"
        mock_query.from_user = mock_admin
        mock_query.message.delete = AsyncMock()
        mock_query.answer = AsyncMock()

        mock_update = MagicMock()
        mock_update.callback_query = mock_query
        mock_update.effective_user = mock_admin

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await admin_callback_dispatcher(mock_update, mock_context)

        # User remains BANNED and appeal marked REJECTED
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 7007)
            self.assertEqual(db_user.status, "BANNED")

            db_appeal = await get_appeal_by_id(session, appeal_id)
            self.assertEqual(db_appeal.status, "REJECTED")

    async def test_admin_list_appeals_command(self):
        """Verifies /appeals command lists all pending appeals for administrators."""
        async with self.session_factory() as session:
            user = await get_or_create_user(session, user_id=8008, first_name="WaitingUser")
            user.status = "BANNED"
            user.ban_reason = "Inappropriate communication"
            appeal = await create_appeal(session, user_id=8008, appeal_text="Please let me back into the community.")
            appeal_id = appeal.id
            await session.commit()

        mock_user = MagicMock()
        mock_user.id = 5952301026  # Admin

        mock_update = MagicMock()
        mock_update.effective_user = mock_user
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await list_appeals_handler(mock_update, mock_context)

        self.assertGreaterEqual(mock_update.message.reply_text.await_count, 1)
        found_appeal = any(
            f"APPEAL #{appeal_id}" in call[0][0]
            for call in mock_update.message.reply_text.call_args_list
        )
        self.assertTrue(found_appeal, "Pending appeal card must be displayed to admin")

    async def test_rules_command_includes_ten_guidelines(self):
        """Verifies /rules displays the 10 explicit professional guidelines."""
        mock_user = MagicMock()
        mock_user.id = 12345

        mock_update = MagicMock()
        mock_update.effective_user = mock_user
        mock_update.callback_query = None
        mock_update.message.reply_text = AsyncMock()

        mock_context = MagicMock()

        await rules_handler(mock_update, mock_context)

        mock_update.message.reply_text.assert_awaited_once()
        text = mock_update.message.reply_text.call_args[0][0]

        # Verify all 10 rules are represented
        self.assertIn("1.", text)
        self.assertIn("Respectful & Professional", text)
        self.assertIn("2.", text)
        self.assertIn("No Abusive, Insulting or Threatening Language", text)
        self.assertIn("3.", text)
        self.assertIn("No Harassment or Spam", text)
        self.assertIn("4.", text)
        self.assertIn("No Fake Jobs or Misleading Opportunities", text)
        self.assertIn("5.", text)
        self.assertIn("Zero Upfront Fees", text)
        self.assertIn("6.", text)
        self.assertIn("No Crypto Deposits", text)
        self.assertIn("7.", text)
        self.assertIn("Never Request Credentials", text)
        self.assertIn("8.", text)
        self.assertIn("Legitimate Freelance Focus", text)
        self.assertIn("9.", text)
        self.assertIn("4-day restriction", text)
        self.assertIn("10.", text)
        self.assertIn("Appeals Process", text)


    async def test_you_are_stupid_detected_deleted_restricted(self):
        """
        Specific test requirement 8: Proves that 'You are stupid.' is automatically:
        1. Detected as an abusive communication violation.
        2. Deleted immediately from 'Legally Freelancing Working'.
        3. Restricts the user from sending messages for 4 days in Telegram.
        4. Updates user status to RESTRICTED in database with 4-day expiry.
        5. Sends DM with /appeal instructions and posts group notice.
        6. Alerts administrators with violation details.
        """
        # 1. Setup verified user in DB
        async with self.session_factory() as session:
            await get_or_create_user(
                session=session,
                user_id=888123,
                first_name="InsultUser",
                username="insult_guy",
            )
            user = await get_user_by_id(session, 888123)
            user.status = "VERIFIED"
            user.rules_accepted = True
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 888123
        mock_user.first_name = "InsultUser"
        mock_user.username = "insult_guy"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 9901
        mock_message.text = "You are stupid."
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        # 1. Offending message was deleted
        mock_message.delete.assert_awaited_once()

        # 2. Telegram restrict_chat_member called with 4-day restriction
        mock_context.bot.restrict_chat_member.assert_awaited_once()
        _, kwargs = mock_context.bot.restrict_chat_member.call_args
        self.assertEqual(kwargs.get("chat_id"), -1004335696952)
        self.assertEqual(kwargs.get("user_id"), 888123)
        self.assertFalse(kwargs.get("permissions").can_send_messages)

        until_date = kwargs.get("until_date")
        self.assertIsNotNone(until_date)
        now = datetime.now(timezone.utc)
        self.assertGreater(until_date, now + timedelta(days=3))
        self.assertLessEqual(until_date, now + timedelta(days=5))

        # 3. User status in DB updated to RESTRICTED for 4 days
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 888123)
            self.assertIsNotNone(db_user)
            self.assertEqual(db_user.status, "RESTRICTED")
            self.assertEqual(db_user.violation_count, 1)
            self.assertIsNotNone(db_user.restricted_until)
            self.assertIn("ABUSIVE", db_user.restriction_reason.upper())

        # 4. DM sent to user with /appeal instructions
        dm_sent = any(
            call.kwargs.get("chat_id") == 888123 and "/appeal" in call.kwargs.get("text", "")
            for call in mock_context.bot.send_message.call_args_list
        )
        self.assertTrue(dm_sent, "DM with /appeal instructions must be sent to restricted user")

        # 5. Group warning notice sent
        group_notice_sent = any(
            call.kwargs.get("chat_id") == -1004335696952 and "Communication Rule Violation" in call.kwargs.get("text", "")
            for call in mock_context.bot.send_message.call_args_list
        )
        self.assertTrue(group_notice_sent, "Public warning notice must be posted in the group")

        # 6. Admin alert sent
        admin_alert_sent = any(
            call.kwargs.get("chat_id") == 5952301026 and "COMMUNICATION VIOLATION DETECTED" in call.kwargs.get("text", "")
            for call in mock_context.bot.send_message.call_args_list
        )
        self.assertTrue(admin_alert_sent, "Admin must be alerted of the communication violation")

    async def test_unverified_user_abusive_message_triggers_4_day_restriction(self):
        """Verifies that an unverified user posting abuse gets a 4-day restriction, not just an onboarding verify prompt."""
        # Unverified user in DB
        async with self.session_factory() as session:
            await get_or_create_user(
                session=session,
                user_id=777222,
                first_name="UnverifiedAbuser",
                username="unverified_abuser",
            )
            user = await get_user_by_id(session, 777222)
            user.status = "UNVERIFIED"
            user.rules_accepted = False
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 777222
        mock_user.first_name = "UnverifiedAbuser"
        mock_user.username = "unverified_abuser"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 9902
        mock_message.text = "You are stupid."
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await group_message_moderation_handler(mock_update, mock_context)

        # Message deleted
        mock_message.delete.assert_awaited_once()

        # Restricted for 4 days
        mock_context.bot.restrict_chat_member.assert_awaited_once()

        # Database updated to RESTRICTED
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 777222)
            self.assertEqual(db_user.status, "RESTRICTED")
            self.assertEqual(db_user.violation_count, 1)


    async def test_normal_professional_messages_receive_no_action(self):
        """
        Verifies requirement:
        Normal professional messages, conversation, opinions, job discussions,
        disagreements, and harmless words receive NO ACTION (never deleted, never restricted).
        """
        test_messages = [
            "Hello everyone, looking for freelance Python opportunities.",
            "I disagree with this approach, using PostgreSQL with ACID transactions is much better.",
            "What is the average hourly rate for a Senior React developer?",
            "Can someone review my Upwork portfolio and give constructive criticism?",
            "Damn, this bug took 3 hours to debug!",
            "This library is crap, avoid it for production apps.",
            "Are there any remote Flutter gigs available?",
        ]

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        for idx, text in enumerate(test_messages):
            mock_user = MagicMock()
            mock_user.id = 90000 + idx
            mock_user.first_name = f"User{idx}"
            mock_user.username = f"user_{idx}"
            mock_user.is_bot = False

            mock_message = MagicMock()
            mock_message.message_id = 12000 + idx
            mock_message.text = text
            mock_message.delete = AsyncMock()

            mock_update = MagicMock()
            mock_update.effective_chat = mock_chat
            mock_update.effective_user = mock_user
            mock_update.effective_message = mock_message

            mock_context = MagicMock()
            mock_context.bot.send_message = AsyncMock()
            mock_context.bot.restrict_chat_member = AsyncMock()

            await group_message_moderation_handler(mock_update, mock_context)

            # Normal professional message = NO ACTION
            mock_message.delete.assert_not_awaited()
            mock_context.bot.restrict_chat_member.assert_not_awaited()

    async def test_aggressive_fighting_triggers_4_day_restriction(self):
        """Verifies clear aggressive fighting ('shut up and fuck off') triggers deletion and 4-day restriction."""
        async with self.session_factory() as session:
            await get_or_create_user(
                session=session,
                user_id=666111,
                first_name="Fighter",
                username="fighter_guy",
            )

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 666111
        mock_user.first_name = "Fighter"
        mock_user.username = "fighter_guy"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 9988
        mock_message.text = "Shut up and fuck off, fight me!"
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        await group_message_moderation_handler(mock_update, mock_context)

        # Message deleted and member restricted
        mock_message.delete.assert_awaited_once()
        mock_context.bot.restrict_chat_member.assert_awaited_once()

        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, 666111)
            self.assertEqual(db_user.status, "RESTRICTED")
            self.assertEqual(db_user.violation_count, 1)


    async def test_multilingual_hindi_abusive_messages_detected_and_restricted(self):
        """Verifies Hindi and Hinglish abusive insults and threats trigger message deletion and 4-day restriction."""
        test_cases = [
            "Tu ek number ka chutiya hai",
            "Kutte kamine madarchod nikal yahan se",
            "Main tere ko jaan se maar dunga",
            "तुम बहुत बड़े चूतिया हो",
            "जान से मार दूंगा तुझे",
        ]

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        for idx, text in enumerate(test_cases):
            user_id = 70100 + idx
            async with self.session_factory() as session:
                await get_or_create_user(session, user_id=user_id, first_name=f"HindiUser{idx}")

            mock_user = MagicMock()
            mock_user.id = user_id
            mock_user.first_name = f"HindiUser{idx}"
            mock_user.username = f"hindi_user_{idx}"
            mock_user.is_bot = False

            mock_message = MagicMock()
            mock_message.message_id = 70100 + idx
            mock_message.text = text
            mock_message.delete = AsyncMock()

            mock_update = MagicMock()
            mock_update.effective_chat = mock_chat
            mock_update.effective_user = mock_user
            mock_update.effective_message = mock_message

            mock_context = MagicMock()
            mock_context.bot.send_message = AsyncMock()
            mock_context.bot.restrict_chat_member = AsyncMock()

            await group_message_moderation_handler(mock_update, mock_context)

            # Deletion and 4-day restriction verified
            mock_message.delete.assert_awaited_once()
            mock_context.bot.restrict_chat_member.assert_awaited_once()

    async def test_multilingual_gujarati_abusive_messages_detected_and_restricted(self):
        """Verifies Gujarati and Gujlish abusive insults and threats trigger message deletion and 4-day restriction."""
        test_cases = [
            "Tu saav gadhedo che",
            "Bhonk ma lodu, chup mar",
            "Hu tane mari nakis saale",
            "તમે સાવ ગધેડા છો",
            "મારી નાખીશ તને",
        ]

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        for idx, text in enumerate(test_cases):
            user_id = 80100 + idx
            async with self.session_factory() as session:
                await get_or_create_user(session, user_id=user_id, first_name=f"GujUser{idx}")

            mock_user = MagicMock()
            mock_user.id = user_id
            mock_user.first_name = f"GujUser{idx}"
            mock_user.username = f"guj_user_{idx}"
            mock_user.is_bot = False

            mock_message = MagicMock()
            mock_message.message_id = 80100 + idx
            mock_message.text = text
            mock_message.delete = AsyncMock()

            mock_update = MagicMock()
            mock_update.effective_chat = mock_chat
            mock_update.effective_user = mock_user
            mock_update.effective_message = mock_message

            mock_context = MagicMock()
            mock_context.bot.send_message = AsyncMock()
            mock_context.bot.restrict_chat_member = AsyncMock()

            await group_message_moderation_handler(mock_update, mock_context)

            # Deletion and 4-day restriction verified
            mock_message.delete.assert_awaited_once()
            mock_context.bot.restrict_chat_member.assert_awaited_once()

    async def test_multilingual_mixed_codeswitched_and_obfuscated_abusive_messages(self):
        """Verifies mixed language code-switching and obfuscated/leetspeak abuse are detected."""
        test_cases = [
            "You are a stupid gadhedo",
            "Shut up you chutiya moron",
            "Tu gadhedo idiot che",
            "Y0u @re $tup!d",
            "Kiiiillll yooouuu",
        ]

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        for idx, text in enumerate(test_cases):
            user_id = 90100 + idx
            async with self.session_factory() as session:
                await get_or_create_user(session, user_id=user_id, first_name=f"MixedUser{idx}")

            mock_user = MagicMock()
            mock_user.id = user_id
            mock_user.first_name = f"MixedUser{idx}"
            mock_user.username = f"mixed_user_{idx}"
            mock_user.is_bot = False

            mock_message = MagicMock()
            mock_message.message_id = 90100 + idx
            mock_message.text = text
            mock_message.delete = AsyncMock()

            mock_update = MagicMock()
            mock_update.effective_chat = mock_chat
            mock_update.effective_user = mock_user
            mock_update.effective_message = mock_message

            mock_context = MagicMock()
            mock_context.bot.send_message = AsyncMock()
            mock_context.bot.restrict_chat_member = AsyncMock()

            await group_message_moderation_handler(mock_update, mock_context)

            # Deletion and restriction verified
            mock_message.delete.assert_awaited_once()
            mock_context.bot.restrict_chat_member.assert_awaited_once()

    async def test_multilingual_normal_professional_messages_receive_no_action(self):
        """Verifies normal professional conversations in Hindi, Gujarati, and English receive NO ACTION."""
        normal_multilingual_messages = [
            # Hindi / Hinglish professional
            "Namaste dosto, kya kisi ke paas Python freelance project hai?",
            "Mera budget $500 hai milestone basis par kaam karenge.",
            "Mujhe lagta hai ye database schema theek nahi hai, discuss karte hain.",
            # Gujarati / Gujlish professional
            "Kem cho badhane, mare website banavva mate designer joiye che.",
            "Hu freelance full-stack developer chu, portfolio review karsho?",
            "Aa approach barabar nathi, bije rite kariye.",
            # English professional
            "Can someone review my FastAPI pull request?",
            "What is the standard contract for a 3-month freelance engagement?",
            # Mild frustration (harmless words)
            "Damn, this bug took 3 hours to solve!",
            "Yaar ye library bau slow che.",
        ]

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        for idx, text in enumerate(normal_multilingual_messages):
            user_id = 60100 + idx
            async with self.session_factory() as session:
                await get_or_create_user(session, user_id=user_id, first_name=f"ProUser{idx}")

            mock_user = MagicMock()
            mock_user.id = user_id
            mock_user.first_name = f"ProUser{idx}"
            mock_user.username = f"pro_user_{idx}"
            mock_user.is_bot = False

            mock_message = MagicMock()
            mock_message.message_id = 60100 + idx
            mock_message.text = text
            mock_message.delete = AsyncMock()

            mock_update = MagicMock()
            mock_update.effective_chat = mock_chat
            mock_update.effective_user = mock_user
            mock_update.effective_message = mock_message

            mock_context = MagicMock()
            mock_context.bot.send_message = AsyncMock()
            mock_context.bot.restrict_chat_member = AsyncMock()

            await group_message_moderation_handler(mock_update, mock_context)

            # Normal professional multilingual messages = NO ACTION
            mock_message.delete.assert_not_awaited()
            mock_context.bot.restrict_chat_member.assert_not_awaited()

    async def test_restricted_user_offset_naive_datetime_comparison_safe(self):
        """Verifies that an offset-naive restricted_until datetime from SQLite does not cause TypeError."""
        user_id = 998877
        async with self.session_factory() as session:
            user = await get_or_create_user(session, user_id=user_id, first_name="NaiveRestricted")
            user.status = "RESTRICTED"
            # Set an offset-naive datetime (tzinfo=None) in the future
            user.restricted_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
            user.violation_count = 1
            await session.commit()

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.first_name = "NaiveRestricted"
        mock_user.username = "naive_restricted"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 9988771
        mock_message.text = "Hello can I speak now?"
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        # Must NOT raise TypeError: can't compare offset-naive and offset-aware datetimes
        await group_message_moderation_handler(mock_update, mock_context)

        # Offending message from restricted member must be deleted
        mock_message.delete.assert_awaited_once()

    async def test_exact_4_day_restriction_expiry_timestamp_sent_to_telegram(self):
        """Verifies that restrictChatMember receives an exact until_date timestamp = current time + 4 days (345,600 seconds)."""
        user_id = 881122
        async with self.session_factory() as session:
            await get_or_create_user(session, user_id=user_id, first_name="AbusiveUser")

        mock_chat = MagicMock()
        mock_chat.id = -1004335696952
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.first_name = "AbusiveUser"
        mock_user.username = "abusive_user"
        mock_user.is_bot = False

        mock_message = MagicMock()
        mock_message.message_id = 556677
        mock_message.text = "You are a stupid idiot and moron!"
        mock_message.delete = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        start_time = datetime.now(timezone.utc)
        await group_message_moderation_handler(mock_update, mock_context)
        end_time = datetime.now(timezone.utc)

        # 1. Message deleted
        mock_message.delete.assert_awaited_once()

        # 2. Telegram restrict_chat_member called
        mock_context.bot.restrict_chat_member.assert_awaited_once()
        _, kwargs = mock_context.bot.restrict_chat_member.call_args

        until_date = kwargs.get("until_date")
        self.assertIsNotNone(until_date, "until_date must not be None")

        # Convert to unix timestamp if datetime
        if isinstance(until_date, datetime):
            until_ts = int(until_date.timestamp())
        else:
            until_ts = int(until_date)

        # Exactly 4 days = 4 * 24 * 3600 = 345,600 seconds
        expected_min_ts = int((start_time + timedelta(days=4)).timestamp())
        expected_max_ts = int((end_time + timedelta(days=4)).timestamp())

        self.assertGreaterEqual(until_ts, expected_min_ts)
        self.assertLessEqual(until_ts, expected_max_ts)

        # Confirm permissions: can_send_messages MUST be False
        perms = kwargs.get("permissions")
        self.assertFalse(perms.can_send_messages)

        # 3. Verify exact restore date/time displayed in group message and DM
        expected_expiry_str = until_date.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Check group notification
        group_msg_calls = [
            call for call in mock_context.bot.send_message.call_args_list
            if call.kwargs.get("chat_id") == -1004335696952
        ]
        self.assertTrue(len(group_msg_calls) >= 1, "Group notification must be sent")
        group_text = group_msg_calls[0].kwargs.get("text", "")
        self.assertIn("⚠️ <b>User restricted for 4 days.</b>", group_text)
        self.assertIn(f"🕐 <b>Messaging will be restored on:</b> {expected_expiry_str}", group_text)

        # Check private DM notification
        dm_msg_calls = [
            call for call in mock_context.bot.send_message.call_args_list
            if call.kwargs.get("chat_id") == user_id
        ]
        self.assertTrue(len(dm_msg_calls) >= 1, "Private DM notification must be sent to restricted user")
        dm_text = dm_msg_calls[0].kwargs.get("text", "")
        self.assertIn(f"🕐 <b>Messaging will be restored on:</b> {expected_expiry_str}", dm_text)
        self.assertIn("You are restricted for 4 days", dm_text)

    async def test_unrestrict_command_by_admin_and_unauthorized(self):
        """Verifies /unrestrict <user_id> restores messaging permissions when run by authorized admin."""
        target_id = 771122
        async with self.session_factory() as session:
            user = await get_or_create_user(session, user_id=target_id, first_name="RestrictedTarget")
            user.status = "RESTRICTED"
            user.restricted_until = datetime.now(timezone.utc) + timedelta(days=4)
            user.restriction_reason = "Abusive language"
            user.violation_count = 1
            await session.commit()

        # Case 1: Unauthorized user tries to unrestrict
        mock_user = MagicMock()
        mock_user.id = 999999  # Not an admin

        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_user = mock_user
        mock_update.message = mock_message

        mock_context = MagicMock()
        mock_context.args = [str(target_id)]
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"):
            await unrestrict_user_handler(mock_update, mock_context)

        mock_message.reply_text.assert_awaited_once_with("⛔ Unauthorized.")
        mock_context.bot.restrict_chat_member.assert_not_awaited()

        # Case 2: Authorized admin runs /unrestrict <user_id>
        mock_admin = MagicMock()
        mock_admin.id = 5952301026  # Authorized admin

        mock_admin_msg = MagicMock()
        mock_admin_msg.reply_text = AsyncMock()

        mock_admin_update = MagicMock()
        mock_admin_update.effective_user = mock_admin
        mock_admin_update.message = mock_admin_msg

        with patch.object(settings, "ADMIN_IDS_RAW", "5952301026"), \
             patch.object(settings, "TELEGRAM_GROUP_ID", "-1004335696952"), \
             patch.object(settings, "TELEGRAM_GROUP_NAME", "Legally Freelancing Working"):
            await unrestrict_user_handler(mock_admin_update, mock_context)

        # Verify Telegram permissions restored
        mock_context.bot.restrict_chat_member.assert_awaited_once()
        _, kwargs = mock_context.bot.restrict_chat_member.call_args
        self.assertEqual(int(kwargs.get("chat_id")), -1004335696952)
        self.assertEqual(kwargs.get("user_id"), target_id)
        perms = kwargs.get("permissions")
        self.assertTrue(perms.can_send_messages)

        # Verify DB state restored to VERIFIED
        async with self.session_factory() as session:
            db_user = await get_user_by_id(session, target_id)
            self.assertEqual(db_user.status, "VERIFIED")
            self.assertIsNone(db_user.restricted_until)
            self.assertIsNone(db_user.restriction_reason)

        # Verify DM sent to user
        mock_context.bot.send_message.assert_awaited_once()
        _, dm_kwargs = mock_context.bot.send_message.call_args
        self.assertEqual(dm_kwargs.get("chat_id"), target_id)
        self.assertIn("Restriction Lifted", dm_kwargs.get("text"))


if __name__ == "__main__":
    unittest.main()

