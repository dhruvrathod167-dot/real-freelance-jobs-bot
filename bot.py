"""
Real Freelance Jobs - Main Application Entrypoint
Coordinates the python-telegram-bot asynchronous Application
and the FastAPI health check/monitoring web service.
"""

import asyncio
import sys
from typing import NoReturn, Optional
import uvicorn
import httpx
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
)
from telegram.error import TelegramError, NetworkError, TimedOut, RetryAfter
from telegram.request import HTTPXRequest

from config import settings
from database.db import init_db, close_db
from utils.logger import logger

# Handlers
from handlers.start import (
    start_handler,
    rules_handler,
    help_handler,
    myid_handler,
    monetization_handler,
)
from handlers.verification import (
    verify_handler,
    status_handler,
    confirm_verify_callback,
    cancel_verify_callback,
)
from handlers.jobs import job_conversation_handler
from handlers.reports import report_handler
from handlers.admin import (
    admin_dashboard_handler,
    pending_jobs_handler,
    approve_job_handler,
    broadcast_job_handler,
    reject_job_handler,
    ban_user_handler,
    unban_user_handler,
    unrestrict_user_handler,
    job_detail_handler,
    user_detail_handler,
    stats_handler,
    admin_callback_dispatcher,
    feature_job_handler,
    sponsor_job_handler,
    suspicious_user_handler,
    unflag_user_handler,
    list_appeals_handler,
)
from handlers.appeal import appeal_handler
from handlers.group import (
    group_message_moderation_handler,
    new_member_onboarding_handler,
    chat_member_onboarding_handler,
    auto_restore_expired_restrictions,
    ensure_owner_active,
)
from services.ai_analyzer import verify_ai_connection
from api.server import app as fastapi_app


class ResilientHTTPXRequest(HTTPXRequest):
    """
    Resilient HTTPXRequest with automated retries and exponential backoff
    for Windows DNS glitches ([Errno 11001]), TLS drops, and network timeouts.
    """
    async def do_request(self, *args, **kwargs) -> tuple[int, bytes]:
        max_retries = 4
        for attempt in range(1, max_retries + 1):
            try:
                return await super().do_request(*args, **kwargs)
            except RetryAfter as exc:
                wait_sec = float(exc.retry_after) + 0.5
                logger.warning(f"Telegram rate limited. Waiting {wait_sec:.1f}s before retrying...")
                await asyncio.sleep(wait_sec)
            except (NetworkError, TimedOut) as exc:
                if attempt < max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        f"Transient Telegram network glitch ({exc}). Retrying attempt {attempt}/{max_retries} in {backoff:.1f}s..."
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"Telegram network request failed after {max_retries} attempts: {exc}")
                    raise


async def global_error_handler(update: object, context) -> None:
    """Catches unhandled exceptions, suppresses transient polling network noise, and alerts user gracefully."""
    if isinstance(context.error, (NetworkError, TimedOut)):
        logger.warning(f"Handled transient network glitch: {context.error}")
        return

    logger.error(f"Unhandled Telegram exception: {context.error}", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message and update.effective_chat:
        try:
            await update.effective_message.reply_text(
                "⚠️ A temporary network glitch occurred while connecting to Telegram. Please resend your message or try again in a moment."
            )
        except Exception:
            pass


def build_bot_application() -> Application:
    """Builds and wires all Telegram handlers into the Application instance."""
    if not settings.telegram_token or settings.telegram_token.startswith("your_"):
        logger.warning(
            "TELEGRAM_BOT_TOKEN is not set in environment or .env file! "
            "Please configure your token before running the bot in polling mode."
        )

    # Build Application with resilient network timeouts and automatic connection retries
    req = ResilientHTTPXRequest(
        connection_pool_size=32,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=15.0,
        httpx_kwargs={"transport": httpx.AsyncHTTPTransport(retries=3)},
    )
    app_builder = ApplicationBuilder().token(settings.telegram_token).request(req)
    application = app_builder.build()

    # Add Error Handler
    application.add_error_handler(global_error_handler)

    # 1. Start, Rules, Help, Identity & Pricing
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("rules", rules_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("myid", myid_handler))
    application.add_handler(CommandHandler("pricing", monetization_handler))
    application.add_handler(CommandHandler("sponsor", monetization_handler))
    application.add_handler(CommandHandler("premium", monetization_handler))
    application.add_handler(CallbackQueryHandler(myid_handler, pattern="^view_myid$"))
    application.add_handler(CallbackQueryHandler(monetization_handler, pattern="^view_pricing$"))

    # 2. Verification Flow
    application.add_handler(CommandHandler("verify", verify_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CallbackQueryHandler(verify_handler, pattern="^start_verify$"))
    application.add_handler(CallbackQueryHandler(rules_handler, pattern="^view_rules$"))
    application.add_handler(CallbackQueryHandler(status_handler, pattern="^view_status$"))
    application.add_handler(CallbackQueryHandler(confirm_verify_callback, pattern="^confirm_verify_pledge$"))
    application.add_handler(CallbackQueryHandler(cancel_verify_callback, pattern="^cancel_verify$"))

    # 3. Job Submission Conversation
    application.add_handler(job_conversation_handler)

    # 4. Reporting & Member Appeals
    application.add_handler(CommandHandler("report", report_handler))
    application.add_handler(CommandHandler("appeal", appeal_handler))

    # 5. Admin Moderation Suite
    application.add_handler(CommandHandler("admin", admin_dashboard_handler))
    application.add_handler(CommandHandler("pending", pending_jobs_handler))
    application.add_handler(CommandHandler("approve", approve_job_handler))
    application.add_handler(CommandHandler("broadcast", broadcast_job_handler))
    application.add_handler(CommandHandler("reject", reject_job_handler))
    application.add_handler(CommandHandler("ban", ban_user_handler))
    application.add_handler(CommandHandler("unban", unban_user_handler))
    application.add_handler(CommandHandler("unrestrict", unrestrict_user_handler))
    application.add_handler(CommandHandler("appeals", list_appeals_handler))
    application.add_handler(CommandHandler("feature", feature_job_handler))
    application.add_handler(CommandHandler("suspicious", suspicious_user_handler))
    application.add_handler(CommandHandler("unflag", unflag_user_handler))
    application.add_handler(CommandHandler("job", job_detail_handler))
    application.add_handler(CommandHandler("user", user_detail_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CallbackQueryHandler(admin_callback_dispatcher, pattern="^adm_"))

    # 6. Group Message Monitoring & Automatic Member Onboarding
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS,
            new_member_onboarding_handler
        )
    )
    application.add_handler(
        ChatMemberHandler(
            chat_member_onboarding_handler,
            ChatMemberHandler.CHAT_MEMBER
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            group_message_moderation_handler
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.UpdateType.EDITED_MESSAGE & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            group_message_moderation_handler
        )
    )

    return application


def find_available_port(host: str, start_port: int, max_attempts: int = 20) -> int:
    """Finds first available TCP port to avoid WinError 10048 address conflicts."""
    import socket
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                # Do NOT set SO_REUSEADDR on Windows to correctly detect occupied ports
                bind_host = host if host in ("0.0.0.0", "127.0.0.1") else "0.0.0.0"
                s.bind((bind_host, port))
                return port
            except OSError:
                continue
    return start_port


async def run_fastapi_server(stop_event: Optional[asyncio.Event] = None) -> None:
    """Runs uvicorn server for health checks and REST endpoints."""
    port = find_available_port(settings.FASTAPI_HOST, settings.FASTAPI_PORT)
    if port != settings.FASTAPI_PORT:
        logger.warning(f"[WARN] Default port {settings.FASTAPI_PORT} is in use; binding to port {port} instead.")

    config = uvicorn.Config(
        app=fastapi_app,
        host=settings.FASTAPI_HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info(f"FastAPI health check server running on http://{settings.FASTAPI_HOST}:{port}")
    try:
        await server.serve()
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception as exc:
        logger.warning(f"FastAPI server ended: {exc}")

    if stop_event and not stop_event.is_set():
        # Keep bot process alive even if web server port encountered an issue
        await stop_event.wait()


async def auto_unrestrict_background_loop(bot) -> None:
    """Periodically checks and auto-restores sending permissions for users whose 4-day restrictions expired."""
    while True:
        try:
            restored = await auto_restore_expired_restrictions(bot)
            if restored:
                logger.info(f"Auto-unrestricted {len(restored)} users whose restrictions expired: {restored}")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"Error in auto-unrestrict background loop: {exc}")
        await asyncio.sleep(60)


async def main() -> None:
    """Master asynchronous initialization and execution loop."""
    logger.info("Starting Real Freelance Jobs Bot System...")

    # 1. Check Render deployment and environment variables
    is_render = settings.is_render_deployment()
    valid_env, missing_vars = settings.validate_required_env_vars()

    if is_render:
        logger.info("[INFO] Running on Render platform")
        if not valid_env:
            logger.error(f"[ERROR] Missing required environment variables on Render: {', '.join(missing_vars)}")
            logger.error("Please configure these variables in Render dashboard")
            await run_fastapi_server()
            return
        else:
            logger.info("[OK] All required environment variables configured on Render")

    # 1.5. Validate Telegram token format safely
    token_valid, token_msg = settings.validate_telegram_token()
    if not token_valid:
        logger.warning(f"[WARN] Telegram token validation failed: {token_msg}")
        logger.warning("[WARN] The bot polling service cannot start without a valid token.")
        logger.warning("Running FastAPI health-check server only.")
        await run_fastapi_server()
        return
    else:
        logger.info("[OK] Telegram token format is valid")

    # 2. Initialize Database Schema
    await init_db()

    # 3. Verify AI Provider Connectivity
    ai_status = await verify_ai_connection()
    if ai_status["status"] == "connected":
        logger.info(f"[OK] AI Connection Verified: {ai_status['message']}")
    elif ai_status["status"] == "quota_exhausted":
        logger.warning(f"[WARN] AI Status: {ai_status['message']}")
    elif ai_status["status"] == "fallback":
        logger.info(f"[INFO] AI Mode: {ai_status['message']}")
    else:
        logger.warning(f"[WARN] AI Status: {ai_status['message']} (Automated heuristic fallback active)")

    # 4. Check Bot Configuration
    if not settings.telegram_token or settings.telegram_token.startswith("your_") or settings.telegram_token.startswith("dummy"):
        logger.warning(
            "[WARN] No valid TELEGRAM_BOT_TOKEN found in environment or .env file! "
            "The bot polling service cannot start without a valid token. "
            "Running FastAPI health-check server only."
        )
        await run_fastapi_server()
        return

    # 4. Build Bot Application
    bot_app = build_bot_application()

    # 5. Launch Bot & FastAPI Concurrently
    logger.info(f"Connecting bot @{settings.BOT_USERNAME}...")
    try:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                async with bot_app:
                    await bot_app.start()
                    me = await bot_app.bot.get_me()
                    logger.info(f"[OK] Telegram Connection Verified: Logged in as @{me.username} (ID: {me.id})")

                    # Target group startup logging and verification
                    target_gid = settings.effective_group_id
                    target_gname = settings.TELEGRAM_GROUP_NAME
                    logger.info(f"Target Broadcast Group Configured: '{target_gname}' (Chat ID: {target_gid or 'NOT_CONFIGURED'})")
                    if target_gid:
                        try:
                            target_chat = await bot_app.bot.get_chat(target_gid)
                            member = await bot_app.bot.get_chat_member(chat_id=target_gid, user_id=me.id)
                            logger.info(
                                f"[OK] Target Group Verified: '{target_chat.title}' (ID: {target_chat.id}, Type: {target_chat.type}) | "
                                f"Bot Status: {member.status}"
                            )
                        except TelegramError as t_err:
                            logger.warning(
                                f"[WARN] Could not verify target group '{target_gname}' (ID: {target_gid}): {t_err}. "
                                f"Ensure bot is added to the group with admin permissions."
                            )
                        except Exception as g_err:
                            logger.warning(f"[WARN] Error inspecting target group: {g_err}")
                    # Check if updater is already running to avoid duplicate polling
                    if hasattr(bot_app, 'updater') and bot_app.updater and bot_app.updater.running:
                        logger.warning("[WARN] Bot updater is already running, avoiding duplicate polling")
                    else:
                        await bot_app.updater.start_polling(
                            allowed_updates=["message", "edited_message", "callback_query", "chat_member", "my_chat_member"],
                            bootstrap_retries=5,
                            poll_interval=0.5,
                            timeout=20,
                        )
                        logger.info(f"Bot @{me.username} polling started successfully!")

                    # CRITICAL: Ensure owner is active and has full permissions
                    try:
                        await ensure_owner_active(bot_app.bot)
                        logger.info(f"[OK] Owner {settings.OWNER_ID} status verified and permissions ensured")
                    except Exception as owner_exc:
                        logger.warning(f"[WARN] Could not ensure owner status: {owner_exc}")

                    # Spawn background task for auto-restoring expired 4-day restrictions
                    unrestrict_task = asyncio.create_task(auto_unrestrict_background_loop(bot_app.bot))

                    # Run FastAPI alongside bot polling with guaranteed cleanup
                    stop_event = asyncio.Event()
                    try:
                        await run_fastapi_server(stop_event)
                    finally:
                        stop_event.set()
                        unrestrict_task.cancel()
                        try:
                            await unrestrict_task
                        except asyncio.CancelledError:
                            pass
                        if bot_app.updater and bot_app.updater.running:
                            await bot_app.updater.stop()
                        if bot_app.running:
                            await bot_app.stop()
                break
            except TelegramError as exc:
                if "InvalidToken" in type(exc).__name__ or "rejected by the server" in str(exc):
                    logger.error(
                        "❌ TELEGRAM TOKEN REJECTED: The Telegram server rejected your bot token. "
                        "Please verify your token with @BotFather."
                    )
                    break
                else:
                    logger.warning(f"Telegram connection attempt {attempt}/{max_retries} failed: {exc}")
                    if attempt < max_retries:
                        await asyncio.sleep(2.0)
                    else:
                        logger.error("Could not establish connection to Telegram API after retries.")
            except Exception as exc:
                logger.error(f"Fatal error during execution: {exc}", exc_info=True)
                break
    finally:
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Service shutdown requested. Goodbye!")
