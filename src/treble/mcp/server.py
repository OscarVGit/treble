"""MCP server exposing Treble's procedures as tools.

Run over stdio with ``treble-mcp``. Each tool mirrors a CLI command and calls
the same shared operation, so an agent gets the same options and the same
safety gates as a human — including the confirmation step: a mutating or
destructive action with ``yes=false`` returns ``status=confirmation_required``
with a prompt, and the agent is expected to ask the human, then re-call with
``yes=true`` (equivalent to a human passing ``--yes``).

Client configuration (e.g. Claude Desktop / opencode), stdio transport:

    {
      "mcpServers": {
        "treble": { "command": "treble-mcp" }
      }
    }
"""

from __future__ import annotations

from treble.mcp import tools


def _server_class():
    """The MCP server class across SDK generations.

    mcp 1.x exposes ``FastMCP``; mcp 2.x renamed it to ``MCPServer`` (and
    ``mcp.server.fastmcp`` raises on import). Both share the ``tool()``/
    ``run()`` surface used here.
    """
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError:
        from mcp.server.mcpserver import MCPServer

        return MCPServer


def build_server():
    server = _server_class()("treble")

    @server.tool()
    def list_procedures() -> dict:
        """List the registered procedures (name, risk, description)."""
        return tools.list_procedures()

    @server.tool()
    def show_procedure(name: str) -> dict:
        """Show a procedure's stored definition (YAML)."""
        return tools.show_procedure(name)

    @server.tool()
    def explain_procedure(name: str) -> dict:
        """Show a procedure's exact command, risk and working directory."""
        return tools.explain_procedure(name)

    @server.tool()
    def run(intent: str, dry_run: bool = False, yes: bool = False) -> dict:
        """Run a registered procedure by natural-language intent or bare name.

        If the selected procedure is mutating or destructive and ``yes`` is
        false, this returns ``status=confirmation_required`` with a prompt and
        does not execute. Ask the human for consent, then re-call with
        ``yes=true``.
        """
        return tools.run_intent(intent, dry_run=dry_run, yes=yes)

    @server.tool()
    def test(name: str, dry_run: bool = False, yes: bool = False) -> dict:
        """Run a registered procedure by name (deterministic, no model)."""
        return tools.run_named(name, dry_run=dry_run, yes=yes)

    @server.tool()
    def remove(name: str, dry_run: bool = False, yes: bool = False) -> dict:
        """Remove a registered procedure (asks for confirmation unless yes)."""
        return tools.remove_procedure(name, dry_run=dry_run, yes=yes)

    @server.tool()
    def stats() -> dict:
        """Usage summary of past invocations (requests, hot/unused procedures)."""
        return tools.stats()

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
