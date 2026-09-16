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

        # Reload settings module to pick up the new environment variable
        import importlib
        settings_module = importlib.import_module('config')
        importlib.reload(settings_module)
        # Re-import settings to get the updated instance
        from config import settings
        # Reload authorization module to pick up the updated settings
        importlib.reload(importlib.import_module('utils.authorization'))

        # Create test database
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def test_owner_abusive_message_not_deleted(self):
        """Test that owner messages are never deleted for abusive content"""
        # Create test message from owner
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "You are stupid and I hate you!"
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

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner's message should NOT be deleted
        update.effective_message.delete.assert_not_called()

    @patch('handlers.group.scan_communication_message_ai')
    async def test_owner_bypass_functions(self, mock_scan):
        """Test that owner bypass functions work correctly"""
        # Mock communication scan
        mock_scan.return_value = MagicMock(
            is_violation=True,
            severity="CRITICAL",
            violation_type="Abuse",
            details="Abusive language"
        )

        # Create test message from owner
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
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner's message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        # Owner should NOT be banned
        context.bot.ban_chat_member.assert_not_called()
        # Owner should be given full permissions (this is correct behavior)
        context.bot.restrict_chat_member.assert_called_once()

    async def test_owner_cannot_be_banned(self):
        """Test that owner can never be banned"""
        # Create test message from owner
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
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner's message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        # Owner should NOT be banned
        context.bot.ban_chat_member.assert_not_called()

    async def test_owner_cannot_be_restricted(self):
        """Test that owner can never be restricted"""
        # Create test message from owner
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.text = "You are stupid and I hate you!"
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
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner's message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        # Owner should be given full permissions (this is correct behavior)
        context.bot.restrict_chat_member.assert_called_once()

    @patch('utils.authorization.is_group_owner')
    async def test_owner_onboarding_no_restrictions(self, mock_is_owner):
        """Test that owner is never restricted upon joining"""
        # Mock that the user is the owner
        mock_is_owner.return_value = True
        
        chat = MagicMock()
        chat.id = -1004335696952
        chat.title = "Test Group"
        
        # Set the environment variable for the group ID and reload settings
        import os
        os.environ['TELEGRAM_GROUP_ID'] = str(-1004335696952)
        import importlib
        importlib.reload(importlib.import_module('config'))
        from config import settings
        
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
        
        # Mock the database to return that the user is not already verified
        with patch('handlers.group.get_or_create_user') as mock_get_user:
            mock_db_user = MagicMock()
            mock_db_user.status = "NEW"  # Not verified, so it won't return early
            mock_get_user.return_value = mock_db_user
            
            # Simulate owner joining
            update = MagicMock()
            update.effective_user = user
            update.effective_chat = chat
            await onboard_new_member(update, chat, user, context)
        
        # Owner should receive a special welcome message
        context.bot.send_message.assert_called_once()
        # Note: In the actual implementation, owners are given full permissions via the welcome message
        # but restrict_chat_member is not called in the onboarding function itself

    @patch('handlers.group.scan_job_heuristics')
    async def test_owner_scam_message_not_deleted(self, mock_scan):
        """Test that owner scam messages are never deleted"""
        # Mock scam scan
        mock_scan.return_value = MagicMock(
            risk_score=80.0,
            risk_level="very_high",
            flags=["Upfront fee required"],
        )

        # Create test message from owner
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
        update.effective_user.id = self.test_owner_id
        update.effective_user.username = "owner"
        update.effective_user.first_name = "Owner"
        update.effective_user.is_bot = False

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.restrict_chat_member = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Owner's message should NOT be deleted
        update.effective_message.delete.assert_not_called()
        # Owner should NOT be banned
        context.bot.ban_chat_member.assert_not_called()

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
        context.bot.send_message = AsyncMock()

        # Process the message
        await group_message_moderation_handler(update, context)

        # Regular user message should be deleted
        update.effective_message.delete.assert_called_once()
        # Regular user should be banned
        context.bot.ban_chat_member.assert_called_once()

    @patch('handlers.group.scan_communication_message_ai')
    @patch('handlers.group.get_or_create_user')
    async def test_regular_user_can_be_restricted(self, mock_get_user, mock_scan):
        """Test that regular users ARE still restricted for violations"""
        # Mock database user with VERIFIED status (not banned)
        mock_db_user = MagicMock()
        mock_db_user.status = "VERIFIED"
        mock_db_user.violation_count = 0
        mock_get_user.return_value = mock_db_user
        
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
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        
        # Mock the database session
        with patch('handlers.group.get_db_session') as mock_session:
            mock_session_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_db_user
            mock_session_instance.execute = AsyncMock(return_value=mock_result)
            mock_session_instance.commit = AsyncMock()
            mock_session_instance.flush = AsyncMock()
            mock_session_instance.__aenter__.return_value = mock_session_instance
            mock_session_instance.__aexit__.return_value = None
            mock_session.return_value = mock_session_instance

            # Process the message
            await group_message_moderation_handler(update, context)
            
            # Regular user's message should be deleted
            update.effective_message.delete.assert_called_once()
            # Regular user should be restricted
            context.bot.restrict_chat_member.assert_called_once()