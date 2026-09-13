"""
User Verification Handler
Guides users through the anti-scam commitment checklist,
creates a persistent verification profile keyed by Telegram ID,
and displays account status and risk indicators.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from telegram.ext import ContextTypes
from config import settings
from database.db import get_db_session
from database.crud import (
    get_or_create_user,
    get_user_by_id,
    confirm_user_rules,
)
from utils.logger import logger
from utils.rate_limiter import command_rate_limiter
from utils.formatters import (
    format_user_verification_status,
    COMMUNITY_SAFETY_DISCLAIMER,
)


async def verify_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Presents the verification anti-scam checklist to the user."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        retry_secs = command_rate_limiter.retry_after(user.id)
        msg = f"⏳ Please wait {retry_secs}s before sending another request."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    # Fetch user status
    async with get_db_session() as session:
        db_user = await get_or_create_user(
            session=session,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

        if db_user.status == "BANNED":
            reply = "🚫 <b>Account Banned</b>\nYour account has been restricted from participating due to safety violations."
            if update.callback_query:
                await update.callback_query.message.reply_text(reply, parse_mode="HTML")
            else:
                await update.message.reply_text(reply, parse_mode="HTML")
            return

        if db_user.status == "SUSPICIOUS":
            reply = (
                "⚠️ <b>Account Under Observation (Suspicious Signals)</b>\n"
                "Your account was previously flagged for elevated risk indicators.\n"
                "Any job postings you submit will be held for strict administrative verification."
            )
            if update.callback_query:
                await update.callback_query.message.reply_text(reply, parse_mode="HTML")
            else:
                await update.message.reply_text(reply, parse_mode="HTML")
            return

        if db_user.status == "VERIFIED" and db_user.rules_accepted:
            reply = (
                "✅ <b>Already Verified</b>\n"
                "Your account is verified and in good standing. You can submit legitimate job postings using /submit."
            )
            if update.callback_query:
                await update.callback_query.message.reply_text(reply, parse_mode="HTML")
            else:
                await update.message.reply_text(reply, parse_mode="HTML")
            return

    checklist_text = (
        "🛡️ <b>COMMUNITY VERIFICATION PLEDGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "To protect freelancers from fraudulent schemes, all posters must explicitly confirm adherence to our safety standards.\n\n"
        "<b>Please confirm that you agree:</b>\n"
        "1. ❌ <b>NO Upfront Fees:</b> You will NEVER charge applicants for registration, equipment, training, or software.\n"
        "2. ❌ <b>NO Crypto Deposits:</b> You will NOT request payments or security deposits via USDT, TRC20, BNB, or gift cards.\n"
        "3. ❌ <b>NO Credential Phishing:</b> You will NEVER request OTPs, passwords, private keys, seed phrases, or credit card numbers.\n"
        "4. ❌ <b>NO Fake Opportunities:</b> You will only submit verifiable freelance or remote roles with real compensation.\n\n"
        "<i>Note: Telegram account existence alone is not proof of identity. All job submissions undergo automated security risk screening.</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{COMMUNITY_SAFETY_DISCLAIMER}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ I Agree & Confirm All Terms", callback_data="confirm_verify_pledge")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_verify")]
    ]

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            checklist_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            checklist_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def confirm_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the user clicking 'I Agree & Confirm All Terms'."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user = update.effective_user
    if not user:
        return

    async with get_db_session() as session:
        db_user = await confirm_user_rules(session, user.id)

    # Lift chat restrictions across configured and known community groups
    target_chats = set()
    if settings.TELEGRAM_GROUP_ID:
        try:
            target_chats.add(int(settings.TELEGRAM_GROUP_ID))
        except ValueError:
            pass
    from handlers.group import KNOWN_COMMUNITY_CHATS
    target_chats.update(KNOWN_COMMUNITY_CHATS)

    for chat_id in target_chats:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )
            )
            logger.info(f"Lifted group restrictions for newly verified user {user.id} in {chat_id}")
        except Exception as exc:
            logger.debug(f"Could not unrestrict user {user.id} in group {chat_id}: {exc}")

    success_text = (
        "🎉 <b>Verification Successful!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Status:</b> ✅ Verified Member\n"
        f"<b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"<b>Account Risk Rating:</b> Low Risk (0/100)\n\n"
        f"<b>Next Action:</b>\n"
        f"You are now verified and authorized to participate in <b>{settings.TELEGRAM_GROUP_NAME}</b>!\n\n"
        f"• You may share freelance job opportunities directly in the group (screened in real time for safety).\n"
        f"• You can also use <b>/submit</b> to submit a freelance job for automated AI risk screening and moderator review.\n\n"
        f"<i>Safety Reminder: Verification confirms commitment to community rules. We NEVER claim that any person, company, or job is 100% genuine or legally verified. Never pay upfront fees or provide credentials.</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{COMMUNITY_SAFETY_DISCLAIMER}"
    )

    keyboard = [
        [InlineKeyboardButton("📝 Submit a Freelance Job (/submit)", callback_data="start_submit")]
    ]

    await query.message.edit_text(
        success_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cancel_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles cancellation of verification."""
    query = update.callback_query
    if not query:
        return
    await query.answer("Verification cancelled.")
    await query.message.edit_text(
        "Verification was cancelled. You may restart at any time with /verify.",
        parse_mode="HTML"
    )


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /status command: retrieves user's profile and shows current standing."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        retry = command_rate_limiter.retry_after(user.id)
        await update.message.reply_text(f"⏳ Please wait {retry}s.")
        return

    async with get_db_session() as session:
        db_user = await get_user_by_id(session, user.id)

    if not db_user:
        text = (
            "You have not registered a profile yet.\n"
            "Please send /start or /verify to begin."
        )
    else:
        text = format_user_verification_status(
            user_id=db_user.id,
            status=db_user.status,
            risk_score=db_user.risk_score,
            submission_count=db_user.submission_count,
            flag_notes=db_user.flag_notes,
        )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")
