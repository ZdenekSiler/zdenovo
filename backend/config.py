import os
from pathlib import Path


def read_secret(name: str, env_fallback: str = "") -> str:
    """Read a secret from /run/secrets/<name> (prod) or fall back to env var (dev)."""
    secret_path = Path(f"/run/secrets/{name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    return os.environ.get(env_fallback or name.upper(), "")
