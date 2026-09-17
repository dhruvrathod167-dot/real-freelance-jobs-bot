"""
Ban & Restriction Appeal Handler
Provides /appeal command in private bot chat for restricted or banned members
to submit formal reconsideration requests to administrators.
"""

import asyncio
import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import settings
from database.db import get_db_session
from database.crud import (
    get_user_by_id,
    get_active_user_appeal,
    create_appeal,
)
from utils.rate_limiter import command_rate_limiter
from utils.logger import logger


async def appeal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /appeal [statement] command."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    try:
        if not asyncio.run(command_rate_limiter.is_allowed(user.id)):
            retry_secs = command_rate_limiter.retry_after(user.id)
            await update.message.reply_text(f"⏳ Please wait {retry_secs}s before sending another command.")
            return
    except RuntimeError:
        # We're already in an event loop, check synchronously
        if not command_rate_limiter.is_allowed(user.id):
            retry_secs = command_rate_limiter.retry_after(user.id)
            await update.message.reply_text(f"⏳ Please wait {retry_secs}s before sending another command.")
            return

    # Check if called in a group
    if chat.type != "private":
        try:
            await update.message.reply_text(
                f"ℹ️ Appeals must be submitted via private DM with @{settings.BOT_USERNAME}. Send /appeal in private chat.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    async with get_db_session() as session:
        db_user = await get_user_by_id(session, user.id)
        if not db_user:
            await update.message.reply_text(
                "❌ Profile not found. Please send /verify to register your account.",
                parse_mode="HTML"
            )
            return

        # Check if user actually has penalties
        if db_user.status not in ("BANNED", "RESTRICTED"):
            await update.message.reply_text(
                "ℹ️ <b>No Active Penalties</b>\n\n"
                "Your account is in good standing. You do not currently have any active bans or restrictions.",
                parse_mode="HTML"
            )
            return

        # Check if an appeal is already pending
        existing_appeal = await get_active_user_appeal(session, user.id)
        if existing_appeal:
            await update.message.reply_text(
                f"⏳ <b>Appeal Pending Review (ID #{existing_appeal.id})</b>\n\n"
                f"You already have a pending appeal awaiting administrator consideration. "
                f"Please allow our moderation team time to review your case.",
                parse_mode="HTML"
            )
            return

        # Check for statement text
        statement = " ".join(context.args).strip() if context.args else None

        if not statement:
            penalty_reason = db_user.ban_reason or db_user.restriction_reason or "Community policy violation"
            prompt_text = (
                "⚖️ <b>COMMUNITY MODERATION APPEAL</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Account Status:</b> {db_user.status}\n"
                f"<b>Recorded Reason:</b> {html.escape(penalty_reason)}\n\n"
                "To submit a formal reconsideration request to our administrators, please provide a clear explanation:\n\n"
                "<code>/appeal &lt;Explain why your restriction or ban should be lifted&gt;</code>"
            )
            await update.message.reply_text(prompt_text, parse_mode="HTML")
            return

        if len(statement) < 10:
            await update.message.reply_text(
                "❌ Please provide a more detailed explanation (at least 10 characters) explaining why your penalty should be reconsidered."
            )
            return

        # Store appeal in database
        appeal = await create_appeal(session, user_id=user.id, appeal_text=statement)

    # Confirm to user
    confirm_text = (
        f"✅ <b>Appeal Submitted Successfully (ID #{appeal.id})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Your appeal has been forwarded to community administrators for formal review.\n"
        f"You will receive an automated notification here once a decision has been reached."
    )
    await update.message.reply_text(confirm_text, parse_mode="HTML")

    # Alert administrators
    admin_card = (
        f"⚖️ <b>NEW COMMUNITY APPEAL #{appeal.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> @{user.username or 'None'} (<code>{user.id}</code>)\n"
        f"🏷️ <b>Name:</b> {html.escape(user.first_name)}\n"
        f"🛡️ <b>Current Status:</b> {db_user.status}\n"
        f"🚫 <b>Penalty Reason:</b> {html.escape(db_user.ban_reason or db_user.restriction_reason or 'None')}\n\n"
        f"📝 <b>User Appeal Statement:</b>\n"
        f"<i>\"{html.escape(statement)}\"</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Select an action below:</i>"
    )

    admin_keyboard = [
        [
            InlineKeyboardButton("✅ Unban / Restore", callback_data=f"adm_appeal_unban_{appeal.id}"),
            InlineKeyboardButton("🚫 Keep Permanent Ban", callback_data=f"adm_appeal_reject_{appeal.id}"),
        ]
    ]

    for admin_id in settings.admin_id_list:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_card,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(admin_keyboard)
            )
        except Exception as exc:
            logger.warning(f"Could not deliver appeal alert to admin {admin_id}: {exc}")
