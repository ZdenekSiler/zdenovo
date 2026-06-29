"""Rate limiting middleware using slowapi."""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Global limiter instance - use IP address as key
limiter = Limiter(key_func=get_remote_address)

# Common limits
LIMIT_COMMENT_SUBMIT = "5/minute"  # 5 comments per minute per IP
LIMIT_GENERATION = "1/minute"      # 1 generation per minute per IP (expensive)
