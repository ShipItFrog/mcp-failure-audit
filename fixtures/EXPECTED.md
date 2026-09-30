# Fixture answer key

What the auditor should report for each fixture. Used to score audit runs in `TEST-LOG.md`:

- **True positive** — an expected finding reported under the right rule (or an accepted alternative), at a severity inside the expected range.
- **False positive** — anything reported for a line under "Must not be flagged", or any finding not in this file that doesn't hold up on inspection.
- **Missed** — an expected finding not reported.

**Audit runs must use label-stripped copies.** The fixtures carry `# R<n>` and `NOT-A-FINDING` comments for human readers; an auditor that can read them is being shown the answers. Score only runs on copies with those comments and the module docstrings removed.

"Observed" cells come from `probe.py` (results in each folder's `probe-results*.json`); rows marked *static* or *source only* have no runtime observation.

## `py-sdk1/bad_server.py` — SDK 1.30.0 (`mcp==1.30.0`)

| Rule | Where | Expected severity | Observed |
|---|---|---|---|
| R1 | `get_note` — returns `{"ok": False, ...}` | Medium | `isError=False` |
| R3 | `add_note` — returns `"Error: name must not be empty"` | Medium | `isError=False` |
| R4 | `connect_db` — uncaught exception with internal details | Medium–High | internal host:port and service-account name sent to the model |
| R4 | `load_config` — `ToolError(f"...{e}")` | Medium | the server's internal file path sent to the model |
| R4 | `read_file` — file I/O with no sanitizing `try` | Medium | full attempted path, including `DATA_DIR` and `..\..\`, sent to the model |
| R11 | `read_file` — `DATA_DIR / relative` | High | *static* |
| R2 | `check_backend` — `raise McpError(...)` | Low | `isError=True`, error code lost |
| R6 | `strict_lookup` — `CallToolResult(..., is_error=True)` | High | `isError=False`; `is_error: true` goes out as an ignored extra key |
| R7 | module level — `print("fixture-bad-sdk1 starting")` | High | flushed onto the wire mid-session together with the 9 KB print |
| R7 | `debug_echo` — `print(...)` in handler | High | 9 KB message: response lost, client timed out |
| R13 | `note_resource` — returns `""` when missing | Medium | 1 content item, no error |
| R9 | `API_KEY = "demo-key-..."` | High | *static* — judged on the pattern, not on how real the value looks |
| R10 | `DATA_DIR = Path("/Users/alice/...")` | Low | *static* |

**Must not be flagged**

| Line | Why |
|---|---|
| `add_note` — `NOTES[name] = text` (R14) | R14 is 2.x-only; 1.x runs sync tools serially on the event loop |
| `log_something` — `await ctx.info(...)` (R8) | not deprecated in 1.x |
| `requirements.txt` (R15) | 1.x imports, pinned `mcp==1.30.0` — consistent |

## `py-sdk2/bad_server.py` — SDK 2.2.0 (`mcp==2.2.0`)

| Rule | Where | Expected severity | Observed |
|---|---|---|---|
| R1 | `get_note` | Medium | `isError=False` |
| R3 | `add_note` | Medium | `isError=False` |
| R14 | `create_note` — `global _next_id` read-modify-write in a sync tool | Medium–High | *source only* (a race needs concurrent calls) |
| R4 | `load_config` — `ToolError(f"...{e}")` | Medium | the server's internal file path sent to the model |
| R2 | `check_backend` — `raise MCPError(...)` | Medium | JSON-RPC error `-32000`, no tool result |
| R6 | `lookup_or_default` — reads `result.isError` | Medium | masked error on every call (missing and existing note) |
| R11 | `read_file` | High | *static* (error text masked on 2.x) |
| R7 | module level — `print("fixture-bad-sdk2 starting")` | Low | buffered; reached the real stdout only after shutdown |
| R8 | `log_something` — `await ctx.info(...)` | Low | 3 deprecation warnings on stderr |
| R13 | `note_resource` — returns `""` when missing | Medium | 1 content item, no error |
| R13 | `archived_note` — `raise ResourceError(...)` for a missing item | Low | JSON-RPC error `-32603` instead of `-32602` |
| R9 | `API_KEY` | High | *static* |
| R10 | `DATA_DIR` | Low | *static* |

**Must not be flagged**

| Line | Why |
|---|---|
| `connect_db` — uncaught exception with internal details (R4) | always masked on 2.x high-level tools: the model sees only `Error executing tool connect_db` |
| `strict_lookup` — `CallToolResult(..., isError=True)` (R6) | the 2.x constructor accepts the camelCase alias; the flag is set |
| `add_note` — `NOTES[name] = text` (R14) | a single atomic dict assignment |
| `lookup_or_default` — `return "(default note)"` (R1) | returning a default is the tool's documented purpose |
| `debug_echo` — `print(...)` in handler (R7) | kept off the wire while serving; **Low** (hygiene) is acceptable, Medium/High is a false positive |
| `requirements.txt` (R15) | 2.x imports, pinned `mcp==2.2.0` — consistent |

## `py-sdk2/lowlevel_server.py` — SDK 2.2.0, low-level `Server`

| Rule | Where | Expected severity | Observed |
|---|---|---|---|
| R5 | `call_tool` — no `try/except` | High | JSON-RPC error `0: 'pear'` (raw exception text) |
| R3 | `call_tool` — `params.arguments["item"]` never validated | Medium | missing argument → JSON-RPC error `0: "'item'"`; **also satisfied by** an R5 finding that names the missing validation |

**Must not be flagged**

| Line | Why |
|---|---|
| `requirements.txt` (R15) | the low-level `Server(..., on_call_tool=...)` form is 2.x, pinned `mcp==2.2.0` — consistent |
