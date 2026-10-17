"""Delete expired YouTube discovery runs and cache rows.

Run this on idle installs. Discovery requests also purge as they run.

    uv run python scripts/purge_discovery.py
"""

from __future__ import annotations

from cineforge.runtime import get_runtime


def main() -> None:
    removed = get_runtime().discovery.purge()
    print(f"removed {removed} expired discovery rows")


if __name__ == "__main__":
    main()
