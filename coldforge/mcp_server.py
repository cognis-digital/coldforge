"""COLDFORGE MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations

from coldforge.core import scan, to_json


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-coldforge[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-coldforge[mcp]'")
        return 1
    app = FastMCP("coldforge")

    @app.tool()
    def coldforge_scan(target: str) -> str:
        """Render personalized cold-outreach sequences from templates + contacts CSV.

        Returns JSON findings.
        """
        return to_json(scan(target))

    app.run()
    return 0
