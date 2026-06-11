"""API v2 compatibility domain package."""

from arena.api_v2.handlers import DEPRECATED_ENDPOINTS, V2Handlers, cfg_get_max_timeout, make_v2_handlers

__all__ = ["DEPRECATED_ENDPOINTS", "V2Handlers", "cfg_get_max_timeout", "make_v2_handlers"]
