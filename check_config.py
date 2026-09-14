#!/usr/bin/env python3
"""
Safe configuration checker - reports only what's configured/missing, never values
"""

from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent))

from config import settings

def check_config():
    """Check configuration without exposing secrets"""
    print("=== CONFIGURATION CHECK ===")

    # Check Telegram Bot Token
    if not settings.TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN: Not configured")
    else:
        print("[OK] TELEGRAM_BOT_TOKEN: Configured")

        # Validate token format
        is_valid, message = settings.validate_telegram_token()
        if not is_valid:
            print("[ERROR] Token validation: Failed")
        else:
            print("[OK] Token validation: Passed")

    # Check AI API Key
    if not settings.AI_API_KEY:
        print("[ERROR] AI_API_KEY: Not configured")
    else:
        print("[OK] AI_API_KEY: Configured")

    # Check admin/owner IDs
    if not settings.OWNER_ID_RAW:
        print("[WARN] OWNER_ID: Not configured")
    else:
        print("[OK] OWNER_ID: Configured")

    if not settings.ADMIN_IDS_RAW:
        print("[WARN] ADMIN_IDS: Not configured")
    else:
        print("[OK] ADMIN_IDS: Configured")

    # Check deployment environment
    if settings.is_render_deployment():
        print("[OK] Environment: Render deployment")
    else:
        print("[INFO] Environment: Local development")

    # Check database
    db_config = settings.DATABASE_URL
    if "sqlite" in db_config:
        print("[OK] Database: SQLite (local)")
    elif "postgresql" in db_config:
        print("[OK] Database: PostgreSQL (production)")
    else:
        print("[INFO] Database: Custom")

if __name__ == "__main__":
    check_config()