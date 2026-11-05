"""Small runtime switches that must stay safe to import during health checks."""
import os


def semantic_cache_enabled() -> bool:
    """Return whether optional Chroma answer caching and local ONNX are enabled."""
    return os.getenv("SEMANTIC_CACHE", "off").strip().lower() in {"1", "true", "yes", "on"}
