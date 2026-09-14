#!/usr/bin/env python3
"""
Test script to verify Telegram token and bot functionality
Run this script to validate the bot is working correctly
"""

import os
import sys
import asyncio
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

from config import settings
from utils.logger import logger

async def test_token():
    """Test the Telegram token connectivity"""
    print("=== TELEGRAM TOKEN TEST ===")

    # Check if token is configured
    if not settings.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is not configured!")
        return False

    print("✅ Token is configured")

    # Validate token format
    is_valid, message = settings.validate_telegram_token()
    if not is_valid:
        print(f"❌ Token validation failed: {message}")
        return False
    print("✅ Token format is valid")

    # Test actual connection to Telegram
    try:
        bot = Bot(token=settings.telegram_token)
        bot_info = await bot.get_me()
        print(f"✅ Bot connected successfully!")
        print(f"   Username: @{bot_info.username}")
        print(f"   ID: {bot_info.id}")
        return True
    except Exception as e:
        print("❌ Failed to connect to Telegram")
        return False

async def test_handlers():
    """Test basic handlers without full bot setup"""
    print("\n=== HANDLER TEST ===")

    # Test that handlers can be imported
    try:
        from handlers.start import start_handler, myid_handler
        print("✅ Start handlers imported successfully")

        from handlers.verification import verify_handler
        print("✅ Verification handlers imported successfully")

        from handlers.reports import report_handler
        print("✅ Report handlers imported successfully")

        return True
    except Exception as e:
        print(f"❌ Failed to import handlers: {e}")
        return False

async def test_database():
    """Test database connectivity"""
    print("\n=== DATABASE TEST ===")

    try:
        from database.db import init_db, close_db
        await init_db()
        print("✅ Database initialized successfully")
        await close_db()
        return True
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

async def test_ai_connection():
    """Test AI provider connection"""
    print("\n=== AI CONNECTION TEST ===")

    try:
        from services.ai_analyzer import verify_ai_connection
        status = await verify_ai_connection()

        if status["status"] == "connected":
            print(f"✅ AI Connection: {status['message']}")
            return True
        elif status["status"] == "quota_exhausted":
            print(f"⚠️ AI Quota: {status['message']}")
            return True  # This is acceptable
        elif status["status"] == "fallback":
            print(f"ℹ️ AI Fallback: {status['message']}")
            return True  # This is acceptable
        else:
            print(f"❌ AI Connection Failed: {status['message']}")
            return False
    except Exception as e:
        print(f"❌ AI Connection Error: {e}")
        return False

async def main():
    """Run all tests"""
    print("Real Freelance Bot - Diagnostic Test")
    print("=" * 50)

    # Check if we're on Render
    is_render = settings.is_render_deployment()
    if is_render:
        print("🚀 Running on Render platform")
    else:
        print("💻 Running in local development mode")

    tests = [
        ("Token Test", test_token),
        ("Handlers Test", test_handlers),
        ("Database Test", test_database),
        ("AI Connection Test", test_ai_connection),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)

    all_passed = True
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if not result:
            all_passed = False

    if all_passed:
        print("\n🎉 All tests passed! The bot should be ready to run.")
    else:
        print("\n⚠️ Some tests failed. Please fix the issues before deploying.")

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))