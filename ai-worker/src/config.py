import os
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_float(name: str, default: float | None = None) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        if default is None:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name}: must be a number") from exc


def _parse_int(name: str, default: int | None = None) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        if default is None:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name}: must be an integer") from exc


REDIS_URL = _require_env('REDIS_URL')
DATABASE_URL = _require_env('DATABASE_URL')
AUTO_MATCH_DISTANCE_THRESHOLD = _parse_float('AUTO_MATCH_DISTANCE_THRESHOLD', default=0.5)
AUTO_MATCH_MIN_CONFIRMED = _parse_int('AUTO_MATCH_MIN_CONFIRMED', default=2)
