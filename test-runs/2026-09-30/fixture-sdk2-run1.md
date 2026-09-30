The audit of `py-sdk2` is done, and no files were changed. Here is the auditor's report as it returned it.

---

# MCP failure-handling audit: py-sdk2

I found 15 defects: 4 High, 6 Medium and 5 Low. The pin matches the code, so no version-dependent rule is in doubt. I changed no files.

## Target and SDK

- **Target:** `…\scratchpad\audit-run\blind\py-sdk2`
- **Files:** `server.py`, `lowlevel_server.py`, `requirements.txt`. There were no tests, examples or client scripts, so nothing was excluded. There are also no hidden files, no `pyproject.toml`, no lock file and no `config/` directory.
- **Entry points and transport (both stdio):**
  - `server.py:21` `mcp = MCPServer("notes-sdk2")`, started by `server.py:131` `mcp.run()` (no argument, so stdio).
  - `lowlevel_server.py:40` `Server("inventory-sdk2", on_list_tools=list_tools, on_call_tool=call_tool)`, started by `lowlevel_server.py:44` `async with stdio_server() as (read_stream, write_stream):`.
- **SDK: 2.x.** Evidence:
  - `server.py:10` `from mcp import MCPError`
  - `server.py:11` `from mcp.server.mcpserver import Context, MCPServer`
  - `lowlevel_server.py:40` uses the low-level `on_call_tool=` style.
  - There are no 1.x signals.
- **Pin (R15):** `requirements.txt:1` `mcp==2.2.0` is exactly the 2.2.0 baseline and matches the code. **Clean.**

## Findings (most severe first)

### 1. High, R11: path traversal and arbitrary file read (`server.py:99`)
- **Code:** `return (DATA_DIR / relative).read_text()`
- **What goes wrong:** `relative` comes straight from the tool argument and is never checked.
  - `../../..` escapes the notes folder.
  - An absolute path like `/etc/passwd` replaces `DATA_DIR` entirely, because `Path / absolute` gives the absolute path.
  - So the model, or a prompt injection, can read any file the server process can read.
- **Fix:** `p = (DATA_DIR / relative).resolve()`, then `if not p.is_relative_to(DATA_DIR.resolve()): raise ToolError("path outside allowed folder")`.

### 2. High, R5: low-level `on_call_tool` has no try/except (`lowlevel_server.py:36`)
- **Code:** `count = INVENTORY[params.arguments["item"]]`, inside `async def call_tool(ctx, params):` (line 33).
- **What goes wrong:**
  - An unknown item (e.g. `"pear"`), a missing `item` key, or `arguments=None` raises `KeyError` or `TypeError`.
  - 2.x does not wrap low-level handlers, so the client gets **JSON-RPC error code 0 with the raw `str(e)`** (e.g. `'pear'`) instead of an `is_error` result. The model may never see the failure.
- **R3 overlap:** the handler also never checks `params.arguments` against the `inputSchema` it advertises (R3). Here that missing check only shows up through this same unguarded line, so I report it once.
- **Fix:**
  - Check that `params.arguments` is a dict with a string `item`.
  - For an unknown item, return `types.CallToolResult(content=[types.TextContent(type="text", text=f"unknown item: {item}")], is_error=True)`.
  - Wrap the body in `try: ... except MCPError: raise` and `except Exception: logger.exception(...)`, then return a generic `is_error=True` result.

### 3. High, R14: race on the ID counter in a sync tool (`server.py:46-48`)
- **Code:**
  ```
  global _next_id
  note_id = _next_id
  _next_id = note_id + 1
  ```
- **What goes wrong:**
  - On 2.x, sync `def` tools run on worker threads, up to 40 at once.
  - Two concurrent `create_note` calls can read the same `_next_id` and get the same ID. The second `NOTES[str(note_id)] = text` then silently overwrites the first note, and both callers are told they succeeded.
  - This corrupts IDs and loses data. It only happens with concurrent calls.
- **Related, outside the rule set:** `NOTES[str(note_id)]` will also silently overwrite a note that `add_note` saved under a numeric name such as `"1"`.
- **Fix:** hold a module-level `threading.Lock` around the read, the increment and the insert, or make the tool `async def`.

### 4. High, R9: hardcoded credential (`server.py:15`)
- **Code:** `API_KEY = "demo-key-0000-not-a-real-secret"`
- **What goes wrong:** a key-shaped literal is committed in source. The rule flags these even when they look like demo values. It is currently unused.
- **Fix:** `API_KEY = os.environ["NOTES_API_KEY"]` (or `.get` with an empty default), and document the variable in the README.

### 5. Medium, R6: `.isError` read on a 2.x `CallToolResult` (`server.py:91`)
- **Code:** `if result.isError:`
- **What goes wrong:** on 2.x, reading `.isError` raises. So `lookup_or_default` fails on every call, whether or not the note exists, and the model only sees the masked `Error executing tool lookup_or_default`.
- **Fix:**
  - Use `result.is_error`.
  - Once that works, line 92 `return "(default note)"` turns a lookup of a missing name into a success with made-up content (R1 pattern). Either raise `ToolError(f"no note named {name}")` or state clearly in the returned text that a default was used.

### 6. Medium, R3: input check returned as a normal result (`server.py:38`)
- **Code:** `return "Error: name must not be empty"`
- **What goes wrong:** the result goes out with `isError: false`. The text is readable, but clients and the model get a success flag for a rejected write.
- **Fix:** `raise ToolError("invalid name: must not be empty")`, or use a `Field(min_length=1)` constraint. Note that `min_length` alone would still let whitespace-only names through, and the current `.strip()` check rejects those.

### 7. Medium, R1: missing note returned as a success (`server.py:30`)
- **Code:** `return {"ok": False, "error": f"No note named {name}"}`
- **What goes wrong:** a lookup by exact name that finds nothing is sent as JSON text with `isError: false`.
- **Fix:** `raise ToolError(f"No note named {name}")` from `mcp.server.mcpserver.exceptions`.

### 8. Medium, R13: missing resource returns empty content (`server.py:119`)
- **Code:** `return NOTES.get(name, "")`
- **What goes wrong:** `notes://<missing>` is a successful read with one empty content item. The spec wants error `-32602`, and the client cannot tell "missing" from "empty note".
- **Fix:** `if name not in NOTES: raise ResourceNotFoundError(f"No note {name}")`.

### 9. Medium, R4: exception text passed through `ToolError` (`server.py:69`)
- **Code:** `raise ToolError(f"Failed to read config: {e}")`
- **What goes wrong:**
  - 2.x sends `ToolError` text verbatim, so the `OSError` string, including the server's absolute install path (`.../config/app.cfg`), reaches the model.
  - There is no `config/` directory in the target, so every call to `load_config` currently takes this path.
  - 2.x also does not log the cause of a deliberate `ToolError`, so the operator gets nothing on stderr.
- **Fix:** `logger.exception("config read failed")`, then `raise ToolError("Config file unavailable") from e`.

### 10. Medium, R2: protocol error raised inside a tool (`server.py:75`)
- **Code:** `raise MCPError(code=-32000, message="backend unavailable")`
- **What goes wrong:** on 2.x this becomes a JSON-RPC error for `tools/call`, not an `is_error` result. Clients only *may* show protocol errors to the model, so whether the failure is visible depends on the client.
- **Fix:** `raise ToolError("backend unavailable")`.

### 11. Low, R7: print at import time on the stdio server (`server.py:23`)
- **Code:** `print("notes-sdk2 starting")`
- **What goes wrong:**
  - With default block buffering on a pipe, this stays in Python's buffer and reaches the real stdout only after shutdown, which is harmless.
  - If the server is launched with `python -u` or `PYTHONUNBUFFERED`, the line reaches the client's stdout before `run()`. That would make this **Medium**.
- **Fix:** `print(..., file=sys.stderr)` or `logging`.

### 12. Low, R7: print inside a handler (`server.py:105`)
- **Code:** `print(f"debug: {msg}")`
- **What goes wrong:** 2.x redirects stdout to stderr at the file-descriptor level while serving, so this is hygiene only.
- **Fix:** same as finding 11.

### 13. Low, R8: deprecated protocol-level logging (`server.py:112`)
- **Code:** `await ctx.info("hello from the tool")`
- **What goes wrong:** this is deprecated on 2.x (SEP-2577). It emits up to three `MCPDeprecationWarning`s per call, and on 2026-07-28 connections nothing is sent unless the client opted in.
- **Fix:** use `logging.getLogger(__name__)` for operator diagnostics, and put anything the model needs into the tool result.

### 14. Low, R13: plain `ResourceError` for a missing item (`server.py:126`)
- **Code:** `raise ResourceError(f"No archived note {name}")`
- **What goes wrong:** the client gets `-32603` instead of `-32602`. The message only echoes the caller's input, so it is not an R4 leak.
- **Fix:** `raise ResourceNotFoundError(...)`.

### 15. Low, R10: machine-specific path (`server.py:16`)
- **Code:** `DATA_DIR = Path("/Users/alice/Documents/notes")`
- **What goes wrong:** this is one developer's home directory, so `read_file` cannot work on any other machine.
- **Fix:** read it from an environment variable or config, or use a path relative to the project.

## Checked and clean

- **R15:** the pin `mcp==2.2.0` matches the 2.x code.
- **R4, `connect_db`:** the uncaught `RuntimeError` at `server.py:57`, with internal host and account name, is masked by 2.x `MCPServer`, so it is not a finding. The same applies to uncaught `read_file` errors.
- **R6, `strict_lookup`:** `CallToolResult(..., isError=True)` in a constructor (`server.py:83`) is valid on 2.x. That tool flags misses correctly.
- **R2:** no ctx elicitation or sampling calls, and no `ErrorData` returned from `on_call_tool`.
- **R5, `list_tools`** (`lowlevel_server.py:17`): no `try`, but it only builds a static literal and has no runtime failure path, so I did not flag it.
- **R7, `lowlevel_server.py`:** no stdout writes, and `stdio_server()` is called without a `stdout=` override, so protection stays on.
- **R11, other file access:** `load_config` uses a fixed path. The resource templates don't touch the filesystem and don't relax `ResourceSecurity`.
- **R14, other sync handlers:** they only do reads or single atomic assignments (`NOTES[name] = text`), and no handler deletes keys.
- **R9 and R10 in `lowlevel_server.py`:** none found.
- **R12:** not applicable, because both servers use stdio.

## Could not verify

- **Launch command (R7, finding 11):** whether the server is started with `python -u` or `PYTHONUNBUFFERED`. Either would raise finding 11 to Medium.
- **Client behavior (R2, finding 10):** whether the connecting client shows JSON-RPC errors to the model.
- **R14 race (finding 3):** this is from reading the source only. A single call cannot show a race, and it needs concurrent `tools/call` requests.
- **Config contents:** what `config/app.cfg` would contain in deployment. `load_config` returns the whole file to the model, so any secrets in it would reach the model. That is outside the rule set, and the file is absent from the target.

---

I can explain any of these findings in more detail or draft fixes, starting with the four High ones. I won't edit any files unless you ask me to.
