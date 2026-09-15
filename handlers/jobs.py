"""
Job Submission Conversation Handler
Guides users through submitting a freelance job opening via a 10-step guided wizard,
validates inputs, initiates the automated screening engine, stores the submission,
and routes alerts to administrators.
"""

import html
import warnings
from telegram.warnings import PTBUserWarning
warnings.filterwarnings("ignore", category=PTBUserWarning)

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import settings
from database.db import get_db_session
from database.crud import (
    get_user_by_id,
    create_job_submission,
    flag_user_suspicious,
)
from services.moderation import run_full_security_screening, ModerationDecision
from utils.logger import logger
from utils.rate_limiter import submission_rate_limiter
from utils.formatters import (
    format_admin_job_review,
    get_risk_badge,
    COMMUNITY_SAFETY_DISCLAIMER,
)


async def _delete_temporary_message(message, delay_seconds: int = 10) -> None:
    """Delete a temporary message after specified delay."""
    try:
        await asyncio.sleep(delay_seconds)
        await message.delete()
    except Exception:
        # Ignore errors if message already deleted or chat issues
        pass


async def _safe_background_task(coro, task_name: str = "background_task"):
    """Safely execute a background task without propagating exceptions to the main handler."""
    try:
        await coro
    except Exception as exc:
        logger.error(f"Background task '{task_name}' failed: {exc}")
        # Don't propagate exceptions to the main handler


async def _auto_approve_and_publish_job(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    user,
    draft: dict,
    job_id: int,
    decision
) -> None:
    """Automatically approve and publish a low-risk job to the target group."""
    from handlers.admin import _execute_approval
    
    try:
        # Update job status to APPROVED and publish to group
        await _execute_approval(
            job_id=job_id,
            admin_id=0,  # 0 indicates auto-approval
            context=context,
            reply_target=query.message,
            pending_message=query.message
        )
        
        # Update user response to show successful publication
        user_response = (
            f"🎉 <b>Job Approved & Published!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {get_risk_badge(decision.final_score, decision.risk_level)}\n"
            f"<b>Status:</b> ✅ Live in Community\n\n"
            f"Your job passed all automated security checks and has been published to the community.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )
        
        await query.message.edit_text(user_response, parse_mode="HTML")
        
    except Exception as exc:
        logger.error(f"Auto-approval and publishing failed for job {job_id}: {exc}")
        raise exc

# Conversation States
(
    STATE_COMPANY_NAME,
    STATE_COMPANY_WEBSITE,
    STATE_CONTACT_EMAIL,
    STATE_JOB_TITLE,
    STATE_JOB_DESCRIPTION,
    STATE_PAYMENT_RATE,
    STATE_EXPECTED_WORK,
    STATE_COUNTRY_REGION,
    STATE_APPLICATION_METHOD,
    STATE_ORIGINAL_SOURCE,
    STATE_CONFIRMATION,
) = range(11)


async def submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Initiates job submission workflow after checking user eligibility."""
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    # IMPORTANT: Job submission must ONLY work in private chat with bot
    chat = update.effective_chat
    if chat.type != "private":
        msg = (
            "⚠️ <b>Job Submission in Private Chat Only</b>\n\n"
            "To submit a job, please open a private chat with me (@BotUsername) and use /submit there.\n\n"
            "This ensures your job details remain private until approved by moderators."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    # Check user verification status in DB
    async with get_db_session() as session:
        db_user = await get_user_by_id(session, user.id)

    if not db_user or db_user.status == "PENDING" or not db_user.rules_accepted:
        msg = (
            "⚠️ <b>Verification Required</b>\n\n"
            "You must complete your verification pledge before submitting job postings.\n"
            "Please send /verify to verify your membership in one tap."
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    if db_user.status in ("RESTRICTED", "BANNED"):
        msg = "🚫 <b>Submission Restricted</b>\nYour account is not permitted to post new jobs."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    # Notice for suspicious users
    if db_user.status == "SUSPICIOUS":
        suspicious_notice = (
            "⚠️ <b>Notice: Profile Under Observation</b>\n"
            "<i>Your account currently has elevated risk indicators. "
            "You may proceed, but your submission will be held for manual administrator review.</i>\n\n"
        )
    else:
        suspicious_notice = ""

    # Rate limiting (bypassed for administrators)
    if not settings.is_admin(user.id) and not submission_rate_limiter.is_allowed(user.id):
        msg = "⏳ <b>Rate Limit Reached</b>\nYou have reached the submission limit. Please try again later."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    # Clear previous job draft in context
    context.user_data.clear()
    context.user_data["job_draft"] = {}

    intro_text = (
        "💼 <b>JOB SUBMISSION ASSISTANT (Step 1/10)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please provide the details of your freelance or remote opportunity.\n"
        "<i>You can type /cancel at any point to abort.</i>\n\n"
        "🏢 <b>1. What is the official Company or Client Name?</b>\n"
        "(e.g., <code>Acme Technologies Ltd.</code> or <code>Independent Client - John Doe</code>)"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(intro_text, parse_mode="HTML")
    else:
        await update.message.reply_text(intro_text, parse_mode="HTML")

    return STATE_COMPANY_NAME


async def step_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("❌ Company name is too short. Please enter a valid name:")
        return STATE_COMPANY_NAME

    context.user_data["job_draft"]["company_name"] = text
    await update.message.reply_text(
        "🌐 <b>Step 2/10: Official Company Website</b>\n\n"
        "Please enter the company website URL (e.g., <code>https://example.com</code>).\n"
        "<i>Note: URL shorteners like bit.ly are strictly prohibited.</i>",
        parse_mode="HTML"
    )
    return STATE_COMPANY_WEBSITE


async def step_company_website(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith(("http://", "https://")):
        text = "https://" + text

    context.user_data["job_draft"]["company_website"] = text
    await update.message.reply_text(
        "✉️ <b>Step 3/10: Official Contact Email</b>\n\n"
        "Enter an official business contact email for hiring inquiries\n"
        "(e.g., <code>careers@example.com</code>):",
        parse_mode="HTML"
    )
    return STATE_CONTACT_EMAIL


async def step_contact_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if "@" not in text or "." not in text:
        await update.message.reply_text("❌ Please enter a valid email address (must contain @ and domain):")
        return STATE_CONTACT_EMAIL

    context.user_data["job_draft"]["contact_email"] = text
    await update.message.reply_text(
        "📌 <b>Step 4/10: Job Title</b>\n\n"
        "Enter a descriptive job title (e.g., <code>Senior React Developer</code>, <code>Content Writer - FinTech</code>):",
        parse_mode="HTML"
    )
    return STATE_JOB_TITLE


async def step_job_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) < 3:
        await update.message.reply_text("❌ Job title is too short. Please provide a descriptive title:")
        return STATE_JOB_TITLE

    context.user_data["job_draft"]["job_title"] = text
    await update.message.reply_text(
        "📄 <b>Step 5/10: Complete Job Description</b>\n\n"
        "Provide a comprehensive description of the role, requirements, project goals, and timeline:",
        parse_mode="HTML"
    )
    return STATE_JOB_DESCRIPTION


async def step_job_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) < 20:
        await update.message.reply_text("❌ Description is too brief. Please provide detailed requirements:")
        return STATE_JOB_DESCRIPTION

    context.user_data["job_draft"]["job_description"] = text
    await update.message.reply_text(
        "💰 <b>Step 6/10: Payment & Compensation Rate</b>\n\n"
        "Specify the budget, hourly rate, or fixed milestone amount\n"
        "(e.g., <code>$45 - $60/hr</code>, <code>$2,500 fixed project</code>, or <code>€30/hr</code>).\n"
        "<i>Remember: Legitimate compensation only. No crypto deposit schemes.</i>",
        parse_mode="HTML"
    )
    return STATE_PAYMENT_RATE


async def step_payment_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["job_draft"]["payment_rate"] = text
    await update.message.reply_text(
        "📝 <b>Step 7/10: Expected Deliverables & Work</b>\n\n"
        "Summarize the concrete deliverables expected from the freelancer\n"
        "(e.g., <code>Design 5 landing page prototypes in Figma and deliver assets</code>):",
        parse_mode="HTML"
    )
    return STATE_EXPECTED_WORK


async def step_expected_work(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["job_draft"]["expected_work"] = text
    await update.message.reply_text(
        "🌍 <b>Step 8/10: Country / Region Scope</b>\n\n"
        "Enter geographic requirements (e.g., <code>Remote Worldwide</code>, <code>US / Canada Only</code>, <code>Europe (CET)</code>):",
        parse_mode="HTML"
    )
    return STATE_COUNTRY_REGION


async def step_country_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["job_draft"]["country_region"] = text
    await update.message.reply_text(
        "📬 <b>Step 9/10: Application & Contact Method</b>\n\n"
        "How should qualified candidates apply?\n"
        "(e.g., <code>Send portfolio to careers@example.com with subject #ReactDev</code> or <code>Apply via company career portal: https://example.com/jobs</code>):",
        parse_mode="HTML"
    )
    return STATE_APPLICATION_METHOD


async def step_application_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["job_draft"]["application_method"] = text
    await update.message.reply_text(
        "🔗 <b>Step 10/10: Original Source (Optional)</b>\n\n"
        "If this job was originally published on a public board (LinkedIn, Wellfound, GitHub), share the link.\n"
        "Otherwise, type <code>Direct</code> or <code>None</code>:",
        parse_mode="HTML"
    )
    return STATE_ORIGINAL_SOURCE


async def step_original_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["job_draft"]["original_source"] = text if text.lower() not in ("none", "direct") else None

    draft = context.user_data["job_draft"]

    # Preview summary before final screening
    preview_card = (
        "📋 <b>JOB SUBMISSION PREVIEW</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏢 <b>Company:</b> {html.escape(draft['company_name'])}\n"
        f"🌐 <b>Website:</b> {html.escape(draft['company_website'])}\n"
        f"✉️ <b>Email:</b> {html.escape(draft['contact_email'])}\n"
        f"📌 <b>Title:</b> {html.escape(draft['job_title'])}\n"
        f"💰 <b>Rate:</b> {html.escape(draft['payment_rate'])}\n"
        f"🌍 <b>Region:</b> {html.escape(draft['country_region'])}\n"
        f"📬 <b>Apply:</b> {html.escape(draft['application_method'])}\n\n"
        f"📝 <b>Deliverables:</b>\n{html.escape(draft['expected_work'])}\n\n"
        f"📄 <b>Description:</b>\n{html.escape(draft['job_description'][:300])}...\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Click 'Submit for Screening' to run automated fraud checks.</i>"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 Submit for Screening", callback_data="confirm_job_submission")],
        [InlineKeyboardButton("❌ Cancel Submission", callback_data="cancel_job_submission")]
    ]

    await update.message.reply_text(
        preview_card,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_CONFIRMATION


async def confirm_job_submission_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Runs automated security screening and stores job submission."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    draft = context.user_data.get("job_draft")

    if not draft or not user:
        await query.message.edit_text("❌ Submission session expired. Please send /submit again.")
        return ConversationHandler.END

    # IMMEDIATE ACKNOWLEDGMENT - Don't block while running checks
    acknowledgment_msg = (
        "✅ <b>Job Submission Received!</b>\n\n"
        "🔍 Your submission is being screened for security and quality checks.\n"
        "You'll receive a notification once the review is complete."
    )
    acknowledgment_msg_obj = await query.message.edit_text(acknowledgment_msg, parse_mode="HTML")
    
    # Schedule auto-delete of acknowledgment message after 10 seconds
    asyncio.create_task(_safe_background_task(
        _delete_temporary_message(acknowledgment_msg_obj, 10),
        "acknowledgment_message_delete"
    ))

    # Run automated screening pipeline asynchronously
    try:
        decision = await run_full_security_screening(
            company_name=draft["company_name"],
            company_website=draft["company_website"],
            contact_email=draft["contact_email"],
            job_title=draft["job_title"],
            job_description=draft["job_description"],
            payment_rate=draft["payment_rate"],
            expected_work=draft["expected_work"],
            country_region=draft["country_region"],
            application_method=draft["application_method"],
        )
    except Exception as exc:
        logger.error(f"Security screening failed for job: {exc}")
        # Fall back to manual review on any error
        decision = ModerationDecision(
            final_score=25.0,
            risk_level="review",
            action="hold_review",
            all_flags=["System error during automated screening"],
            reasons=["Automated checks failed, requiring manual review"],
            ai_data={},
            website_data={}
        )

    # Persist job to database
    async with get_db_session() as session:
        job = await create_job_submission(
            session=session,
            user_id=user.id,
            company_name=draft["company_name"],
            company_website=draft["company_website"],
            contact_email=draft["contact_email"],
            job_title=draft["job_title"],
            job_description=draft["job_description"],
            payment_rate=draft["payment_rate"],
            expected_work=draft["expected_work"],
            country_region=draft["country_region"],
            application_method=draft["application_method"],
            original_source=draft.get("original_source"),
            risk_score=decision.final_score,
            risk_level=decision.risk_level,
            detected_flags=decision.all_flags,
            ai_analysis=decision.ai_data,
            status="PENDING_REVIEW"
        )
        job_id = job.id

        # If elevated or high risk detected, automatically flag user profile as SUSPICIOUS
        if decision.final_score >= 50.0:
            await flag_user_suspicious(
                session=session,
                user_id=user.id,
                reason=f"Elevated risk on Job #{job_id}: {', '.join(decision.all_flags[:2]) if decision.all_flags else 'Elevated score'}",
                risk_score=decision.final_score,
                actor_id=0  # 0 indicates automated system action
            )

    badge = get_risk_badge(decision.final_score, decision.risk_level)

    # AUTOMATIC APPROVAL FOR LOW_RISK JOBS
    if decision.action == "queue" and decision.risk_level == "low":
        # Automatically approve and publish LOW_RISK jobs
        try:
            await _auto_approve_and_publish_job(context, query, user, draft, job_id, decision)
            return ConversationHandler.END
        except Exception as exc:
            logger.error(f"Auto-approval failed for job {job_id}: {exc}")
            # Fall back to manual review
            decision.action = "hold_review"
    
    # Alert administrators only for REVIEW_REQUIRED or HIGH_RISK jobs
    if decision.action in ["hold_review", "block_review"]:
        admin_review_card = format_admin_job_review(
            job_id=job_id,
            user_id=user.id,
            username=user.username,
            company_name=draft["company_name"],
            job_title=draft["job_title"],
            payment_rate=draft["payment_rate"],
            country_region=draft["country_region"],
            company_website=draft["company_website"],
            contact_email=draft["contact_email"],
            application_method=draft["application_method"],
            expected_work=draft["expected_work"],
            job_description=draft["job_description"],
            risk_score=decision.final_score,
            risk_level=decision.risk_level,
            detected_flags=decision.all_flags,
            ai_reasons=decision.reasons,
        )

        admin_keyboard = [
            [
                InlineKeyboardButton("✅ Approve & Publish", callback_data=f"adm_approve_{job_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{job_id}"),
            ],
            [
                InlineKeyboardButton("⭐ Feature", callback_data=f"adm_feature_{job_id}"),
                InlineKeyboardButton("💎 Sponsor", callback_data=f"adm_sponsor_{job_id}"),
            ],
            [
                InlineKeyboardButton("⚠️ Flag Suspicious", callback_data=f"adm_suspicious_{user.id}"),
                InlineKeyboardButton("🚫 Ban Poster", callback_data=f"adm_ban_{user.id}"),
            ]
        ]

        for admin_id in settings.admin_id_list:
            try:
                sent_admin_msg = await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_review_card,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(admin_keyboard)
                )
                from handlers.admin import record_pending_moderation_message
                record_pending_moderation_message(job_id=job_id, chat_id=admin_id, message_id=sent_admin_msg.message_id)
            except Exception as exc:
                logger.warning(f"Could not deliver admin review alert to admin {admin_id}: {exc}")

    # Respond to user based on screening action
    if decision.action == "queue":
        user_response = (
            f"✅ <b>Job Received & Pre-Screened Successfully!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {badge}\n"
            f"<b>Status:</b> ⏳ Moderation Queue\n\n"
            f"Your job passed automated security checks with low risk indicators. "
            f"A moderator will review and broadcast it to the verified community shortly.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )
    elif decision.action == "hold_review":
        flags_text = "\n".join([f"• {html.escape(f)}" for f in decision.all_flags]) if decision.all_flags else "Standard safety review"
        user_response = (
            f"ℹ️ <b>Job Received - Verification Hold</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {badge}\n"
            f"<b>Status:</b> 🔍 Pending Manual Verification\n\n"
            f"Our automated security system detected one or more risk indicators:\n"
            f"<i>{flags_text}</i>\n\n"
            f"A community moderator will manually review the listing. "
            f"If verified, your opportunity will be approved for publication.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )
    else:  # block_review
        flags_text = "\n".join([f"• {html.escape(f)}" for f in decision.all_flags]) if decision.all_flags else "High security risk indicators detected"
        user_response = (
            f"⚠️ <b>Publication Blocked - Elevated Risk Indicators</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {badge}\n"
            f"<b>Status:</b> 🛑 Held for Administrative Investigation\n\n"
            f"The automated screening engine identified several high-risk indicators:\n"
            f"<i>{flags_text}</i>\n\n"
            f"To protect community members, publication has been blocked pending manual review. "
            f"If you believe this detection was triggered in error, please contact community moderators.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )

    # Respond to user based on screening action
    if decision.action == "queue":
        # This case is now handled by auto-approval above
        user_response = (
            f"🎉 <b>Job Approved & Published!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {badge}\n"
            f"<b>Status:</b> ✅ Live in Community\n\n"
            f"Your job passed all automated security checks and has been published to the community.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )
    elif decision.action == "hold_review":
        flags_text = "\n".join([f"• {html.escape(f)}" for f in decision.all_flags]) if decision.all_flags else "Standard safety review"
        user_response = (
            f"ℹ️ <b>Job Received - Verification Hold</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {badge}\n"
            f"<b>Status:</b> 🔍 Pending Manual Verification\n\n"
            f"Our automated security system detected one or more risk indicators:\n"
            f"<i>{flags_text}</i>\n\n"
            f"A community moderator will manually review the listing. "
            f"If verified, your opportunity will be approved for publication.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )
    else:  # block_review
        flags_text = "\n".join([f"• {html.escape(f)}" for f in decision.all_flags]) if decision.all_flags else "High security risk indicators detected"
        user_response = (
            f"⚠️ <b>Publication Blocked - Elevated Risk Indicators</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job ID:</b> #{job_id}\n"
            f"<b>Risk Assessment:</b> {badge}\n"
            f"<b>Status:</b> 🛑 Held for Administrative Investigation\n\n"
            f"The automated screening engine identified several high-risk indicators:\n"
            f"<i>{flags_text}</i>\n\n"
            f"To protect community members, publication has been blocked pending manual review. "
            f"If you believe this detection was triggered in error, please contact community moderators.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )

    await query.message.edit_text(user_response, parse_mode="HTML")
    context.user_data.clear()
    submission_rate_limiter.reset(user.id)
    return ConversationHandler.END


async def cancel_job_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels ongoing job submission."""
    context.user_data.clear()
    if update.effective_user:
        submission_rate_limiter.reset(update.effective_user.id)
    msg = "Submission cancelled. You can restart anytime using /submit."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg)
    else:
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# Build ConversationHandler for /submit
job_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("submit", submit_start),
        CallbackQueryHandler(submit_start, pattern="^start_submit$"),
    ],
    states={
        STATE_COMPANY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_company_name)],
        STATE_COMPANY_WEBSITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_company_website)],
        STATE_CONTACT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_contact_email)],
        STATE_JOB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_job_title)],
        STATE_JOB_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_job_description)],
        STATE_PAYMENT_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_payment_rate)],
        STATE_EXPECTED_WORK: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_expected_work)],
        STATE_COUNTRY_REGION: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_country_region)],
        STATE_APPLICATION_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_application_method)],
        STATE_ORIGINAL_SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_original_source)],
        STATE_CONFIRMATION: [
            CallbackQueryHandler(confirm_job_submission_callback, pattern="^confirm_job_submission$"),
            CallbackQueryHandler(cancel_job_submission, pattern="^cancel_job_submission$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_job_submission),
        CallbackQueryHandler(cancel_job_submission, pattern="^cancel_job_submission$"),
    ],
    allow_reentry=True,
    per_message=False,
)
