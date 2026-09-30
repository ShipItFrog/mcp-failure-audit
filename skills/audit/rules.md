# Audit rules

> Status: **skeleton (v0.1.0-dev)**. Rule IDs, scope, and sources are final; detection heuristics, severity, and fix examples are still being written.
> Baseline: MCP spec revision 2026-07-28; official Python SDK `mcp` 1.x (latest 1.30.0) and 2.x (latest 2.2.0). Checked 2026-09-29.

Applies-to key: **1.x** = official Python SDK 1.x (`mcp.server.fastmcp`), **2.x** = official Python SDK 2.x (`MCPServer`), **3p** = third-party `fastmcp` package.

| ID | Rule | Applies to | Source |
|---|---|---|---|
| R1 | **Swallowed errors.** A tool reports failure by returning a normal value (string, dict like `{"ok": False, "error": ...}`, or `None`) instead of raising `ToolError`. The result goes out with `is_error = false`, so the model treats the failure as success. | 1.x, 2.x | https://py.sdk.modelcontextprotocol.io/servers/handling-errors/ |
| R2 | **Tool errors sent as protocol errors.** Raising a protocol-level error (e.g. `MCPError`) inside a tool: in 2.x it becomes a JSON-RPC error the model may never see; in 1.x it is wrapped as a tool error but the error code is lost. Tool failures belong in the tool result (`isError`). | 1.x, 2.x | https://modelcontextprotocol.io/specification/2026-07-28/server/tools |
| R3 | **Input-validation failures not reported as tool errors.** Hand-written argument checks must raise `ToolError`, not return a normal value. | 1.x, 2.x | https://modelcontextprotocol.io/specification/2025-11-25/changelog (SEP-1303) |
| R4 | **Exception details leaked to the model.** Raw exception text (`str(e)`, tracebacks) reaches the client. Default in 1.x and 2.0.x; masked by default from 2.1.0; `mask_error_details` is off by default in 3p. Any version leaks if code puts `str(e)` into the error message itself. | 1.x, 2.x, 3p | https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.0 |
| R5 | **Low-level `Server` handlers without try/except.** Unhandled exceptions become JSON-RPC errors instead of `is_error` results. | 2.x only | https://py.sdk.modelcontextprotocol.io/migration/ |
| R6 | **Wrong error-flag spelling for the SDK version.** 1.x uses `isError=True`; 2.x uses `is_error=True`. | 1.x, 2.x | https://py.sdk.modelcontextprotocol.io/migration/ |
| R7 | **stdout corruption on the stdio transport.** Anything other than MCP messages on stdout breaks the connection: `print()`, or `logging` pointed at `sys.stdout`. In 1.x any `print()` is fatal; in 2.x prints at import time or before serving are fatal. | 1.x, 2.x | https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio |
| R8 | **Deprecated protocol-level logging** (`ctx.log`, `ctx.info`, ...), deprecated in spec 2026-07-28 (SEP-2577). Low severity. | 2.x | https://modelcontextprotocol.io/specification/2026-07-28/changelog |
| R9 | **Hardcoded secrets.** The spec says stdio servers SHOULD take credentials from the environment; flagging literal keys and tokens in code follows from that. | all | https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization |
| R10 | **Hardcoded machine-specific paths** (e.g. a developer's home directory). *House rule — not in the MCP spec.* Reported as a portability risk. | all | — |
| R11 | **Path traversal.** Paths built from tool arguments must be resolved and checked against an allowed root. | all | https://modelcontextprotocol.io/specification/2026-07-28/server/resources |
| R12 | **HTTP transport only:** token passthrough, tokens in URL query strings, missing `Origin` validation, binding to `0.0.0.0` for local servers. | all (HTTP) | https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices |
| R13 | **Missing resource returned as empty contents** instead of error `-32602`. | all | https://modelcontextprotocol.io/specification/2026-07-28/server/resources |
| R14 | **Unlocked shared state in sync tools.** 2.x runs sync tools on worker threads; shared mutable state needs a lock. | 2.x | https://py.sdk.modelcontextprotocol.io/migration/ |
