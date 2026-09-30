"""Deliberately broken MCP server -- official Python SDK 2.x (MCPServer).

TEST FIXTURE. Every defect is intentional and labelled with the audit rule it should
trigger. Lines marked NOT-A-FINDING look suspicious but are fine on SDK 2.x; the
auditor should leave them alone. Do not copy this code into a real server.
"""

from pathlib import Path

from mcp import MCPError
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import CallToolResult, TextContent

API_KEY = "demo-key-0000-not-a-real-secret"  # R9: literal credential in source
DATA_DIR = Path("/Users/alice/Documents/notes")  # R10: one developer's machine path

NOTES = {"welcome": "hello"}
_next_id = 1

mcp = MCPServer("fixture-bad-sdk2")

print("fixture-bad-sdk2 starting")  # R7 (Low): import-time stdout write; buffered, so it only surfaces after shutdown


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
    NOTES[name] = text
    return "saved"


@mcp.tool()
def create_note(text: str) -> int:
    """Create a note with a new numeric id."""
    global _next_id
    note_id = _next_id
    _next_id = note_id + 1  # R14: read-modify-write on shared state; 2.x runs sync tools on worker threads
    NOTES[str(note_id)] = text
    return note_id


@mcp.tool()
def connect_db() -> str:
    """Pretend to open a database connection."""
    # NOT-A-FINDING on 2.x (R4): unexpected exceptions are always masked (UnexpectedToolError)
    raise RuntimeError("connect failed: host db-internal-01.corp:5432 refused (service account svc_notes)")


CONFIG_FILE = Path(__file__).resolve().parent / "config" / "app.cfg"


@mcp.tool()
def load_config() -> str:
    """Read the server's config file."""
    try:
        return CONFIG_FILE.read_text()
    except OSError as e:
        raise ToolError(f"Failed to read config: {e}")  # R4: ToolError text is sent verbatim, so the internal path leaks


@mcp.tool()
def check_backend() -> str:
    """Ping the backend service."""
    raise MCPError(code=-32000, message="backend unavailable")  # R2: becomes a JSON-RPC error, not a tool result


@mcp.tool()
def strict_lookup(name: str) -> CallToolResult:
    """Look up a note, flagging a miss as an error."""
    if name not in NOTES:
        # NOT-A-FINDING on 2.x (R6): the constructor accepts the camelCase alias
        return CallToolResult(content=[TextContent(type="text", text="not found")], isError=True)
    return CallToolResult(content=[TextContent(type="text", text=NOTES[name])])


@mcp.tool()
def lookup_or_default(name: str) -> str:
    """Look up a note, falling back to a default."""
    result = strict_lookup(name)
    if result.isError:  # R6: 2.x models have no .isError attribute -- this raises AttributeError
        return "(default note)"
    return result.content[0].text


@mcp.tool()
def read_file(relative: str) -> str:
    """Read a file from the notes folder."""
    return (DATA_DIR / relative).read_text()  # R11: no resolve() / allowed-root check


@mcp.tool()
def debug_echo(msg: str) -> str:
    """Echo a message back."""
    print(f"debug: {msg}")  # R7 Low only (hygiene) on 2.x: stdout is diverted while serving
    return msg


@mcp.tool()
async def log_something(ctx: Context) -> str:
    """Emit a protocol-level log message."""
    await ctx.info("hello from the tool")  # R8: deprecated in spec 2026-07-28 (SEP-2577)
    return "logged"


@mcp.resource("notes://{name}")
def note_resource(name: str) -> str:
    """A note as a resource."""
    return NOTES.get(name, "")  # R13: a missing resource comes back as empty content


@mcp.resource("archive://{name}")
def archived_note(name: str) -> str:
    """An archived note as a resource."""
    if name not in NOTES:
        raise ResourceError(f"No archived note {name}")  # R13: plain ResourceError maps to -32603, not -32602
    return NOTES[name]


if __name__ == "__main__":
    mcp.run()
