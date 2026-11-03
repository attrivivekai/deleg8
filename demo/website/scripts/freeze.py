"""Export a static snapshot of every parameter-less GET HTML page (used for GitHub Pages).

Usage: BASE_PATH=/deleg8-website STATIC_MODE=1 python scripts/freeze.py dist
New pages are picked up automatically, no need to register them here.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STATIC_MODE", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import BASE_DIR, app  # noqa: E402


def html_routes() -> list[str]:
    paths = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods:
            continue
        if "{" in route.path or route.path.startswith("/api"):
            continue
        paths.append(route.path)
    return sorted(paths)


def main(out: str = "dist") -> None:
    out_dir = Path(out)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    client = TestClient(app)
    for path in html_routes():
        res = client.get(path)
        res.raise_for_status()
        target = out_dir / path.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(res.text)
        print(f"froze {path} -> {target}")
    shutil.copytree(BASE_DIR / "static", out_dir / "static")
    (out_dir / ".nojekyll").touch()


if __name__ == "__main__":
    main(*sys.argv[1:])
