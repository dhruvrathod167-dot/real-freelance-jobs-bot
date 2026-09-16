"""
End-to-end smoke test for complete /submit workflow.
Tests the actual submission process from start to finish including:
- All 10 submission steps
- Background screening
- Risk assessment
- Auto-approval for LOW_RISK
- Admin moderation for REVIEW_REQUIRED
- Blocking for HIGH_RISK
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Chat, InlineKeyboardButton, CallbackQuery
from telegram.ext import ContextTypes
from handlers.jobs import (
    submit_start,
    step_company_name,
    step_company_website,
    step_contact_email,
    step_job_title,
    step_job_description,
    step_payment_rate,
    step_expected_work,
    step_country_region,
    step_application_method,
    step_original_source,
    confirm_job_submission_callback,
    cancel_job_submission
)


class TestSubmitEndToEnd:
    """End-to-end test for complete /submit workflow."""
    
    def create_mock_update(self, chat_type="private", user_id=12345):
        """Create a mock update with specified chat type and user"""
        update = MagicMock(spec=Update)
        update.effective_user = MagicMock(spec=User)
        update.effective_user.id = user_id
        update.effective_user.first_name = "Test"
        update.effective_user.username = "testuser"
        update.effective_user.last_name = "User"
        update.effective_user.status = "VERIFIED"
        update.effective_user.rules_accepted = True
        
        update.effective_chat = MagicMock(spec=Chat)
        update.effective_chat.type = chat_type if isinstance(chat_type, str) else 'private'
        
        # Add message attribute for submit_start function
        update.message = MagicMock()
        update.message.text = ""
        update.message.reply_text = AsyncMock()
        update.message.edit_text = AsyncMock()
        
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
    @patch('handlers.jobs.run_full_security_screening')
    @patch('handlers.jobs.create_job_submission')
    @patch('handlers.jobs.get_risk_badge')
    @patch('handlers.jobs.format_admin_job_review')
    @patch('handlers.jobs._safe_background_task')
    @patch('handlers.jobs._delete_temporary_message')
    @patch('handlers.jobs._auto_approve_and_publish_job')
    @patch('asyncio.create_task')
    @patch('handlers.jobs.submission_rate_limiter')
    @pytest.mark.asyncio
    async def test_complete_submit_workflow_low_risk(
        self, 
        mock_rate_limiter, 
        mock_create_task, 
        mock_auto_approve,
        mock_delete_message,
        mock_safe_task,
        mock_format_admin,
        mock_get_risk_badge,
        mock_create_job,
        mock_get_user,
        mock_settings,
        mock_screening
    ):
        """Test complete /submit workflow with LOW_RISK auto-approval."""
        
        # Setup mocks
        mock_settings.is_admin.return_value = False
        mock_settings.admin_id_list = [123]
        
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_user.is_owner = False  # Add this to bypass owner checks
        mock_get_user.return_value = mock_user
        
        # Mock the database session
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session_factory.return_value.__aexit__.return_value = None
        
        with patch('handlers.jobs.get_db_session', mock_session_factory), \
             patch('handlers.jobs.submission_rate_limiter') as mock_rate_limiter:
            mock_rate_limiter.is_allowed.return_value = True
            mock_rate_limiter.reset = AsyncMock()
        
        # Mock screening decision for LOW_RISK
        from services.moderation import ModerationDecision
        mock_decision = ModerationDecision(
            final_score=15.0,
            risk_level="low",
            action="queue",
            all_flags=[],
reasons=["Low risk job"],
            ai_data={"risk_score": 15.0},
            website_data={"is_reachable": True, "has_https": True}
        )
        mock_screening.return_value = mock_decision
        
        mock_job = MagicMock()
        mock_job.id = 1
        mock_create_job.return_value = mock_job
        
        mock_get_risk_badge.return_value = "🟢 LOW RISK"
        mock_format_admin.return_value = "Admin review card"
    
        # Start the conversation
        update = self.create_mock_update()
        context = self.create_mock_context()
        
        # Add message text to avoid AttributeError
        update.message.text = "/submit"
        
        result = await submit_start(update, context)
        print(f"Debug: submit_start returned {result}")
        assert result == 1  # STATE_COMPANY_NAME
        
        # Step 1: Company Name
        update.message.text = "Test Company"
        result = await step_company_name(update, context)
        assert result == 2  # STATE_COMPANY_WEBSITE
        assert context.user_data["job_draft"]["company_name"] == "Test Company"
        
        # Step 2: Company Website
        update.message.text = "https://testcompany.com"
        result = await step_company_website(update, context)
        assert result == 3  # STATE_CONTACT_EMAIL
        assert context.user_data["job_draft"]["company_website"] == "https://testcompany.com"
        
        # Step 3: Contact Email
        update.message.text = "test@testcompany.com"
        result = await step_contact_email(update, context)
        assert result == 4  # STATE_JOB_TITLE
        assert context.user_data["job_draft"]["contact_email"] == "test@testcompany.com"
        
        # Step 4: Job Title
        update.message.text = "Software Developer"
        result = await step_job_title(update, context)
        assert result == 5  # STATE_JOB_DESCRIPTION
        assert context.user_data["job_draft"]["job_title"] == "Software Developer"
        
        # Step 5: Job Description
        update.message.text = "Looking for a skilled developer with experience in React and Node.js"
        result = await step_job_description(update, context)
        assert result == 6  # STATE_PAYMENT_RATE
        assert context.user_data["job_draft"]["job_description"] == "Looking for a skilled developer with experience in React and Node.js"
        
        # Step 6: Payment Rate
        update.message.text = "$50/hr"
        result = await step_payment_rate(update, context)
        assert result == 7  # STATE_EXPECTED_WORK
        assert context.user_data["job_draft"]["payment_rate"] == "$50/hr"
        
        # Step 7: Expected Work
        update.message.text = "Develop web applications and APIs"
        result = await step_expected_work(update, context)
        assert result == 8  # STATE_COUNTRY_REGION
        assert context.user_data["job_draft"]["expected_work"] == "Develop web applications and APIs"
        
        # Step 8: Country Region
        update.message.text = "Remote Worldwide"
        result = await step_country_region(update, context)
        assert result == 9  # STATE_APPLICATION_METHOD
        assert context.user_data["job_draft"]["country_region"] == "Remote Worldwide"
        
        # Step 9: Application Method
        update.message.text = "Apply via email to careers@testcompany.com"
        result = await step_application_method(update, context)
        assert result == 10  # STATE_ORIGINAL_SOURCE
        assert context.user_data["job_draft"]["application_method"] == "Apply via email to careers@testcompany.com"
        
        # Step 10: Original Source
        update.message.text = "Direct"
        result = await step_original_source(update, context)
        assert result == 11  # STATE_CONFIRMATION
        
        # Verify preview card is shown
        update.message.reply_text.assert_called()
        preview_text = update.message.reply_text.call_args[0][0]
        assert "JOB SUBMISSION PREVIEW" in preview_text
        assert "Test Company" in preview_text
        assert "Software Developer" in preview_text
        
        # Confirm submission
        update.callback_query = MagicMock(spec=CallbackQuery)
        update.callback_query.answer = AsyncMock()
        update.callback_query.message = update.message
        
        # Execute the final submission callback
        result = await confirm_job_submission_callback(update, context)
        
        # Verify the workflow completed successfully
        assert result is not None
        
        # Verify acknowledgment message was sent exactly once
        update.message.edit_text.assert_called()
        acknowledgment_text = update.message.edit_text.call_args[0][0]
        assert "Job Submission Received" in acknowledgment_text
        assert "screened for security" in acknowledgment_text
        
        # Verify auto-approval was called for LOW_RISK
        mock_auto_approve.assert_called_once()
        
        # Verify background tasks were created
        mock_create_task.assert_called()
        
        # Verify rate limiter was reset
        mock_rate_limiter.reset.assert_called_once()
    
    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    @patch('handlers.jobs.run_full_security_screening')
    @patch('handlers.jobs.create_job_submission')
    @patch('handlers.jobs.get_risk_badge')
    @patch('handlers.jobs.format_admin_job_review')
    @patch('handlers.jobs._safe_background_task')
    @patch('handlers.jobs._delete_temporary_message')
    @patch('asyncio.create_task')
    @patch('handlers.jobs.submission_rate_limiter')
    @pytest.mark.asyncio
    async def test_complete_submit_workflow_review_required(
        self, 
        mock_rate_limiter, 
        mock_create_task, 
        mock_delete_message,
        mock_safe_task,
        mock_format_admin,
        mock_get_risk_badge,
        mock_create_job,
        mock_get_user,
        mock_settings,
        mock_screening
    ):
        """Test complete /submit workflow with REVIEW_REQUIRED."""
        
        # Setup mocks
        mock_settings.is_admin.return_value = False
        mock_settings.admin_id_list = [123]
        
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        # Mock the database session
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session_factory.return_value.__aexit__.return_value = None
        
        with patch('handlers.jobs.get_db_session', mock_session_factory):
            mock_rate_limiter.is_allowed.return_value = True
            mock_rate_limiter.reset = AsyncMock()
        
        # Mock screening decision for REVIEW_REQUIRED
        from services.moderation import ModerationDecision
        mock_decision = ModerationDecision(
            final_score=35.0,
            risk_level="review",
            action="hold_review",
            all_flags=["Standard safety review"],
            reasons=["Manual review required"],
            ai_data={"risk_score": 35.0},
            website_data={"is_reachable": True, "has_https": True}
        )
        mock_screening.return_value = mock_decision
        
        mock_job = MagicMock()
        mock_job.id = 2
        mock_create_job.return_value = mock_job
        
        mock_get_risk_badge.return_value = "🟡 REVIEW REQUIRED"
        mock_format_admin.return_value = "Admin review card"
        
        # Start the conversation
        update = self.create_mock_update()
        context = self.create_mock_context()
        
        result = await submit_start(update, context)
        assert result == 1  # STATE_COMPANY_NAME
        
        # Simulate all steps (abbreviated for brevity)
        steps_data = {
            "company_name": "Test Company",
            "company_website": "https://testcompany.com",
            "contact_email": "test@testcompany.com",
            "job_title": "Software Developer",
            "job_description": "Looking for a skilled developer",
            "payment_rate": "$50/hr",
            "expected_work": "Develop web applications",
            "country_region": "Remote",
            "application_method": "Apply via email",
            "original_source": "Direct"
        }
        
        # Simulate all steps quickly
        for i, (field, value) in enumerate(steps_data.items()):
            update.message.text = value
            if i == 0:  # Company name
                result = await step_company_name(update, context)
            elif i == 1:  # Company website
                result = await step_company_website(update, context)
            elif i == 2:  # Contact email
                result = await step_contact_email(update, context)
            elif i == 3:  # Job title
                result = await step_job_title(update, context)
            elif i == 4:  # Job description
                result = await step_job_description(update, context)
            elif i == 5:  # Payment rate
                result = await step_payment_rate(update, context)
            elif i == 6:  # Expected work
                result = await step_expected_work(update, context)
            elif i == 7:  # Country region
                result = await step_country_region(update, context)
            elif i == 8:  # Application method
                result = await step_application_method(update, context)
            elif i == 9:  # Original source
                result = await step_original_source(update, context)
        
        # Confirm submission
        update.callback_query = MagicMock(spec=CallbackQuery)
        update.callback_query.answer = AsyncMock()
        update.callback_query.message = update.message
        
        # Execute the final submission callback
        result = await confirm_job_submission_callback(update, context)
        
        # Verify the workflow completed successfully
        assert result is not None
        
        # Verify acknowledgment message was sent exactly once
        update.message.edit_text.assert_called()
        acknowledgment_text = update.message.edit_text.call_args[0][0]
        assert "Job Submission Received" in acknowledgment_text
        
        # Verify auto-approval was NOT called for REVIEW_REQUIRED
        mock_auto_approve.assert_not_called()
        
        # Verify admin review card was sent
        mock_format_admin_review.assert_called()
        
        # Verify background tasks were created
        mock_create_task.assert_called()
        
        # Verify rate limiter was reset
        mock_rate_limiter.reset.assert_called_once()
    
    @patch('handlers.jobs.settings')
    @patch('database.crud.get_user_by_id')
    @patch('handlers.jobs.run_full_security_screening')
    @patch('handlers.jobs.create_job_submission')
    @patch('handlers.jobs.get_risk_badge')
    @patch('handlers.jobs.format_admin_job_review')
    @patch('handlers.jobs._safe_background_task')
    @patch('handlers.jobs._delete_temporary_message')
    @patch('asyncio.create_task')
    @patch('handlers.jobs.submission_rate_limiter')
    @pytest.mark.asyncio
    async def test_complete_submit_workflow_high_risk(
        self, 
        mock_rate_limiter, 
        mock_create_task, 
        mock_delete_message,
        mock_safe_task,
        mock_format_admin,
        mock_get_risk_badge,
        mock_create_job,
        mock_get_user,
        mock_settings,
        mock_screening
    ):
        """Test complete /submit workflow with HIGH_RISK blocking."""
        
        # Setup mocks
        mock_settings.is_admin.return_value = False
        mock_settings.admin_id_list = [123]
        
        mock_user = MagicMock()
        mock_user.status = "VERIFIED"
        mock_user.rules_accepted = True
        mock_get_user.return_value = mock_user
        
        # Mock the database session
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session_factory.return_value.__aexit__.return_value = None
        
        with patch('handlers.jobs.get_db_session', mock_session_factory):
            mock_rate_limiter.is_allowed.return_value = True
            mock_rate_limiter.reset = AsyncMock()
        
        # Mock screening decision for HIGH_RISK
        from services.moderation import ModerationDecision
        mock_decision = ModerationDecision(
            final_score=65.0,
            risk_level="high",
            action="block_review",
            all_flags=["High security risk indicators detected"],
            reasons=["High risk score"],
            ai_data={"risk_score": 65.0},
            website_data={"is_reachable": True, "has_https": True}
        )
        mock_screening.return_value = mock_decision
        
        mock_job = MagicMock()
        mock_job.id = 3
        mock_create_job.return_value = mock_job
        
        mock_get_risk_badge.return_value = "🔴 HIGH RISK"
        mock_format_admin.return_value = "Admin review card"
        
        # Start the conversation
        update = self.create_mock_update()
        context = self.create_mock_context()
        
        result = await submit_start(update, context)
        assert result == 1  # STATE_COMPANY_NAME
        
        # Simulate all steps quickly
        steps_data = {
            "company_name": "Test Company",
            "company_website": "https://testcompany.com",
            "contact_email": "test@testcompany.com",
            "job_title": "Software Developer",
            "job_description": "Looking for a skilled developer",
            "payment_rate": "$50/hr",
            "expected_work": "Develop web applications",
            "country_region": "Remote",
            "application_method": "Apply via email",
            "original_source": "Direct"
        }
        
        # Simulate all steps quickly
        for i, (field, value) in enumerate(steps_data.items()):
            update.message.text = value
            if i == 0:  # Company name
                result = await step_company_name(update, context)
            elif i == 1:  # Company website
                result = await step_company_website(update, context)
            elif i == 2:  # Contact email
                result = await step_contact_email(update, context)
            elif i == 3:  # Job title
                result = await step_job_title(update, context)
            elif i == 4:  # Job description
                result = await step_job_description(update, context)
            elif i == 5:  # Payment rate
                result = await step_payment_rate(update, context)
            elif i == 6:  # Expected work
                result = await step_expected_work(update, context)
            elif i == 7:  # Country region
                result = await step_country_region(update, context)
            elif i == 8:  # Application method
                result = await step_application_method(update, context)
            elif i == 9:  # Original source
                result = await step_original_source(update, context)
        
        # Confirm submission
        update.callback_query = MagicMock(spec=CallbackQuery)
        update.callback_query.answer = AsyncMock()
        update.callback_query.message = update.message
        
        # Execute the final submission callback
        result = await confirm_job_submission_callback(update, context)
        
        # Verify the workflow completed successfully
        assert result is not None
        
        # Verify acknowledgment message was sent exactly once
        update.message.edit_text.assert_called()
        acknowledgment_text = update.message.edit_text.call_args[0][0]
        assert "Job Submission Received" in acknowledgment_text
        
        # Verify auto-approval was NOT called for HIGH_RISK
        mock_auto_approve.assert_not_called()
        
        # Verify admin review card was sent (even for blocked jobs)
        mock_format_admin_review.assert_called()
        
        # Verify background tasks were created
        mock_create_task.assert_called()
        
        # Verify rate limiter was reset
        mock_rate_limiter.reset.assert_called_once()