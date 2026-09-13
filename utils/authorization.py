"""
Authorization & Privilege Checking Utility Module
Handles owner/admin privilege verification and bypass logic.
Provides centralized methods to check if a user is the group owner,
admin, or should be exempt from moderation enforcement.
"""

from config import settings
from utils.logger import logger


def is_group_owner(user_id: int) -> bool:
    """
    Check if a user is the Telegram Group Owner.
    Owner has FULL BYPASS of all automatic moderation and enforcement.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if user is the group owner, False otherwise
    """
    return settings.is_owner(user_id)


def should_skip_moderation(user_id: int) -> bool:
    """
    Determine if automatic moderation should be skipped for a user.
    Returns True if user is the group owner (full bypass).
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if user should bypass all moderation checks
    """
    if is_group_owner(user_id):
        logger.info(f"Skipping moderation for group owner {user_id}")
        return True
    return False


def should_skip_message_delete(user_id: int) -> bool:
    """
    Determine if message deletion should be skipped for a user.
    Owner messages are NEVER deleted.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if messages should not be auto-deleted
    """
    if is_group_owner(user_id):
        logger.info(f"Skipping message deletion for owner {user_id}")
        return True
    return False


def should_skip_restrictions(user_id: int) -> bool:
    """
    Determine if automatic restrictions should be skipped for a user.
    Owner can NEVER be restricted.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if user should not be restricted
    """
    if is_group_owner(user_id):
        logger.info(f"Skipping restrictions for owner {user_id}")
        return True
    return False


def should_skip_ban(user_id: int) -> bool:
    """
    Determine if automatic bans should be skipped for a user.
    Owner can NEVER be banned.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if user should not be banned
    """
    if is_group_owner(user_id):
        logger.info(f"Skipping ban for owner {user_id}")
        return True
    return False


def should_skip_permission_changes(user_id: int) -> bool:
    """
    Determine if automatic permission changes should be skipped for a user.
    Owner permissions are NEVER modified by the bot.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        True if user permissions should not be modified
    """
    if is_group_owner(user_id):
        logger.info(f"Skipping permission changes for owner {user_id}")
        return True
    return False
