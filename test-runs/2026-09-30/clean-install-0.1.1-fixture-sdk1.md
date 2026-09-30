<!-- permission denials in this run: 0 -->

# MCP failure-handling audit: py-sdk1

**Target:** `server.py` and `requirements.txt`. This is a stdio server built on the official `mcp` SDK 1.x (`from mcp.server.fastmcp import ...`, pinned `mcp==1.30.0`).

The auditor's summary line says 11 findings (6 High, 4 Medium, 1 Low), but its list has 13 (6 High, 5 Medium, 2 Low). The full list is below as it reported it.

## Findings (most severe first)

1. **High, R11: path traversal in `read_file`** (`server.py:80`). `(DATA_DIR / relative).read_text()` never checks `relative`. An input like `../../.ssh/id_rsa`, or any absolute path, reads any file the server process can read.
   - *Fix:* resolve the path, then raise `ToolError` unless `p.is_relative_to(DATA_DIR.resolve())`.
2. **High, R7: `print` to stdout inside a tool** (`server.py:86`). `print(f"debug: {msg}")` shares the JSON-RPC stdout buffer. Once enough caller-controlled text builds up, it gets glued onto a protocol frame. That response is lost and the client times out.
   - *Fix:* print to `file=sys.stderr` or use `logging`.
3. **High, R7: `print` to stdout at import time** (`server.py:22`). `print("notes-sdk1 starting")` puts non-JSON text on the protocol stream. Same mechanism and fix as #2.
4. **High, R6: error flag spelled the 2.x way** (`server.py:73`). SDK 1.x ignores `is_error=True` as an unknown extra key and still sends `isError: false`. A "not found" looks like a success.
   - *Fix:* use `isError=True`, or raise `ToolError`.
5. **High, R9: hardcoded secret** (`server.py:15`). `API_KEY = "demo-key-0000-not-a-real-secret"` is committed in source, though it isn't used anywhere.
   - *Fix:* read it from an environment variable, or delete it.
6. **High, R4: internal details leak in `connect_db`** (`server.py:46`). The `RuntimeError` text reaches the model word for word and exposes the host `db-internal-01.corp:5432` and the service account `svc_notes`. It contains no password or token, so the auditor notes Medium is also defensible.
   - *Fix:* log with `logger.exception`, then raise a generic `ToolError`.
7. **Medium, R1: failed lookup returned as success** (`server.py:29`). `{"ok": False, "error": ...}` goes out with `isError: false`.
   - *Fix:* raise `ToolError`.
8. **Medium, R3: rejected input returned as success** (`server.py:37`). `return "Error: name must not be empty"` is also sent as a success.
   - *Fix:* raise `ToolError`. `Field(min_length=1)` also helps, but it still lets whitespace-only names through.
9. **Medium, R4: `ToolError` built from `str(e)`** (`server.py:58`). The `OSError` text reveals absolute install paths.
   - *Fix:* log it, then raise a generic `ToolError ... from e`.
10. **Medium, R4: no `try` around the file read in `read_file`** (`server.py:80`). Any `OSError` goes to the model word for word, including the developer's home path.
    - *Fix:* wrap the read, re-raise `ToolError` as is, and turn anything else into a sanitized `ToolError`.
11. **Medium, R13: missing resource returned as empty content** (`server.py:100`). `NOTES.get(name, "")` makes a missing note look the same as an empty one.
    - *Fix:* raise an exception on a miss, such as `ValueError`, with a clean message.
12. **Low, R2: `McpError` raised inside a tool** (`server.py:65`). On 1.x this still works as a tool error, but the `-32000` code is lost. After a 2.x migration it would become a JSON-RPC error.
    - *Fix:* raise `ToolError("backend unavailable")`.
13. **Low, R10: hardcoded machine-specific path** (`server.py:16`). `Path("/Users/alice/Documents/notes")` breaks on any other machine.
    - *Fix:* read the path from an environment variable or config, or make it relative to the project.

## Checked and clean
- **R5:** the server uses no low-level `Server` handlers.
- **R8:** does not apply on 1.x. `await ctx.info(...)` at `server.py:93` is correctly awaited.
- **R12:** does not apply, because the server is stdio-only.
- **R14:** does not apply on 1.x, where sync tools don't run concurrently.
- **R15:** the pin `mcp==1.30.0` matches the 1.x code.

## Could not verify
- **Finding #3:** the auditor did not test exactly when a short string printed before `run()` reaches the client, or how each client handles a non-JSON line. The rule rates it High regardless.
- **`config/app.cfg`:** this file is not in the target, so `load_config` would always fail and go down the leaking path in #9. It's unknown whether the file is supplied when the server is deployed.

---

This audit was read-only, and I haven't changed any files. I can explain any finding in more detail or draft fixes, starting with the path traversal (#1) and the stdout prints (#2–3), if you'd like.
