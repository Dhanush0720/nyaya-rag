"""Settings, read from environment variables or a .env file in the project root."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


class Settings:
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db: str = os.getenv("MONGODB_DB", "nyaya")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_embed_model: str = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
    gemini_gen_model: str = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash")
    embed_dim: int = int(os.getenv("EMBED_DIM", "768"))

    jwt_secret: str = os.getenv("JWT_SECRET") or secrets.token_urlsafe(32)
    jwt_secret_is_ephemeral: bool = not os.getenv("JWT_SECRET")
    token_hours: int = int(os.getenv("TOKEN_HOURS", "12"))

    max_upload_bytes: int = 5 * 1024 * 1024
    max_chars: int = 300_000


settings = Settings()
