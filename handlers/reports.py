"""
Community Scam and Abuse Reporting Handler
Allows users to report suspicious job listings or abusive accounts.
Alerts administrators with one-tap moderation buttons.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config import settings
from database.db import get_db_session
from database.crud import create_report, get_job_by_id
from utils.logger import logger
from utils.rate_limiter import command_rate_limiter
from utils.formatters import COMMUNITY_SAFETY_DISCLAIMER


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /report command in direct messages or group chats."""
    user = update.effective_user
    if not user:
        return

    if not command_rate_limiter.is_allowed(user.id):
        retry = command_rate_limiter.retry_after(user.id)
        await update.message.reply_text(f"⏳ Please wait {retry}s.")
        return

    # Check if this is a reply to another message in a group or channel
    reply_msg = update.message.reply_to_message
    args = context.args or []

    target_user_id = None
    target_job_id = None
    reason_text = ""

    if reply_msg:
        target_user = reply_msg.from_user
        if target_user:
            target_user_id = target_user.id
        reason_text = " ".join(args) if args else "Suspicious message or scam attempt reported in group."
    elif args:
        # Check if first argument is a job ID (e.g. /report 123 upfront fee asked)
        if args[0].isdigit() or (args[0].startswith("#") and args[0][1:].isdigit()):
            raw_id = args[0].replace("#", "")
            target_job_id = int(raw_id)
            reason_text = " ".join(args[1:]) if len(args) > 1 else "Suspicious job listing reported by user."
        else:
            reason_text = " ".join(args)
    else:
        instructions = (
            "🚨 <b>HOW TO REPORT SUSPICIOUS ACTIVITY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "To report a fraudulent job or suspicious user:\n\n"
            "<b>Option 1: Report a Job ID</b>\n"
            "<code>/report &lt;job_id&gt; &lt;reason&gt;</code>\n"
            "<i>Example: /report 42 poster requested 50 USDT deposit</i>\n\n"
            "<b>Option 2: Reply in Group</b>\n"
            "Reply directly to any suspicious message in our group with <code>/report &lt;reason&gt;</code>.\n\n"
            "Our moderators investigate every report promptly."
        )
        await update.message.reply_text(instructions, parse_mode="HTML")
        return

    if not reason_text.strip():
        reason_text = "Unspecified suspicious activity"

    # Persist report in database
    async with get_db_session() as session:
        report = await create_report(
            session=session,
            reporter_id=user.id,
            reason=reason_text,
            target_job_id=target_job_id,
            target_user_id=target_user_id,
        )
        report_id = report.id

    await update.message.reply_text(
        f"✅ <b>Report Submitted (#{report_id})</b>\n\n"
        f"Thank you for helping protect our community. Our safety team has been alerted and will investigate.",
        parse_mode="HTML"
    )

    # Notify administrators
    admin_alert = (
        f"🚨 <b>COMMUNITY REPORT FILED (#{report_id})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Reporter:</b> @{user.username or user.first_name} (<code>{user.id}</code>)\n"
    )
    if target_job_id:
        admin_alert += f"💼 <b>Target Job:</b> #{target_job_id}\n"
    if target_user_id:
        admin_alert += f"🎯 <b>Target User:</b> <code>{target_user_id}</code>\n"
    admin_alert += f"📝 <b>Reason:</b> {reason_text}\n"

    keyboard = []
    if target_job_id:
        keyboard.append([
            InlineKeyboardButton("🔍 View Job", callback_data=f"adm_viewjob_{target_job_id}"),
            InlineKeyboardButton("❌ Reject Job", callback_data=f"adm_reject_{target_job_id}"),
        ])
    if target_user_id:
        keyboard.append([
            InlineKeyboardButton("🚫 Ban Reported User", callback_data=f"adm_ban_{target_user_id}"),
        ])

    for admin_id in settings.admin_id_list:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_alert,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
        except Exception as exc:
            logger.warning(f"Could not alert admin {admin_id} about report #{report_id}: {exc}")
