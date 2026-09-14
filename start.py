#!/usr/bin/env python3
"""
Startup script for Render deployment
Checks environment variables before starting the bot
"""

import os
import sys
import logging
from pathlib import Path

# Add the current directory to the path
sys.path.append(str(Path(__file__).parent))

from config import settings

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s'
)
logger = logging.getLogger(__name__)

def check_environment():
    """Check if required environment variables are set"""
    logger.info("Checking environment variables...")

    # Check Telegram Bot Token
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN is not set!")
        return False
    else:
        logger.info("✅ TELEGRAM_BOT_TOKEN is configured")

        # Validate token format without exposing the token
        token_valid, token_msg = settings.validate_telegram_token()
        if not token_valid:
            logger.error(f"❌ Telegram token validation failed: {token_msg}")
            return False
        else:
            logger.info("✅ Telegram token format is valid")

    # Check AI API Key
    if not settings.AI_API_KEY:
        logger.error("❌ AI_API_KEY is not set!")
        return False
    else:
        logger.info("✅ AI_API_KEY is configured")

    # Check other important variables
    if not settings.OWNER_ID_RAW:
        logger.warning("⚠️ OWNER_ID is not set (will use default admin)")

    if not settings.ADMIN_IDS_RAW:
        logger.warning("⚠️ ADMIN_IDS is not set")

    return True

def main():
    """Main entry point"""
    logger.info("=== REAL FREELANCE JOBS BOT STARTUP ===")

    # Check if running on Render
    if settings.is_render_deployment():
        logger.info("🚀 Deploying on Render platform")

    # Verify environment variables
    if not check_environment():
        logger.error("❌ Missing required environment variables. Please configure them in Render dashboard.")
        return 1

    logger.info("✅ All required environment variables are configured")

    # Import and run the bot
    try:
        from bot import main as bot_main
        import asyncio
        return asyncio.run(bot_main())
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())