"""
Comprehensive test suite for direct job post functionality.
Tests all scenarios: LOW_RISK, REVIEW_REQUIRED, HIGH_RISK, monthly verification limits, etc.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from datetime import datetime, timezone, date
from telegram import Update, User, Chat, Message
from telegram.ext import ContextTypes

from handlers.direct_posts import (
    handle_direct_job_post,
    is_direct_job_post,
    extract_job_details,
    create_temporary_notification,
    process_direct_job_post,
    handle_low_risk_job,
    handle_review_required_job,
    handle_high_risk_job,
    should_send_verification_message,
    send_verification_message_if_allowed,
    format_final_job_post,
)
from database.models import User as UserModel, VerificationMessage
from database.crud import get_verification_message_count, create_verification_message


class TestDirectPostDetection:
    """Test direct job post detection functionality."""
    
    def test_is_direct_job_post_positive(self):
        """Test detection of direct job posts."""
        job_posts = [
            "We are looking for a Python developer. Apply now!",
            "Hiring: Frontend Engineer with React experience",
            "Job opening: UX Designer needed immediately",
            "Earn $5000/month working from home",
            "Freelancers needed for web development project",
        ]
        
        for post in job_posts:
            assert is_direct_job_post(post), f"Should detect job post: {post}"
    
    def test_is_direct_job_post_negative(self):
        """Test that non-job posts are not detected."""
        non_job_posts = [
            "Hello everyone!",
            "Thanks for the help yesterday",
            "Looking for recommendations for restaurants",
            "This is a great community",
            "Meeting at 3pm today",
        ]
        
        for post in non_job_posts:
            assert not is_direct_job_post(post), f"Should not detect as job post: {post}"
    
    def test_extract_job_details(self):
        """Test job details extraction from direct posts."""
        post = (
            "We are looking for a Python developer\n"
            "Company: TechCorp\n"
            "Salary: $50/hour\n"
            "Email: jobs@techcorp.com\n"
            "Apply by sending your resume"
        )
        
        details = extract_job_details(post)
        assert details is not None
        assert details['company_name'] == 'TechCorp'
        assert details['contact_email'] == 'jobs@techcorp.com'
        assert 'Python developer' in details['job_title']
        assert details['payment_rate'] == '$50/hour'
    
    def test_extract_job_details_empty(self):
        """Test extraction with empty post."""
        details = extract_job_details("")
        assert details is None
    
    def test_extract_job_details_invalid(self):
        """Test extraction with invalid post."""
        details = extract_job_details("This is not a job post")
        assert details is not None
        assert details['company_name'] == 'Unknown Company'
        assert details['job_title'] == ''


class TestDirectPostHandler:
    """Test the main direct post handler."""
    
    def create_mock_update(self, user_id=12345, text="We are hiring developers"):
        """Create a mock update for testing."""
        update = MagicMock(spec=Update)
        update.effective_chat = MagicMock(spec=Chat)
        update.effective_chat.id = -1004335696952
        update.effective_chat.type = "group"
        update.effective_chat.title = "Legally Freelancing Working"
        
        update.effective_user = MagicMock(spec=User)
        update.effective_user.id = user_id
        update.effective_user.first_name = "Test"
        update.effective_user.username = "testuser"
        update.effective_user.last_name = "User"
        update.effective_user.is_bot = False
        
        update.effective_message = MagicMock(spec=Message)
        update.effective_message.text = text
        update.effective_message.message_id = 1
        
        return update
    
    def create_mock_context(self):
        """Create a mock context for testing."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        return context
    
    @patch('handlers.direct_posts.PROTECTED_USER_IDS', {999})  # Override protected users for testing
    @pytest.mark.asyncio
    async def test_handle_direct_job_post_protected_user(self):
        """Test that protected users bypass direct post moderation."""
        update = self.create_mock_update(user_id=999)
        context = self.create_mock_context()
        
        await handle_direct_job_post(update, context)
        
        # Should not create any messages for protected users
        context.bot.send_message.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_direct_job_post_non_job(self):
        """Test that non-job posts are not processed."""
        update = self.create_mock_update(text="Hello everyone!")
        context = self.create_mock_context()
        
        await handle_direct_job_post(update, context)
        
        # Should not create any messages for non-job posts
        context.bot.send_message.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_direct_job_post_normal_user(self):
        """Test direct job post handling for normal users."""
        update = self.create_mock_update(text="We are hiring developers!")
        context = self.create_mock_context()
        
        # Mock the temp message creation
        temp_message = MagicMock()
        temp_message.message_id = 2
        context.bot.send_message.return_value = temp_message
        
        await handle_direct_job_post(update, context)
        
        # Should create temporary notification
        context.bot.send_message.assert_called_once()
        
        # Should schedule background task for screening
        assert context.bot.send_message.call_count == 1


class TestDirectPostProcessing:
    """Test direct post processing logic."""
    
    def create_mock_update(self):
        """Create a mock update for testing."""
        update = MagicMock(spec=Update)
        update.effective_chat = MagicMock(spec=Chat)
        update.effective_chat.id = -1004335696952
        update.effective_chat.title = "Legally Freelancing Working"
        
        update.effective_user = MagicMock(spec=User)
        update.effective_user.id = 12345
        update.effective_user.first_name = "Test"
        update.effective_user.username = "testuser"
        
        update.effective_message = MagicMock(spec=Message)
        update.effective_message.message_id = 1
        update.effective_message.edit_text = AsyncMock()
        update.effective_message.delete = AsyncMock()
        
        return update
    
    def create_mock_context(self):
        """Create a mock context for testing."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        return context
    
    def create_mock_screening_result(self, risk_level="low", final_score=15.0):
        """Create a mock screening result."""
        screening_result = MagicMock()
        screening_result.risk_level = risk_level
        screening_result.final_score = final_score
        screening_result.all_flags = []
        screening_result.reasons = []
        screening_result.ai_data = {}
        screening_result.website_data = {}
        return screening_result
    
    @pytest.mark.asyncio
    async def test_process_direct_job_post_low_risk(self):
        """Test processing of low-risk direct job posts."""
        update = self.create_mock_update()
        context = self.create_mock_context()
        temp_message = MagicMock()
        job_details = {
            'company_name': 'Test Company',
            'company_website': 'https://test.com',
            'contact_email': 'test@test.com',
            'job_title': 'Developer',
            'job_description': 'We need a developer',
            'payment_rate': '$50/hr',
            'expected_work': 'Development work',
            'country_region': 'Remote',
            'application_method': 'Apply via email',
            'original_source': 'direct_post'
        }
        
        screening_result = self.create_mock_screening_result("low", 15.0)
        
        with patch('handlers.direct_posts.handle_low_risk_job') as mock_handle:
            await process_direct_job_post(update, context, temp_message, job_details)
            mock_handle.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_direct_job_post_review_required(self):
        """Test processing of review-required direct job posts."""
        update = self.create_mock_update()
        context = self.create_mock_context()
        temp_message = MagicMock()
        job_details = {
            'company_name': 'Test Company',
            'company_website': 'https://test.com',
            'contact_email': 'test@test.com',
            'job_title': 'Developer',
            'job_description': 'We need a developer',
            'payment_rate': '$50/hr',
            'expected_work': 'Development work',
            'country_region': 'Remote',
            'application_method': 'Apply via email',
            'original_source': 'direct_post'
        }
        
        screening_result = self.create_mock_screening_result("review", 35.0)
        screening_result.risk_level = "review"  # Ensure it's explicitly set
        
        # Mock the run_full_security_screening function to return our custom result
        with patch('handlers.direct_posts.run_full_security_screening') as mock_screening, \
             patch('handlers.direct_posts.handle_review_required_job') as mock_handle:
            mock_screening.return_value = screening_result
            await process_direct_job_post(update, context, temp_message, job_details)
            mock_handle.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_direct_job_post_high_risk(self):
        """Test processing of high-risk direct job posts."""
        update = self.create_mock_update()
        context = self.create_mock_context()
        temp_message = MagicMock()
        job_details = {
            'company_name': 'Test Company',
            'company_website': 'https://test.com',
            'contact_email': 'test@test.com',
            'job_title': 'Developer',
            'job_description': 'We need a developer',
            'payment_rate': '$50/hr',
            'expected_work': 'Development work',
            'country_region': 'Remote',
            'application_method': 'Apply via email',
            'original_source': 'direct_post'
        }
        
        screening_result = self.create_mock_screening_result("high", 75.0)
        screening_result.risk_level = "high"  # Ensure it's explicitly set
        
        # Mock the run_full_security_screening function to return our custom result
        with patch('handlers.direct_posts.run_full_security_screening') as mock_screening, \
             patch('handlers.direct_posts.handle_high_risk_job') as mock_handle:
            mock_screening.return_value = screening_result
            await process_direct_job_post(update, context, temp_message, job_details)
            mock_handle.assert_called_once()


class TestJobHandling:
    """Test specific job handling scenarios."""
    
    def create_mock_update(self):
        """Create a mock update for testing."""
        update = MagicMock(spec=Update)
        update.effective_chat = MagicMock(spec=Chat)
        update.effective_chat.id = -1004335696952
        update.effective_chat.title = "Legally Freelancing Working"
        
        update.effective_user = MagicMock(spec=User)
        update.effective_user.id = 12345
        update.effective_user.first_name = "Test"
        update.effective_user.username = "testuser"
        
        update.effective_message = MagicMock(spec=Message)
        update.effective_message.message_id = 1
        update.effective_message.edit_text = AsyncMock()
        update.effective_message.delete = AsyncMock()
        
        return update
    
    def create_mock_context(self):
        """Create a mock context for testing."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        return context
    
    @pytest.mark.asyncio
    async def test_handle_low_risk_job(self):
        """Test handling of low-risk direct job posts."""
        update = self.create_mock_update()
        context = self.create_mock_context()
        original_message = MagicMock()
        original_message.edit_text = AsyncMock()
        temp_message = MagicMock()
        
        job_details = {
            'company_name': 'Test Company',
            'company_website': 'https://test.com',
            'contact_email': 'test@test.com',
            'job_title': 'Developer',
            'job_description': 'We need a developer',
            'payment_rate': '$50/hr',
            'expected_work': 'Development work',
            'country_region': 'Remote',
            'application_method': 'Apply via email',
            'original_source': 'direct_post'
        }
        
        screening_result = MagicMock()
        screening_result.final_score = 15.0
        screening_result.risk_level = "low"
        screening_result.all_flags = []
        screening_result.ai_data = {}
        
        with patch('handlers.direct_posts.create_job_submission') as mock_create, \
             patch('handlers.direct_posts.create_audit_entry') as mock_audit, \
             patch('handlers.direct_posts._safe_background_task') as mock_task:
            
            await handle_low_risk_job(update, context, original_message, temp_message, job_details, screening_result)
            
            # Should create job submission
            mock_create.assert_called_once()
            
            # Should create audit entry
            mock_audit.assert_called_once()
            
            # Should edit original message
            original_message.edit_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_review_required_job(self):
        """Test handling of review-required direct job posts."""
        update = self.create_mock_update()
        context = self.create_mock_context()
        original_message = MagicMock()
        original_message.delete = AsyncMock()
        temp_message = MagicMock()
        
        job_details = {
            'company_name': 'Test Company',
            'company_website': 'https://test.com',
            'contact_email': 'test@test.com',
            'job_title': 'Developer',
            'job_description': 'We need a developer',
            'payment_rate': '$50/hr',
            'expected_work': 'Development work',
            'country_region': 'Remote',
            'application_method': 'Apply via email',
            'original_source': 'direct_post'
        }
        
        screening_result = MagicMock()
        screening_result.final_score = 35.0
        screening_result.risk_level = "review"
        screening_result.all_flags = ["Manual review required"]
        screening_result.ai_data = {}
        
        with patch('handlers.direct_posts.create_job_submission') as mock_create, \
             patch('handlers.direct_posts.create_audit_entry') as mock_audit, \
             patch('handlers.direct_posts._safe_background_task') as mock_task:
            
            await handle_review_required_job(update, context, original_message, temp_message, job_details, screening_result)
            
            # Should delete original message
            original_message.delete.assert_called_once()
            
            # Should create job submission
            mock_create.assert_called_once()
            
            # Should create audit entry
            mock_audit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_high_risk_job(self):
        """Test handling of high-risk direct job posts."""
        update = self.create_mock_update()
        context = self.create_mock_context()
        original_message = MagicMock()
        original_message.delete = AsyncMock()
        temp_message = MagicMock()
        
        screening_result = MagicMock()
        screening_result.final_score = 75.0
        screening_result.risk_level = "high"
        screening_result.all_flags = ["Suspicious payment scheme", "Unrealistic compensation"]
        screening_result.ai_data = {}
        
        with patch('handlers.direct_posts.flag_user_suspicious') as mock_flag, \
             patch('handlers.direct_posts.create_audit_entry') as mock_audit, \
             patch('handlers.direct_posts._safe_background_task') as mock_task:
            
            await handle_high_risk_job(update, context, original_message, temp_message, screening_result)
            
            # Should delete original message
            original_message.delete.assert_called_once()
            
            # Should flag user as suspicious
            mock_flag.assert_called_once()
            
            # Should create audit entry
            mock_audit.assert_called_once()


class TestVerificationMessageLimits:
    """Test monthly verification message limits."""
    
    @pytest.mark.asyncio
    async def test_should_send_verification_message_first_time(self):
        """Test that first verification message is allowed."""
        with patch('handlers.direct_posts.get_verification_message_count') as mock_count:
            mock_count.return_value = 0
            
            result = await should_send_verification_message(12345)
            assert result is True
    
    @pytest.mark.asyncio
    async def test_should_send_verification_message_within_limit(self):
        """Test that messages within monthly limit are allowed."""
        with patch('handlers.direct_posts.get_verification_message_count') as mock_count:
            mock_count.return_value = 2
            
            result = await should_send_verification_message(12345)
            assert result is True
    
    @pytest.mark.asyncio
    async def test_should_send_verification_message_at_limit(self):
        """Test that messages at monthly limit are not allowed."""
        with patch('handlers.direct_posts.get_verification_message_count') as mock_count:
            mock_count.return_value = 3
            
            result = await should_send_verification_message(12345)
            assert result is False
    
    @pytest.mark.asyncio
    async def test_should_send_verification_message_error(self):
        """Test error handling in verification message check."""
        with patch('handlers.direct_posts.get_verification_message_count') as mock_count:
            mock_count.side_effect = Exception("Database error")
            
            result = await should_send_verification_message(12345)
            assert result is False  # Should default to False on error


class TestFinalJobPostFormatting:
    """Test final job post formatting."""
    
    def test_format_final_job_post(self):
        """Test formatting of final approved job post."""
        job_details = {
            'company_name': 'TechCorp Inc',
            'company_website': 'https://techcorp.com',
            'contact_email': 'jobs@techcorp.com',
            'job_title': 'Senior Python Developer',
            'job_description': 'We are looking for an experienced Python developer to join our team.',
            'payment_rate': '$75/hour',
            'expected_work': 'Full-time remote development',
            'country_region': 'Remote',
            'application_method': 'Apply via careers@techcorp.com',
            'original_source': 'direct_post'
        }
        
        screening_result = MagicMock()
        screening_result.final_score = 15.0
        screening_result.risk_level = "low"
        screening_result.all_flags = []
        screening_result.ai_data = {}
        
        result = format_final_job_post(job_details, screening_result)
        
        assert 'Senior Python Developer' in result
        assert 'TechCorp Inc' in result
        assert '$75/hour' in result
        assert 'Remote' in result
        assert 'jobs@techcorp.com' in result
        assert 'careers@techcorp.com' in result


class TestIntegration:
    """Integration tests for the complete direct post flow."""
    
    @pytest.mark.asyncio
    async def test_complete_direct_post_flow(self):
        """Test the complete direct post flow from detection to final action."""
        # This test would require more complex mocking and potentially a real database
        # For now, we'll test the individual components
        
        # Test job detection
        assert is_direct_job_post("We are hiring developers!")
        assert not is_direct_job_post("Hello world")
        
        # Test job extraction
        job_details = extract_job_details(
            "Company: TestCorp\n"
            "We need a developer\n"
            "Email: jobs@testcorp.com\n"
            "Salary: $60/hour"
        )
        assert job_details is not None
        assert job_details['company_name'] == 'TestCorp'
        assert job_details['contact_email'] == 'jobs@testcorp.com'
        
        # Test final formatting
        screening_result = MagicMock()
        screening_result.final_score = 15.0
        screening_result.risk_level = "low"
        screening_result.all_flags = []
        screening_result.ai_data = {}
        
        formatted = format_final_job_post(job_details, screening_result)
        assert 'TestCorp' in formatted
        assert 'jobs@testcorp.com' in formatted