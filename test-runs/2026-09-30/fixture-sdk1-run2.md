Here is the auditor's report. It's a read-only audit and no files were changed.

# MCP failure-handling audit: py-sdk1

I found 12 defects: 4 High, 6 Medium and 2 Low.

## Target and SDK detected

- **Target:** `…\scratchpad\audit-run\blind\py-sdk1`
- **Files:** there are only two, `server.py` and `requirements.txt`. The directory has no tests, examples, client scripts, dotfiles or `.gitignore`, so nothing was excluded.
- **Entry point:** `server.py:20` `mcp = FastMCP("notes-sdk1")`, started at `server.py:104` `mcp.run()`.
- **Transport:** stdio, because `run()` is called with no argument. R7 applies and R12 does not.
- **SDK:** official `mcp` 1.x. The evidence is `server.py:10` `from mcp.server.fastmcp import Context, FastMCP`, `:11` `from mcp.server.fastmcp.exceptions import ToolError`, and `:12` `from mcp.shared.exceptions import McpError`. The file has no 2.x signals.
- **Pin (R15):** `requirements.txt:1` `mcp==1.30.0`. This is an exact pin to the baseline version, so the 1.x rules apply without version caveats.

## Findings

### High

**1. R11: a tool argument controls file access** at `server.py:80`
```python
return (DATA_DIR / relative).read_text()
```
There is no `resolve()` and no allowed-root check. `relative="../../../.ssh/id_rsa"` escapes the folder. An absolute path is worse: `DATA_DIR / "/etc/passwd"`, or `"C:\\Windows\\win.ini"` on Windows, throws `DATA_DIR` away completely. So the model, or a prompt injection, can read any file the server process can read.
*Fix:* `p = (DATA_DIR / relative).resolve()`, then `if not p.is_relative_to(DATA_DIR.resolve()): raise ToolError("path outside allowed folder")`.

**2. R6: the error flag uses the 2.x spelling on 1.x** at `server.py:73`
```python
return CallToolResult(content=[TextContent(type="text", text="not found")], is_error=True)
```
1.30.0 silently accepts `is_error` as an unknown extra key. The response goes out as `isError: false` with a stray `is_error: true` that clients ignore. The model sees a successful call with the text "not found", which is the opposite of what the tool meant.
*Fix:* use `isError=True`, or better, `raise ToolError(f"No note named {name}")`.

**3. R7: stdout writes on the stdio transport**, mainly `server.py:86`, plus `server.py:22`
```python
print(f"debug: {msg}")          # :86, inside debug_echo
print("notes-sdk1 starting")    # :22, at import time
```
1.x does nothing to divert stdout. Both prints go into the same buffer as the JSON-RPC frames. The caller controls `msg`, and once about 8 KB builds up, the flush glues the print text onto a JSON-RPC frame. That call's response is lost and the client times out. The rule's 1.30.0 probe of this pattern with a 9 KB message got no response. The 20-byte import-time print at `:22` does no harm by itself, but it adds to the same buffer.
*Fix:* `print(..., file=sys.stderr)`, or stdlib `logging` configured before `FastMCP(...)` is constructed.

**4. R9: hardcoded secret** at `server.py:15`
```python
API_KEY = "demo-key-0000-not-a-real-secret"
```
This is a credential-shaped literal assigned to a key name. The rule flags it even when the value looks like a demo. It is never used in `server.py`, but it shows the pattern that a real key would follow into the repository.
*Fix:* delete it, or read it with `os.environ["NOTES_API_KEY"]` and document the variable.

### Medium

**5. R1: a failed lookup is returned as a normal result** at `server.py:29`
```python
return {"ok": False, "error": f"No note named {name}"}
```
This is a lookup by exact identifier that finds nothing, and it goes out with `isError: false`. The rule rates this Medium rather than High only because the payload has readable error text; the model has to read `ok: false` to notice the failure.
*Fix:* `raise ToolError(f"No note named {name}")`.

**6. R3: an input-validation failure is returned as a normal result** at `server.py:37`
```python
return "Error: name must not be empty"
```
The rejection goes out with `isError: false`, so the model or client may treat it as success. The text does say "Error", which keeps this at Medium. This is R3 rather than R1 because R3 is the more specific rule.
*Fix:* `raise ToolError("invalid name: must not be empty")`, or use `name: str = Field(min_length=1)` with a strip validator.

**7. R4: an uncaught exception leaks internal infrastructure** at `server.py:46`
```python
raise RuntimeError("connect failed: host db-internal-01.corp:5432 refused (service account svc_notes)")
```
1.x sends this to the model word for word: `Error executing tool connect_db: connect failed: host db-internal-01.corp:5432 refused (service account svc_notes)`. That exposes an internal hostname, a port and a service-account name, and nothing is logged on the server. I rated it Medium because the text has no password, token or full connection string.
*Fix:* `logger.exception(...)` to stderr, then `raise ToolError("Database unavailable; see server logs")`.

**8. R4: `str(e)` is put into a ToolError** at `server.py:58`
```python
raise ToolError(f"Failed to read config: {e}")
```
The text of an `OSError` includes the full resolved path, for example `[Errno 2] No such file or directory: 'C:\\Users\\...\\config\\app.cfg'`. That reveals the server's install location and the OS username. `config/app.cfg` does not exist in the target (I checked by reading it directly), so as shipped this leak happens on every call to `load_config`.
*Fix:* `logger.exception("config read failed")`, then `raise ToolError("Config unavailable; see server logs")`.

**9. R4: file work with no sanitizing `try`** at `server.py:80`
```python
return (DATA_DIR / relative).read_text()
```
This is a different defect on the same line as finding 1. `FileNotFoundError`, `IsADirectoryError`, `PermissionError` and `UnicodeDecodeError` all reach the model verbatim, including the absolute path (`/Users/alice/Documents/notes/...`). That also tells an attacker how the directory is laid out, which helps with the traversal in finding 1.
*Fix:* `except ToolError: raise`, then `except Exception: logger.exception(...); raise ToolError("Could not read file")`.

**10. R13: a missing resource comes back as empty content** at `server.py:100`
```python
return NOTES.get(name, "")
```
`notes://missing` is a successful read with one empty content item, which looks the same as a real empty note. The spec expects an error here.
*Fix (1.x):* raise an exception such as `raise ValueError(f"Unknown note: {name}")`. On 1.x the error code will be 0 and the message goes to the client, so keep it free of internal detail.

### Low

**11. R2: a protocol error is raised inside a tool** at `server.py:65`
```python
raise McpError(ErrorData(code=-32000, message="backend unavailable"))
```
On 1.x this is wrapped into `isError: true` with the text "backend unavailable", so the model still sees a failure. Only the `-32000` code is lost.
*Fix:* `raise ToolError("backend unavailable")`.

**12. R10: hardcoded path into one developer's home** at `server.py:16`
```python
DATA_DIR = Path("/Users/alice/Documents/notes")
```
This path only works on one machine. Anywhere else, every `read_file` call fails, and the error leaks this path (finding 9).
*Fix:* take it from an environment variable or config, or use a path relative to the project.

## Checked and clean

- **R15:** `mcp==1.30.0` is an exact pin that matches the 1.x code.
- **R1, other tools:** `load_config`, `connect_db`, `check_backend`, `debug_echo` and `log_something` do not return failures as normal results. `get_note` is annotated with bare `dict` but returns a dict on both branches, so the `None` caveat does not apply.
- **R5:** there are no low-level handlers (`@server.call_tool()`, `read_resource()`, `get_prompt()` or `list_*()`). Everything goes through FastMCP.
- **Rules that do not apply to this server:**
  - R8 is 2.x only. On 1.x `ctx.info` is not deprecated, and `server.py:93` awaits it correctly.
  - R14 is 2.x only. On 1.x sync tools run one at a time on the event loop, so the `NOTES` mutation in `add_note` does not race.
  - R12 is for HTTP only, and this server uses stdio.

## Could not verify

- **The contents of `config/app.cfg`.** It is not in the target. If it exists wherever the server is deployed, `load_config` returns the whole file to the model. The code alone doesn't tell me whether it holds secrets.
- **Whether `DATA_DIR` exists where the server is deployed.** If it doesn't, `read_file` fails on every call, and the traversal in finding 1 only works with absolute-path arguments.
- **R7 when stdout is unbuffered.** Finding 3 assumes the default block buffering on a pipe. If the server is started with `python -u` or `PYTHONUNBUFFERED`, each print becomes its own non-JSON line on stdout instead. Whether that line is skipped or breaks the session depends on the client.

---

I can explain any of these in more detail or draft fixes. I'd start with the path check in finding 1 and the `is_error` spelling in finding 2. I won't edit `server.py` unless you ask me to.
