"""
Rate Limiter Utility
In-memory sliding window rate limiter to mitigate bot flooding and spam.
"""

import time
import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from utils.logger import logger
from utils.security import log_security_event


class SecurityRateLimiter:
    """Enhanced sliding-window rate limiter with security features."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 10):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.user_history: Dict[int, List[float]] = defaultdict(list)
        self.blocked_users: Dict[int, Tuple[float, str]] = {}  # user_id -> (unblock_time, reason)
        self.lock = asyncio.Lock()

    async def is_allowed(self, user_id: int, action: str = "general") -> bool:
        """Returns True if the request is permitted, False if rate limited."""
        async with self.lock:
            # Check if user is permanently blocked
            if user_id in self.blocked_users:
                unblock_time, reason = self.blocked_users[user_id]
                if time.time() < unblock_time:
                    return False
                else:
                    # Block expired, remove it
                    del self.blocked_users[user_id]
                    logger.info(f"Rate limit block expired for user {user_id}")

            now = time.time()
            timestamps = self.user_history[user_id]

            # Evict timestamps outside the sliding window
            valid_timestamps = [t for t in timestamps if now - t < self.window_seconds]
            self.user_history[user_id] = valid_timestamps

            if len(valid_timestamps) >= self.max_requests:
                # Auto-block users who exceed limits significantly
                if len(valid_timestamps) >= self.max_requests * 2:
                    block_duration = 300  # 5 minutes
                    self.blocked_users[user_id] = (now + block_duration, f"Rate limit exceeded for {action}")
                    logger.warning(f"User {user_id} auto-blocked for exceeding rate limits on {action}")
                    log_security_event("RATE_LIMIT_AUTO_BLOCK", user_id, {
                        "action": action,
                        "attempts": len(valid_timestamps),
                        "max_allowed": self.max_requests,
                        "block_duration": block_duration
                    })
                    return False

                return False

            self.user_history[user_id].append(now)
            return True

    async def retry_after(self, user_id: int) -> int:
        """Calculates remaining seconds until a request is permitted."""
        async with self.lock:
            now = time.time()
            timestamps = self.user_history.get(user_id, [])
            if not timestamps:
                return 0
            oldest = timestamps[0]
            remaining = int(self.window_seconds - (now - oldest))
            return max(remaining, 1)

    async def reset(self, user_id: int) -> None:
        """Purges rate-limiting history for a user, allowing immediate requests."""
        async with self.lock:
            if user_id in self.user_history:
                del self.user_history[user_id]
            if user_id in self.blocked_users:
                del self.blocked_users[user_id]

    async def get_status(self, user_id: int) -> Dict[str, any]:
        """Get current rate limiting status for a user."""
        async with self.lock:
            now = time.time()
            timestamps = self.user_history.get(user_id, [])
            valid_timestamps = [t for t in timestamps if now - t < self.window_seconds]
            
            return {
                "user_id": user_id,
                "current_count": len(valid_timestamps),
                "max_requests": self.max_requests,
                "window_seconds": self.window_seconds,
                "is_blocked": user_id in self.blocked_users,
                "retry_after": await self.retry_after(user_id)
            }

    async def block_user(self, user_id: int, duration: int = 300, reason: str = "Manual block") -> None:
        """Manually block a user from rate-limited actions."""
        async with self.lock:
            unblock_time = time.time() + duration
            self.blocked_users[user_id] = (unblock_time, reason)
            logger.info(f"User {user_id} manually blocked for {duration} seconds. Reason: {reason}")
            log_security_event("RATE_LIMIT_MANUAL_BLOCK", user_id, {
                "duration": duration,
                "reason": reason
            })

    async def unblock_user(self, user_id: int) -> None:
        """Manually unblock a user."""
        async with self.lock:
            if user_id in self.blocked_users:
                del self.blocked_users[user_id]
                logger.info(f"User {user_id} unblocked from rate limiting")
                log_security_event("RATE_LIMIT_UNBLOCK", user_id, {})


class RateLimitManager:
    """Manages multiple rate limiters for different actions."""

    def __init__(self):
        self.limiters = {
            "commands": SecurityRateLimiter(max_requests=6, window_seconds=10),
            "submissions": SecurityRateLimiter(max_requests=5, window_seconds=60),  # 5 submissions per minute
            "messages": SecurityRateLimiter(max_requests=20, window_seconds=30),  # 20 messages per 30 seconds
            "admin_actions": SecurityRateLimiter(max_requests=15, window_seconds=60),  # 15 admin actions per minute
            "appeals": SecurityRateLimiter(max_requests=3, window_seconds=300),  # 3 appeals per 5 minutes
            "reports": SecurityRateLimiter(max_requests=5, window_seconds=60),  # 5 reports per minute
        }

    async def check_limit(self, user_id: int, action_type: str) -> Tuple[bool, Optional[int]]:
        """Check if user is allowed to perform an action.
        Returns (allowed, retry_after_seconds)"""
        limiter = self.limiters.get(action_type)
        if not limiter:
            logger.warning(f"Unknown rate limit action type: {action_type}")
            return True, None

        allowed = await limiter.is_allowed(user_id, action_type)
        if not allowed:
            retry_after = await limiter.retry_after(user_id)
            return False, retry_after
        
        return True, None

    async def get_user_status(self, user_id: int) -> Dict[str, Dict[str, any]]:
        """Get rate limiting status for all action types for a user."""
        status = {}
        for action_type, limiter in self.limiters.items():
            status[action_type] = await limiter.get_status(user_id)
        return status

    async def reset_user_limits(self, user_id: int) -> None:
        """Reset all rate limits for a user."""
        for limiter in self.limiters.values():
            await limiter.reset(user_id)

    async def block_user(self, user_id: int, duration: int = 300, reason: str = "Security violation") -> None:
        """Block user across all rate limiters."""
        for limiter in self.limiters.values():
            await limiter.block_user(user_id, duration, reason)

    async def unblock_user(self, user_id: int) -> None:
        """Unblock user across all rate limiters."""
        for limiter in self.limiters.values():
            await limiter.unblock_user(user_id)


# Global rate limiter instance
rate_limiter_manager = RateLimitManager()

# Backward compatibility
command_rate_limiter = rate_limiter_manager.limiters["commands"]
submission_rate_limiter = rate_limiter_manager.limiters["submissions"]
