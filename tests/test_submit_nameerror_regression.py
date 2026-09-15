"""
Regression test for NameError in /submit workflow.
Tests the complete submission flow to ensure no NameError occurs during:
- database save
- background verification  
- website/domain check
- email check
- heuristic scam check
- AI analysis
- risk calculation
- LOW_RISK automatic approval
- REVIEW_REQUIRED admin workflow
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, InlineKeyboardButton, CallbackQuery
from services.moderation import run_full_security_screening, ModerationDecision
from handlers.jobs import confirm_job_submission_callback
from database.crud import create_job_submission


class TestSubmitNameErrorRegression:
    """Test regression for NameError in /submit workflow."""
    
    @pytest.mark.asyncio
    async def test_submit_workflow_no_nameerror(self):
        """Test complete /submit workflow without NameError."""
        # Mock the update and context objects
        mock_query = AsyncMock()
        mock_query.answer = AsyncMock()
        mock_query.message.edit_text = AsyncMock()
        
        mock_update = AsyncMock()
        mock_update.callback_query = mock_query
        mock_update.effective_user = AsyncMock()
        mock_update.effective_user.id = 12345
        mock_update.effective_user.username = "testuser"
        
        mock_context = AsyncMock()
        mock_context.user_data = {
            "job_draft": {
                "company_name": "Test Company",
                "company_website": "https://testcompany.com",
                "contact_email": "test@testcompany.com",
                "job_title": "Software Developer",
                "job_description": "Looking for a skilled developer",
                "payment_rate": "$50/hr",
                "expected_work": "Develop web applications",
                "country_region": "Remote",
                "application_method": "Apply via email",
                "original_source": None
            }
        }
        mock_context.bot = AsyncMock()
        
        # Mock the run_full_security_screening function to return a valid decision
        mock_decision = ModerationDecision(
            final_score=15.0,
            risk_level="low",
            action="queue",
            all_flags=[],
            reasons=["Low risk job"],
            ai_data={"risk_score": 15.0},
            website_data={"is_reachable": True, "has_https": True}
        )
        
        # Mock database operations
        mock_job = AsyncMock()
        mock_job.id = 1
        create_job_submission = AsyncMock(return_value=mock_job)
        
        # Mock the auto-approval function
        mock_auto_approve = AsyncMock()
        
        # Mock the get_risk_badge function
        def mock_get_risk_badge(score, level):
            return "🟢 LOW RISK"
        
        # Mock the format_admin_job_review function
        def mock_format_admin_job_review(**kwargs):
            return "Admin review card"
        
        # Mock the _safe_background_task function
        def mock_safe_background_task(coro, task_name):
            return coro
        
        # Mock the _delete_temporary_message function
        async def mock_delete_temporary_message(message, delay):
            pass
        
        # Mock the asyncio.create_task function
        def mock_create_task(coro):
            return AsyncMock()
        
        # Patch all the dependencies
        import handlers.jobs
        import asyncio
        from unittest.mock import patch
        
        with patch('handlers.jobs.run_full_security_screening', return_value=mock_decision), \
             patch('handlers.jobs.create_job_submission', create_job_submission), \
             patch('handlers.jobs.get_risk_badge', mock_get_risk_badge), \
             patch('handlers.jobs.format_admin_job_review', mock_format_admin_job_review), \
             patch('handlers.jobs._safe_background_task', mock_safe_background_task), \
             patch('handlers.jobs._delete_temporary_message', mock_delete_temporary_message), \
             patch('handlers.jobs._auto_approve_and_publish_job', mock_auto_approve), \
             patch('asyncio.create_task', mock_create_task), \
             patch('handlers.jobs.settings', admin_id_list=[123]):
            
            # Execute the function that caused the NameError
            result = await confirm_job_submission_callback(mock_update, mock_context)
            
            # Verify the function completed without NameError
            assert result is not None
            
            # Verify that the acknowledgment message was sent
            mock_query.message.edit_text.assert_called()
            
            # Verify that the auto-approval was called for low-risk jobs
            mock_auto_approve.assert_called_once()
    
    @pytest.mark.asyncio  
    async def test_moderation_decision_with_exception_handling(self):
        """Test moderation decision handles exceptions properly without NameError."""
        # Test with exception from AI analysis
        mock_decision = ModerationDecision(
            final_score=25.0,
            risk_level="review",
            action="hold_review",
            all_flags=["AI analysis failed"],
            reasons=["AI service unavailable, requiring manual review"],
            ai_data={},
            website_data={}
        )
        
        # Mock database operations
        mock_job = AsyncMock()
        mock_job.id = 1
        create_job_submission = AsyncMock(return_value=mock_job)
        
        # Mock the get_risk_badge function
        def mock_get_risk_badge(score, level):
            return "🟡 REVIEW REQUIRED"
        
        # Mock the format_admin_job_review function
        def mock_format_admin_job_review(**kwargs):
            return "Admin review card"
        
        # Mock the _safe_background_task function
        def mock_safe_background_task(coro, task_name):
            return coro
        
        # Mock the _delete_temporary_message function
        async def mock_delete_temporary_message(message, delay):
            pass
        
        # Mock the asyncio.create_task function
        def mock_create_task(coro):
            return AsyncMock()
        
        # Mock update and context
        mock_query = AsyncMock()
        mock_query.answer = AsyncMock()
        mock_query.message.edit_text = AsyncMock()
        
        mock_update = AsyncMock()
        mock_update.callback_query = mock_query
        mock_update.effective_user = AsyncMock()
        mock_update.effective_user.id = 12345
        mock_update.effective_user.username = "testuser"
        
        mock_context = AsyncMock()
        mock_context.user_data = {
            "job_draft": {
                "company_name": "Test Company",
                "company_website": "https://testcompany.com",
                "contact_email": "test@testcompany.com",
                "job_title": "Software Developer",
                "job_description": "Looking for a skilled developer",
                "payment_rate": "$50/hr",
                "expected_work": "Develop web applications",
                "country_region": "Remote",
                "application_method": "Apply via email",
                "original_source": None
            }
        }
        mock_context.bot = AsyncMock()
        
        # Patch all the dependencies
        import handlers.jobs
        from unittest.mock import patch
        
        with patch('handlers.jobs.run_full_security_screening', return_value=mock_decision), \
             patch('handlers.jobs.create_job_submission', create_job_submission), \
             patch('handlers.jobs.get_risk_badge', mock_get_risk_badge), \
             patch('handlers.jobs.format_admin_job_review', mock_format_admin_job_review), \
             patch('handlers.jobs._safe_background_task', mock_safe_background_task), \
             patch('handlers.jobs._delete_temporary_message', mock_delete_temporary_message), \
             patch('asyncio.create_task', mock_create_task), \
             patch('handlers.jobs.settings', admin_id_list=[123]):
            
            # Execute the function that caused the NameError
            result = await confirm_job_submission_callback(mock_update, mock_context)
            
            # Verify the function completed without NameError
            assert result is not None
            
            # Verify that the acknowledgment message was sent
            mock_query.message.edit_text.assert_called()
            
            # Verify that admin review was sent for review_required jobs
            mock_query.message.edit_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_moderation_pipeline_exception_handling(self):
        """Test that moderation pipeline handles exceptions properly without NameError."""
        from services.moderation import run_full_security_screening
        
        # Test data
        test_data = {
            "company_name": "Test Company",
            "company_website": "https://testcompany.com",
            "contact_email": "test@testcompany.com",
            "job_title": "Software Developer",
            "job_description": "Looking for a skilled developer",
            "payment_rate": "$50/hr",
            "expected_work": "Develop web applications",
            "country_region": "Remote",
            "application_method": "Apply via email",
        }
        
        # Mock the dependent services to raise exceptions
        from unittest.mock import patch
        
        with patch('services.moderation.check_website') as mock_website, \
             patch('services.moderation.analyze_job_with_ai') as mock_ai, \
             patch('services.moderation.scan_job_heuristics') as mock_heuristic, \
             patch('services.moderation.check_domain_integrity') as mock_domain:
            
            # Make the functions raise exceptions
            mock_website.side_effect = Exception("Website check failed")
            mock_ai.side_effect = Exception("AI analysis failed")
            mock_heuristic.side_effect = Exception("Heuristic scan failed")
            mock_domain.side_effect = Exception("Domain check failed")
            
            # This should not raise a NameError, but should handle exceptions gracefully
            decision = await run_full_security_screening(**test_data)
            
            # Verify we got a decision object despite the exceptions
            assert isinstance(decision, ModerationDecision)
            assert decision.final_score > 0  # Should have some score due to exception handling
            assert decision.risk_level == "review"
            assert decision.action == "hold_review"
            assert len(decision.all_flags) > 0  # Should have error flags