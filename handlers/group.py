"""
Telegram Group Moderation & Onboarding Handler
Monitors the official community group ("Legally Freelancing Working").
Provides automatic new-member onboarding, verification prompts,
enforces restrictions for unverified members, screens all freelance job
posts for scam and fraud indicators in real time, deletes high-risk posts,
flags suspicious actors, and alerts administrators.

OWNER FULL BYPASS:
- Group owner can send ANY message/content without restrictions
- Bot NEVER deletes, restricts, mutes, or bans the owner
- All automatic moderation/enforcement is skipped for the owner
- Owner has full manual control over all members
- Normal moderation rules remain unchanged for regular members/admins
"""

import html
import re
import time
from typing import Dict, Tuple, Set, Optional
from telegram import (
    Update,
    Chat,
    User,
    ChatMember,
    ChatPermissions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from datetime import datetime, timezone, timedelta
from config import settings
from database.db import get_db_session
from database.crud import (
    get_or_create_user,
    create_audit_entry,
    flag_user_suspicious,
    restrict_user_communication,
    ban_user_permanent,
    unban_and_restore_user,
    get_expired_restrictions,
)
from services.scam_detector import scan_job_heuristics
from services.communication_moderator import (
    scan_communication_message,
    scan_communication_message_ai,
)
from utils.logger import logger


def format_until_date(until_date: Optional[datetime]) -> str:
    """Format until_date for display in restriction messages."""
    if not until_date:
        return "🔒 Restricted permanently"
    
    if until_date.tzinfo is None:
        until_date = until_date.replace(tzinfo=timezone.utc)
    
    return f"🔒 Restricted until: {until_date.strftime('%d %b %Y, %I:%M %p')}"
from utils.authorization import (
    is_group_owner,
    is_authorized_admin,
    should_skip_moderation,
    should_skip_message_delete,
    should_skip_restrictions,
    should_skip_ban,
    should_skip_permission_changes,
)

# In-memory TTL de-duplication caches to prevent duplicate group messages
RECENT_WELCOMES: Dict[Tuple[int, int], float] = {}  # (chat_id, user_id) -> timestamp
LAST_UNVERIFIED_WARNING: Dict[Tuple[int, int], float] = {}  # (chat_id, user_id) -> timestamp

# Track active community group chat IDs so verification can lift restrictions
KNOWN_COMMUNITY_CHATS: Set[int] = set()

# Keywords indicating freelance job promotion attempts
JOB_POSTING_SIGNALS = [
    r"\b(hiring|we are looking for|job opening|apply now|dm me for work)\b",
    r"\b(earn \$|salary:|pay:|hourly rate|work from home opportunity)\b",
    r"\b(freelancers needed|looking for developer|looking for designer|need a writer)\b",
    r"\b(job alert|remote job|freelance role|contract work|paying \$)\b",
]


def cleanup_cache(cache: dict, max_age: float = 300.0) -> None:
    """Purges expired timestamps from in-memory de-duplication tracking."""
    now = time.time()
    for key in [k for k, v in cache.items() if now - v > max_age]:
        cache.pop(key, None)


async def onboard_new_member(chat: Chat, user: User, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Welcomes a new member joining the community group ("Legally Freelancing Working"),
    enforces unverified posting restrictions, and sends the verification prompt
    with the inline 'Verify Account' button.
    """
    if not user or user.is_bot:
        return

    # 🚨 URGENT OWNER FIX: Ensure owner is always active, even if joining as new member
    if settings.owner_id and user.id == settings.owner_id:
        logger.info(f"New member is owner {user.id}, ensuring active status")
        await ensure_owner_active(context.bot)

    KNOWN_COMMUNITY_CHATS.add(chat.id)
    cleanup_cache(RECENT_WELCOMES, max_age=300.0)
    cache_key = (chat.id, user.id)
    now = time.time()

    # Prevent duplicate welcome messages if multiple events fire in close succession
    if cache_key in RECENT_WELCOMES and (now - RECENT_WELCOMES[cache_key]) < 60.0:
        return
    RECENT_WELCOMES[cache_key] = now

    # Fetch or register user record in database
    async with get_db_session() as session:
        db_user = await get_or_create_user(
            session=session,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

    user_mention = f"@{user.username}" if user.username else html.escape(user.first_name)
    group_title = html.escape(chat.title or settings.TELEGRAM_GROUP_NAME)

    # ✅ OWNER FULL BYPASS: Owner is granted immediate verification with no restrictions
    if is_group_owner(user.id):
        welcome_text = (
            f"👋 Welcome, Group Owner {user_mention}!\n\n"
            f"✅ <b>Highest Authority Verified</b>\n"
            f"You have full authority in this community with complete bypass of all automatic moderation.\n"
            f"You can post any content and have full manual control over all members."
        )
        keyboard = [
            [InlineKeyboardButton("📝 Submit a Freelance Job", url=f"https://t.me/{settings.BOT_USERNAME}?start=submit")]
        ]
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Owner {user.id} ({user_mention}) welcomed with full authority bypass")
        except TelegramError as exc:
            logger.warning(f"Could not send owner welcome message in {chat.title}: {exc}")
        return

    # 1. If user is already verified, send a welcoming greeting
    if db_user.status == "VERIFIED" and db_user.rules_accepted:
        welcome_text = (
            f"👋 Welcome back to <b>{group_title}</b>, {user_mention}!\n\n"
            f"✅ <b>Account Status: Verified</b>\n"
            f"Your account is verified in our community. You can post freelance opportunities directly in the group "
            f"or submit jobs via private chat with @{settings.BOT_USERNAME} for automated security screening."
        )
        keyboard = [
            [InlineKeyboardButton("📝 Submit a Freelance Job", url=f"https://t.me/{settings.BOT_USERNAME}?start=submit")]
        ]
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except TelegramError as exc:
            logger.warning(f"Could not send verified welcome message in {chat.title}: {exc}")
        return

    # 2. Restrict chat member permissions so unverified members cannot post
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
        )
        logger.info(f"Restricted unverified new member {user.id} ({user_mention}) in {chat.title}")
    except TelegramError as exc:
        logger.warning(f"Could not restrict new member permissions (bot may need can_restrict_members admin rights): {exc}")

    # 3. Send welcome & verification onboarding message
    welcome_text = (
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

    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=welcome_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except TelegramError as exc:
        logger.warning(f"Could not send onboarding verification message in {chat.title}: {exc}")


async def new_member_onboarding_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles StatusUpdate.NEW_CHAT_MEMBERS service messages in community groups."""
    message = update.effective_message
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup") or not message:
        return

    KNOWN_COMMUNITY_CHATS.add(chat.id)
    new_members = message.new_chat_members or []
    for member in new_members:
        await onboard_new_member(chat, member, context)


async def chat_member_onboarding_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles ChatMemberUpdated events (e.g. member joins via invite link or join request)."""
    cmu = update.chat_member
    chat = update.effective_chat
    if not cmu or not chat or chat.type not in ("group", "supergroup"):
        return

    KNOWN_COMMUNITY_CHATS.add(chat.id)
    old_status = cmu.old_chat_member.status if cmu.old_chat_member else None
    new_status = cmu.new_chat_member.status if cmu.new_chat_member else None

    # Detect join transition (from non-member to member)
    if old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status in (ChatMember.MEMBER, ChatMember.RESTRICTED):
        user = cmu.new_chat_member.user
        await onboard_new_member(chat, user, context)


async def group_message_moderation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Monitors all messages in community groups ("Legally Freelancing Working"):
    1. Keeps unverified users restricted from sending messages (deletes messages & prompts verification).
    2. Allows verified users to send freelance/job messages in the group.
    3. Scans all posted messages in real-time for scam/fraud indicators (upfront fees, deposits,
       crypto schemes, OTP/passwords, suspicious links, and unrealistic compensation).
    4. Automatically deletes high-risk messages, restricts the sender, flags them as SUSPICIOUS,
       and immediately alerts administrators.
    5. Allows low-risk messages to remain visible without false claims of 100% legal verification.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # Only process group and supergroup text messages
    if not chat or chat.type not in ("group", "supergroup") or not message:
        return

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    KNOWN_COMMUNITY_CHATS.add(chat.id)

    # Never moderate messages from bot itself
    if not user or user.is_bot:
        return

    # ✅ OWNER FULL BYPASS: Owner messages are NEVER moderated, restricted, or deleted
    if is_group_owner(user.id) or should_skip_moderation(user.id):
        await ensure_owner_active(context.bot)
        logger.info(f"Skipping all moderation for group owner {user.id}")
        # Owner can post anything without automatic moderation
        is_job_post = any(re.search(pat, text, re.IGNORECASE) for pat in JOB_POSTING_SIGNALS)
        if is_job_post:
            async with get_db_session() as session:
                await create_audit_entry(
                    session=session,
                    actor_id=user.id,
                    action="GROUP_JOB_POST_OWNER",
                    target_type="GROUP_MESSAGE",
                    target_id=str(message.message_id),
                    details=f"Owner posted freelance message in {chat.title} (auto-approved)"
                )
        return

    user_mention = f"@{user.username}" if user.username else html.escape(user.first_name)
    group_title = html.escape(chat.title or settings.TELEGRAM_GROUP_NAME)

    # Check user verification status in database
    async with get_db_session() as session:
        db_user = await get_or_create_user(
            session=session,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

    now = datetime.now(timezone.utc)

    # 1. ENFORCE BANS: If user is banned, delete message and ban from chat
    # ✅ OWNER BYPASS: Owner can NEVER be banned
    if should_skip_ban(user.id):
        logger.info(f"Skipping ban enforcement for owner {user.id}")
    elif db_user.status == "BANNED":
        try:
            await message.delete()
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            logger.info(f"Enforced ban for user {user.id} in {chat.title}")
        except TelegramError:
            pass
        return

    # 2. ENFORCE TEMPORARY RESTRICTIONS (e.g. 4-day communication mute)
    # ✅ OWNER BYPASS: Owner can NEVER be restricted
    if should_skip_restrictions(user.id):
        logger.info(f"Skipping restriction enforcement for owner {user.id}")
    elif db_user.status == "RESTRICTED" and db_user.restricted_until:
        restricted_until = db_user.restricted_until
        if restricted_until.tzinfo is None:
            restricted_until = restricted_until.replace(tzinfo=timezone.utc)
        if restricted_until > now:
            try:
                await message.delete()
                logger.info(f"Deleted message from restricted user {user.id} (restricted until {restricted_until})")
            except TelegramError:
                pass
            return
        else:
            # 4-day restriction has expired: automatically restore sending permissions
            async with get_db_session() as session:
                await unban_and_restore_user(
                    session=session,
                    user_id=user.id,
                    actor_id=0,
                    notes="4-day restriction expired automatically upon message attempt"
                )
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    )
                )
                logger.info(f"Automatically restored permissions for user {user.id} in {chat.title}")
            except TelegramError:
                pass

    # 3. COMMUNITY COMMUNICATION MODERATION (Multilingual: English, Hindi, Gujarati, Hinglish, Gujlish)
    # Severity Threshold: ONLY clear serious abuse, repeated insults, harassment, threats, or aggressive fighting
    # (severity in ["SERIOUS", "CRITICAL"]) trigger message deletion + 4-day restriction + audit log.
    # Mild/ambiguous messages, opinions, disagreements, or harmless words = NO ACTION.
    # ✅ OWNER BYPASS: Owner messages are NEVER moderated for communication violations
    if should_skip_moderation(user.id) or should_skip_message_delete(user.id):
        logger.info(f"Skipping communication moderation for owner {user.id}")
    else:
        comm_scan = await scan_communication_message_ai(text)
        if comm_scan.is_violation and comm_scan.severity in ("SERIOUS", "CRITICAL"):
            if should_skip_restrictions(user.id):
                # Admin/Owner: never automatically restrict or delete
                logger.info(f"Communication violation for privileged user {user.id} flagged for review without auto-enforcement")
                alert_text = (
                    f"⚠️ <b>PRIVILEGED USER COMMUNICATION REVIEW REQUIRED</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>User:</b> {user_mention} (<code>{user.id}</code>)\n"
                    f"💬 <b>Group:</b> {group_title}\n"
                    f"⚠️ <b>Type:</b> {comm_scan.violation_type} ({comm_scan.severity})\n"
                    f"📌 <b>Reason:</b> {comm_scan.details}\n"
                    f"📊 <b>Note:</b> Automated restriction/deletion skipped for privileged user.\n\n"
                    f"📄 <b>Message Text:</b>\n"
                    f"<code>{html.escape(text[:300])}</code>"
                )
                for admin_id in settings.admin_id_list:
                    if admin_id != user.id:
                        try:
                            await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
                        except TelegramError:
                            pass
                return

            # A. Delete abusive/harassing/spam message immediately
            try:
                await message.delete()
                logger.info(f"Deleted {comm_scan.violation_type} ({comm_scan.severity}) message from user {user.id} in {chat.title}: {comm_scan.details}")
            except TelegramError as exc:
                logger.warning(f"Could not delete message: {exc}")

            # B. First violation -> Restrict for exactly 4 days
            if db_user.violation_count == 0:
                duration_days = 4
                until_date = now + timedelta(days=duration_days)
                async with get_db_session() as session:
                    await restrict_user_communication(
                        session=session,
                        user_id=user.id,
                        duration_days=duration_days,
                        reason=comm_scan.details,
                        actor_id=0
                    )

                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=ChatPermissions(
                            can_send_messages=False,
                            can_send_polls=False,
                            can_send_other_messages=False,
                            can_add_web_page_previews=False,
                        ),
                        until_date=until_date
                    )
                    logger.info(f"Restricted user {user.id} for 4 days in {chat.title} (until {until_date.isoformat()}, unix timestamp: {int(until_date.timestamp())})")
                except TelegramError as exc:
                    logger.warning(f"Could not restrict chat member {user.id}: {exc}")

                restore_time_str = until_date.strftime("%Y-%m-%d %H:%M:%S UTC")

                # Post group notice
                restriction_expiry = format_until_date(until_date)
                group_notice = (
                    f"⚠️ <b>User restricted for 4 days.</b>\n"
                    f"<i>Communication Rule Violation</i>\n"
                    f"{user_mention} — ⚠️ <b>You are restricted for 4 days.</b>\n"
                    f"<b>Reason:</b> <i>{html.escape(comm_scan.details)}</i>\n\n"
                    f"{restriction_expiry}\n\n"
                    f"⚖️ <i>Community Rule: Be respectful and professional. No abusive language, harassment, or spam.</i>"
                )
                try:
                    await context.bot.send_message(chat_id=chat.id, text=group_notice, parse_mode="HTML")
                except TelegramError:
                    pass

                # Notify user in DM
                restriction_expiry = format_until_date(until_date)
                dm_notice = (
                    f"⚠️ <b>You are restricted for 4 days.</b>\n"
                    f"{restriction_expiry}\n\n"
                    f"<b>Group:</b> {group_title}\n"
                    f"<b>Reason:</b> {html.escape(comm_scan.details)}\n\n"
                    f"Your sending permissions will automatically be restored at that exact time.\n"
                    f"If you believe this action was applied in error, you may submit an appeal using /appeal.\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Community Rules:</b>\n"
                    f"• Be respectful and professional.\n"
                    f"• No abusive, insulting or threatening language.\n"
                    f"• No harassment or spam."
                )
                try:
                    await context.bot.send_message(chat_id=user.id, text=dm_notice, parse_mode="HTML")
                except Exception:
                    pass

            else:
                # Repeated serious violation -> Extended 14-day restriction or Permanent Ban
                if db_user.violation_count == 1 and comm_scan.severity != "CRITICAL":
                    duration_days = 14
                    until_date = now + timedelta(days=duration_days)
                    restore_time_str = until_date.strftime("%Y-%m-%d %H:%M:%S UTC")
                    async with get_db_session() as session:
                        await restrict_user_communication(
                            session=session,
                            user_id=user.id,
                            duration_days=duration_days,
                            reason=f"Repeated communication violation: {comm_scan.details}",
                            actor_id=0
                        )
                    try:
                        await context.bot.restrict_chat_member(
                            chat_id=chat.id,
                            user_id=user.id,
                            permissions=ChatPermissions(
                                can_send_messages=False,
                                can_send_polls=False,
                                can_send_other_messages=False,
                                can_add_web_page_previews=False,
                            ),
                            until_date=until_date
                        )
                        logger.info(f"Restricted user {user.id} for 14 days in {chat.title} (until {until_date.isoformat()}, unix timestamp: {int(until_date.timestamp())})")
                    except TelegramError:
                        pass

                    restriction_expiry = format_until_date(until_date)
                    group_notice = (
                        f"⚠️ <b>User restricted for 14 days.</b>\n"
                        f"{user_mention} has received an extended restriction for repeated violations.\n"
                        f"<b>Reason:</b> <i>{html.escape(comm_scan.details)}</i>\n\n"
                        f"{restriction_expiry}"
                    )
                    try:
                        await context.bot.send_message(chat_id=chat.id, text=group_notice, parse_mode="HTML")
                    except TelegramError:
                        pass

                    restriction_expiry = format_until_date(until_date)
                    dm_notice = (
                        f"🚫 <b>Extended Communication Restriction Notice</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"You have received an <b>extended 14-day restriction</b> in <b>{group_title}</b> due to repeated violations.\n\n"
                        f"<b>Reason:</b> {html.escape(comm_scan.details)}\n"
                        f"{restriction_expiry}\n\n"
                        f"You may submit an appeal using /appeal."
                    )
                    try:
                        await context.bot.send_message(chat_id=user.id, text=dm_notice, parse_mode="HTML")
                    except Exception:
                        pass

                else:
                    # Severe or 3+ violations -> Permanent Ban
                    async with get_db_session() as session:
                        await ban_user_permanent(
                            session=session,
                            user_id=user.id,
                            reason=f"Repeated severe communication violations: {comm_scan.details}",
                            actor_id=0
                        )
                    try:
                        await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
                    except TelegramError:
                        pass

                    restriction_expiry = format_until_date(None)  # Permanent ban
                    dm_notice = (
                        f"🚫 <b>Account Permanently Banned</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{restriction_expiry}\n\n"
                        f"Your account has been <b>permanently banned</b> from <b>{group_title}</b>.\n"
                        f"<b>Reason:</b> Repeated severe communication violations ({html.escape(comm_scan.details)})\n\n"
                        f"You may submit an appeal to community administrators using /appeal."
                    )
                    try:
                        await context.bot.send_message(chat_id=user.id, text=dm_notice, parse_mode="HTML")
                    except Exception:
                        pass

            # Alert Administrators
            alert_text = (
                f"🛡️ <b>COMMUNICATION VIOLATION DETECTED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>User:</b> {user_mention} (<code>{user.id}</code>)\n"
                f"💬 <b>Group:</b> {group_title}\n"
                f"⚠️ <b>Type:</b> {comm_scan.violation_type} ({comm_scan.severity})\n"
                f"📌 <b>Reason:</b> {comm_scan.details}\n"
                f"📊 <b>Total Violations:</b> {db_user.violation_count + 1}\n\n"
                f"📄 <b>Message Text:</b>\n"
                f"<code>{html.escape(text[:300])}</code>"
            )
            for admin_id in settings.admin_id_list:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
                except TelegramError:
                    pass

            return

    # 4. FOR ALL MEMBERS: Real-time heuristic scam and fraud risk analysis
    # ✅ OWNER & ADMIN PROTECTION: Owner & Admin messages bypass auto-ban/delete
    scan = scan_job_heuristics(
        job_title="",
        job_description=text,
        payment_rate="",
        expected_work="",
        application_method="",
    )

    is_high_risk = scan.risk_score >= 50.0

    if is_high_risk:
        if should_skip_ban(user.id) or should_skip_message_delete(user.id):
            logger.info(f"High-risk content from privileged user {user.id}; marked for review without auto-ban")
            flags_bulleted = "\n".join(f"• {f}" for f in scan.flags) if scan.flags else "• Severe fraud indicators"
            alert_text = (
                f"⚠️ <b>HIGH RISK CONTENT — PRIVILEGED USER REVIEW REQUIRED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>User:</b> {user_mention} (<code>{user.id}</code>)\n"
                f"💬 <b>Group:</b> {group_title}\n"
                f"📊 <b>Risk Score:</b> {scan.risk_score:.1f}/100 ({scan.risk_level.upper()})\n"
                f"⚠️ <b>Detected Flags:</b>\n{flags_bulleted}\n\n"
                f"📄 <b>Message Text:</b>\n"
                f"<code>{html.escape(text[:300])}{'...' if len(text) > 300 else ''}</code>\n\n"
                f"<i>Note: Automated enforcement skipped for privileged user (Owner/Admin).</i>"
            )
            for admin_id in settings.admin_id_list:
                if admin_id != user.id:
                    try:
                        await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
                    except TelegramError:
                        pass
            return
        # A. Delete malicious scam post immediately
        try:
            await message.delete()
            logger.info(f"Deleted scam post (Score: {scan.risk_score}) from user {user.id} in {chat.title}")
        except TelegramError as exc:
            logger.warning(f"Could not delete group message: {exc}")

        # B. Permanent Ban for clearly malicious scam content
        async with get_db_session() as session:
            await ban_user_permanent(
                session=session,
                user_id=user.id,
                reason=f"Malicious scam post in {chat.title}: {', '.join(scan.flags)}",
                actor_id=0,
                risk_score=scan.risk_score,
            )
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            logger.info(f"Permanently banned scam poster {user.id} in {chat.title}")
        except TelegramError as exc:
            logger.warning(f"Could not ban user {user.id}: {exc}")

        # C. Alert Administrators
        flags_bulleted = "\n".join(f"• {f}" for f in scan.flags) if scan.flags else "• Severe fraud indicators"
        alert_text = (
            f"🚨 <b>MALICIOUS SCAM CONTENT DETECTED IN GROUP</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {user_mention} (<code>{user.id}</code>)\n"
            f"💬 <b>Group:</b> {group_title}\n"
            f"📊 <b>Risk Score:</b> {scan.risk_score:.1f}/100 ({scan.risk_level.upper()})\n"
            f"⚠️ <b>Detected Flags:</b>\n{flags_bulleted}\n\n"
            f"📄 <b>Message Text:</b>\n"
            f"<code>{html.escape(text[:300])}{'...' if len(text) > 300 else ''}</code>\n\n"
            f"<i>Action: Message removed, user permanently banned from group.</i>"
        )
        for admin_id in settings.admin_id_list:
            try:
                await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
            except TelegramError:
                pass

        # D. Post community safety alert in group
        group_notice = (
            f"🚨 <b>Community Safety Alert</b>\n"
            f"A malicious scam message from {user_mention} was removed, and the account has been permanently banned:\n"
            f"• {scan.flags[0] if scan.flags else 'Suspicious payment/credential scheme'}\n\n"
            f"🛡️ <i>Community Rule: {group_title} strictly prohibits upfront fees, registration deposits, crypto schemes, and credential requests.</i>"
        )
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=group_notice,
                parse_mode="HTML"
            )
        except TelegramError:
            pass

        # E. Notify banned user in DM with appeal instructions
        dm_ban_notice = (
            f"🚫 <b>Account Permanently Banned</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Your account has been permanently banned from <b>{group_title}</b> for posting deceptive or scam job content.\n\n"
            f"<b>Detected Indicators:</b> {', '.join(scan.flags[:2]) if scan.flags else 'Fraud risk'}\n\n"
            f"If you believe this was in error, you may submit a formal appeal to administrators using /appeal."
        )
        try:
            await context.bot.send_message(chat_id=user.id, text=dm_ban_notice, parse_mode="HTML")
        except Exception:
            pass

        return

    # 5. NORMAL PROFESSIONAL MESSAGES / CONVERSATION / OPINIONS / DISAGREEMENTS:
    # NO ACTION. Normal conversation remains completely untouched!
    is_job_post = any(re.search(pat, text, re.IGNORECASE) for pat in JOB_POSTING_SIGNALS)
    if is_job_post:
        async with get_db_session() as session:
            await create_audit_entry(
                session=session,
                actor_id=user.id,
                action="GROUP_JOB_POST_ALLOWED",
                target_type="GROUP_MESSAGE",
                target_id=str(message.message_id),
                details=f"User posted freelance message in {chat.title}. Risk: {scan.risk_score:.1f}"
            )


async def auto_restore_expired_restrictions(bot) -> None:
    """
    Background worker: checks database for users whose temporary restrictions
    have reached their expiration timestamp, updates their status to VERIFIED,
    restores Telegram sending permissions in Legally Freelancing Working, and notifies them.
    """
    async with get_db_session() as session:
        expired_users = await get_expired_restrictions(session)
        if not expired_users:
            return []

        target_chat_id = settings.effective_group_id
        for user in expired_users:
            await unban_and_restore_user(
                session=session,
                user_id=user.id,
                actor_id=0,
                notes="Automatic expiration of 4-day communication restriction"
            )
            # Restore group chat permissions
            if target_chat_id:
                try:
                    await bot.restrict_chat_member(
                        chat_id=target_chat_id,
                        user_id=user.id,
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                        )
                    )
                    logger.info(f"Auto-restored group sending permissions for user {user.id} in {target_chat_id}")
                except Exception as exc:
                    logger.warning(f"Could not auto-restore chat permissions for user {user.id}: {exc}")

            # Notify user in DM
            try:
                await bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"✅ <b>Temporary Restriction Expired</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Your 4-day temporary restriction in <b>{html.escape(settings.TELEGRAM_GROUP_NAME)}</b> "
                        f"has expired. Your sending permissions have been automatically restored.\n\n"
                        f"Please ensure all future messages comply with our professional community rules."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

        return [u.id for u in expired_users]


async def ensure_owner_active(bot) -> None:
    """
    URGENT OWNER FIX: Ensure the group owner is never banned or restricted.
    If owner is marked BANNED/RESTRICTED, automatically restore to active/verified status
    and ensure full messaging permissions.
    """
    from config import settings

    owner_id = settings.owner_id
    if not owner_id:
        logger.warning("No OWNER_ID configured, skipping owner auto-restore check")
        return

    logger.info(f"Checking owner {owner_id} status for auto-restore")

    async with get_db_session() as session:
        # Get or create owner user record
        db_user = await get_or_create_user(
            session=session,
            user_id=owner_id,
            first_name="Group Owner",
            last_name="",
            username="owner",
        )

        was_banned_or_restricted = db_user.status in ("BANNED", "RESTRICTED")

        # If owner is banned or restricted, automatically restore
        if was_banned_or_restricted:
            logger.warning(f"Owner {owner_id} is {db_user.status}, automatically restoring to active status")
            db_user.status = "VERIFIED"
            db_user.rules_accepted = True
            db_user.restriction_expires_at = None
            db_user.banned_reason = None
            await session.commit()
        elif db_user.status != "VERIFIED":
            # Ensure owner is at least verified
            logger.info(f"Setting owner {owner_id} to VERIFIED status")
            db_user.status = "VERIFIED"
            db_user.rules_accepted = True
            await session.commit()

        # Ensure owner has full messaging permissions in the group
        target_chat_id = settings.effective_group_id
        should_grant = False
        if target_chat_id == -1004335696952:
            should_grant = True
        elif was_banned_or_restricted and target_chat_id and isinstance(target_chat_id, int):
            should_grant = True
        else:
            # Always ensure owner has full permissions regardless of status
            should_grant = True

        if should_grant:
            try:
                await bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=owner_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=True,
                        can_invite_users=True,
                        can_pin_messages=True,
                    )
                )
                logger.info(f"Ensured owner {owner_id} has full permissions in group {target_chat_id}")
            except Exception as exc:
                logger.warning(f"Could not ensure owner permissions: {exc}")

        if was_banned_or_restricted:
            # Notify owner about auto-restore (in DM if possible)
            try:
                await bot.send_message(
                    chat_id=owner_id,
                    text=(
                        f"🔧 <b>System Status Update</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Your account status has been automatically updated to <b>ACTIVE</b>.\n\n"
                        f"As the group owner, you have full authority and cannot be restricted or banned by the bot.\n"
                        f"You can send any message and have complete control over the group.\n\n"
                        f"Group: {html.escape(settings.TELEGRAM_GROUP_NAME)}"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
