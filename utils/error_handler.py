"""
Secure Error Handler Module
Provides centralized error handling that prevents sensitive information leakage
while maintaining useful debugging capabilities.
"""

import traceback
import html
from typing import Optional, Dict, Any, Union
from enum import Enum
from utils.logger import logger
from utils.security import log_security_event


class ErrorType(Enum):
    """Types of errors that can occur."""
    VALIDATION_ERROR = "validation_error"
    AUTHORIZATION_ERROR = "authorization_error"
    DATABASE_ERROR = "database_error"
    TELEGRAM_API_ERROR = "telegram_api_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    SECURITY_ERROR = "security_error"
    SYSTEM_ERROR = "system_error"
    BUSINESS_LOGIC_ERROR = "business_logic_error"


class SecurityError(Exception):
    """Base exception for security-related errors."""
    pass


class UserFacingError(Exception):
    """Exception that can be safely shown to users."""
    
    def __init__(self, message: str, error_type: ErrorType = ErrorType.VALIDATION_ERROR):
        self.message = message
        self.error_type = error_type
        super().__init__(message)


async def handle_error(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle errors securely, preventing information leakage.
    
    Args:
        error: The exception that occurred
        context: Additional context about where the error occurred
        user_id: Telegram user ID (if available)
        action: The action being performed when the error occurred
    
    Returns:
        Dict containing error details for logging (without sensitive info)
    """
    # Extract error details
    error_type = _classify_error(error)
    error_name = error.__class__.__name__
    error_message = str(error)
    
    # Sanitize error message for logging
    safe_error_message = _sanitize_error_message(error_message)
    
    # Create error context
    error_context = {
        "error_type": error_type.value,
        "error_name": error_name,
        "error_message": safe_error_message,
        "context": context or {},
        "timestamp": None,  # Will be added by logger
    }
    
    # Log the error
    log_message = f"Error occurred: {error_name} ({error_type.value})"
    if action:
        log_message += f" during {action}"
    if user_id:
        log_message += f" by user {user_id}"
    
    logger.error(log_message, exc_info=True)
    
    # Log security event if it's a security-related error
    if error_type in [ErrorType.SECURITY_ERROR, ErrorType.AUTHORIZATION_ERROR]:
        log_security_event(
            "SECURITY_ERROR",
            user_id or 0,
            {
                "error_type": error_type.value,
                "error_name": error_name,
                "action": action,
                "context": _sanitize_context(context)
            }
        )
    
    return error_context


def _classify_error(error: Exception) -> ErrorType:
    """Classify the type of error."""
    error_type = type(error)
    
    if isinstance(error, SecurityError):
        return ErrorType.SECURITY_ERROR
    elif isinstance(error, UserFacingError):
        return ErrorType.VALIDATION_ERROR
    elif "AuthorizationError" in error_type.__name__ or "Permission" in error_type.__name__:
        return ErrorType.AUTHORIZATION_ERROR
    elif "DatabaseError" in error_type.__name__ or "SQL" in error_type.__name__:
        return ErrorType.DATABASE_ERROR
    elif "TelegramError" in error_type.__name__:
        return ErrorType.TELEGRAM_API_ERROR
    elif "RateLimit" in error_type.__name__:
        return ErrorType.RATE_LIMIT_ERROR
    elif "ValueError" in error_type.__name__ or "ValidationError" in error_type.__name__:
        return ErrorType.VALIDATION_ERROR
    else:
        return ErrorType.SYSTEM_ERROR


def _sanitize_error_message(message: str) -> str:
    """Sanitize error messages to prevent information leakage."""
    if not message or not isinstance(message, str):
        return "Unknown error"
    
    # Remove potential sensitive information
    sanitized = message
    
    # Remove IP addresses
    import re
    sanitized = re.sub(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', '[IP_REDACTED]', sanitized)
    
    # Remove URLs that might contain sensitive parameters
    sanitized = re.sub(r'https?://[^\s]+', '[URL_REDACTED]', sanitized)
    
    # Remove email-like patterns
    sanitized = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]', sanitized)
    
    # Remove potential tokens or API keys
    sanitized = re.sub(r'\b[A-Za-z0-9]{20,}\b', '[TOKEN_REDACTED]', sanitized)
    
    # Remove file paths
    sanitized = re.sub(r'/[^\s]+', '[PATH_REDACTED]', sanitized)
    
    # Truncate if too long
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."
    
    return sanitized


def _sanitize_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Sanitize context dictionary to remove sensitive information."""
    if not context:
        return {}
    
    sanitized = {}
    
    for key, value in context.items():
        # Skip sensitive keys
        if key.lower() in ['password', 'token', 'secret', 'key', 'api_key', 'auth', 'credential']:
            sanitized[key] = '[REDACTED]'
        elif isinstance(value, str):
            # Sanitize string values
            if len(value) > 100:
                sanitized[key] = value[:100] + "..."
            else:
                sanitized[key] = value
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_context(value)
        else:
            sanitized[key] = str(value)
    
    return sanitized


async def create_user_safe_error_message(
    error: Exception,
    default_message: str = "⚠️ An unexpected error occurred. Please try again later."
) -> str:
    """
    Create a user-safe error message.
    
    Args:
        error: The exception that occurred
        default_message: Default message to show if error can't be categorized
    
    Returns:
        Safe error message for users
    """
    try:
        error_type = _classify_error(error)
        
        if isinstance(error, UserFacingError):
            return error.message
        
        # User-friendly messages based on error type
        error_messages = {
            ErrorType.VALIDATION_ERROR: "⚠️ Invalid input. Please check your information and try again.",
            ErrorType.AUTHORIZATION_ERROR: "⛔ You don't have permission to perform this action.",
            ErrorType.RATE_LIMIT_ERROR: "⏱️ You're sending messages too quickly. Please wait a moment and try again.",
            ErrorType.DATABASE_ERROR: "⚠️ A technical error occurred. Please try again later.",
            ErrorType.TELEGRAM_API_ERROR: "⚠️ Could not send message. Please try again.",
            ErrorType.SECURITY_ERROR: "⚠️ A security issue was detected. Please contact support.",
            ErrorType.SYSTEM_ERROR: "⚠️ A system error occurred. Please try again later.",
            ErrorType.BUSINESS_LOGIC_ERROR: "⚠️ This action cannot be completed at this time.",
        }
        
        return error_messages.get(error_type, default_message)
        
    except Exception:
        # If anything goes wrong with error handling, return the default message
        return default_message


async def handle_telegram_error(update, error: Exception, context: Dict[str, Any]) -> None:
    """
    Handle Telegram API errors securely.
    
    Args:
        update: Telegram update object
        error: The Telegram error that occurred
        context: Additional context
    """
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None
    
    # Handle the error
    error_context = {
        "chat_id": chat_id,
        "context": context
    }
    
    await handle_error(error, error_context, user_id, "telegram_api")
    
    # Send user-friendly message if possible
    try:
        if update and update.effective_message:
            safe_message = await create_user_safe_error_message(
                error,
                "⚠️ Unable to process your request. Please try again."
            )
            await update.effective_message.reply_text(safe_message)
    except Exception:
        # If we can't send the error message, just log it
        pass


async def handle_database_error(error: Exception, operation: str, user_id: Optional[int] = None) -> None:
    """
    Handle database errors securely.
    
    Args:
        error: The database error that occurred
        operation: The database operation being performed
        user_id: User ID (if available)
    """
    error_context = {
        "operation": operation,
        "details": "Database operation failed"
    }
    
    await handle_error(error, error_context, user_id, "database")


# Decorator for error handling
def secure_error_handler(operation_name: str = None):
    """
    Decorator to automatically handle errors in handlers.
    
    Args:
        operation_name: Name of the operation for logging
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Extract update object for user ID
                update = None
                for arg in args:
                    if hasattr(arg, 'effective_user'):
                        update = arg
                        break
                
                user_id = update.effective_user.id if update and update.effective_user else None
                
                # Handle the error
                await handle_error(
                    e,
                    {"function": func.__name__},
                    user_id,
                    operation_name or func.__name__
                )
                
                # Return user-friendly response
                safe_message = await create_user_safe_error_message(e)
                
                if update and update.effective_message:
                    await update.effective_message.reply_text(safe_message)
                
                return None
                
        return wrapper
    return decorator