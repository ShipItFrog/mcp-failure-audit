"""Deliberately broken MCP server -- official Python SDK 1.x (FastMCP).

TEST FIXTURE. Every defect is intentional and labelled with the audit rule it should
trigger. Lines marked NOT-A-FINDING look suspicious but are fine on SDK 1.x; the
auditor should leave them alone. Do not copy this code into a real server.
"""

from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, ErrorData, TextContent

API_KEY = "demo-key-0000-not-a-real-secret"  # R9: literal credential in source
DATA_DIR = Path("/Users/alice/Documents/notes")  # R10: one developer's machine path

NOTES = {"welcome": "hello"}

mcp = FastMCP("fixture-bad-sdk1")

print("fixture-bad-sdk1 starting")  # R7: stdout write at import time


@mcp.tool()
def get_note(name: str) -> dict:
    """Return a note by name."""
    if name not in NOTES:
        return {"ok": False, "error": f"No note named {name}"}  # R1: failure sent as success
    return {"ok": True, "text": NOTES[name]}


@mcp.tool()
def add_note(name: str, text: str) -> str:
    """Save a note."""
    if not name.strip():
        return "Error: name must not be empty"  # R3: validation failure sent as success
    NOTES[name] = text  # NOT-A-FINDING (R14 is 2.x-only): 1.x runs sync tools on the event loop
    return "saved"


@mcp.tool()
def connect_db() -> str:
    """Pretend to open a database connection."""
    # R4: SDK 1.x forwards str(e) to the model, so internal infrastructure details leak
    raise RuntimeError("connect failed: host db-internal-01.corp:5432 refused (service account svc_notes)")


CONFIG_FILE = Path(__file__).resolve().parent / "config" / "app.cfg"


@mcp.tool()
def load_config() -> str:
    """Read the server's config file."""
    try:
        return CONFIG_FILE.read_text()
    except OSError as e:
        raise ToolError(f"Failed to read config: {e}")  # R4: str(e) carries the server's internal file path


@mcp.tool()
def check_backend() -> str:
    """Ping the backend service."""
    # R2: protocol-level error raised inside a tool
    raise McpError(ErrorData(code=-32000, message="backend unavailable"))


@mcp.tool()
def strict_lookup(name: str) -> CallToolResult:
    """Look up a note, flagging a miss as an error."""
    if name not in NOTES:
        # R6: 2.x spelling on a 1.x model -- the error flag may be silently dropped
        return CallToolResult(content=[TextContent(type="text", text="not found")], is_error=True)
    return CallToolResult(content=[TextContent(type="text", text=NOTES[name])])


@mcp.tool()
def read_file(relative: str) -> str:
    """Read a file from the notes folder."""
    return (DATA_DIR / relative).read_text()  # R11: no resolve() / allowed-root check; R4: 1.x sends the attempted path in the error


@mcp.tool()
def debug_echo(msg: str) -> str:
    """Echo a message back."""
    print(f"debug: {msg}")  # R7: stdout write inside a handler
    return msg


@mcp.tool()
async def log_something(ctx: Context) -> str:
    """Emit a protocol-level log message."""
    await ctx.info("hello from the tool")  # NOT-A-FINDING on 1.x (R8 applies to 2.x)
    return "logged"


@mcp.resource("notes://{name}")
def note_resource(name: str) -> str:
    """A note as a resource."""
    return NOTES.get(name, "")  # R13: a missing resource comes back as empty content


if __name__ == "__main__":
    mcp.run()
