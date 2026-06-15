"""Compatibility facade for bridge composition/wiring helpers.

Concrete builders live under arena.wiring.* so the composition layer can grow
without turning this facade into another monolith.
"""
from __future__ import annotations

from arena.wiring.core import (  # noqa: F401
    BridgeContainer,
    build_container,
    build_context_handlers,
    build_handler_registry,
    export_handler_attrs,
)
from arena.wiring.public import PublicWiringContext, build_public_handlers  # noqa: F401
from arena.wiring.platform import (  # noqa: F401
    AdminWiringContext,
    ServiceWiringContext,
    SystemWiringContext,
    build_admin_handlers,
    build_service_handlers,
    build_system_handlers,
)
