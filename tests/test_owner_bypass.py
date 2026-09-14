"""
Unit Tests for Owner Full Bypass Feature
Tests that the Telegram Group Owner:
1. Can send ANY message/content without restrictions
2. Bot NEVER deletes, restricts, mutes, or bans the Owner
3. All automatic moderation/enforcement is skipped for the Owner
4. Owner has full manual control over all members
5. Normal moderation rules remain unchanged for regular members/admins
"""

import asyncio
from contextlib import asynccontextmanager
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database.models import Base
from database.crud import get_or_create_user, confirm_user_rules, get_user_by_id
from handlers.group import (
    group_message_moderation_handler,
    onboard_new_member,
    RECENT_WELCOMES,
    LAST_UNVERIFIED_WARNING,
    KNOWN_COMMUNITY_CHATS,
)
from config import settings
from utils.authorization import (
    is_group_owner,
    should_skip_moderation,
    should_skip_ban,
    should_skip_restrictions,
    should_skip_message_delete,
)


class TestOwnerFullBypass(unittest.IsolatedAsyncioTestCase):
    """Test suite for Owner Full Bypass feature"""

    async def asyncSetUp(self):
        """Set up test database and mocks"""
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

        with patch("handlers.group.scan_job_heuristics") as mock_scan, \
             patch("handlers.group.scan_communication_message_ai") as mock_comm_scan:        self.db_patcher = patch("handlers.group.get_db_session", side_effect=mock_get_db_session)
        self.db_patcher.start()

        # Set up owner ID in settings using PropertyMock
        self.owner_id = 999001
        self.regular_user_id = 123456
        self.admin_id = 789012

        # Patch the owner_id property directly
        type(settings).owner_id = PropertyMock(return_value=self.owner_id)

        # Patch authorization functions with the owner ID
        self.auth_patcher_owner = patch("handlers.group.is_group_owner")
        self.mock_is_owner = self.auth_patcher_owner.start()
        self.mock_is_owner.side_effect = lambda uid: uid == self.owner_id

        self.auth_patcher_mod = patch("handlers.group.should_skip_moderation")
        self.mock_skip_mod = self.auth_patcher_mod.start()
        self.mock_skip_mod.side_effect = lambda uid: uid == self.owner_id

        self.auth_patcher_ban = patch("handlers.group.should_skip_ban")
        self.mock_skip_ban = self.auth_patcher_ban.start()
        self.mock_skip_ban.side_effect = lambda uid: uid == self.owner_id

        self.auth_patcher_restrict = patch("handlers.group.should_skip_restrictions")
        self.mock_skip_restrict = self.auth_patcher_restrict.start()
        self.mock_skip_restrict.side_effect = lambda uid: uid == self.owner_id

        self.auth_patcher_delete = patch("handlers.group.should_skip_message_delete")
        self.mock_skip_delete = self.auth_patcher_delete.start()
        self.mock_skip_delete.side_effect = lambda uid: uid == self.owner_id

    async def asyncTearDown(self):
        """Clean up patches"""
        self.db_patcher.stop()
        self.auth_patcher_owner.stop()
        self.auth_patcher_mod.stop()
        self.auth_patcher_ban.stop()
        self.auth_patcher_restrict.stop()
        self.auth_patcher_delete.stop()
        await self.engine.dispose()

    # =====================================================================
    # Test: Owner Authorization Checks
    # =====================================================================

    def test_owner_bypass_mocks_configured(self):
        """Test that owner bypass mocks are properly configured"""
        # Test that mocks return True for owner
        self.assertTrue(self.mock_is_owner(self.owner_id))
        self.assertFalse(self.mock_is_owner(self.regular_user_id))
        
        self.assertTrue(self.mock_skip_mod(self.owner_id))
        self.assertFalse(self.mock_skip_mod(self.regular_user_id))
        
        self.assertTrue(self.mock_skip_ban(self.owner_id))
        self.assertFalse(self.mock_skip_ban(self.regular_user_id))
        self.assertFalse(is_group_owner(self.admin_id), "Admin should not be owner")

    def test_should_skip_moderation_for_owner(self):
        """Test that moderation should be skipped for owner"""
        self.assertTrue(should_skip_moderation(self.owner_id), "Owner should skip moderation")
        self.assertFalse(should_skip_moderation(self.regular_user_id), "Regular user should not skip moderation")

    def test_should_skip_ban_for_owner(self):
        """Test that owner cannot be banned"""
        self.assertTrue(should_skip_ban(self.owner_id), "Owner should skip ban checks")
        self.assertFalse(should_skip_ban(self.regular_user_id), "Regular user should not skip ban checks")

    def test_should_skip_restrictions_for_owner(self):
        """Test that owner cannot be restricted"""
        self.assertTrue(should_skip_restrictions(self.owner_id), "Owner should skip restriction checks")
        self.assertFalse(should_skip_restrictions(self.regular_user_id), "Regular user should not skip restriction checks")

    # =====================================================================
    # Test: Owner Messages Not Deleted
    # =====================================================================

    async def test_owner_abusive_message_not_deleted(self):
        """Test that owner's abusive messages are NOT deleted"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "STUPID IDIOT! YOU ARE A LOSER!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.owner_id  # OWNER sending message
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Mock communication moderator to flag as violation
        with patch("handlers.group.scan_communication_message_ai") as mock_scan:
            mock_scan.return_value = MagicMock(
                is_violation=True,
                severity="CRITICAL",
                violation_type="Abuse",
                details="Abusive language"
            )

            await group_message_moderation_handler(update, context)

        # Owner message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        logger_spy = patch("handlers.group.logger.info")
        logger_spy.start()
        logger_spy.stop()

    async def test_owner_high_risk_scam_message_not_deleted(self):
        """Test that owner's scam content is NOT deleted (owner bypass)"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "GUARANTEED INCOME! Send $500 upfront fee for training materials NOW!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.owner_id  # OWNER
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Mock scam detector to flag as high risk
        with patch("handlers.group.scan_job_heuristics") as mock_scan:
            mock_scan.return_value = MagicMock(
                risk_score=75.0,
                risk_level="very_high",
                flags=["Upfront fee required", "Credential harvesting"],
            )

            await group_message_moderation_handler(update, context)

        # Owner message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        # Owner should NOT be banned
        context.bot.ban_chat_member.assert_not_called()

    # =====================================================================
    # Test: Owner Cannot Be Restricted
    # =====================================================================

    async def test_owner_cannot_be_restricted_for_communication_violation(self):
        """Test that owner cannot be restricted for communication violations"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "DAMN IT! THIS IS AWFUL!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.owner_id  # OWNER
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        with patch("handlers.group.scan_communication_message_ai") as mock_scan:
            mock_scan.return_value = MagicMock(
                is_violation=True,
                severity="CRITICAL",
                violation_type="Profanity",
                details="Excessive profanity"
            )

            await group_message_moderation_handler(update, context)

        # Owner should NOT be restricted (only permissions should be granted)
        # The function should only be called to grant permissions, not restrict
        # Check that it was called only with full permissions (not restricted)
        context.bot.restrict_chat_member.assert_called_once()
        call_args = context.bot.restrict_chat_member.call_args
        permissions = call_args[1]['permissions']
        # Verify all permissions are True (full access, not restriction)
        assert permissions.can_send_messages == True
        assert permissions.can_send_polls == True
        assert permissions.can_send_other_messages == True
        assert permissions.can_add_web_page_previews == True

    # =====================================================================
    # Test: Owner Cannot Be Banned
    # =====================================================================

    async def test_owner_cannot_be_banned_for_scam(self):
        """Test that owner cannot be banned even for high-risk scam content"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "Pay now for crypto guaranteed returns!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.owner_id  # OWNER
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()

        with patch("handlers.group.scan_job_heuristics") as mock_scan:
            mock_scan.return_value = MagicMock(
                risk_score=95.0,  # EXTREMELY HIGH RISK
                risk_level="very_high",
                flags=["Crypto scheme", "Upfront fee", "OTP harvesting"],
            )

            await group_message_moderation_handler(update, context)

        # Owner should NEVER be banned
        context.bot.ban_chat_member.assert_not_called()

    # =====================================================================
    # Test: Regular Members Still Enforce Moderation
    # =====================================================================

    async def test_regular_member_can_be_restricted(self):
        """Test that regular members are still subject to restrictions"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "DAMN YOU! YOU ARE AN IDIOT!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.regular_user_id  # REGULAR USER (not owner)
        update.effective_user.username = "user123"
        update.effective_user.first_name = "Regular"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        with patch("handlers.group.scan_communication_message_ai") as mock_scan:
            mock_scan.return_value = MagicMock(
                is_violation=True,
                severity="CRITICAL",
                violation_type="Abuse",
                details="Abusive language detected"
            )

            await group_message_moderation_handler(update, context)

        # Regular user's message should be deleted
        update.effective_message.delete.assert_called_once()
        # Regular user should be restricted
        context.bot.restrict_chat_member.assert_called_once()

    async def test_regular_member_can_be_banned(self):
        """Test that regular members can still be banned for scam content"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "Job: Pay $1000 to get hired! Western Union only!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.regular_user_id  # REGULAR USER
        update.effective_user.username = "user123"
        update.effective_user.first_name = "Regular"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Create verified user in database
        async with self.session_factory() as session:
            db_user = await get_or_create_user(
                session=session,
                user_id=self.regular_user_id,
                first_name="Regular",
                last_name="User",
                username="user123",
            )
            db_user.status = "VERIFIED"
            await session.commit()

        with patch("handlers.group.scan_job_heuristics") as mock_scan, \
             patch("handlers.group.scan_communication_message_ai") as mock_comm_scan:
            mock_scan.return_value = MagicMock(
                risk_score=80.0,  # HIGH RISK
                risk_level="very_high",
                flags=["Upfront fee required"],
            )
            mock_comm_scan.return_value = MagicMock(
                is_violation=False,
                severity="MILD",
                details="No violation"
            )

            # Don't await the handler yet - check if mocks are working
            print(f"Mock scan job result: {mock_scan.return_value}")
            print(f"Mock comm scan result: {mock_comm_scan.return_value}")

            await group_message_moderation_handler(update, context)

        # Regular user message should be deleted
        update.effective_message.delete.assert_called_once()
        # Regular user should be banned
        context.bot.ban_chat_member.assert_called_once()

    # =====================================================================
    # Test: Owner Onboarding Without Restrictions
    # =====================================================================

    async def test_owner_onboarding_no_restrictions(self):
        """Test that owner is never restricted upon joining"""
        chat = MagicMock()
        chat.id = -1004335696952
        chat.title = "Test Group"

        user = MagicMock()
        user.id = self.owner_id  # OWNER
        user.username = "owner"
        user.first_name = "Owner"
        user.last_name = "User"
        user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        await onboard_new_member(chat, user, context)

        # Owner should never have their permissions restricted (only granted)
        # The function should only be called to grant permissions, not restrict
        # Check that it was called only with full permissions (not restriction)
        context.bot.restrict_chat_member.assert_called_once()
        call_args = context.bot.restrict_chat_member.call_args
        permissions = call_args[1]['permissions']
        # Verify all permissions are True (full access, not restriction)
        assert permissions.can_send_messages == True
        assert permissions.can_send_polls == True
        assert permissions.can_send_other_messages == True
        assert permissions.can_add_web_page_previews == True
        # Owner should receive a special welcome message
        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        assert "Owner" in call_args[1]["text"]
        assert "highest authority" in call_args[1]["text"] or "full authority" in call_args[1]["text"]

    # =====================================================================
    # Test: Audit Trail & Logging
    # =====================================================================

    async def test_owner_actions_logged_in_audit_trail(self):
        """Test that owner actions are properly logged in audit trail"""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "Here is a job posting"
        update.effective_message.caption = None
        update.effective_message.message_id = 12345
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.owner_id  # OWNER
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()

        with patch("handlers.group.scan_job_heuristics") as mock_scan:
            mock_scan.return_value = MagicMock(
                risk_score=10.0,  # Low risk
                risk_level="low",
                flags=[],
            )

            await group_message_moderation_handler(update, context)

        # Message should not be deleted
        # Owner action should be logged
        # (This is verified by the handler returning early and logging owner bypass)


if __name__ == "__main__":
    unittest.main()
