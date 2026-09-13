"""
Rate Limiter Utility
In-memory sliding window rate limiter to mitigate bot flooding and spam.
"""

import time
from collections import defaultdict
from typing import Dict, List


class RateLimiter:
    """Sliding-window rate limiter per user ID."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 10):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.user_history: Dict[int, List[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        """Returns True if the request is permitted, False if rate limited."""
        now = time.time()
        timestamps = self.user_history[user_id]

        # Evict timestamps outside the sliding window
        valid_timestamps = [t for t in timestamps if now - t < self.window_seconds]
        self.user_history[user_id] = valid_timestamps

        if len(valid_timestamps) >= self.max_requests:
            return False

        self.user_history[user_id].append(now)
        return True

    def retry_after(self, user_id: int) -> int:
        """Calculates remaining seconds until a request is permitted."""
        now = time.time()
        timestamps = self.user_history.get(user_id, [])
        if not timestamps:
            return 0
        oldest = timestamps[0]
        remaining = int(self.window_seconds - (now - oldest))
        return max(remaining, 1)

    def reset(self, user_id: int) -> None:
        """Purges rate-limiting history for a user, allowing immediate requests."""
        if user_id in self.user_history:
            del self.user_history[user_id]


# Global rate limiters
command_rate_limiter = RateLimiter(max_requests=6, window_seconds=10)
# Supports repeatable job submissions while preventing automated microsecond flood spam
submission_rate_limiter = RateLimiter(max_requests=100, window_seconds=3600)
