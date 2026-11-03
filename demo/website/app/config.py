import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    base_path: str
    static_mode: bool


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./deleg8.db"),
        # Prefix for all links; set when the site is served from a sub-path (GitHub Pages).
        base_path=os.getenv("BASE_PATH", "").rstrip("/"),
        # True when exporting a static snapshot: forms are disabled client-side.
        static_mode=os.getenv("STATIC_MODE", "0") == "1",
    )
