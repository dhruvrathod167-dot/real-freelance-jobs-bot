"""
Admin Moderation and Control Suite
Restricted to administrators configured via ADMIN_IDS.
Provides commands and interactive buttons to review pending listings,
approve/reject jobs, ban fraudulent actors, and inspect audit metrics.
"""

import html
from typing import Dict, List, Tuple, Set, Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import settings
from database.db import get_db_session
from database.crud import (
    get_job_by_id,
    get_pending_jobs,
    update_job_status,
    get_user_by_id,
    set_user_status,
    get_system_stats,
    create_audit_entry,
    set_job_tier,
    flag_user_suspicious,
    get_pending_appeals,
    get_appeal_by_id,
    resolve_appeal,
    unban_and_restore_user,
)
from utils.logger import logger
from utils.rate_limiter import submission_rate_limiter
from utils.formatters import (
    format_job_card,
    format_admin_job_review,
    get_risk_badge,
    COMMUNITY_SAFETY_DISCLAIMER,
)

# In-memory tracking of pending moderation card messages sent to administrators: job_id -> [(chat_id, message_id), ...]
PENDING_MODERATION_MESSAGES: Dict[int, List[Tuple[int, int]]] = {}

# In-flight approval tracking to prevent duplicate execution from double clicks
_approvals_in_progress: Set[int] = set()


def record_pending_moderation_message(job_id: int, chat_id: int, message_id: int) -> None:
    """Registers an admin pending moderation card message ID for auto-deletion on review."""
    if job_id not in PENDING_MODERATION_MESSAGES:
        PENDING_MODERATION_MESSAGES[job_id] = []
    PENDING_MODERATION_MESSAGES[job_id].append((chat_id, message_id))


async def delete_pending_moderation_messages(job_id: int, bot, current_msg=None) -> None:
    """
    Deletes old pending moderation messages for the job from admin chats.
    Never touches messages in community groups (e.g. Legally Freelancing Working).
    """
    if current_msg:
        try:
            await current_msg.delete()
        except Exception as exc:
            logger.debug(f"Could not delete current admin message: {exc}")

    entries = PENDING_MODERATION_MESSAGES.pop(job_id, [])
    for chat_id, msg_id in entries:
        if current_msg and current_msg.chat_id == chat_id and current_msg.message_id == msg_id:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as exc:
            logger.debug(f"Could not delete pending moderation card {msg_id} in {chat_id}: {exc}")


def is_authorized_admin(user_id: int) -> bool:
    """Verifies whether caller ID matches configured administrators."""
    return settings.is_admin(user_id)


async def admin_dashboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /admin command: displays overview dashboard."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ <i>Access restricted to authorized administrators.</i>", parse_mode="HTML")
        return

    async with get_db_session() as session:
        stats = await get_system_stats(session)

    dash_text = (
        "🛡️ <b>ADMINISTRATION DASHBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>Pending Jobs:</b> {stats['pending_jobs']}\n"
        f"✅ <b>Approved Jobs:</b> {stats['approved_jobs']}\n"
        f"❌ <b>Rejected Jobs:</b> {stats['rejected_jobs']}\n"
        f"👥 <b>Verified Users:</b> {stats['verified_users']} / {stats['total_users']}\n"
        f"🚫 <b>Banned Users:</b> {stats['banned_users']}\n"
        f"🚨 <b>Open Reports:</b> {stats['open_reports']}\n\n"
        "<b>Admin Commands:</b>\n"
        "• /pending - View pending submissions\n"
        "• /approve &lt;job_id&gt; - Approve & broadcast\n"
        "• /reject &lt;job_id&gt; [reason] - Reject submission\n"
        "• /job &lt;job_id&gt; - Inspect specific job\n"
        "• /user &lt;user_id&gt; - Inspect user profile\n"
        "• /feature &lt;job_id&gt; - Toggle ⭐ featured status\n"
        "• /sponsor &lt;job_id&gt; - Toggle 💎 sponsored status\n"
        "• /suspicious &lt;user_id&gt; [reason] - Flag suspicious account\n"
        "• /unflag &lt;user_id&gt; - Restore flagged account\n"
        "• /ban &lt;user_id&gt; [reason] - Ban user\n"
        "• /unban &lt;user_id&gt; - Restore banned user\n"
        "• /appeals - Review pending user appeals\n"
        "• /stats - Community statistics\n"
    )

    keyboard = [
        [InlineKeyboardButton("⏳ Review Pending Jobs", callback_data="adm_list_pending")],
        [InlineKeyboardButton("📊 System Statistics", callback_data="adm_view_stats")],
    ]

    await update.message.reply_text(dash_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def pending_jobs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /pending command: displays list of pending jobs."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("Unauthorized", show_alert=True)
        else:
            await update.message.reply_text("⛔ Unauthorized.")
        return

    async with get_db_session() as session:
        jobs = await get_pending_jobs(session, limit=5)

    if not jobs:
        msg = "✅ <b>No pending jobs!</b> All submissions have been moderated."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    if update.callback_query:
        await update.callback_query.answer()

    for job in jobs:
        badge = get_risk_badge(job.risk_score, job.risk_level)
        flags_text = ", ".join(job.detected_flags) if job.detected_flags else "None"
        card = (
            f"📌 <b>Job #{job.id}: {html.escape(job.job_title)}</b>\n"
            f"🏢 <b>Company:</b> {html.escape(job.company_name)}\n"
            f"💰 <b>Rate:</b> {html.escape(job.payment_rate)}\n"
            f"🛡️ <b>Risk:</b> {badge}\n"
            f"⚠️ <b>Flags:</b> {html.escape(flags_text[:120])}\n"
            f"👤 <b>Poster ID:</b> <code>{job.user_id}</code>"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{job.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{job.id}"),
                InlineKeyboardButton("🔍 Details", callback_data=f"adm_viewjob_{job.id}"),
            ]
        ]
        target = update.callback_query.message if update.callback_query else update.message
        sent_card = await target.reply_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        record_pending_moderation_message(job_id=job.id, chat_id=sent_card.chat_id, message_id=sent_card.message_id)


async def approve_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /approve <id> command."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /approve <job_id>")
        return

    job_id = int(context.args[0])
    await _execute_approval(job_id=job_id, admin_id=user.id, context=context, reply_target=update.message)


async def broadcast_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /broadcast <job_id>: broadcasts or re-broadcasts an approved job to Legally Freelancing Working."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /broadcast <job_id>")
        return

    job_id = int(context.args[0])
    await _execute_approval(job_id=job_id, admin_id=user.id, context=context, reply_target=update.message)


async def reject_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /reject <id> [reason] command."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /reject <job_id> [reason]")
        return

    job_id = int(context.args[0])
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Submission did not satisfy community verification standards."
    await _execute_rejection(job_id=job_id, admin_id=user.id, reason=reason, context=context, reply_target=update.message)


async def ban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /ban <user_id> [reason]."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /ban <user_id> [reason]")
        return

    target_id = int(context.args[0])
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Safety violations / fraudulent activity."

    async with get_db_session() as session:
        updated = await set_user_status(session, user_id=target_id, status="BANNED", flag_notes=reason, actor_id=user.id)

    if updated:
        await update.message.reply_text(f"🚫 User <code>{target_id}</code> has been banned. Reason: {html.escape(reason)}", parse_mode="HTML")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🚫 <b>Account Suspended</b>\nYour account has been restricted from participating in Real Freelance Jobs.\nReason: {html.escape(reason)}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ User not found in database.")


async def unban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /unban <user_id>: unbans user, clears restrictions, restores group permissions."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /unban <user_id>")
        return

    target_id = int(context.args[0])

    async with get_db_session() as session:
        updated = await unban_and_restore_user(session, user_id=target_id, actor_id=user.id, notes="Unbanned by admin command")

    if updated:
        target_chat_id = settings.effective_group_id
        if target_chat_id:
            try:
                await context.bot.unban_chat_member(chat_id=target_chat_id, user_id=target_id, only_if_banned=False)
                await context.bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=target_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    )
                )
            except Exception as exc:
                logger.warning(f"Could not unban user {target_id} in Telegram group: {exc}")

        await update.message.reply_text(
            f"✅ User <code>{target_id}</code> unbanned and restored to <b>VERIFIED</b> in {html.escape(settings.TELEGRAM_GROUP_NAME)}.",
            parse_mode="HTML"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎉 <b>Account Restored</b>\nYour account has been unbanned by an administrator. You can now participate normally in <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b>.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ User not found.")


async def unrestrict_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /unrestrict <user_id>: manually restores messaging permissions immediately for a restricted user."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /unrestrict <user_id>")
        return

    target_id = int(context.args[0])

    async with get_db_session() as session:
        updated = await unban_and_restore_user(
            session=session,
            user_id=target_id,
            actor_id=user.id,
            notes="Manually unrestricted by admin command"
        )

    if updated:
        target_chat_id = settings.effective_group_id
        if target_chat_id:
            try:
                await context.bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=target_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    )
                )
                logger.info(f"Admin {user.id} manually unrestricted user {target_id} in {settings.TELEGRAM_GROUP_NAME}")
            except Exception as exc:
                logger.warning(f"Could not restore permissions for user {target_id} in Telegram group: {exc}")

        await update.message.reply_text(
            f"✅ User <code>{target_id}</code> communication restriction lifted. Messaging permissions restored in <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b>.",
            parse_mode="HTML"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎉 <b>Restriction Lifted</b>\nYour communication restriction in <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b> has been lifted by an administrator. You can now send messages again.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ User not found.")



async def list_appeals_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /appeals command: lists pending appeals."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    async with get_db_session() as session:
        appeals = await get_pending_appeals(session, limit=10)

    if not appeals:
        await update.message.reply_text("✅ No pending appeals. All cases have been reviewed.", parse_mode="HTML")
        return

    await update.message.reply_text(f"⚖️ <b>Pending Appeals ({len(appeals)})</b>", parse_mode="HTML")
    for appeal in appeals:
        card = (
            f"⚖️ <b>Appeal #{appeal.id}</b>\n"
            f"👤 <b>User ID:</b> <code>{appeal.user_id}</code>\n"
            f"📅 <b>Date:</b> {appeal.created_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"📝 <b>Statement:</b>\n"
            f"<i>\"{html.escape(appeal.appeal_text)}\"</i>"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ Unban / Restore", callback_data=f"adm_appeal_unban_{appeal.id}"),
                InlineKeyboardButton("🚫 Keep Permanent Ban", callback_data=f"adm_appeal_reject_{appeal.id}"),
            ]
        ]
        await update.message.reply_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def feature_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /feature <job_id>: toggles ⭐ featured placement for a job."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /feature <job_id>")
        return

    job_id = int(context.args[0])
    async with get_db_session() as session:
        job = await get_job_by_id(session, job_id)
        if not job:
            await update.message.reply_text(f"❌ Job #{job_id} not found.")
            return

        new_val = not job.is_featured
        tier = "featured" if new_val else ("sponsored" if job.is_sponsored else "standard")
        await set_job_tier(session, job_id=job_id, is_featured=new_val, is_sponsored=job.is_sponsored, listing_tier=tier, actor_id=user.id)

    status_str = "⭐ FEATURED" if new_val else "STANDARD (Unfeatured)"
    await update.message.reply_text(f"✅ Job #{job_id} tier updated to <b>{status_str}</b>.", parse_mode="HTML")


async def sponsor_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /sponsor <job_id>: toggles 💎 sponsored status for a job."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /sponsor <job_id>")
        return

    job_id = int(context.args[0])
    async with get_db_session() as session:
        job = await get_job_by_id(session, job_id)
        if not job:
            await update.message.reply_text(f"❌ Job #{job_id} not found.")
            return

        new_val = not job.is_sponsored
        tier = "sponsored" if new_val else ("featured" if job.is_featured else "standard")
        await set_job_tier(session, job_id=job_id, is_featured=job.is_featured, is_sponsored=new_val, listing_tier=tier, actor_id=user.id)

    status_str = "💎 SPONSORED" if new_val else "STANDARD (Unsponsored)"
    await update.message.reply_text(f"✅ Job #{job_id} tier updated to <b>{status_str}</b>.", parse_mode="HTML")


async def suspicious_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /suspicious <user_id> [reason]: flags an account as SUSPICIOUS."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /suspicious <user_id> [reason]")
        return

    target_id = int(context.args[0])
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Manually flagged by administrator"

    async with get_db_session() as session:
        updated = await flag_user_suspicious(session, user_id=target_id, reason=reason, risk_score=70.0, actor_id=user.id)

    if updated:
        await update.message.reply_text(f"⚠️ User <code>{target_id}</code> flagged as <b>SUSPICIOUS</b>. Reason: {html.escape(reason)}", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ User <code>{target_id}</code> not found.", parse_mode="HTML")


async def unflag_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /unflag <user_id>: restores suspicious/flagged user back to VERIFIED."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /unflag <user_id>")
        return

    target_id = int(context.args[0])
    async with get_db_session() as session:
        updated = await set_user_status(session, user_id=target_id, status="VERIFIED", flag_notes="Cleared flags by administrator", actor_id=user.id)

    if updated:
        await update.message.reply_text(f"✅ User <code>{target_id}</code> flags cleared and restored to <b>VERIFIED</b>.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ User <code>{target_id}</code> not found.", parse_mode="HTML")


async def job_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /job <id> command to inspect full scan details."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /job <job_id>")
        return

    job_id = int(context.args[0])
    await _show_job_inspection(job_id=job_id, reply_target=update.message)


async def user_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /user <user_id> command."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /user <user_id>")
        return

    target_id = int(context.args[0])
    async with get_db_session() as session:
        target = await get_user_by_id(session, target_id)

    if not target:
        await update.message.reply_text(f"❌ User <code>{target_id}</code> not found.", parse_mode="HTML")
        return

    card = (
        f"👤 <b>USER PROFILE INSPECTION</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{target.id}</code>\n"
        f"🏷️ <b>Name:</b> {html.escape(target.first_name)} {html.escape(target.last_name or '')}\n"
        f"📎 <b>Username:</b> @{target.username or 'None'}\n"
        f"🛡️ <b>Status:</b> {target.status}\n"
        f"📊 <b>Risk Score:</b> {target.risk_score:.0f}/100\n"
        f"💼 <b>Jobs Submitted:</b> {target.submission_count}\n"
        f"🚨 <b>Reports Against User:</b> {target.reported_count}\n"
        f"📝 <b>Rules Confirmed:</b> {'Yes' if target.rules_accepted else 'No'}\n"
        f"📌 <b>Notes:</b> {html.escape(target.flag_notes or 'None')}\n"
        f"📅 <b>Created:</b> {target.created_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    keyboard = [
        [
            InlineKeyboardButton("🚫 Ban User", callback_data=f"adm_ban_{target.id}"),
            InlineKeyboardButton("✅ Unban User", callback_data=f"adm_unban_{target.id}"),
        ]
    ]

    await update.message.reply_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /stats command."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    async with get_db_session() as session:
        stats = await get_system_stats(session)

    text = (
        "📊 <b>REAL FREELANCE JOBS PLATFORM STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Users Registered:</b> {stats['total_users']}\n"
        f"✅ <b>Verified Members:</b> {stats['verified_users']}\n"
        f"🚫 <b>Banned Accounts:</b> {stats['banned_users']}\n\n"
        f"💼 <b>Total Job Submissions:</b> {stats['total_jobs']}\n"
        f"🟢 <b>Approved & Published:</b> {stats['approved_jobs']}\n"
        f"⏳ <b>Pending Review:</b> {stats['pending_jobs']}\n"
        f"🔴 <b>Rejected (Scam/Fraud):</b> {stats['rejected_jobs']}\n\n"
        f"🚨 <b>Open Abuse Reports:</b> {stats['open_reports']}\n"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def admin_callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatches inline button clicks for administrator operations."""
    query = update.callback_query
    if not query:
        return

    user = update.effective_user or (query.from_user if query else None)
    if not user or not is_authorized_admin(user.id):
        await query.answer("⛔ Unauthorized action.", show_alert=True)
        return

    data = query.data

    if data == "adm_list_pending":
        await pending_jobs_handler(update, context)
    elif data == "adm_view_stats":
        await stats_handler(update, context)
    elif data.startswith("adm_approve_"):
        job_id = int(data.split("_")[2])
        await query.answer()
        await _execute_approval(job_id=job_id, admin_id=user.id, context=context, reply_target=query.message, pending_message=query.message)
    elif data.startswith("adm_broadcast_"):
        job_id = int(data.split("_")[2])
        await query.answer()
        await _execute_approval(job_id=job_id, admin_id=user.id, context=context, reply_target=query.message, pending_message=query.message)
    elif data.startswith("adm_reject_"):
        job_id = int(data.split("_")[2])
        await query.answer()
        await _execute_rejection(job_id=job_id, admin_id=user.id, reason="Did not meet community standards", context=context, reply_target=query.message, pending_message=query.message)
    elif data.startswith("adm_viewjob_"):
        job_id = int(data.split("_")[2])
        await query.answer()
        await _show_job_inspection(job_id=job_id, reply_target=query.message)
    elif data.startswith("adm_ban_"):
        target_id = int(data.split("_")[2])
        await query.answer()
        async with get_db_session() as session:
            await set_user_status(session, user_id=target_id, status="BANNED", flag_notes="Banned via inline admin button", actor_id=user.id)
        await query.message.reply_text(f"🚫 User <code>{target_id}</code> was banned.", parse_mode="HTML")
    elif data.startswith("adm_unban_"):
        target_id = int(data.split("_")[2])
        await query.answer()
        async with get_db_session() as session:
            await set_user_status(session, user_id=target_id, status="VERIFIED", flag_notes="Unbanned by admin", actor_id=user.id)
        await query.message.reply_text(f"✅ User <code>{target_id}</code> was restored to VERIFIED.", parse_mode="HTML")
    elif data.startswith("adm_feature_"):
        job_id = int(data.split("_")[2])
        await query.answer()
        async with get_db_session() as session:
            job = await get_job_by_id(session, job_id)
            if job:
                new_val = not job.is_featured
                await set_job_tier(session, job_id=job_id, is_featured=new_val, is_sponsored=job.is_sponsored, listing_tier="featured" if new_val else "standard", actor_id=user.id)
                status_txt = "marked as ⭐ FEATURED" if new_val else "reverted to STANDARD"
                await query.message.reply_text(f"Job #{job_id} {status_txt}.")
    elif data.startswith("adm_sponsor_"):
        job_id = int(data.split("_")[2])
        await query.answer()
        async with get_db_session() as session:
            job = await get_job_by_id(session, job_id)
            if job:
                new_val = not job.is_sponsored
                await set_job_tier(session, job_id=job_id, is_featured=job.is_featured, is_sponsored=new_val, listing_tier="sponsored" if new_val else "standard", actor_id=user.id)
                status_txt = "marked as 💎 SPONSORED" if new_val else "reverted to STANDARD"
                await query.message.reply_text(f"Job #{job_id} {status_txt}.")
    elif data.startswith("adm_suspicious_"):
        target_id = int(data.split("_")[2])
        await query.answer()
        async with get_db_session() as session:
            await flag_user_suspicious(session, user_id=target_id, reason="Flagged via inline admin button", actor_id=user.id)
        await query.message.reply_text(f"⚠️ User <code>{target_id}</code> flagged as SUSPICIOUS.", parse_mode="HTML")
    elif data.startswith("adm_appeal_unban_"):
        appeal_id = int(data.split("_")[3])
        await query.answer()
        async with get_db_session() as session:
            appeal = await get_appeal_by_id(session, appeal_id)
            if not appeal or appeal.status != "PENDING":
                await query.message.reply_text("❌ Appeal not found or already processed.")
                return
            await resolve_appeal(session, appeal_id=appeal_id, status="APPROVED", admin_id=user.id, notes="Approved by admin via inline button")
            await unban_and_restore_user(session, user_id=appeal.user_id, actor_id=user.id, notes=f"Unbanned via Appeal #{appeal_id}")
            appeal_user_id = appeal.user_id

        target_chat_id = settings.effective_group_id
        if target_chat_id:
            try:
                await context.bot.unban_chat_member(chat_id=target_chat_id, user_id=appeal_user_id, only_if_banned=False)
                await context.bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=appeal_user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    )
                )
            except Exception as exc:
                logger.warning(f"Could not unban user {appeal_user_id} in group: {exc}")

        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=user.id,
            text=f"✅ <b>Appeal #{appeal_id} APPROVED!</b> User <code>{appeal_user_id}</code> has been unbanned and restored to <b>VERIFIED</b> in {html.escape(settings.TELEGRAM_GROUP_NAME)}.",
            parse_mode="HTML"
        )

        # Notify user in DM
        try:
            await context.bot.send_message(
                chat_id=appeal_user_id,
                text=(
                    f"🎉 <b>Appeal Approved!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your appeal (ID #{appeal_id}) has been reviewed and <b>approved</b> by an administrator.\n"
                    f"Your account and sending permissions have been fully restored in <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b>.\n\n"
                    f"Please review /rules and keep future communications professional."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
    elif data.startswith("adm_appeal_reject_"):
        appeal_id = int(data.split("_")[3])
        await query.answer()
        async with get_db_session() as session:
            appeal = await get_appeal_by_id(session, appeal_id)
            if not appeal or appeal.status != "PENDING":
                await query.message.reply_text("❌ Appeal not found or already processed.")
                return
            await resolve_appeal(session, appeal_id=appeal_id, status="REJECTED", admin_id=user.id, notes="Rejected by admin via inline button")
            appeal_user_id = appeal.user_id

        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=user.id,
            text=f"🚫 <b>Appeal #{appeal_id} REJECTED.</b> Permanent ban maintained for user <code>{appeal_user_id}</code>.",
            parse_mode="HTML"
        )

        # Notify user in DM
        try:
            await context.bot.send_message(
                chat_id=appeal_user_id,
                text=(
                    f"⚖️ <b>Appeal Decision: Not Approved</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your appeal (ID #{appeal_id}) has been reviewed by administrators.\n"
                    f"After consideration of the violation history, the penalty will remain in effect."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass


async def _execute_approval(
    job_id: int,
    admin_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    reply_target,
    pending_message=None
) -> None:
    """Approves job, verifies broadcast to Legally Freelancing Working, and notifies submitter."""
    if job_id in _approvals_in_progress:
        msg = f"⏳ Approval for Job #{job_id} is already in progress. Please wait."
        try:
            if pending_message:
                await context.bot.send_message(chat_id=admin_id, text=msg)
            elif reply_target:
                await reply_target.reply_text(msg)
        except Exception:
            pass
        return

    _approvals_in_progress.add(job_id)
    try:
        async with get_db_session() as session:
            job = await get_job_by_id(session, job_id)
            if not job:
                if pending_message:
                    await context.bot.send_message(chat_id=admin_id, text="❌ Job not found.")
                elif reply_target:
                    await reply_target.reply_text("❌ Job not found.")
                return

            # Prevent duplicate approval/broadcast if already approved and broadcasted
            if job.status == "APPROVED" and job.channel_message_id:
                await delete_pending_moderation_messages(job_id=job_id, bot=context.bot, current_msg=pending_message)
                already_msg = (
                    f"ℹ️ <b>Job #{job_id} is already approved and published.</b>\n"
                    f"<b>Group:</b> {html.escape(settings.TELEGRAM_GROUP_NAME)}\n"
                    f"<b>Telegram Message ID:</b> <code>{job.channel_message_id}</code>\n"
                    f"<i>Duplicate broadcast was prevented.</i>"
                )
                try:
                    if pending_message:
                        await context.bot.send_message(chat_id=admin_id, text=already_msg, parse_mode="HTML")
                    elif reply_target:
                        await reply_target.reply_text(already_msg, parse_mode="HTML")
                except Exception:
                    await context.bot.send_message(chat_id=admin_id, text=already_msg, parse_mode="HTML")
                return

            # Prepare verified post card with sponsorship & featured badges
            card_html = format_job_card(
                job_id=job.id,
                company_name=job.company_name,
                job_title=job.job_title,
                payment_rate=job.payment_rate,
                country_region=job.country_region,
                expected_work=job.expected_work,
                job_description=job.job_description,
                application_method=job.application_method,
                company_website=job.company_website,
                contact_email=job.contact_email,
                risk_score=job.risk_score,
                risk_level=job.risk_level,
                show_risk=False,
                is_featured=job.is_featured,
                is_sponsored=job.is_sponsored,
            )

            # 1. Resolve Target Group ID
            target_chat_id = settings.effective_group_id
            if not target_chat_id:
                from handlers.group import KNOWN_COMMUNITY_CHATS
                if KNOWN_COMMUNITY_CHATS:
                    target_chat_id = next(iter(KNOWN_COMMUNITY_CHATS))

            broadcast_success = False
            channel_msg_id = None
            broadcast_error = None

            # 2. Call Telegram API to send the approved job and verify send operation succeeds
            if not target_chat_id:
                broadcast_error = "Target group chat ID is not configured. (TELEGRAM_GROUP_ID is empty in config/.env)"
                logger.error(f"Cannot broadcast Job #{job_id}: {broadcast_error}")
            else:
                try:
                    published = await context.bot.send_message(
                        chat_id=target_chat_id,
                        text=card_html,
                        parse_mode="HTML"
                    )
                    channel_msg_id = published.message_id
                    broadcast_success = True
                    logger.info(
                        f"Successfully broadcasted approved Job #{job_id} to '{settings.TELEGRAM_GROUP_NAME}' "
                        f"({target_chat_id}), Telegram Message ID: {channel_msg_id}"
                    )
                except TelegramError as exc:
                    broadcast_error = f"Telegram API Error ({type(exc).__name__}): {exc}"
                    logger.error(f"Failed to broadcast Job #{job_id} to group {target_chat_id}: {exc}")
                except Exception as exc:
                    broadcast_error = f"Unexpected Error ({type(exc).__name__}): {exc}"
                    logger.error(f"Unexpected error broadcasting Job #{job_id} to group {target_chat_id}: {exc}")

            # 3. Update Database Status
            if broadcast_success:
                admin_notes = f"Approved by admin {admin_id}"
                await update_job_status(
                    session=session,
                    job_id=job_id,
                    status="APPROVED",
                    admin_notes=admin_notes,
                    channel_message_id=channel_msg_id,
                    actor_id=admin_id,
                )
            else:
                # Keep in retryable state (PENDING_REVIEW) if broadcast fails
                admin_notes = f"Approval attempted by admin {admin_id}; Broadcast Failed: {broadcast_error}"
                await update_job_status(
                    session=session,
                    job_id=job_id,
                    status="PENDING_REVIEW",
                    admin_notes=admin_notes,
                    channel_message_id=None,
                    actor_id=admin_id,
                )

        # 4. Handle Cleanup and Reporting
        if broadcast_success:
            # Delete old pending moderation message(s) from admin chat
            await delete_pending_moderation_messages(job_id=job_id, bot=context.bot, current_msg=pending_message)

            # Report verified outcome to Admin
            success_msg = (
                f"✅ <b>Job #{job_id} Approved!</b> Broadcast to <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b> completed.\n"
                f"<b>Telegram Message ID:</b> <code>{channel_msg_id}</code>\n"
                f"<b>Target Group ID:</b> <code>{target_chat_id}</code>"
            )
            try:
                if pending_message:
                    await context.bot.send_message(chat_id=admin_id, text=success_msg, parse_mode="HTML")
                elif reply_target:
                    await reply_target.reply_text(success_msg, parse_mode="HTML")
                else:
                    await context.bot.send_message(chat_id=admin_id, text=success_msg, parse_mode="HTML")
            except Exception:
                await context.bot.send_message(chat_id=admin_id, text=success_msg, parse_mode="HTML")

            # Reset submitter rate limit and allow them to start another /submit immediately
            submission_rate_limiter.reset(job.user_id)

            # Notify submitter of approval & publication
            try:
                notify_text = (
                    f"🎉 <b>Your Job Posting Has Been Approved!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Job #{job_id}:</b> {html.escape(job.job_title)}\n\n"
                    f"Your listing has been verified by our moderators and published to our community in <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b>.\n\n"
                    f"You can immediately submit another opportunity anytime using /submit.\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{COMMUNITY_SAFETY_DISCLAIMER}"
                )
                await context.bot.send_message(chat_id=job.user_id, text=notify_text, parse_mode="HTML")
            except Exception as exc:
                logger.warning(f"Could not notify job poster {job.user_id}: {exc}")

        else:
            # Broadcast Failed: do NOT report "completed"; show actual failure and keep job retryable
            fail_keyboard = [
                [
                    InlineKeyboardButton("🔄 Retry Broadcast / Approve", callback_data=f"adm_approve_{job_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{job_id}"),
                ]
            ]
            fail_text = (
                f"⚠️ <b>Job #{job_id} Broadcast FAILED!</b>\n\n"
                f"<b>Target Group:</b> {html.escape(settings.TELEGRAM_GROUP_NAME)} (<code>{target_chat_id or 'NOT_SET'}</code>)\n"
                f"<b>Error Details:</b> <code>{html.escape(str(broadcast_error))}</code>\n\n"
                f"The job was NOT published to the group and remains in <b>PENDING_REVIEW</b> state. "
                f"Please verify that the bot is an administrator with posting permissions in the group and click Retry."
            )
            # Delete old button message if provided so we can present the retry card
            if pending_message:
                try:
                    await pending_message.delete()
                except Exception:
                    pass
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=fail_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(fail_keyboard)
                )
            elif reply_target:
                await reply_target.reply_text(
                    fail_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(fail_keyboard)
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=fail_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(fail_keyboard)
                )

    finally:
        _approvals_in_progress.discard(job_id)


async def _execute_rejection(
    job_id: int,
    admin_id: int,
    reason: str,
    context: ContextTypes.DEFAULT_TYPE,
    reply_target,
    pending_message=None
) -> None:
    """Rejects job, deletes old pending moderation card, and sends courteous explanation to submitter."""
    async with get_db_session() as session:
        job = await get_job_by_id(session, job_id)
        if not job:
            if pending_message:
                await context.bot.send_message(chat_id=admin_id, text="❌ Job not found.")
            elif reply_target:
                await reply_target.reply_text("❌ Job not found.")
            return

        await update_job_status(
            session=session,
            job_id=job_id,
            status="REJECTED",
            admin_notes=reason,
            actor_id=admin_id,
        )

    # 1. Delete old pending moderation message(s) from admin chat
    await delete_pending_moderation_messages(job_id=job_id, bot=context.bot, current_msg=pending_message)

    # 2. Inform admin
    admin_msg = f"❌ <b>Job #{job_id} Rejected.</b> Reason: {html.escape(reason)}"
    try:
        if pending_message:
            await context.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")
        elif reply_target:
            await reply_target.reply_text(admin_msg, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")
    except Exception:
        await context.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")

    # 3. Reset submitter rate limit and allow them to start another /submit immediately
    submission_rate_limiter.reset(job.user_id)

    # 4. Inform submitter courteously without defamatory claims
    try:
        notify_text = (
            f"📋 <b>Job Submission Status Update</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Job #{job_id}:</b> {html.escape(job.job_title)}\n"
            f"<b>Status:</b> ❌ Not Approved for Publication\n\n"
            f"<b>Reason:</b> {html.escape(reason)}\n\n"
            f"To maintain a high safety threshold, we cannot publish listings that trigger security flags or lack complete verifiable information.\n\n"
            f"You may submit a revised opportunity anytime using /submit.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{COMMUNITY_SAFETY_DISCLAIMER}"
        )
        await context.bot.send_message(chat_id=job.user_id, text=notify_text, parse_mode="HTML")
    except Exception as exc:
        logger.warning(f"Could not notify submitter {job.user_id}: {exc}")


async def _show_job_inspection(job_id: int, reply_target) -> None:
    """Displays full diagnostic inspection card for a given job."""
    async with get_db_session() as session:
        job = await get_job_by_id(session, job_id)
        if not job:
            await reply_target.reply_text("❌ Job not found.")
            return

        user = await get_user_by_id(session, job.user_id)

    review_text = format_admin_job_review(
        job_id=job.id,
        user_id=job.user_id,
        username=user.username if user else None,
        company_name=job.company_name,
        job_title=job.job_title,
        payment_rate=job.payment_rate,
        country_region=job.country_region,
        company_website=job.company_website,
        contact_email=job.contact_email,
        application_method=job.application_method,
        expected_work=job.expected_work,
        job_description=job.job_description,
        risk_score=job.risk_score,
        risk_level=job.risk_level,
        detected_flags=job.detected_flags,
        ai_reasons=job.ai_analysis.get("reasons", []),
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{job.id}"),
            InlineKeyboardButton("📢 Broadcast", callback_data=f"adm_broadcast_{job.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{job.id}"),
        ],
        [
            InlineKeyboardButton("🚫 Ban Poster", callback_data=f"adm_ban_{job.user_id}"),
        ]
    ]

    await reply_target.reply_text(review_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def list_appeals_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /appeals command: lists pending appeals for admin review."""
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.message.reply_text("⛔ <i>Access restricted to authorized administrators.</i>", parse_mode="HTML")
        return

    async with get_db_session() as session:
        appeals = await get_pending_appeals(session, limit=10)

    if not appeals:
        await update.message.reply_text("✅ <b>No pending appeals to review.</b> All appeals are up to date.", parse_mode="HTML")
        return

    await update.message.reply_text(f"⚖️ <b>Pending Appeals ({len(appeals)} total):</b>", parse_mode="HTML")

    for appeal in appeals:
        async with get_db_session() as session:
            target_user = await get_user_by_id(session, appeal.user_id)

        user_status = target_user.status if target_user else "UNKNOWN"
        penalty_reason = (target_user.ban_reason or target_user.restriction_reason or "None") if target_user else "None"
        created_str = appeal.created_at.strftime("%Y-%m-%d %H:%M UTC") if appeal.created_at else "Recently"

        card = (
            f"⚖️ <b>APPEAL #{appeal.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> @{target_user.username if target_user and target_user.username else 'None'} (<code>{appeal.user_id}</code>)\n"
            f"🏷️ <b>Status:</b> {user_status}\n"
            f"🚫 <b>Reason:</b> {html.escape(penalty_reason)}\n"
            f"📅 <b>Submitted:</b> {created_str}\n\n"
            f"📝 <b>Statement:</b>\n"
            f"<i>\"{html.escape(appeal.appeal_text)}\"</i>"
        )

        keyboard = [
            [
                InlineKeyboardButton(f"✅ Unban #{appeal.id}", callback_data=f"adm_appeal_unban_{appeal.id}"),
                InlineKeyboardButton(f"🚫 Keep Ban #{appeal.id}", callback_data=f"adm_appeal_reject_{appeal.id}"),
            ]
        ]
        await update.message.reply_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
