import os
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DATABASE_URL = _require_env('DATABASE_URL')
REDIS_URL = _require_env('REDIS_URL')
