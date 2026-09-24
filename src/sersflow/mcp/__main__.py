"""Console entry: ``sersflow-mcp``."""

from __future__ import annotations

from sersflow.mcp.runtime import configure_stderr_logging
from sersflow.mcp.server import create_server


def main() -> None:
    configure_stderr_logging()
    create_server().run()


if __name__ == "__main__":
    main()
