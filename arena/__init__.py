"""Arena Unified Bridge — internal package.

The bridge began life as a single ``unified_bridge.py`` file. It is being split
into focused modules under this package while keeping ``unified_bridge.py`` as a
thin façade that re-exports public names, so the runtime entrypoint
(``python unified_bridge.py serve``) and existing imports keep working unchanged.
"""
