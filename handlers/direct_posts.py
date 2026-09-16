"""
Direct Job Post Handler
Handles direct job posts in the group "Legally Freelancing Working".
Implements temporary message notifications, job verification, and cleanup.
"""

import asyncio
import html
import re
from datetime import datetime, timezone, date
from typing import Dict, Optional, Tuple
from telegram import Update, Message, Chat, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import settings
from database.db import get_db_session
from database.crud import (
    get_or_create_user,
    create_job_submission,
    create_audit_entry,
    flag_user_suspicious,
    get_verification_message_count,
    create_verification_message,
)
from services.moderation import run_full_security_screening
from utils.logger import logger
from handlers.jobs import _safe_background_task, _delete_temporary_message

# Keywords indicating direct job posting attempts
JOB_POSTING_SIGNALS = [
    r"\b(hiring|we are looking for|job opening|apply now|dm me for work)\b",
    r"\b(earn \$|salary:|pay:|hourly rate|work from home opportunity)\b",
    r"\b(freelancers needed|looking for developer|looking for designer|need a writer)\b",
    r"\b(job alert|remote job|freelance role|contract work|paying \$)\b",
    r"\b(seek|need|require|opportunity|position|vacancy)\b",
    r"\b(contact me|dm for details|send cv|resume|portfolio)\b",
    r"\b(payment|compensation|budget|fee|salary)\b",
]

# Owner and Admin IDs that should be protected
PROTECTED_USER_IDS = {settings.owner_id}.union(set(settings.admin_id_list or []))


async def handle_direct_job_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles direct job posts in the group.
    1. Creates temporary notification message
    2. Extracts job details from the post
    3. Runs security screening
    4. Takes action based on risk level
    5. Cleans up temporary messages
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not chat or chat.type not in ("group", "supergroup") or not message or not user:
        return

    # Skip if user is bot
    if user.is_bot:
        return

    # Check if this is actually a job post
    text = (message.text or message.caption or "").strip()
    if not text or not is_direct_job_post(text):
        return

    # Check if user is protected (owner/admin)
    if user.id in PROTECTED_USER_IDS:
        logger.info(f"Skipping direct job post moderation for protected user {user.id}")
        return

    # Create temporary notification message
    temp_message = await create_temporary_notification(update, context)
    if not temp_message:
        return

    # Schedule cleanup of temporary message after 5 seconds
    asyncio.create_task(_safe_background_task(
        _delete_temporary_message(temp_message, 5),
        "direct_post_temp_message_cleanup"
    ))

    # Extract job details from the post
    job_details = extract_job_details(text)
    if not job_details:
        logger.warning(f"Could not extract job details from post by {user.id}")
        return

    # Run security screening in background
    asyncio.create_task(_safe_background_task(
        process_direct_job_post(update, context, temp_message, job_details),
        "direct_job_post_screening"
    ))


def is_direct_job_post(text: str) -> bool:
    """Check if the message contains job posting signals."""
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in JOB_POSTING_SIGNALS)


def extract_job_details(text: str) -> Optional[Dict[str, str]]:
    """Extract basic job details from a direct post."""
    try:
        # Simple extraction - in production, this would be more sophisticated
        lines = text.split('\n')
        
        job_details = {
            'company_name': 'Unknown Company',
            'company_website': '',
            'contact_email': '',
            'job_title': '',
            'job_description': text,
            'payment_rate': '',
            'expected_work': '',
            'country_region': 'Unknown',
            'application_method': '',
            'original_source': 'direct_post'
        }

        # Try to extract company name (look for company mentions)
        for line in lines:
            if any(keyword in line.lower() for keyword in ['company', 'organization', 'firm']):
                # Clean up the company name by removing the prefix
                if line.lower().startswith('company:'):
                    job_details['company_name'] = line.replace('Company:', '').strip()
                else:
                    job_details['company_name'] = line.strip()
                break

        # Try to extract job title
        for line in lines:
            if any(keyword in line.lower() for keyword in ['developer', 'designer', 'writer', 'manager', 'engineer']):
                job_details['job_title'] = line.strip()
                break

        # Try to extract contact information
        for line in lines:
            if '@' in line and '.' in line:
                # Clean up the email by removing any prefix
                if line.lower().startswith('email:'):
                    job_details['contact_email'] = line.replace('Email:', '').replace('email:', '').strip()
                else:
                    job_details['contact_email'] = line.strip()
                break

        # Try to extract payment rate
        for line in lines:
            if any(keyword in line.lower() for keyword in ['salary:', 'pay:', 'hourly rate:', '$', 'compensation:']):
                if line.lower().startswith('salary:'):
                    job_details['payment_rate'] = line.replace('Salary:', '').strip()
                elif line.lower().startswith('pay:'):
                    job_details['payment_rate'] = line.replace('Pay:', '').strip()
                else:
                    job_details['payment_rate'] = line.strip()
                break

        # Return None for empty text
        if not text.strip():
            return None

        return job_details
    except Exception as exc:
        logger.error(f"Error extracting job details: {exc}")
        return None


async def create_temporary_notification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[Message]:
    """Create temporary notification message for direct job post."""
    try:
        user = update.effective_user
        user_mention = f"@{user.username}" if user.username else html.escape(user.first_name)
        
        notification_text = (
            f"⚠️ Direct Job Post Detected\n\n"
            f"👤 Posted by: {user_mention}\n"
            f"🔍 Job and company are being checked.\n\n"
            f"Please submit jobs through @{settings.BOT_USERNAME} for faster verification."
        )

        temp_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=notification_text,
            parse_mode="HTML"
        )
        
        logger.info(f"Created temporary notification for direct job post by {user.id}")
        return temp_message
        
    except TelegramError as exc:
        logger.error(f"Failed to create temporary notification: {exc}")
        return None


async def process_direct_job_post(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    temp_message: Message,
    job_details: Dict[str, str]
) -> None:
    """
    Process direct job post with full security screening.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    try:
        # Run full security screening
        screening_result = await run_full_security_screening(
            company_name=job_details['company_name'],
            company_website=job_details['company_website'],
            contact_email=job_details['contact_email'],
            job_title=job_details['job_title'],
            job_description=job_details['job_description'],
            payment_rate=job_details['payment_rate'],
            expected_work=job_details['expected_work'],
            country_region=job_details['country_region'],
            application_method=job_details['application_method'],
        )

        # Determine action based on risk level
        if screening_result.risk_level == "low":
            await handle_low_risk_job(update, context, message, temp_message, job_details, screening_result)
        elif screening_result.risk_level == "review":
            await handle_review_required_job(update, context, message, temp_message, job_details, screening_result)
        else:  # high or very_high
            await handle_high_risk_job(update, context, message, temp_message, screening_result)

    except Exception as exc:
        logger.error(f"Error processing direct job post: {exc}")
        # Clean up temp message on error
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_error_cleanup"
        ))


async def handle_low_risk_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    original_message: Message,
    temp_message: Message,
    job_details: Dict[str, str],
    screening_result
) -> None:
    """Handle LOW_RISK direct job post - allow it to remain as final job post."""
    
    chat = update.effective_chat
    user = update.effective_user

    try:
        # Create job submission in database
        async with get_db_session() as session:
            db_user = await get_or_create_user(
                session=session,
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
            )

            job = await create_job_submission(
                session=session,
                user_id=user.id,
                company_name=job_details['company_name'],
                company_website=job_details['company_website'],
                contact_email=job_details['contact_email'],
                job_title=job_details['job_title'],
                job_description=job_details['job_description'],
                payment_rate=job_details['payment_rate'],
                expected_work=job_details['expected_work'],
                country_region=job_details['country_region'],
                application_method=job_details['application_method'],
                original_source="direct_post",
                risk_score=screening_result.final_score,
                risk_level=screening_result.risk_level,
                detected_flags=screening_result.all_flags,
                ai_analysis=screening_result.ai_data,
            )

            # Create audit entry
            await create_audit_entry(
                session=session,
                actor_id=user.id,
                action="DIRECT_JOB_POST_APPROVED",
                target_type="JOB",
                target_id=str(job.id),
                details=f"Direct job post approved (LOW_RISK): {job_details['job_title']}"
            )

        # Format final job post
        final_job_text = format_final_job_post(job_details, screening_result)
        
        # Edit original message to show approved job post
        try:
            await original_message.edit_text(
                final_job_text,
                parse_mode="HTML"
            )
            logger.info(f"Approved direct job post #{job.id} by {user.id}")
        except TelegramError:
            # If we can't edit, create a new message
            await context.bot.send_message(
                chat_id=chat.id,
                text=final_job_text,
                parse_mode="HTML"
            )

        # Clean up temporary message
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_low_risk_cleanup"
        ))

    except Exception as exc:
        logger.error(f"Error handling low-risk job: {exc}")
        # Clean up temp message on error
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_low_risk_error_cleanup"
        ))


async def handle_review_required_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    original_message: Message,
    temp_message: Message,
    job_details: Dict[str, str],
    screening_result
) -> None:
    """Handle REVIEW_REQUIRED direct job post - remove and send to admin."""
    
    chat = update.effective_chat
    user = update.effective_user

    try:
        # Remove original message
        await original_message.delete()
        logger.info(f"Removed REVIEW_REQUIRED direct job post by {user.id}")

        # Create job submission in database for admin review
        async with get_db_session() as session:
            db_user = await get_or_create_user(
                session=session,
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
            )

            job = await create_job_submission(
                session=session,
                user_id=user.id,
                company_name=job_details['company_name'],
                company_website=job_details['company_website'],
                contact_email=job_details['contact_email'],
                job_title=job_details['job_title'],
                job_description=job_details['job_description'],
                payment_rate=job_details['payment_rate'],
                expected_work=job_details['expected_work'],
                country_region=job_details['country_region'],
                application_method=job_details['application_method'],
                original_source="direct_post",
                risk_score=screening_result.final_score,
                risk_level=screening_result.risk_level,
                detected_flags=screening_result.all_flags,
                ai_analysis=screening_result.ai_data,
            )

            # Create audit entry
            await create_audit_entry(
                session=session,
                actor_id=user.id,
                action="DIRECT_JOB_POST_REVIEW_REQUIRED",
                target_type="JOB",
                target_id=str(job.id),
                details=f"Direct job post requires manual review: {job_details['job_title']}"
            )

            # Send to admin for review
            admin_text = (
                f"📋 <b>Direct Job Post Requires Manual Review</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Posted by:</b> {user.username or user.first_name} (<code>{user.id}</code>)\n"
                f"💬 <b>Original Post:</b>\n"
                f"<code>{html.escape(job_details['job_description'][:500])}</code>\n\n"
                f"📊 <b>Risk Assessment:</b>\n"
                f"• Score: {screening_result.final_score:.1f}/100\n"
                f"• Level: {screening_result.risk_level.upper()}\n"
                f"• Flags: {', '.join(screening_result.all_flags[:3]) if screening_result.all_flags else 'None'}\n\n"
                f"🔍 <b>Job Details:</b>\n"
                f"• Company: {job_details['company_name']}\n"
                f"• Title: {job_details['job_title']}\n"
                f"• Contact: {job_details['contact_email']}\n\n"
                f"Use /approve {job.id} to publish this job."
            )

            for admin_id in settings.admin_id_list:
                if admin_id != user.id:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_text,
                            parse_mode="HTML"
                        )
                    except TelegramError:
                        pass

        # Clean up temporary message
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_review_cleanup"
        ))

    except Exception as exc:
        logger.error(f"Error handling review-required job: {exc}")
        # Clean up temp message on error
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_review_error_cleanup"
        ))


async def handle_high_risk_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    original_message: Message,
    temp_message: Message,
    screening_result
) -> None:
    """Handle HIGH_RISK direct job post - remove and ban user."""
    
    chat = update.effective_chat
    user = update.effective_user

    try:
        # Remove original message
        await original_message.delete()
        logger.info(f"Removed HIGH_RISK direct job post by {user.id}")

        # Flag user as suspicious
        async with get_db_session() as session:
            await flag_user_suspicious(
                session=session,
                user_id=user.id,
                reason=f"High-risk direct job post: {', '.join(screening_result.all_flags)}",
                actor_id=0
            )

            # Create audit entry
            await create_audit_entry(
                session=session,
                actor_id=0,  # System action
                action="DIRECT_JOB_POST_REJECTED_HIGH_RISK",
                target_type="USER",
                target_id=str(user.id),
                details=f"High-risk direct job post removed: {', '.join(screening_result.all_flags)}"
            )

        # Ban user from chat
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            logger.info(f"Banned user {user.id} for high-risk direct job post")
        except TelegramError:
            pass

        # Send community safety alert
        group_notice = (
            f"🚨 <b>Community Safety Alert</b>\n"
            f"A suspicious job post was removed and the poster has been restricted:\n"
            f"• Risk Score: {screening_result.final_score:.1f}/100\n"
            f"• Detected Issues: {', '.join(screening_result.all_flags[:2]) if screening_result.all_flags else 'Suspicious content'}\n\n"
            f"🛡️ <i>Community Rule: {chat.title or settings.TELEGRAM_GROUP_NAME} strictly prohibits suspicious job postings.</i>"
        )
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=group_notice,
                parse_mode="HTML"
            )
        except TelegramError:
            pass

        # Clean up temporary message
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_high_risk_cleanup"
        ))

    except Exception as exc:
        logger.error(f"Error handling high-risk job: {exc}")
        # Clean up temp message on error
        asyncio.create_task(_safe_background_task(
            _delete_temporary_message(temp_message, 1),
            "direct_post_high_risk_error_cleanup"
        ))


def format_final_job_post(job_details: Dict[str, str], screening_result) -> str:
    """Format the final approved job post."""
    return (
        f"📋 <b>{job_details['job_title']}</b>\n\n"
        f"🏢 <b>{job_details['company_name']}</b>\n"
        f"💼 {job_details['expected_work']}\n"
        f"💰 {job_details['payment_rate']}\n"
        f"🌐 {job_details['country_region']}\n"
        f"📧 {job_details['contact_email']}\n\n"
        f"📝 {job_details['job_description']}\n\n"
        f"🔗 Apply through: {job_details['application_method']}\n\n"
        f"<i>Posted directly in group. Verified for security screening.</i>"
    )


async def should_send_verification_message(user_id: int) -> bool:
    """Check if verification message should be sent based on monthly limit."""
    try:
        current_date = datetime.now(timezone.utc)
        calendar_month = current_date.year * 100 + current_date.month
        
        async with get_db_session() as session:
            count = await get_verification_message_count(
                session=session,
                user_id=user_id,
                message_type="welcome",
                calendar_month=calendar_month
            )
            
            # Maximum 3 verification messages per calendar month
            return count < 3
            
    except Exception as exc:
        logger.error(f"Error checking verification message count: {exc}")
        return False


async def send_verification_message_if_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send verification message only if within monthly limit."""
    user = update.effective_user
    if not user or user.is_bot:
        return

    # Check if verification message should be sent
    if not await should_send_verification_message(user.id):
        logger.info(f"Skipping verification message for {user.id} - monthly limit reached")
        return

    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return

    # Send verification message
    try:
        user_mention = f"@{user.username}" if user.username else html.escape(user.first_name)
        group_title = html.escape(chat.title or settings.TELEGRAM_GROUP_NAME)

        verification_text = (
            f"👋 Welcome to <b>{group_title}</b>, {user_mention}!\n\n"
            f"🛡️ <b>Account Verification Required</b>\n"
            f"Please verify your account with @{settings.BOT_USERNAME} before posting or submitting freelance jobs.\n\n"
            f"To protect our community from fraudulent schemes, upfront fees, and unverified solicitations, "
            f"all new members must complete our quick verification pledge.\n\n"
            f"👉 <b>Tap the button below to verify your account with the bot:</b>"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Verify Account", url=f"https://t.me/{settings.BOT_USERNAME}?start=verify")],
            [InlineKeyboardButton("📖 Safety Rules", url=f"https://t.me/{settings.BOT_USERNAME}?start=rules")]
        ]

        await context.bot.send_message(
            chat_id=chat.id,
            text=verification_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Track this verification message
        current_date = datetime.now(timezone.utc)
        calendar_month = current_date.year * 100 + current_date.month
        
        async with get_db_session() as session:
            await create_verification_message(
                session=session,
                user_id=user.id,
                message_type="welcome",
                calendar_month=calendar_month
            )

        logger.info(f"Sent verification message to {user.id}")

    except Exception as exc:
        logger.error(f"Error sending verification message: {exc}")