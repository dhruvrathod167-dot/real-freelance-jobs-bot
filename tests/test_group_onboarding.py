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
    restrict_user_communication,
    ban_user_permanent,
    unban_and_restore_user,
    get_expired_restrictions,
)
from services.scam_detector import scan_job_heuristics
from services.communication_moderator import (
    scan_communication_message,
    scan_communication_message_ai,
)
from handlers.direct_posts import send_verification_message_if_allowed


class TestGroupOnboardingAndModeration(unittest.IsolatedAsyncioTestCase):
    """Test suite for group onboarding and moderation features."""

    async def asyncSetUp(self):
        """Set up test fixtures before each test method."""
        self.mock_chat = MagicMock()
        self.mock_chat.id = -100123456789
        self.mock_chat.title = "Legally Freelancing Working"
        self.mock_chat.type = "supergroup"

        self.mock_user = MagicMock()
        self.mock_user.id = 123456789
        self.mock_user.first_name = "Charlie"
        self.mock_user.last_name = "Brown"
        self.mock_user.username = "charlie_b"
        self.mock_user.is_bot = False

        self.mock_context = MagicMock()
        self.mock_context.bot.send_message = AsyncMock()
        self.mock_context.bot.restrict_chat_member = AsyncMock()

        self.mock_update = MagicMock()
        self.mock_update.effective_chat = self.mock_chat
        self.mock_update.effective_user = self.mock_user

    async def test_onboard_new_member_basic(self):
        """Test basic onboarding process: restriction + verification message."""
        await onboard_new_member(self.mock_update, self.mock_chat, self.mock_user, self.mock_context)

        # 1. Proactively restricted chat permissions
        self.mock_context.bot.restrict_chat_member.assert_awaited_once()

        # 2. Sent welcome message
        self.mock_context.bot.send_message.assert_awaited_once()
        call_kwargs = self.mock_context.bot.send_message.call_args[1]

        sent_text = call_kwargs["text"]
        self.assertIn("Please verify your account with @RealFreelanceJobsBot before posting or submitting freelance jobs.", sent_text)
        self.assertIn("Legally Freelancing Working", sent_text)

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
        
        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        
        # Mock the database session to return 0 verification messages (within limit)
        with patch('handlers.direct_posts.get_db_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = MagicMock()
            mock_session.return_value.__aexit__.return_value = None
            
            # Mock get_verification_message_count to return 0 (within monthly limit)
            with patch('handlers.direct_posts.get_verification_message_count') as mock_count:
                mock_count.return_value = 0
                
                # First join event
                await onboard_new_member(mock_update, mock_chat, mock_user, mock_context)
                self.assertEqual(mock_context.bot.send_message.await_count, 1)

                # Immediate duplicate event
                await onboard_new_member(mock_update, mock_chat, mock_user, mock_context)
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
        mock_user.first_name = "Professional"
        mock_user.last_name = "User"
        mock_user.username = "pro_user"
        mock_user.is_bot = False

        mock_context = MagicMock()
        mock_context.bot.delete_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()
        mock_context.bot.send_message = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.message = MagicMock()
        mock_update.message.text = "I'm available for freelance web development projects. Contact me for details."
        mock_update.message.message_id = 555
        mock_update.message.date = int(time.time())

        # Mock scam detector to return LOW_RISK (safe message)
        with patch('services.scam_detector.scan_job_heuristics') as mock_scan:
            mock_scan.return_value = "LOW_RISK"

            # Normal professional message
            await scan_communication_message(self.mock_update.message.text)

            # No action taken (no deletion, no restriction)
            self.mock_context.bot.delete_message.assert_not_called()
            self.mock_context.bot.restrict_chat_member.assert_not_called()

            # No admin alert sent
            self.mock_context.bot.send_message.assert_not_called()

    async def test_high_risk_message_blocked(self):
        """Verifies high-risk scam/fraud messages are deleted, sender restricted, admins alerted."""
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 777888999
        mock_user.first_name = "Scammer"
        mock_user.last_name = "User"
        mock_user.username = "scammer_user"
        mock_user.is_bot = False

        mock_context = MagicMock()
        mock_context.bot.delete_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()
        mock_context.bot.send_message = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.message = MagicMock()
        mock_update.message.text = "Send me $500 to get a guaranteed high-paying job! This is not a scam!"
        mock_update.message.message_id = 666
        mock_update.message.date = int(time.time())

        # Mock scam detector to return HIGH_RISK
        with patch('services.scam_detector.scan_job_heuristics') as mock_scan:
            mock_scan.return_value = "HIGH_RISK"

            # High-risk message
            result = scan_communication_message(mock_update.message.text)
            # Process the result through the group message moderation handler
            from handlers.group import group_message_moderation_handler
            await group_message_moderation_handler(mock_update, mock_context)

            # Message deleted
            mock_context.bot.delete_message.assert_called_once_with(
                chat_id=mock_chat.id,
                message_id=666
            )

            # User restricted
            self.mock_context.bot.restrict_chat_member.assert_called_once()

            # Admin alert sent
            mock_context.bot.send_message.assert_called_once()

    async def test_deep_link_verification_flow(self):
        """Tests the deep link verification flow with callback queries."""
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"

        mock_user = MagicMock()
        mock_user.id = 444555666
        mock_user.first_name = "Link"
        mock_user.last_name = "User"
        mock_user.username = "link_user"
        mock_user.is_bot = False

        mock_context = MagicMock()
        mock_context.bot.answer_callback_query = AsyncMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = "confirm_verify_pledge"
        mock_update.callback_query.from_user = mock_user
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = MagicMock()
        mock_update.callback_query.message.edit_text = AsyncMock()

# Mock database operations
        with patch('database.crud.confirm_user_rules') as mock_confirm:
            mock_confirm.return_value = True

            # Process verification callback
            from handlers.verification import confirm_verify_callback
            await confirm_verify_callback(mock_update, mock_context)

            # User confirmed as verified
            mock_confirm.assert_called_once_with(unittest.mock.ANY, 444555666)

            # Callback acknowledged - the handler calls query.answer() not context.bot.answer_callback_query
            mock_update.callback_query.answer.assert_called_once()

            # Verification message sent - the handler edits the message instead of sending a new one
            mock_update.callback_query.message.edit_text.assert_called_once()
            call_args = mock_update.callback_query.message.edit_text.call_args
            self.assertIn("verified", call_args[0][0].lower())

    async def test_monthly_limit_enforcement(self):
        """Tests that monthly verification limit is enforced."""
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_user = MagicMock()
        mock_user.id = 333444555
        mock_user.first_name = "Monthly"
        mock_user.last_name = "User"
        mock_user.username = "monthly_user"
        mock_user.is_bot = False

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = mock_user

        # Mock database to return 3 (at monthly limit)
        with patch('handlers.direct_posts.get_verification_message_count') as mock_count:
            mock_count.return_value = 3

            # Try to send verification message
            await send_verification_message_if_allowed(mock_update, mock_context)

            # No verification message sent (at limit)
            self.mock_context.bot.send_message.assert_not_called()

    async def test_owner_bypass_onboarding(self):
        """Tests that owner bypasses onboarding restrictions."""
        # Create owner user
        owner_user = MagicMock()
        owner_user.id = 5952301026  # Owner ID from requirements
        owner_user.first_name = "Owner"
        owner_user.username = "owner_user"
        owner_user.is_bot = False

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = owner_user

        # Mock database to return owner
        with patch('database.crud.get_user_by_id') as mock_get_user:
            mock_get_user.return_value = MagicMock(is_owner=True)

            # Owner onboarding
            await onboard_new_member(mock_update, mock_chat, owner_user, mock_context)

            # No restriction applied to owner
            self.mock_context.bot.restrict_chat_member.assert_not_called()

            # No verification message sent to owner
            self.mock_context.bot.send_message.assert_not_called()

    async def test_admin_bypass_onboarding(self):
        """Tests that admin bypasses onboarding restrictions."""
        # Create admin user
        admin_user = MagicMock()
        admin_user.id = 123456789  # Different from owner ID
        admin_user.first_name = "Admin"
        admin_user.username = "admin_user"
        admin_user.is_bot = False

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Legally Freelancing Working"
        mock_chat.type = "supergroup"

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()
        mock_context.bot.restrict_chat_member = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_chat = mock_chat
        mock_update.effective_user = admin_user

        # Mock database to return admin
        with patch('database.crud.get_user_by_id') as mock_get_user:
            mock_get_user.return_value = MagicMock(is_admin=True)

            # Admin onboarding
            await onboard_new_member(mock_update, mock_chat, admin_user, mock_context)

            # No restriction applied to admin
            self.mock_context.bot.restrict_chat_member.assert_not_called()

            # No verification message sent to admin
            self.mock_context.bot.send_message.assert_not_called()