# MCP failure-handling audit: py-sdk1

The auditor found 12 problems: 4 High, 6 Medium and 2 Low. No files were changed.

## Target and SDK

- **Files:** only `server.py` and `requirements.txt`. There are no tests, examples, lock files or `pyproject.toml`, so nothing was skipped.
- **Entry point:** `server.py:20` `mcp = FastMCP("notes-sdk1")`.
- **Transport:** stdio. `server.py:104` calls `mcp.run()` with no arguments.
- **SDK version:** 1.x. The imports at `server.py:10-12` are `mcp.server.fastmcp`, `fastmcp.exceptions.ToolError` and `mcp.shared.exceptions.McpError`. Nothing in the code points to 2.x.
- **Version pin (R15):** `requirements.txt:1` pins `mcp==1.30.0`. That matches the 1.x code and the version the rules assume, so no checks had to wait on the version.

## Findings (most severe first)

1. **High, R6: a failed lookup is reported as a success.** At `server.py:73`, `CallToolResult(..., is_error=True)` uses the 2.x spelling. Version 1.x quietly accepts it as an extra key. The response goes out with `isError: false`, so the model reads "not found" as a normal result. **Fix:** use `isError=True`, or `raise ToolError(f"No note named {name}")`.

2. **High, R7: `print()` writes to stdout, which the stdio transport also uses.** `server.py:86` has `print(f"debug: {msg}")`, and the caller controls how long `msg` is. `server.py:22` also prints at import time. Version 1.x does nothing to stop this. Once about 8 KB of print output has built up, it gets mixed into a protocol message, that response is lost, and the client times out. **Fix:** use `print(..., file=sys.stderr)` or `logging`, set up before `FastMCP(...)` is created.

3. **High, R11: path traversal lets `read_file` read any file.** `server.py:80` runs `(DATA_DIR / relative).read_text()` with no `resolve()` and no check that the path stays inside the folder. `../../.ssh/id_rsa` gets out of the folder, and an absolute path replaces `DATA_DIR` entirely. **Fix:** resolve the path first, then reject it with `ToolError` if it is not inside `DATA_DIR.resolve()` (check with `is_relative_to`).

4. **High, R9: a secret is hardcoded.** `server.py:15` has `API_KEY = "demo-key-0000-not-a-real-secret"`. The rule flags key-like strings even when they look like demo values. **Fix:** read it from an environment variable, or delete it if nothing uses it.

5. **Medium, R1: a missing note comes back as a normal result.** `server.py:29` returns `{"ok": False, "error": ...}` with `isError: false`. **Fix:** `raise ToolError(...)`.

6. **Medium, R3: a bad input returns a message instead of raising an error.** `server.py:37` returns `"Error: name must not be empty"`. It is Medium rather than High only because the text starts with "Error:". **Fix:** `raise ToolError("invalid name: must not be empty")`.

7. **Medium, R4: internal system details are sent to the model.** `server.py:46` raises `RuntimeError` with an internal host, port and service account name (`db-internal-01.corp:5432`, `svc_notes`). Version 1.x passes that text to the model unchanged and logs nothing on the server. **Fix:** log the details to stderr with `logger.exception(...)`, then `raise ToolError("Database unavailable; see server logs")`.

8. **Medium, R4: the raw operating-system error is put inside `ToolError`.** `server.py:58` builds the message as `f"Failed to read config: {e}"`, which sends the server's absolute path and the OS error text. **Fix:** log the details, then `raise ToolError("Failed to read config") from e`.

9. **Medium, R4: file reading has no `try`, so server paths leak.** This is `server.py:80` again, but a separate problem. A `FileNotFoundError` includes the server's base path in its message, and 1.x sends it to the model unchanged. Because of the hardcoded path in #12, this read fails on every machine except that developer's. **Fix:** catch `OSError`, log it, then raise `ToolError("Could not read note file")`.

10. **Medium, R13: an unknown resource comes back as empty content.** `server.py:100` returns `NOTES.get(name, "")`, so the client can't tell an unknown note from an empty one. **Fix:** raise an error for unknown names, for example `ValueError(f"Unknown note: {name}")`.

11. **Low, R2: a protocol-level error is raised inside a tool.** `server.py:65` raises `McpError(ErrorData(code=-32000, ...))`. Version 1.x turns it into `isError: true`, so the model still sees the failure, but the `-32000` error code is lost. **Fix:** `raise ToolError("backend unavailable")`.

12. **Low, R10: a folder path only exists on one machine.** `server.py:16` has `DATA_DIR = Path("/Users/alice/Documents/notes")`. **Fix:** read it from an environment variable, or use a folder relative to the project.

## Checked and clean

- **R15:** the exact pin `mcp==1.30.0` matches the 1.x code.
- **R5:** there are no low-level handlers (`call_tool`, `read_resource`, `get_prompt`, `list_*`).
- **R6, other checks:** nothing reads `.is_error` and nothing uses `structured_content=`.
- **R8:** doesn't apply on 1.x. `ctx.info(...)` at `server.py:93` is correctly awaited.
- **R12:** doesn't apply, because the server only uses stdio.
- **R14:** only applies to 2.x. On 1.x, sync tools run one at a time.

## Could not verify

- **What's in `config/app.cfg`.** `load_config` (`server.py:56`) returns the whole file to the model. If the file contains credentials, that is a High exposure. The `config/` folder isn't in the target, so the auditor couldn't check it.
- **Whether `API_KEY` is a real key.** Nothing else in `server.py` uses it, and the auditor can't tell whether a real key is used somewhere else. Finding #4 stands under the rule either way.
- **When the stdout corruption (R7) actually happens.** It depends on how much print output builds up (about 8 KB). The 20-byte startup print alone would just sit in the buffer until shutdown. The damage comes when large `debug_echo` output is added to it.

---

I can explain any of these findings in more detail or draft fixes. I won't edit any files unless you ask.
