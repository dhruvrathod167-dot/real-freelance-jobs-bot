"""
Test suite for private job submission functionality.
Verifies that job submission works only in private chat and not in group chats.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from unittest import IsolatedAsyncioTestCase
from telegram import Update, User, Chat
from telegram.ext import ContextTypes, ConversationHandler

# Import the functions we're testing
from handlers.jobs import submit_start


class TestPrivateJobSubmission(IsolatedAsyncioTestCase):
    """Test cases for private job submission workflow."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock database session
        self.session_factory = AsyncMock()

    def create_mock_update(self, chat_type="private", user_id=12345):
        """Create a mock update with specified chat type and user"""
        update = MagicMock(spec=Update)
        update.effective_user = MagicMock(spec=User)
        update.effective_user.id = user_id
        update.effective_user.first_name = "Test"
        update.effective_user.username = "testuser"
        update.effective_user.last_name = "User"
        
        update.effective_chat = MagicMock(spec=Chat)
        update.effective_chat.type = chat_type if isinstance(chat_type, str) else 'private'
        
        update.message = MagicMock()
        update.message.text = "/submit"
        update.message.reply_text = AsyncMock()
        
        update.callback_query = None
        
        return update

    def create_mock_context(self):
        """Create a mock context"""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        
        return context

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_submit_in_private_chat_allowed(self, mock_get_user, mock_settings):
        """Test that /submit works in private chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="private", user_id=12345)
        context = self.create_mock_context()
        
        # Mock user verification
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should proceed to conversation (not END)
        self.assertEqual(result, 1)  # STATE_COMPANY_NAME
        update.message.reply_text.assert_called_once()
        # Check that the welcome message contains the job submission form
        call_args = update.message.reply_text.call_args
        self.assertIn("JOB SUBMISSION ASSISTANT", call_args[0][0])

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_submit_in_group_rejected(self, mock_get_user, mock_settings):
        """Test that /submit is rejected in group chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="group", user_id=12345)
        context = self.create_mock_context()
        
        # Mock user verification
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should end conversation
        self.assertEqual(result, ConversationHandler.END)
        update.message.reply_text.assert_called_once()
        # Check that rejection message is sent
        call_args = update.message.reply_text.call_args
        self.assertIn("Job Submission in Private Chat Only", call_args[0][0])

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_submit_in_supergroup_rejected(self, mock_get_user, mock_settings):
        """Test that /submit is rejected in supergroup chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="supergroup", user_id=12345)
        context = self.create_mock_context()
        
        # Mock user verification
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should end conversation
        self.assertEqual(result, ConversationHandler.END)
        update.message.reply_text.assert_called_once()
        # Check that rejection message is sent
        call_args = update.message.reply_text.call_args
        self.assertIn("Job Submission in Private Chat Only", call_args[0][0])

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_unverified_user_rejected_in_private_chat(self, mock_get_user, mock_settings):
        """Test that unverified users are rejected in private chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="private", user_id=12345)
        context = self.create_mock_context()
        
        # Mock user verification pending
        mock_user = MagicMock()
        mock_user.status = "PENDING"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should end conversation
        self.assertEqual(result, ConversationHandler.END)
        update.message.reply_text.assert_called_once()
        # Check that verification required message is sent
        call_args = update.message.reply_text.call_args
        self.assertIn("Verification Required", call_args[0][0])
        self.assertIn("send /verify", call_args[0][0])

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_banned_user_rejected_in_private_chat(self, mock_get_user, mock_settings):
        """Test that banned users are rejected even in private chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="private", user_id=12345)
        context = self.create_mock_context()
        
        # Mock user banned
        mock_user = MagicMock()
        mock_user.status = "BANNED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should end conversation
        self.assertEqual(result, ConversationHandler.END)
        update.message.reply_text.assert_called_once()
        # Check that restriction message is sent
        call_args = update.message.reply_text.call_args
        self.assertIn("Submission Restricted", call_args[0][0])

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_submit_callback_in_private_chat_allowed(self, mock_get_user, mock_settings):
        """Test that start_submit callback works in private chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="private", user_id=12345)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.message = MagicMock()
        update.callback_query.message.reply_text = AsyncMock()
        
        context = self.create_mock_context()
        
        # Mock user verification
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should proceed to conversation
        self.assertEqual(result, 1)  # STATE_COMPANY_NAME
        update.callback_query.answer.assert_called_once()
        update.callback_query.message.reply_text.assert_called_once()

    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    async def test_submit_callback_in_group_rejected(self, mock_get_user, mock_settings):
        """Test that start_submit callback is rejected in group chat"""
        mock_settings.is_admin.return_value = False
        
        update = self.create_mock_update(chat_type="group", user_id=12345)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.message = MagicMock()
        update.callback_query.message.reply_text = AsyncMock()
        
        context = self.create_mock_context()
        
        # Mock user verification
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        result = await submit_start(update, context)
        
        # Should end conversation
        self.assertEqual(result, ConversationHandler.END)
        update.callback_query.answer.assert_called_once()
        update.callback_query.message.reply_text.assert_called_once()
        # Check that rejection message is sent
        call_args = update.callback_query.message.reply_text.call_args
        self.assertIn("Job Submission in Private Chat Only", call_args[0][0])


if __name__ == "__main__":
    unittest.main()