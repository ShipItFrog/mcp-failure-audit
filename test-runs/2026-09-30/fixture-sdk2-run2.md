I ran the audit through the auditor agent, and it made no changes to any files. Here is its report as written:

---

I found 14 defects in this 2.x server: 4 High, 6 Medium and 4 Low. I did not modify any files.

## Target and SDK detected

**Target:** `<run>\blind\py-sdk2`

The project has three files. Short names below refer to these:
- `server.py`: `...\blind\py-sdk2\server.py`
- `lowlevel_server.py`: `...\blind\py-sdk2\lowlevel_server.py`
- `requirements.txt`: `...\blind\py-sdk2\requirements.txt`

**Entry points:** `server.py` (`mcp = MCPServer("notes-sdk2")` at :21, `mcp.run()` at :131) and `lowlevel_server.py` (`Server("inventory-sdk2", on_list_tools=..., on_call_tool=...)` at :40, `stdio_server()` at :44). Nothing was excluded: there are no tests, examples or client scripts. A search for hidden files (`.gitignore`, `.venv`) and other dependency files (`pyproject.toml`, lock files, `setup.py`) found none.

**Transport:** stdio for both. `mcp.run()` has no argument, and the low-level server uses `stdio_server()`. So R7 applies and R12 does not.

**SDK:** 2.x, with no 1.x signals anywhere:
- `server.py:10` `from mcp import MCPError`
- `server.py:11` `from mcp.server.mcpserver import Context, MCPServer`
- `lowlevel_server.py:40` low-level `Server(..., on_call_tool=call_tool)`

**Pin (R15):** `requirements.txt:1` `mcp==2.2.0`. This matches the 2.x code and the rule baseline, so nothing version-dependent is left unverified.

TypeScript: none present.

---

## Findings (most severe first)

### 1. High, R11: tool argument controls file access (path traversal)
`server.py:99`
```python
return (DATA_DIR / relative).read_text()
```
- **What goes wrong:** `relative` is joined to `DATA_DIR` with no `resolve()` and no check that the result stays inside the folder.
  - `relative="../../../etc/passwd"` walks out of the notes folder.
  - An absolute value (`"/etc/passwd"`, `"C:/Windows/win.ini"`) replaces the base entirely, because that is how pathlib `/` works.
  - The tool can read any file the server process can read, and returns the contents to the model.
  - The 2.x traversal protection applies only to resource templates, not tools.
- **Fix:**
  ```python
  p = (DATA_DIR / relative).resolve()
  if not p.is_relative_to(DATA_DIR.resolve()):
      raise ToolError("path outside allowed folder")
  ```

### 2. High, R5: low-level `on_call_tool` handler has no try/except
`lowlevel_server.py:33` `async def call_tool(ctx, params):`, failing at `lowlevel_server.py:36`:
```python
count = INVENTORY[params.arguments["item"]]
```
- **What goes wrong:** 2.x does not wrap low-level handlers, so anything raised here reaches the client as a JSON-RPC error with code 0 and the raw exception text, instead of an `is_error` result:
  - An unknown item raises `KeyError`, sent as `JSON-RPC error 0: 'pear'` (this matches the verified probe).
  - Because 2.x low-level handlers get no input validation (the R3 aspect, folded in here), a missing `item` gives `KeyError: 'item'`. `arguments=None` or a list value gives a `TypeError`. All of these escape the same way.
  - The model may never see the failure. That depends on the client, since clients only MAY show protocol errors.
- **Fix:**
  - Validate the input, and return `types.CallToolResult(content=[types.TextContent(type="text", text="unknown item: ...")], is_error=True)` for a bad or unknown item.
  - Wrap the body in `try: ... except MCPError: raise except Exception: logger.exception(...); return types.CallToolResult(..., is_error=True)`.
  - Unrelated to the rules, but visible here: the handler never checks `params.name`, so a call to any tool name is answered as `stock`.

### 3. High, R14: unlocked read-modify-write of a shared ID counter in a sync tool
`server.py:44` `def create_note(text: str) -> int:`, racing at `server.py:46-48`:
```python
global _next_id
note_id = _next_id
_next_id = note_id + 1
```
- **What goes wrong:** On 2.x, sync tools run on worker threads (up to 40). Two concurrent calls can both read the same `_next_id` and both return the same ID. The second `NOTES[str(note_id)] = text` (line 49) then silently overwrites the first note, and both clients believe their note exists. The severity is High because it corrupts IDs and loses data.
- **Fix:** make the handler `async def`, since there is no `await` between the read and the write. Alternatively, put a module-level `threading.Lock()` around lines 47-49.

### 4. High, R9: hardcoded secret
`server.py:15`
```python
API_KEY = "demo-key-0000-not-a-real-secret"
```
- **What goes wrong:** A credential-shaped literal is assigned to a key name. The rule applies even to values that look like demos. It is not referenced anywhere else in the project, but it sets the pattern for where a real key would go.
- **Fix:** delete it, or read it from the environment (for example `os.environ["NOTES_API_KEY"]`) and document the variable.

### 5. Medium, R1: lookup failure returned as a normal result
`server.py:30` (in `def get_note(name: str) -> dict:` at :27)
```python
return {"ok": False, "error": f"No note named {name}"}
```
- **What goes wrong:** A lookup by exact name that finds nothing is sent with `isError: false` (verified probe `get_note`). The error text is readable, so this is Medium rather than High.
- **Fix:** `raise ToolError(f"No note named {name}")`. `ToolError` is already imported from `mcp.server.mcpserver.exceptions`.

### 6. Medium, R3: input-validation failure returned as a normal result
`server.py:38`
```python
return "Error: name must not be empty"
```
- **What goes wrong:** An empty or whitespace-only `name` is rejected with `isError: false` (verified probe `add_note`).
- **Fix:** `raise ToolError("invalid name: must not be empty")`.

### 7. Medium, R4: exception text leaked through `ToolError`
`server.py:69`
```python
raise ToolError(f"Failed to read config: {e}")
```
- **What goes wrong:** On 2.x, `ToolError` text goes to the model word for word. The `OSError` string includes the absolute config path, for example `[Errno 2] No such file or directory: 'C:\...\config\app.cfg'`, which exposes the install location and OS user name.
  - `config/app.cfg` does not exist in this checkout, so every call currently fails and triggers the leak.
  - 2.x does not log the cause of a deliberate `ToolError`, so the operator gets nothing on stderr.
- **Fix:** `logger.exception("config read failed")`, then `raise ToolError("Could not read server configuration") from e`.

### 8. Medium, R2: protocol error raised inside a tool
`server.py:75`
```python
raise MCPError(code=-32000, message="backend unavailable")
```
- **What goes wrong:** On 2.x this becomes a JSON-RPC error `-32000` for `tools/call`, not an `is_error` result (verified probe `check_backend`). Clients SHOULD show `isError` results to the model but only MAY show protocol errors, so whether the model sees it depends on the client.
- **Fix:** `raise ToolError("backend unavailable")`. The `MCPError` import at :10 then becomes unused.

### 9. Medium, R6: error flag read with the 1.x spelling
`server.py:91`
```python
if result.isError:
```
- **What goes wrong:** On 2.x, reading `.isError` on a `CallToolResult` raises. `lookup_or_default` therefore fails on every call, for both missing and existing notes, returning the masked `Error executing tool lookup_or_default` (verified probe).
- **Fix:** use `result.is_error`.
- After the fix, the missing-note branch (:92) returns the made-up `"(default note)"` with `isError: false`. The docstring says that fallback is intended. If callers need to tell a miss apart, raise `ToolError` instead.

### 10. Medium, R13: missing resource returned as empty content
`server.py:119`
```python
return NOTES.get(name, "")
```
- **What goes wrong:** `notes://<missing>` is a successful read with one empty content item (verified probe `notes://missing`), instead of error `-32602`.
- **Fix:** `from mcp.server.mcpserver.exceptions import ResourceNotFoundError`, then raise it when `name not in NOTES`.

### 11. Low, R13: not-found reported with the wrong resource error type
`server.py:126`
```python
raise ResourceError(f"No archived note {name}")
```
- **What goes wrong:** The client gets `-32603` instead of `-32602`. It does receive an error; only the code is wrong. The message only echoes the caller's input, so this is not an R4 leak.
- **Fix:** `raise ResourceNotFoundError(...)`.

### 12. Low, R7: writes to stdout on a stdio server
- `server.py:23` `print("notes-sdk2 starting")` runs at import time, before `run()`.
- `server.py:105` `print(f"debug: {msg}")` runs inside a handler.
- **What goes wrong:** 2.x protection is intact: `sys.stdout` is not replaced, and no `stdout=` is passed. With default block buffering, both prints stay buffered and reach the real stdout only after shutdown, so this is hygiene only. If the host launches with `python -u` or `PYTHONUNBUFFERED=1`, line 23 is flushed to stdout before `run()` and this rises to Medium (see "Could not verify").
- **Fix:** `print(..., file=sys.stderr)`, or stdlib `logging`.

### 13. Low, R8: deprecated protocol-level logging
`server.py:112`
```python
await ctx.info("hello from the tool")
```
- **What goes wrong:** Each call emits up to three `MCPDeprecationWarning`s. On 2026-07-28 connections nothing is sent unless the client opted in.
- **Fix:** `logging.getLogger(__name__).info(...)`, and put anything the model needs into the tool result.

### 14. Low, R10: hardcoded machine-specific path
`server.py:16`
```python
DATA_DIR = Path("/Users/alice/Documents/notes")
```
- **What goes wrong:** The path points into one developer's home folder, so it does not exist on other machines. On this Windows machine it resolves to `\Users\alice\...` on the current drive.
- **Fix:** read it from an environment variable, or use a path relative to the project.

---

## Checked and clean
- **R4, uncaught exceptions:** `server.py:57` `raise RuntimeError("connect failed: host db-internal-01.corp:5432 refused (service account svc_notes)")` is not a finding on 2.x. High-level tool exceptions are masked (`Error executing tool connect_db`) and the traceback goes to stderr. Uncaught errors in `read_file` are masked the same way. R4 for the low-level handler is folded into R5 (finding 2).
- **R6, constructor spelling:** `server.py:83` `CallToolResult(..., isError=True)` is accepted by the 2.x constructor. The low-level handler returns a `CallToolResult` model, not a dict, so there is no dropped `"is_error"` key.
- **R1, elsewhere:** `strict_lookup` correctly flags a miss as an error. No other tool returns a value on failure.
- **R2, elsewhere:** there are no ctx elicitation or sampling calls, and no `return ErrorData(` in the low-level handler.
- **R5, `list_tools` (`lowlevel_server.py:17`):** it has no `try`, but its body only builds a static literal and has no failure path that depends on runtime input, so I did not report it. If it ever builds its list dynamically, wrap it.
- **R7, `lowlevel_server.py`:** no stdout writes, and `stdio_server()` is called without `stdout=`.
- **R9 / R10 / R11, elsewhere:** `lowlevel_server.py` has no secrets and no file access. `load_config` uses a fixed path built relative to `__file__`. The resource templates do not touch the filesystem.
- **R12:** not applicable, because both entry points use stdio.
- **R14, elsewhere:** the other sync handlers only read, or make single atomic assignments (`NOTES[name] = text`, `NOTES.get(...)`). The low-level handlers are `async`.
- **R15:** `mcp==2.2.0` matches the 2.x code.

## Could not verify
- **How the server is launched:** there is no launch config in the project. If a host runs `server.py` with `python -u` or `PYTHONUNBUFFERED=1`, the import-time print at `server.py:23` becomes Medium under R7.
- **Client behaviour for protocol errors (findings 2 and 8):** whether a given host shows JSON-RPC errors to the model depends on the client.
- **What `config/app.cfg` contains:** the file is not in the target. When it does exist, `load_config` returns the whole file to the model. If it holds credentials, that exposes them. This falls outside the rule set, so I am noting it rather than raising a finding.

---

I can explain any finding in more detail or draft a fix for one. I won't edit any files unless you ask me to. The path traversal in `read_file` (finding 1) and the unprotected low-level handler (finding 2) are the most urgent.
