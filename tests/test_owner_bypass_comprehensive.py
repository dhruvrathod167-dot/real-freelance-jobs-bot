"""
Owner Full Bypass Feature Tests
Tests that the Telegram Group Owner has complete bypass of all automatic moderation.

Requirements:
1. Owner can send ANY message/content without restrictions
2. Bot NEVER deletes, restricts, mutes, or bans the Owner
3. Skip all automatic moderation/enforcement for the Owner
4. Owner has full manual control over all members
5. Keep all existing moderation rules unchanged for normal members/admins
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database.models import Base
from database.crud import get_or_create_user
from handlers.group import group_message_moderation_handler, onboard_new_member
from config import settings
from utils.authorization import (
    is_group_owner,
    should_skip_moderation,
    should_skip_ban,
    should_skip_restrictions,
    should_skip_message_delete,
)


class TestOwnerFullBypass(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Set up test environment"""
        # Set test owner ID
        self.test_owner_id = 999001
        self.test_user_id = 123456

        # Import and set environment after setting test values
        import os
        os.environ['OWNER_ID'] = str(self.test_owner_id)

        # Reload settings to pick up the new environment variable
        import importlib
        importlib.reload(settings)

        # Create test database
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def test_owner_bypass_functions(self):
        """Test that owner bypass functions work correctly"""
        # Owner should bypass all checks
        self.assertTrue(is_group_owner(self.test_owner_id))
        self.assertTrue(should_skip_moderation(self.test_owner_id))
        self.assertTrue(should_skip_ban(self.test_owner_id))
        self.assertTrue(should_skip_restrictions(self.test_owner_id))
        self.assertTrue(should_skip_message_delete(self.test_owner_id))

        # Regular users should not bypass
        self.assertFalse(is_group_owner(self.test_user_id))
        self.assertFalse(should_skip_moderation(self.test_user_id))
        self.assertFalse(should_skip_ban(self.test_user_id))
        self.assertFalse(should_skip_restrictions(self.test_user_id))
        self.assertFalse(should_skip_message_delete(self.test_user_id))

    @patch('handlers.group.scan_communication_message_ai')
    async def test_owner_abusive_message_not_deleted(self, mock_scan):
        """Test that owner's abusive messages are NOT deleted"""
        # Mock communication scan to flag as violation
        mock_scan.return_value = MagicMock(
            is_violation=True,
            severity="CRITICAL",
            violation_type="Abuse",
            details="Abusive language"
        )

        # Create test message from owner
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
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner message should NOT be deleted
        update.effective_message.delete.assert_not_called()

    @patch('handlers.group.scan_job_heuristics')
    async def test_owner_scam_message_not_deleted(self, mock_scan):
        """Test that owner's scam content is NOT deleted"""
        # Mock scam scan to flag as high risk
        mock_scan.return_value = MagicMock(
            risk_score=95.0,
            risk_level="very_high",
            flags=["Upfront fee required", "Credential harvesting"],
        )

        # Create test message from owner with scam content
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "GUARANTEED INCOME! Send $500 upfront fee NOW!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        # Owner should NOT be banned
        context.bot.ban_chat_member.assert_not_called()

    @patch('handlers.group.scan_communication_message_ai')
    async def test_owner_cannot_be_restricted(self, mock_scan):
        """Test that owner cannot be restricted for violations"""
        # Mock communication scan
        mock_scan.return_value = MagicMock(
            is_violation=True,
            severity="CRITICAL",
            violation_type="Profanity",
            details="Excessive profanity"
        )

        # Create test message from owner
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
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner should NOT be restricted
        context.bot.restrict_chat_member.assert_not_called()

    @patch('handlers.group.scan_job_heuristics')
    async def test_owner_cannot_be_banned(self, mock_scan):
        """Test that owner cannot be banned even for high-risk content"""
        # Mock scam scan with extremely high risk
        mock_scan.return_value = MagicMock(
            risk_score=99.0,
            risk_level="very_high",
            flags=["Crypto scheme", "Upfront fee", "Phishing"],
        )

        # Create test message from owner
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "Pay $1000 for crypto guaranteed returns!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner should NEVER be banned or restricted
        context.bot.ban_chat_member.assert_not_called()
        context.bot.restrict_chat_member.assert_not_called()

    @patch('handlers.group.scan_communication_message_ai')
    async def test_regular_user_can_be_restricted(self, mock_scan):
        """Test that regular users ARE still restricted for violations"""
        # Mock communication scan
        mock_scan.return_value = MagicMock(
            is_violation=True,
            severity="CRITICAL",
            violation_type="Abuse",
            details="Abusive language"
        )

        # Create test message from regular user
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
        update.effective_user.id = self.test_user_id
        update.effective_user.username = "user123"
        update.effective_user.first_name = "Regular"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Regular user's message should be deleted
        update.effective_message.delete.assert_called_once()
        # Regular user should be restricted
        context.bot.restrict_chat_member.assert_called_once()

    @patch('handlers.group.scan_job_heuristics')
    async def test_regular_user_can_be_banned(self, mock_scan):
        """Test that regular users ARE still banned for scam content"""
        # Mock scam scan
        mock_scan.return_value = MagicMock(
            risk_score=80.0,
            risk_level="very_high",
            flags=["Upfront fee required"],
        )

        # Create test message from regular user
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "Send $1000 for guaranteed income!"
        update.effective_message.caption = None
        update.effective_message.delete = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Test Group"
        update.effective_user = MagicMock()
        update.effective_user.id = self.test_user_id
        update.effective_user.username = "user123"
        update.effective_user.first_name = "Regular"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Regular user message should be deleted
        update.effective_message.delete.assert_called_once()
        # Regular user should be banned
        context.bot.ban_chat_member.assert_called_once()

    async def test_owner_onboarding_no_restrictions(self):
        """Test that owner is never restricted upon joining"""
        chat = MagicMock()
        chat.id = -1004335696952
        chat.title = "Test Group"

        user = MagicMock()
        user.id = self.test_owner_id
        user.username = "owner"
        user.first_name = "Owner"
        user.last_name = "User"
        user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.restrict_chat_member = AsyncMock()

        # Simulate owner joining
        await onboard_new_member(chat, user, context)

        # Owner should never have their permissions restricted
        context.bot.restrict_chat_member.assert_not_called()
        # Owner should receive a special welcome message
        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        self.assertIn("Owner", call_args[1]["text"])
        self.assertIn("highest authority", call_args[1]["text"])


if __name__ == "__main__":
    unittest.main()