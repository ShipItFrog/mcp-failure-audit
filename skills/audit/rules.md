# Audit rules

> Baseline: MCP spec revision 2026-07-28; official Python SDK `mcp` **1.30.0** and **2.2.0**. Checked 2026-09-30.
> "Verified" lines point to evidence you can re-run: the installed SDK source (`<version>/<path>:<line>`, relative to the `mcp` package) or a wire-level probe of the fixtures in `fixtures/` (`probe.py`). Anything else is marked *source only* or *external*.

## Step 0 — Scope and SDK detection

1. **Find the server entry points:** files that construct `FastMCP(`/`MCPServer(`/`Server(` or call `run(`/`stdio_server(`, plus the modules they import. Exclude tests, examples, and client scripts, and list what you excluded.
2. **Note the transport:** `run()` with no argument, `run("stdio")`, or `stdio_server()` means stdio; `"sse"`/`"streamable-http"` means HTTP. R7 applies to stdio; R12 applies to HTTP.
3. **Detect the SDK:**

| Signal | Means |
|---|---|
| `from mcp.server.fastmcp import ...`, `from mcp.server import FastMCP`, `mcp.server.fastmcp.exceptions`, any `McpError` (`from mcp import McpError`, `mcp.shared.exceptions.McpError`), low-level decorators `@server.call_tool()` / `@server.list_tools()` / `@server.read_resource()` / `@server.get_prompt()` | **1.x** |
| `from mcp.server.mcpserver import ...`, `from mcp.server import MCPServer`, any `MCPError` (`from mcp import MCPError`, `mcp.shared.exceptions.MCPError`), `import mcp_types`, low-level `Server(..., on_call_tool=...)` | **2.x** |
| `from fastmcp import FastMCP` | third-party `fastmcp` (**3p**) |
| Both 1.x and 2.x signals (a compatibility shim) | use the version the dependency pin resolves to (R15); apply that version's rules and list the other version's divergent rules under "Could not verify" |
| Decorator names (`@<x>.tool()`, `@<x>.resource()`), the bare token `MCPServer`, `Context[...]` arity | **not** reliable signals |

4. **Check the pin (R15) before anything else.** If it resolves to a version other than 1.30.x / 2.2.x, still apply the rules, but list every version-dependent "Not a finding" (R4 masking, R6 alias, R7 stdout diversion) under "Could not verify".

Rule scope tags: **1.x**, **2.x**, **3p**; **all** means 1.x, 2.x and 3p. For 3p, SDK-internal behavior (masking, wrapping) was not verified: report what is visible in the code and list the rest under "Could not verify".

## Reporting policy

- **One finding per defect.** When rules overlap on the same line, report the most specific: **R6 > R3 > R1**; for low-level handlers **R5 > R4**. Two genuinely different defects on one line (e.g. a traversal and a leak) are two findings.
- **Evidence:** file, line, verbatim quote. For something *missing* (no pin, no auth, no `try`), quote the nearest anchor: the handler's `def` line, the `run(...)` call, or the dependency file line.
- **Severity:** **High** — the model is misled about success, a response can be lost, the server won't start, or secrets/files are exposed. **Medium** — information leaks, failures a client may still surface, bugs that need concurrency or unusual input. **Low** — hygiene, deprecations, portability. Never go above what the evidence supports; if behavior depends on the client, say so.

---

### R1 — Failure returned as a normal result · all

- **Runtime:** a tool that returns a normal value on failure produces `isError: false`. Identical in 1.x and 2.x. Caveat for `None`: it is a silent success only when the return annotation is missing, `Optional[...]`/`| None`, `-> None`, or bare `dict`; with a non-optional annotation such as `-> str`, the SDK turns `None` into an error result (1.x sends the pydantic text — see R4; 2.x masks it).
- **Verified:** probe `get_note` → `isError=False` on 1.30.0 and 2.2.0; `1.30.0/server/fastmcp/utilities/func_metadata.py:558`, `2.2.0/server/mcpserver/utilities/func_metadata.py:212`; `None` caveat `1.30.0/.../func_metadata.py:144-148`, `2.2.0/.../func_metadata.py:214-219`.
- **Detect:** in tool handlers — `@<instance>.tool()`, `add_tool(...)`, 1.x `@server.call_tool()`, 2.x `on_call_tool=` — failure branches that return `{"ok": False ...}`, `{"error": ...}`, `{"success": False ...}`, strings like "Error…", "Failed…", "Could not…", "Unable to…", a `CallToolResult` without the error flag, or `None`/bare `return` inside `except`; also `except Exception: return ...`. In a high-level tool, `return ErrorData(...)` is also R1 (it is sent as JSON text with the flag false).
- **Not a finding:** a query, filter or search with zero matches, when the result says so explicitly. **Is a finding:** a lookup by exact identifier that finds nothing, or any operation that could not be performed.
- **Severity:** **High** if the returned value hides the failure (`None`, `""`, `[]`, a made-up default); **Medium** if it carries readable error text but the flag is still false.
- **Fix 1.x:** `from mcp.server.fastmcp.exceptions import ToolError` → `raise ToolError("what went wrong")` (the model sees `Error executing tool <name>: what went wrong`).
- **Fix 2.x:** `from mcp.server.mcpserver.exceptions import ToolError` → `raise ToolError("what went wrong")`.
- **Fix 3p:** raise the framework's own tool error (import path not verified here).

### R2 — Protocol error raised inside a tool · 1.x, 2.x

- **Runtime 2.x:** `raise MCPError(...)` in a tool, or `return ErrorData(...)` from a low-level `on_call_tool`, becomes a **JSON-RPC error** for `tools/call`, not an `is_error` result. The spec says clients SHOULD show `isError` results to the model but only MAY show protocol errors. The SDK itself raises `MCPError` inside a tool when an elicitation/sampling request fails or times out.
- **Runtime 1.x:** `raise McpError(ErrorData(...))` in a tool is caught and wrapped into `isError: true`; the error **code is lost**.
- **Verified:** probe `check_backend` → 2.2.0 `JSON-RPC error -32000`; 1.30.0 `isError=True … backend unavailable`; `2.2.0/server/mcpserver/tools/base.py:192`, `2.2.0/shared/jsonrpc_dispatcher.py:99`, `2.2.0/server/runner.py:218-220`, `1.30.0/server/fastmcp/tools/base.py:117`.
- **Detect:** `raise MCPError(` (2.x) or `raise McpError(` (1.x) in tool bodies; `return ErrorData(` in a 2.x low-level `on_call_tool`; in 2.x, elicitation or sampling calls made through `ctx` with no `except MCPError` around them. Do **not** flag `UrlElicitationRequiredError` — it is meant to be a protocol error.
- **Severity:** 2.x **Medium** (client-dependent); 1.x **Low** (behaves like a tool error; only the code is lost).
- **Fix 1.x:** `raise ToolError(msg)` from `mcp.server.fastmcp.exceptions`.
- **Fix 2.x:** `from mcp import MCPError, UrlElicitationRequiredError` and `from mcp.server.mcpserver.exceptions import ToolError`; replace `raise MCPError(...)` with `raise ToolError(msg)`. Around ctx elicitation/sampling: `except UrlElicitationRequiredError: raise` then `except MCPError as e: raise ToolError("<safe summary>") from e`.

### R3 — Input-validation failure returned as a normal result · all

- **Runtime:** same mechanism as R1 — hand-written checks that `return "invalid …"` produce `isError: false`. Typed parameters are validated by the SDK and do come back as errors (with the full pydantic message).
- **Verified:** probe `add_note` → `isError=False` on both versions.
- **Detect:** argument checks at the top of a tool that return instead of raising (`if not <arg>: return "..."`, `return {"error": "bad input"}`); `Any`/`str` params parsed by hand. 1.x low-level: `@server.call_tool(validate_input=False)`, or no `@server.list_tools()` (validation is skipped; only a server-side warning is logged, the client gets no signal). 2.x low-level: arguments are never validated against `inputSchema` unless the handler does it.
- **Severity:** **Medium** (High when the rejection is indistinguishable from success).
- **Fix:** typed parameters / `Field(...)` constraints; for manual checks `raise ToolError("invalid <field>: <reason>")` (import path per version, see R1).

### R4 — Exception details leaked to the model · all

- **Runtime 1.x:** every uncaught exception in a tool reaches the model verbatim: `Error executing tool <name>: <str(e)>`. No masking option exists, and 1.x logs nothing server-side for tool failures. Resource failures leak too (`Error reading resource <uri>: <str(e)>`), though those are logged.
- **Runtime 2.x (MCPServer):** unexpected exceptions are **always masked** (`Error executing tool <name>`, traceback logged to stderr). But `ToolError`/`ResourceError` text is sent **verbatim**, so `ToolError(f"...{e}")` still leaks. Pydantic argument-validation text is sent in full. 2.x **low-level** handlers are not masked — see R5.
- **Verified:** probe `connect_db` → 1.30.0 sends internal host, port and account name; 2.2.0 returns only `Error executing tool connect_db`. `1.30.0/server/fastmcp/tools/base.py:117`, `2.2.0/server/mcpserver/tools/base.py:210`.
- **Detect:** `ToolError(str(e))`, `ToolError(f"...{e}")`, `repr(e)`, `traceback.format_exc()` flowing into a return value or error message. On 1.x only: any `raise` of a non-`ToolError` exception whose message carries internal detail (hosts, paths, account names), and tools doing DB/HTTP/file/subprocess work with no `try` that re-raises a sanitized `ToolError`. Ignore `str(e)` that only goes to a stderr logger, and messages that only echo the caller's own input.
- **Not a finding on 2.x high-level (MCPServer) tools and resources:** an uncaught exception with sensitive text — it is masked.
- **Severity:** **Medium**; **High** if the leaked text can contain credentials, connection strings, or tokens.
- **Fix 1.x:** `except ToolError: raise` then `except Exception: logger.exception("...")` (stderr) and `raise ToolError("Internal error; see server logs")`.
- **Fix 2.x:** let unexpected exceptions propagate (masked), or `logger.exception(...)` then `raise ToolError("<safe summary>") from e`. 2.x does **not** log the cause of a deliberate `ToolError`, so log before raising.
- **3p:** masking not verified — report `str(e)` in error messages as Medium and list uncaught-exception leakage under "Could not verify".

### R5 — Low-level handler without try/except · 1.x, 2.x

- **Runtime 2.x:** no low-level handler is wrapped. An exception escaping any `on_*` handler (`on_call_tool`, `on_read_resource`, `on_get_prompt`, `on_list_*`) reaches `initialize`-based clients (all current stdio clients) as **JSON-RPC error code 0 with the raw `str(e)`**. Exceptions: a pydantic `ValidationError` becomes `-32602 "Invalid request parameters"` with no text; an `MCPError` keeps its own code.
- **Runtime 1.x:** `@server.call_tool()` handlers are wrapped by the SDK (exceptions → `isError: true` with the text — see R4). `@server.read_resource()`, `@server.get_prompt()` and `@server.list_*()` handlers are not: code 0 with `str(e)`.
- **Verified:** probe `lowlevel_server.py` `stock("pear")` → `JSON-RPC error 0: 'pear'`; `2.2.0/shared/jsonrpc_dispatcher.py:98-102`, `:757`; `1.30.0/server/lowlevel/server.py:794`.
- **Detect:** 2.x `Server(..., on_<x>=<fn>)` where `<fn>` has no top-level `try`; 1.x `@server.read_resource()` / `@server.get_prompt()` / `@server.list_*()` bodies with no top-level `try`. A project-wide middleware that catches and returns a result model is a valid mitigation — check before flagging.
- **Severity:** **High** for `on_call_tool` (the error is hidden from the model and raw text leaks); **Medium** for other handlers.
- **Fix 2.x:** `import logging; logger = logging.getLogger(__name__)`, `import mcp.types as types`, `from mcp import MCPError`; then `try: ... except MCPError: raise except Exception: logger.exception(...); return types.CallToolResult(content=[types.TextContent(type="text", text="<safe message>")], is_error=True)`.
- **Fix 1.x:** `from mcp.shared.exceptions import McpError`, `from mcp.types import ErrorData, INTERNAL_ERROR, INVALID_PARAMS`; catch, log to stderr, and `raise McpError(ErrorData(code=INTERNAL_ERROR, message="<safe message>"))` (`INVALID_PARAMS` for a missing resource).

### R6 — Error flag spelled for the wrong SDK version · 1.x, 2.x

- **Runtime 1.x:** `CallToolResult(is_error=True)` (the 2.x spelling) is **silently accepted**: it goes out as an unknown extra `is_error` key next to `isError: false`, and clients ignore it. Same for `structured_content=`.
- **Runtime 2.x:** the constructor accepts both `is_error=` and `isError=`, but **reading or assigning `.isError` raises**, so a tool that checks `result.isError` fails on every call. A 2.x low-level `on_call_tool` that returns a *dict* with an `"is_error"` key has that key dropped (flag false); `"isError"` works.
- **Verified:** probe `strict_lookup` → 1.30.0 `isError=False` with a stray `is_error: true` key; probe `lookup_or_default` → 2.2.0 masked error for both a missing and an existing note. `1.30.0/types.py:141` (`extra="allow"`), `1.30.0/shared/session.py:346`, `2.2.0/../mcp_types/_types.py:48`.
- **Detect:** 1.x: `is_error=` / `structured_content=` in `CallToolResult(...)`, and `.is_error` **only when the receiver is a `CallToolResult`** (ignore `httpx`/`requests` responses, which have their own `.is_error`). 2.x: `.isError` / `.structuredContent` reads or writes on a `CallToolResult`; `"is_error"` keys in dicts returned from `on_call_tool`. In a *high-level* tool, a dict with an `"isError"`/`"is_error"` key is just JSON text with the flag false — report it as R1. In 1.x low-level `@server.call_tool()`, a returned dict becomes structured content with the flag false — R1.
- **Not a finding on 2.x:** `CallToolResult(isError=True)` in a constructor call; `"isError"` in a dict returned from a low-level `on_call_tool`.
- **Severity:** 1.x spelling mistakes and dropped dict keys: **High** (silent). 2.x `.isError` attribute access: **Medium** (the tool fails loudly on every call).
- **Fix:** 1.x `isError=True`, `.isError`; 2.x `is_error=True`, `.is_error`. Return a `CallToolResult` model rather than a look-alike dict.

### R7 — Writes to stdout on the stdio transport · all (stdio only)

- **Runtime 1.x:** no protection. `print()` output shares a buffer with protocol frames. Small prints sit in the buffer; once ~8 KB accumulates, the flush **glues print output onto a JSON-RPC frame and that call's response is lost** — the client just times out.
- **Runtime 2.x:** while serving, stdout is redirected to stderr at the file-descriptor level. With default (block) buffering, prints from import time and from handlers stay in Python's buffer and reach the real stdout only **after shutdown**, which is harmless. Real damage on 2.x needs output flushed to stdout **before `run()`** (`print(..., flush=True)`, `sys.stdout.flush()`, `python -u`/`PYTHONUNBUFFERED` — *source only*; a 9 KB print stayed buffered in the probe), or disabled protection: `sys.stdout` replaced by an object not backed by file descriptor 1, or an explicit `stdout=` passed to `stdio_server()`.
- **Verified:** 1.30.0 probe — `debug_echo` with a 9 KB message: no response within 20 s; the stray stdout line (27,131 chars) is the print text followed by the lost JSON response. 2.2.0 probe — no stray output during the session, including a 9 KB handler print; the import-time and handler prints appeared on the real stdout after shutdown. `1.30.0/server/stdio.py:49`, `2.2.0/server/stdio.py:141`, `:213-217`.
- **Detect (stdio servers only):** `print(` without `file=sys.stderr`; `sys.stdout.write`, `sys.stdout.buffer.write`, `os.write(1, ...)`; `logging.StreamHandler(sys.stdout)` / `stream=sys.stdout` / `basicConfig(stream=sys.stdout)` / `'ext://sys.stdout'`; `rich` `Console()` without `stderr=True`; `click.echo` without `err=True`; subprocesses that inherit stdout; reassignment of `sys.stdout`.
- **Severity:** 1.x **High**. 2.x: **High** if protection is disabled; **Medium** for output flushed or unbuffered before `run()`; **Low** otherwise (hygiene). HTTP-only servers: at most **Low**.
- **Fix:** `print(..., file=sys.stderr)` or stdlib `logging` (the SDK's default handler writes to stderr). Configure logging before constructing the server.

### R8 — Deprecated protocol-level logging · 2.x

- **Runtime 2.x:** `ctx.log/debug/info/warning/error` are deprecated (spec 2026-07-28, SEP-2577). Each call emits up to three `MCPDeprecationWarning`s, and on 2026-07-28 connections nothing is sent unless the client opted in.
- **Verified:** probe `log_something` → three warnings on 2.2.0 stderr; `2.2.0/server/mcpserver/context.py:257`.
- **Detect (2.x):** `.log/.debug/.info/.warning/.error` calls on a parameter annotated `Context` (any name); `session.send_log_message(`; `Connection.log(`.
- **Not a finding on 1.x:** `ctx.info` is not deprecated there (but must be awaited).
- **Severity:** **Low**.
- **Fix 2.x:** stdlib `logging.getLogger(__name__)` for operator diagnostics; put anything the model needs into the tool result.

### R9 — Hardcoded secrets · all

- **Basis:** the spec says stdio servers SHOULD take credentials from the environment (`basic/authorization`); flagging literals follows from that.
- **Detect:** any credential-shaped literal assigned to a key/token/secret/password name or passed as one — **even if it looks like a demo value**; DSNs with embedded credentials; private keys.
- **Not a finding (report Low with a note at most):** an empty string, or an obvious template marker (`<...>`, `your-...-here`) used only as an environment-variable default.
- **Severity:** **High**. **Fix:** read from environment variables; document them in the README; never commit `.env`.

### R10 — Hardcoded machine-specific paths · all · *house rule, not in the MCP spec*

- **Detect:** absolute paths into one developer's home (`/Users/<name>`, `C:\Users\<name>`, `/home/<name>`).
- **Severity:** **Low** (portability). **Fix:** config/env var, or a path relative to the project.

### R11 — File access controlled by tool arguments · all

- **Runtime:** a path built from an argument without `resolve()` plus an allowed-root check can escape the intended folder; a tool that opens a full path given as an argument can read any file the server can. 2.x resource **templates** reject `..`/absolute paths by default (`2.2.0/server/mcpserver/resources/templates.py:47`) unless relaxed by `exempt_params`, a per-resource `security=ResourceSecurity(reject_path_traversal=False, ...)`, or a server-wide `resource_security=`. Tools get no such protection in either version; 1.x templates only exclude `/`.
- **Detect:** `Path(base) / arg`, `os.path.join(base, arg)`, `Path(arg)`/`open(arg)` on an argument, with no `resolve()` + `is_relative_to(root)` check; relaxed `ResourceSecurity` settings on 2.x.
- **Severity:** **High**. **Fix:** `p = (ROOT / arg).resolve(); if not p.is_relative_to(ROOT.resolve()): raise ToolError("path outside allowed folder")`.

### R12 — HTTP transport exposure · all (HTTP only)

- **Runtime:** with no `transport_security`, Host/Origin checks are **off**; the SDK auto-enables them only when the host is exactly `127.0.0.1`/`localhost`/`::1`, so binding `0.0.0.0` also disables DNS-rebinding protection. With `auth=` but neither `token_verifier=` nor `auth_server_provider=`, or with no `auth=` at all, the MCP endpoint has **no auth**. `@custom_route` handlers are never auth-wrapped. Forwarding the inbound bearer token (token passthrough) is not prevented by the SDK.
- **Verified (source only; no HTTP fixture yet):** `1.30.0/server/fastmcp/server.py:191` (localhost auto-enable), `:246-247` (verifier built from `auth_server_provider`), `:1052` (unwrapped route); `2.2.0/server/lowlevel/server.py:742` (auto-enable), `:816` (no-auth route); `2.2.0/server/mcpserver/server.py:1155` (SSE).
- **Detect:** 1.x `FastMCP(host=...)` / 2.x `run("streamable-http", host=...)` and whether `transport_security=` is passed; `auth=` together with `token_verifier=` or `auth_server_provider=`; `get_access_token().token` used in outbound requests; `AuthSettings(...)` where `validate_token_resource` is unset and the verifier doesn't check the audience.
- **Severity:** no auth on a non-loopback bind: **High**. Loopback with Host/Origin checks disabled: **Medium**. No auth on the loopback default with auto-enabled checks: **Low** (note it).

### R13 — Missing resource reported wrongly · 1.x, 2.x

- **Runtime:** returning `""`/`None`/`[]`/a default for a missing item is a **successful** read with one content item. The spec wants error `-32602`. 2.x: raise `ResourceNotFoundError` → `-32602`; a plain `ResourceError` → `-32603`. 1.x cannot emit `-32602` from a resource function (every exception becomes code 0).
- **Verified:** probe `notes://missing` → 1 content item on both; `archive://missing` (plain `ResourceError`) → 2.2.0 `JSON-RPC error -32603`. `2.2.0/server/mcpserver/server.py:465`; `1.30.0/server/fastmcp/resources/types.py:69-71` (single content item), `:73` + `1.30.0/server/lowlevel/server.py:794` (code 0).
- **Detect:** in resource functions (`@<instance>.resource(...)`, especially templated URIs), not-found branches that `return ""`/`None`/`[]`/`{}` or `.get(key, "")`; on 2.x, not-found branches that `raise ResourceError(` instead of `ResourceNotFoundError(`.
- **Not a finding:** an existing resource whose content is legitimately empty.
- **Severity:** empty content for a missing item: **Medium**. 2.x plain `ResourceError` for not-found: **Low** (the client does get an error; only the code is wrong).
- **Fix 2.x:** `from mcp.server.mcpserver.exceptions import ResourceNotFoundError` → `raise ResourceNotFoundError(...)`. **Fix 1.x:** raise an exception rather than returning empty content (the code will be 0, and the message text is sent to the client — see R4).

### R14 — Unlocked shared state in sync handlers · 2.x

- **Runtime 2.x:** sync (`def`) tools, resources, templates and prompts run on worker threads (up to 40), so read-modify-write on shared state races. A cancelled request's thread keeps running.
- **Verified (source only; a single-call probe cannot show a race):** `2.2.0/server/mcpserver/utilities/func_metadata.py:164`.
- **Detect:** check-then-act or read-modify-write on module-level state in a sync handler (`global x; x = x + 1`, `if k not in d: d[k] = ...`, lazy singletons, SQLite connections created at import).
- **Not a finding:** single atomic container operations (`d[k] = v`, `.append(...)`); anything on 1.x, where sync tools run serially on the event loop.
- **Severity:** **Medium** (High when it corrupts IDs, balances, or files).
- **Fix 2.x:** `threading.Lock` around the whole read-modify-write, or make the handler `async def`.

### R15 — SDK version and dependency pin disagree · 1.x, 2.x

- **Runtime:** a fresh `pip install mcp` now installs **2.x**. On 2.x, 1.x code fails at startup: `ModuleNotFoundError` for `mcp.server.fastmcp`, `ImportError` for `McpError`, `AttributeError` at decoration for 1.x low-level decorators. A `try/except ImportError` around the import silently takes the fallback branch.
- **Verified:** `2.2.0/server/fastmcp.py:16`; `2.2.0/server/lowlevel/server.py:154` (no `call_tool` decorator). *External (checked 2026-09-30):* PyPI latest `mcp` = 2.2.0.
- **Detect:** 1.x code (imports **or** low-level decorators) with any `mcp`/`mcp[...]` requirement whose upper bound admits 2.x: unpinned, `>=1.x` with no `<2` (what `uv add` writes by default), `>=2`, `*`. 2.x code with `mcp<2`. If a lock file (`uv.lock`, `poetry.lock`) pins 1.x but the declared requirement allows 2.x, name the install path that breaks (e.g. `pip install .`).
- **Severity:** **High**. **Fix:** pin `mcp>=1.x,<2` for 1.x code, or migrate (`FastMCP` → `MCPServer`, `McpError(ErrorData(...))` → `MCPError(code=..., message=...)`, host/port move from the constructor to `run()`).
