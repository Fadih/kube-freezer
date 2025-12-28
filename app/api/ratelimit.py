"""Rate limiting for API endpoints"""
import time
import logging
from typing import Dict, Tuple
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self, requests_per_minute: int = 60):
        """
        Initialize rate limiter
        
        Args:
            requests_per_minute: Maximum requests per minute per client
        """
        self.requests_per_minute = requests_per_minute
        self._requests: Dict[str, list] = defaultdict(list)
        self._cleanup_interval = 300  # Clean up every 5 minutes
        self._last_cleanup = time.time()
    
    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        """
        Check if request is allowed
        
        Args:
            client_id: Client identifier (IP, user, etc.)
        
        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        now = time.time()
        
        # Cleanup old entries periodically
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()
            self._last_cleanup = now
        
        # Get requests in the last minute
        cutoff = now - 60
        recent_requests = [
            req_time for req_time in self._requests[client_id]
            if req_time > cutoff
        ]
        
        # Update requests list
        self._requests[client_id] = recent_requests
        
        # Check if limit exceeded
        if len(recent_requests) >= self.requests_per_minute:
            remaining = 0
            return False, remaining
        
        # Add current request
        self._requests[client_id].append(now)
        remaining = self.requests_per_minute - len(self._requests[client_id])
        
        return True, remaining
    
    def _cleanup(self):
        """Clean up old request records"""
        now = time.time()
        cutoff = now - 120  # Keep last 2 minutes
        
        for client_id in list(self._requests.keys()):
            self._requests[client_id] = [
                req_time for req_time in self._requests[client_id]
                if req_time > cutoff
            ]
            
            # Remove empty entries
            if not self._requests[client_id]:
                del self._requests[client_id]


# Global rate limiter instance
_rate_limiter = RateLimiter(requests_per_minute=60)


def get_client_id(request) -> str:
    """Get client identifier from request"""
    # Try to get from X-Forwarded-For header (if behind proxy)
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Take first IP in chain
        return forwarded.split(",")[0].strip()
    
    # Fall back to direct client IP
    if hasattr(request.client, "host"):
        return request.client.host
    
    return "unknown"


def check_rate_limit(request) -> bool:
    """
    Check rate limit for request
    
    Args:
        request: FastAPI request object
    
    Returns:
        True if allowed, False if rate limited
    
    Raises:
        HTTPException: If rate limit exceeded
    """
    from fastapi import HTTPException
    
    client_id = get_client_id(request)
    allowed, remaining = _rate_limiter.is_allowed(client_id)
    
    if not allowed:
        logger.warning(f"Rate limit exceeded for client {client_id}")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {_rate_limiter.requests_per_minute} requests per minute.",
            headers={
                "X-RateLimit-Limit": str(_rate_limiter.requests_per_minute),
                "X-RateLimit-Remaining": "0",
                "Retry-After": "60"
            }
        )
    
    return True

