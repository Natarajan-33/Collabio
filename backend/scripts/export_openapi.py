"""Writes the API's OpenAPI schema to a file; the frontend generates its types from it.

    uv run python -m scripts.export_openapi ../frontend/lib/api/openapi.json

Building the schema needs no database or API key: `create_app()` only registers routes.
"""

import json
import sys
from pathlib import Path

from app.main import create_app


def export(path: Path) -> None:
    """Write `create_app().openapi()` to `path` as stable, LF-terminated JSON."""
    schema = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.export_openapi <output.json>")
        return 2
    export(Path(argv[1]))
    print(f"wrote {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
