"""
URGENT OWNER FIX AUTO-RESTORE TESTS
Tests that Owner ID 5952301026 can never be auto-banned or restricted
and is automatically restored if somehow marked as such.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database.models import Base
from database.crud import get_or_create_user
from handlers.group import ensure_owner_active
from config import settings

class TestUrgentOwnerFix(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Set up test environment"""
        # Set the urgent owner ID
        self.urgent_owner_id = 5952301026
        import os
        os.environ['OWNER_ID'] = str(self.urgent_owner_id)

        # Create test database
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @patch('handlers.group.settings')
    async def test_owner_auto_restore_from_banned(self, mock_settings):
        """Test that owner is automatically restored if marked as BANNED"""
        mock_settings.owner_id = self.urgent_owner_id
        mock_settings.effective_group_id = -1004335696952

        # Create mock bot
        bot = MagicMock()
        bot.restrict_chat_member = AsyncMock()

        # Mock database session and user creation
        with patch('handlers.group.get_db_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_user = MagicMock()
            mock_user.status = "BANNED"  # Owner is marked as banned
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_session.commit = AsyncMock()

            # Mock get_or_create_user to return a banned user
            with patch('handlers.group.get_or_create_user') as mock_create_user:
                mock_create_user.return_value = mock_user

                # Call ensure_owner_active
                await ensure_owner_active(bot)

                # Verify owner was restored
                mock_create_user.assert_called_once()
                # Verify bot was called to restore permissions
                bot.restrict_chat_member.assert_called_once()
                call_args = bot.restrict_chat_member.call_args
                self.assertEqual(call_args[1]['user_id'], self.urgent_owner_id)
                self.assertTrue(call_args[1]['permissions'].can_send_messages)
                self.assertTrue(call_args[1]['permissions'].can_pin_messages)

    @patch('handlers.group.settings')
    async def test_owner_auto_restore_from_restricted(self, mock_settings):
        """Test that owner is automatically restored if marked as RESTRICTED"""
        mock_settings.owner_id = self.urgent_owner_id
        mock_settings.effective_group_id = -1004335696952

        # Create mock bot
        bot = MagicMock()
        bot.restrict_chat_member = AsyncMock()

        # Mock database session
        with patch('handlers.group.get_db_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_user = MagicMock()
            mock_user.status = "RESTRICTED"  # Owner is marked as restricted
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_session.commit = AsyncMock()

            with patch('handlers.group.get_or_create_user') as mock_create_user:
                mock_create_user.return_value = mock_user

                # Call ensure_owner_active
                await ensure_owner_active(bot)

                # Verify owner was restored
                mock_create_user.assert_called_once()
                # Verify bot was called to restore permissions
                bot.restrict_chat_member.assert_called_once()

    @patch('handlers.group.settings')
    async def test_owner_already_verified_no_action(self, mock_settings):
        """Test that no action is taken if owner is already VERIFIED"""
        mock_settings.owner_id = self.urgent_owner_id

        # Create mock bot
        bot = MagicMock()
        bot.restrict_chat_member = AsyncMock()

        # Mock database session
        with patch('handlers.group.get_db_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_user = MagicMock()
            mock_user.status = "VERIFIED"  # Owner is already verified
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_session.commit = AsyncMock()

            with patch('handlers.group.get_or_create_user') as mock_create_user:
                mock_create_user.return_value = mock_user

                # Call ensure_owner_active
                await ensure_owner_active(bot)

                # Verify bot was NOT called (no need to restore)
                bot.restrict_chat_member.assert_not_called()

    @patch('handlers.group.settings')
    async def test_owner_always_has_full_permissions(self, mock_settings):
        """Test that owner always has full messaging permissions"""
        mock_settings.owner_id = self.urgent_owner_id
        mock_settings.effective_group_id = -1004335696952

        # Create mock bot
        bot = MagicMock()
        bot.restrict_chat_member = AsyncMock()

        # Mock database session
        with patch('handlers.group.get_db_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_user = MagicMock()
            mock_user.status = "VERIFIED"
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_session.commit = AsyncMock()

            with patch('handlers.group.get_or_create_user') as mock_create_user:
                mock_create_user.return_value = mock_user

                # Call ensure_owner_active
                await ensure_owner_active(bot)

                # Verify owner has ALL permissions
                bot.restrict_chat_member.assert_called_once()
                call_args = bot.restrict_chat_member.call_args
                permissions = call_args[1]['permissions']

                # Owner should have all possible permissions
                self.assertTrue(permissions.can_send_messages)
                self.assertTrue(permissions.can_send_polls)
                self.assertTrue(permissions.can_send_other_messages)
                self.assertTrue(permissions.can_add_web_page_previews)
                self.assertTrue(permissions.can_change_info)
                self.assertTrue(permissions.can_invite_users)
                self.assertTrue(permissions.can_pin_messages)


if __name__ == "__main__":
    unittest.main()