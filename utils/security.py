"""
Security and Authorization Module
Centralized security functions for the Telegram bot.
Provides authorization checks, input validation, and security utilities.
"""

import re
import ipaddress
from typing import Optional, List, Tuple
from config import settings
from utils.logger import logger


class SecurityError(Exception):
    """Base exception for security violations."""
    pass


class AuthorizationError(SecurityError):
    """Exception for authorization failures."""
    pass


class InputValidationError(SecurityError):
    """Exception for input validation failures."""
    pass


def is_owner(user_id: int) -> bool:
    """Check if user ID is the owner (highest authority)."""
    return settings.is_owner(user_id)


def is_admin(user_id: int) -> bool:
    """Check if user ID has admin privileges (including owner)."""
    return settings.is_admin(user_id)


def is_authorized_admin(user_id: int) -> bool:
    """Verify caller is authorized for admin operations."""
    if not user_id:
        return False
    return is_admin(user_id)


def require_owner(user_id: int) -> None:
    """Require owner privileges - raises AuthorizationError if not owner."""
    if not is_owner(user_id):
        raise AuthorizationError("Owner access required")


def require_admin(user_id: int) -> None:
    """Require admin privileges - raises AuthorizationError if not admin."""
    if not is_admin(user_id):
        raise AuthorizationError("Admin access required")


def validate_user_id(user_id: int) -> bool:
    """Validate Telegram user ID format."""
    if not isinstance(user_id, int):
        return False
    return 1 <= user_id <= 2**63 - 1  # Valid Telegram user ID range


def validate_chat_id(chat_id: int) -> bool:
    """Validate Telegram chat ID format."""
    if not isinstance(chat_id, int):
        return False
    return chat_id > 0 or chat_id < -1000000000000  # Positive or supergroup/channel IDs


def validate_job_id(job_id: int) -> bool:
    """Validate job ID format."""
    if not isinstance(job_id, int):
        return False
    return job_id > 0


def validate_callback_data(callback_data: str) -> bool:
    """Validate callback data format to prevent injection."""
    if not callback_data or not isinstance(callback_data, str):
        return False
    
    # Allow only safe characters: letters, numbers, underscores, hyphens, colons
    return bool(re.match(r'^[a-zA-Z0-9_:-]+$', callback_data))


def validate_url(url: str) -> Tuple[bool, str]:
    """
    Validate URL for SSRF protection.
    Returns (is_valid, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "URL is required"
    
    url = url.strip()
    if not url:
        return False, "URL cannot be empty"
    
    # Check for valid URL scheme
    if not url.startswith(('http://', 'https://')):
        return False, "URL must start with http:// or https://"
    
    # Parse URL
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        
        if not parsed.netloc:
            return False, "Invalid URL format"
        
        # Check for localhost/internal IPs
        hostname = parsed.hostname
        if hostname:
            # Block localhost variants
            if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '[::1]'):
                return False, "Blocked localhost access"
            
            # Check for private IP addresses
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback:
                    return False, "Blocked private IP address"
            except ValueError:
                # Not an IP address, continue
                pass
        
        # Block dangerous protocols
        if parsed.scheme not in ('http', 'https'):
            return False, f"Blocked protocol: {parsed.scheme}"
        
        # Check for suspicious patterns
        if '..' in url or url.startswith('//'):
            return False, "Suspicious URL pattern detected"
        
    except Exception as e:
        return False, f"URL validation error: {str(e)}"
    
    return True, "URL is valid"


def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email format."""
    if not email or not isinstance(email, str):
        return False, "Email is required"
    
    email = email.strip()
    if not email:
        return False, "Email cannot be empty"
    
    # Basic email format validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    # Check for suspicious patterns
    if '@' not in email:
        return False, "Email must contain @ symbol"
    
    if len(email) > 254:
        return False, "Email too long"
    
    return True, "Email is valid"


def validate_company_name(name: str) -> Tuple[bool, str]:
    """Validate company name format."""
    if not name or not isinstance(name, str):
        return False, "Company name is required"
    
    name = name.strip()
    if not name:
        return False, "Company name cannot be empty"
    
    if len(name) < 2:
        return False, "Company name too short"
    
    if len(name) > 100:
        return False, "Company name too long"
    
    # Check for suspicious patterns
    if any(char in name for char in ['<', '>', '&', "'", '"', '`']):
        return False, "Invalid characters in company name"
    
    return True, "Company name is valid"


def sanitize_input(text: str, max_length: int = 2000) -> str:
    """Sanitize user input to prevent injection and limit length."""
    if not text or not isinstance(text, str):
        return ""
    
    # Truncate to max length
    if len(text) > max_length:
        text = text[:max_length]
    
    # Remove potentially dangerous characters
    text = text.replace('\x00', '')  # Null bytes
    text = text.replace('\r\n', '\n')  # Normalize line endings
    text = text.replace('\r', '\n')
    
    return text.strip()


def validate_job_submission_data(job_data: dict) -> Tuple[bool, List[str]]:
    """
    Validate complete job submission data.
    Returns (is_valid, error_list)
    """
    errors = []
    
    # Validate required fields
    required_fields = ['company_name', 'company_website', 'contact_email', 'job_title']
    for field in required_fields:
        if field not in job_data or not job_data[field]:
            errors.append(f"{field.replace('_', ' ')} is required")
    
    # Validate individual fields
    if 'company_name' in job_data:
        valid, error = validate_company_name(job_data['company_name'])
        if not valid:
            errors.append(error)
    
    if 'company_website' in job_data:
        valid, error = validate_url(job_data['company_website'])
        if not valid:
            errors.append(error)
    
    if 'contact_email' in job_data:
        valid, error = validate_email(job_data['contact_email'])
        if not valid:
            errors.append(error)
    
    if 'job_title' in job_data:
        if not job_data['job_title'] or len(job_data['job_title']) < 5:
            errors.append("Job title must be at least 5 characters long")
        if len(job_data['job_title']) > 200:
            errors.append("Job title too long")
    
    return len(errors) == 0, errors


def log_security_event(event_type: str, user_id: int, details: dict = None) -> None:
    """Log security events for audit purposes."""
    try:
        log_data = {
            'event_type': event_type,
            'user_id': user_id,
            'timestamp': None,  # Will be added by logger
        }
        if details:
            # Sanitize details before logging
            sanitized_details = {}
            for key, value in details.items():
                if isinstance(value, str):
                    sanitized_details[key] = sanitize_input(value, 500)
                else:
                    sanitized_details[key] = value
            log_data['details'] = sanitized_details
        
        logger.info(f"Security event: {event_type} by user {user_id}")
        
        # Log to audit log if database is available
        try:
            from database.crud import create_audit_entry
            import asyncio
            
            async def log_to_audit():
                await create_audit_entry(
                    user_id=user_id,
                    action=event_type,
                    target_details=str(details) if details else None
                )
            
            # Run in background to avoid blocking
            asyncio.create_task(log_to_audit())
            
        except Exception as e:
            logger.debug(f"Could not log to audit database: {e}")
            
    except Exception as e:
        logger.error(f"Failed to log security event: {e}")


def check_rate_limit(user_id: int, action: str) -> bool:
    """Check if user is rate limited for a specific action."""
    try:
        from utils.rate_limiter import submission_rate_limiter
        
        if hasattr(submission_rate_limiter, 'is_allowed'):
            return submission_rate_limiter.is_allowed(user_id)
        
        return True  # No rate limiting available
        
    except Exception as e:
        logger.warning(f"Rate limit check failed for user {user_id}: {e}")
        return True  # Allow if check fails


def validate_admin_callback(user_id: int, callback_data: str, job_id: Optional[int] = None) -> Tuple[bool, str]:
    """
    Validate admin callback to prevent privilege escalation.
    Returns (is_valid, error_message)
    """
    try:
        # Check authorization first
        if not is_authorized_admin(user_id):
            return False, "Unauthorized access"
        
        # Validate callback data format
        if not validate_callback_data(callback_data):
            return False, "Invalid callback data"
        
        # Validate job ID if provided
        if job_id is not None:
            if not validate_job_id(job_id):
                return False, "Invalid job ID"
        
        # Check for common admin actions
        admin_actions = ['approve', 'reject', 'ban', 'unban', 'restrict', 'unrestrict', 'feature']
        action = callback_data.split(':')[0] if ':' in callback_data else callback_data
        
        if action not in admin_actions:
            return False, f"Invalid admin action: {action}"
        
        return True, "Callback validation passed"
        
    except Exception as e:
        logger.error(f"Admin callback validation error: {e}")
        return False, "Validation error"


# Security decorators for handlers
def require_owner_handler(func):
    """Decorator for handlers that require owner privileges."""
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            await update.message.reply_text("⚠️ <i>User identification error.</i>", parse_mode="HTML")
            return
        
        try:
            require_owner(user_id)
            return await func(update, context, *args, **kwargs)
        except AuthorizationError:
            await update.message.reply_text("⛔ <i>Access restricted to owner only.</i>", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Owner handler error: {e}")
            await update.message.reply_text("⚠️ <i>An internal error occurred.</i>", parse_mode="HTML")
    
    return wrapper


def require_admin_handler(func):
    """Decorator for handlers that require admin privileges."""
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            await update.message.reply_text("⚠️ <i>User identification error.</i>", parse_mode="HTML")
            return
        
        try:
            require_admin(user_id)
            return await func(update, context, *args, **kwargs)
        except AuthorizationError:
            await update.message.reply_text("⛔ <i>Access restricted to authorized administrators.</i>", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Admin handler error: {e}")
            await update.message.reply_text("⚠️ <i>An internal error occurred.</i>", parse_mode="HTML")
    
    return wrapper