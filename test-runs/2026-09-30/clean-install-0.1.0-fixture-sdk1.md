<!-- permission denials in this run: 1 -->

**The audit didn't finish.** The auditor couldn't read the rule set at `<clean-config>/plugins/cache/shipitfrog/mcp-failure-audit/0.1.0/skills/audit/rules.md` because it doesn't have read permission for that file. Without the rules it can't assign rule IDs or severities, so the items below are its preliminary notes, not ranked findings. Nothing was modified.

## What it found in the project

- **Files:** only `server.py` and `requirements.txt`.
- **SDK:** Python FastMCP 1.x (`server.py:10`), pinned exactly to `mcp==1.30.0` (`requirements.txt:1`).
- **How the server talks to its client:** over stdio, the default for `mcp.run()` at `server.py:104`.

## Possible issues (no rule IDs or severities yet)

1. **Writes to stdout break stdio:** `print(...)` at `server.py:22` and `server.py:86`. On stdio, stdout carries the protocol messages, so extra output can corrupt them. Fix: write to stderr or use `logging`.
2. **The error flag probably isn't set:** `server.py:73` uses `is_error=True`, but 1.x expects the camelCase name `isError`. The misspelled field is likely ignored, so the result goes out as a success.
3. **Failures are returned as successes:** `server.py:29` returns `{"ok": False, ...}` and `server.py:37` returns `"Error: ..."`. The client sees `isError: false` for both. Fix: raise `ToolError`.
4. **An internal host and service account leak to the client:** the `RuntimeError` at `server.py:46` names `db-internal-01.corp:5432` and `svc_notes`, and FastMCP sends that text back in the error result.
5. **Server file paths leak to the client:** `server.py:58` puts the `OSError` text, which includes the absolute path, into a `ToolError`.
6. **`read_file` has no error handling and no path check:** at `server.py:80`, a missing file exposes the absolute path, and `../` can reach files outside the data folder. The data folder `DATA_DIR` (line 16) is hardcoded to one developer's machine, so the tool fails anywhere else.
7. **A hardcoded key is in the source:** `API_KEY` at `server.py:15`. It is never used, and whether it counts as a finding depends on the rules.
8. **`McpError` is raised inside a tool** at `server.py:65`. Whether that's a defect depends on how 1.30.0 handles it.
9. **A missing resource returns an empty string instead of an error:** `server.py:100`.

## Checked and clean

- No rules could be applied, so nothing is formally clean.
- The auditor noted that `log_something` (lines 90–94) logs correctly with `await ctx.info(...)`, which goes through the protocol rather than stdout.

## Could not verify

- All rule IDs, severities, and the exceptions each rule makes for specific SDKs.
- Whether the exact `mcp==1.30.0` pin passes rule R15, the dependency-pin check.
- Whether FastMCP 1.30.0 passes a returned `CallToolResult` through unchanged (line 69). This affects how serious item 2 is.
- How 1.30.0 handles an `McpError` raised inside a tool (item 8).

To get the full audit with severities, allow read access to that `rules.md` file and I'll run it again. I can also explain any of these items or draft fixes, but I won't edit any files unless you ask.
