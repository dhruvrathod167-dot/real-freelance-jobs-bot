"""
Start, Rules, and Help Handlers
Provides welcoming, accessible onboarding, transparent community guidelines,
and clear usage instructions for all members.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config import settings
from database.db import get_db_session
from database.crud import get_or_create_user, get_user_by_id
from utils.logger import logger
from utils.rate_limiter import command_rate_limiter
from utils.formatters import (
    COMMUNITY_SAFETY_DISCLAIMER,
    format_my_id_card,
    format_monetization_card,
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start command: greets user, ensures profile exists in DB, shows core menu."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        retry_secs = command_rate_limiter.retry_after(user.id)
        await update.message.reply_text(f"⏳ Please wait {retry_secs}s before sending another command.")
        return

    # Ensure user record exists in database
    async with get_db_session() as session:
        await get_or_create_user(
            session=session,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

    # Support deep linking from group onboarding buttons
    if context.args:
        arg = context.args[0].strip().lower()
        if arg == "verify":
            from handlers.verification import verify_handler
            await verify_handler(update, context)
            return
        elif arg == "rules":
            await rules_handler(update, context)
            return
        elif arg == "submit":
            from handlers.jobs import submit_start
            await submit_start(update, context)
            return

    text = (
        f"👋 <b>Welcome to Real Freelance Jobs</b>\n\n"
        f"This community focuses on legitimate freelance, remote, and contract work opportunities.\n\n"
        f"Before posting or participating, please complete verification to protect the community from fraud.\n\n"
        f"<b>Available Commands:</b>\n"
        f"/verify - Verify your membership profile\n"
        f"/submit - Submit a freelance job for screening\n"
        f"/status - Check your verification status\n"
        f"/appeal - Submit an appeal if restricted or banned\n"
        f"/myid - View your Telegram User ID & Profile\n"
        f"/pricing - View employer services & sponsorship tiers\n"
        f"/report - Report suspicious activity or scams\n"
        f"/rules - Read our community safety rules\n"
        f"/help - Get help and safety tips\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{COMMUNITY_SAFETY_DISCLAIMER}"
    )

    keyboard = [
        [
            InlineKeyboardButton("🛡️ Verify Membership", callback_data="start_verify"),
            InlineKeyboardButton("💼 Submit a Job", callback_data="start_submit"),
        ],
        [
            InlineKeyboardButton("🆔 My Telegram ID", callback_data="view_myid"),
            InlineKeyboardButton("📊 My Status", callback_data="view_status"),
        ],
        [
            InlineKeyboardButton("📜 Community Rules", callback_data="view_rules"),
            InlineKeyboardButton("⭐ Employer Services", callback_data="view_pricing"),
        ]
    ]

    await update.message.reply_text(
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def rules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /rules command: transparent community rules and zero-tolerance policies."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        return

    rules_text = (
        "📜 <b>COMMUNITY RULES & CONDUCT GUIDELINES</b>\n"
        "<i>Legally Freelancing Working Community</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1. <b>Be Respectful & Professional:</b> Treat all members with courtesy. Constructive criticism and professional debates are welcome; toxicity is not.\n\n"
        "2. <b>No Abusive, Insulting or Threatening Language:</b> Personal attacks, hate speech, vulgar slurs, and physical or legal threats will not be tolerated.\n\n"
        "3. <b>No Harassment or Spam:</b> Unsolicited direct messages, promotional spam, bot floods, and repetitive off-topic broadcasting are strictly prohibited.\n\n"
        "4. <b>No Fake Jobs or Misleading Opportunities:</b> Every job listing must represent a real, verifiable client or project.\n\n"
        "5. <b>Zero Upfront Fees:</b> Never ask candidates or freelancers to pay for registration, training, equipment, or starter kits.\n\n"
        "6. <b>No Crypto Deposits or Suspicious Payment Schemes:</b> Transactions requiring crypto deposits, gift cards, or unregulated money transfers are banned.\n\n"
        "7. <b>Never Request Credentials:</b> Asking for OTPs, passwords, bank logins, private keys, or personal identity documents is an immediate permanent ban.\n\n"
        "8. <b>Legitimate Freelance Focus:</b> Keep all group discussions centered on freelance work, client collaboration, tech, rates, and projects.\n\n"
        "9. <b>Strict Enforcement:</b> 1st communication violation results in a <b>4-day restriction</b>. Serious or repeated violations lead to extended restrictions or a permanent ban.\n\n"
        "10. <b>Appeals Process:</b> Permanent bans can only be reconsidered through an official admin review via <code>/appeal &lt;reason&gt;</code> in bot DM.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{COMMUNITY_SAFETY_DISCLAIMER}"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(rules_text, parse_mode="HTML")
    else:
        await update.message.reply_text(rules_text, parse_mode="HTML")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /help command."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        return

    help_text = (
        "💡 <b>REAL FREELANCE JOBS HELP & FAQ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>How do I post a job?</b>\n"
        "1. Complete your one-time verification with /verify.\n"
        "2. Send /submit to launch the job submission assistant.\n"
        "3. Provide required company and role details.\n"
        "4. Automated checks will evaluate the listing. Low-risk posts are approved by moderators and broadcast to our verified channel!\n\n"
        "<b>How does verification work?</b>\n"
        "Use /verify to review and confirm our anti-scam pledges. We create a trust profile based on your Telegram ID.\n\n"
        "<b>How do I report a scammer?</b>\n"
        "Use /report <details> or reply /report to any suspicious message in the group.\n\n"
        "<b>Need admin support?</b>\n"
        "If you have questions regarding a held post or moderation review, contact community moderators.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{COMMUNITY_SAFETY_DISCLAIMER}"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(help_text, parse_mode="HTML")
    else:
        await update.message.reply_text(help_text, parse_mode="HTML")


async def myid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /myid command: displays user Telegram ID, role, and verification details."""
    user = update.effective_user
    chat = update.effective_chat
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        retry = command_rate_limiter.retry_after(user.id)
        msg = f"⏳ Please wait {retry}s."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    async with get_db_session() as session:
        db_user = await get_user_by_id(session, user.id)

    status = db_user.status if db_user else "PENDING"
    risk_score = db_user.risk_score if db_user else 0.0
    is_admin = settings.is_admin(user.id)

    text = format_my_id_card(
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        status=status,
        risk_score=risk_score,
        is_admin=is_admin,
        chat_id=chat.id if chat else user.id,
        chat_type=chat.type if chat else "private",
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def monetization_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /pricing, /sponsor, /premium: displays employer promotion services."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        return

    text = format_monetization_card()

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")

