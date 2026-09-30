The auditor finished. Here is its report as written:

---

# Failure-handling audit: `mcp-server-fetch`

I found no High-severity defects. There are five Medium findings and one Low. The main problems are failures reported as normal results, and raw exception text reaching the model or client.

## Target and SDK detected

- **Target:** the `mcp-server-fetch` 0.6.3 server. Every file reference below is `server.py:NN` or `pyproject.toml:NN`, meaning:
  - `<run>\servers\src\fetch\src\mcp_server_fetch\server.py`
  - `<run>\servers\src\fetch\pyproject.toml`
- **Entry points:**
  - `server.py`: the server is built at line 193 (`server = Server("mcp-fetch")`).
  - `__init__.py`: `main()` calls `serve()`. The installed command is `mcp-server-fetch = "mcp_server_fetch:main"` (`pyproject.toml:33`).
  - `__main__.py`
- **Excluded:** `tests\test_server.py` and `tests\__init__.py` (tests). The folder has no examples or client scripts. I read the `Dockerfile` only for context.
- **Transport:** stdio. `server.py:287` has `async with stdio_server() as (read_stream, write_stream):`.
- **SDK:** official `mcp` **1.x, low-level server**. Evidence:
  - `server.py:6`: `from mcp.shared.exceptions import McpError`
  - `server.py:197`: `@server.list_tools()`
  - `server.py:223`: `@server.call_tool()`
  - `server.py:257`: `@server.get_prompt()`
  - There are no 2.x signals.
- **Pin (R15):**
  - Declared at `pyproject.toml:21`: `"mcp>=1.29.0,<2",`
  - `uv.lock:541-542` resolves `mcp` to **1.29.0**. That is not the 1.30.x baseline the rules were checked against (see "Could not verify").

## Findings

**1. Medium · R1 · `server.py:40`**
```python
return "<error>Page failed to be simplified from HTML</error>"
```
- **What goes wrong:** when readability can't pull an article out of the page (common for JavaScript-heavy pages), `call_tool` returns `Contents of <url>:\n<error>Page failed to be simplified…</error>` with `isError: false`. The fetched HTML is thrown away. The text is readable, but the error flag is false, and the model isn't told that `raw=true` would work.
- **Fix:** raise an exception here, for example `ToolError("Page could not be simplified to markdown; retry with raw=true")`. The 1.x low-level wrapper turns any exception into `isError: true`. Alternatively, fall back to the raw content with a prefix explaining why.
- `get_prompt` calls this function too, so apply fix 3 at the same time.

**2. Medium · R4 · `server.py:224`**
```python
async def call_tool(name, arguments: dict) -> list[TextContent]:
```
- **What goes wrong:** the tool makes HTTP requests and runs readabilipy, which can start a Node.js subprocess, but it has no top-level `try`. The only catch is `except HTTPError` around `client.get`.
- Any other exception reaches the model word for word as `isError: true` text. On 1.x there is no masking, and this code logs nothing to the server's error log. Examples:
  - readabilipy or markdownify failures (lines 36-44)
  - `httpx.InvalidURL`, which is not a subclass of `HTTPError`
  - proxy setup errors from `AsyncClient(proxy=proxy_url)` (lines 75 and 119)
- **Fix:** wrap the body. Use `except McpError: raise`, then `except Exception: logger.exception("fetch failed")` followed by `raise ToolError("Failed to process <url>; see server logs")`.

**3. Medium · R5 · `server.py:258`**
```python
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
```
- **What goes wrong:** the only `try` (line 264) catches `McpError` alone.
- The `url` comes straight from the prompt arguments and is never checked (line 262), so `httpx.InvalidURL` is reachable. `extract_content_from_html` failures are also uncaught.
- Any other exception goes to the client as a JSON-RPC error with code 0 and the raw `str(e)`. This is because of `raise_exceptions=False` (line 288) and the 1.x low-level behaviour.
- **Fix:** check `url` first, for example with `AnyUrl` or the `Fetch` model, and raise `INVALID_PARAMS` if it's bad. Then add a top-level `except Exception` that calls `logger.exception(...)` and raises `McpError(ErrorData(code=INTERNAL_ERROR, message="<safe message>"))`.

**4. Medium · R4 · `server.py:128`**
```python
raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"))
```
- **What goes wrong:** the `repr` of the httpx exception goes to the model. That can include OS error codes, TLS library details, and proxy errors.
- **Fix:** log `e!r` to stderr and send only `f"Failed to fetch {url}: {type(e).__name__}"`. The class name, such as `ConnectError`, `ReadTimeout` or `TooManyRedirects`, still tells the model what kind of failure it was.

**5. Medium (borderline) · R3 · `server.py:241-242`**
```python
if args.start_index >= original_length:
    content = "<error>No more content available.</error>"
```
- **What goes wrong:** a `start_index` past the end of the content comes back as a normal result with `isError: false`.
- A page that returns no content at all (`original_length == 0`) gets the same misleading message.
- The text is explicit, so this is close to the rules' "zero matches, stated explicitly" exemption. Treat it as the least important Medium.
- **Fix:** raise with the length included, for example `start_index 12000 is past the end of the content (length 8000)`.

**6. Low · R2 · `server.py:83, 88, 100, 128, 130, 228, 232`**
```python
raise McpError(ErrorData(
```
- **What goes wrong:** these raises all happen inside the tool's execution path. On 1.x the low-level wrapper turns them into `isError: true` text, so the codes `INVALID_PARAMS` and `INTERNAL_ERROR` are lost. Behaviour is otherwise correct.
- **Why it matters later:** after a migration to 2.x, these would become JSON-RPC protocol errors, which clients only MAY show to the model. That would be Medium.
- **Fix:** raise `ToolError(msg)` in the tool path.

**Outside the rule set (not rated, one line each):**
- `call_tool` (line 224) and `get_prompt` (line 258) never check `name`. Any tool or prompt name runs the fetch instead of being rejected.
- A robots.txt fetch that returns a 5xx status falls through at lines 92-94, and the error page is parsed as robots.txt. That usually allows everything, whereas RFC 9309 says a crawler must assume complete disallow when robots.txt fails with a 5xx.

## Checked and clean

- **R15:** the `<2` upper bound matches the 1.x code.
- **R6:** no `CallToolResult` is built anywhere, and there is no `is_error` or `structured_content` usage.
- **R7 (server code):** `src\` has no `print(`, `sys.stdout`, `os.write`, logging handler pointed at stdout, or subprocess call. argparse only writes output before the server starts, e.g. `--help`, which exits.
- **R9:** no secrets. The user-agent strings are not credentials.
- **R10:** no machine-specific paths.
- **R11:** no file access based on arguments. httpx rejects `file://`. Fetching internal addresses (SSRF) is outside this rule and is already flagged as a caution in the README (lines 11-12).
- **R3 (schema validation):** `@server.list_tools()` is present and `@server.call_tool()` uses the default input validation. `Fetch(**arguments)` also raises on bad input.
- **R5 on `list_tools` / `list_prompts`:** both just return fixed values and have no way to fail.
- **Other R1 candidates:**
  - Line 246 can never run: `max_length` must be greater than 0, so the slice is never empty.
  - The truncation hint at line 254 is part of a successful result, not a failure.
- **Not applicable:**
  - R8 and R14 are 2.x-only.
  - R12 is HTTP-only.
  - R13 needs resources, and the server defines none.

## Could not verify

- **SDK behaviour on 1.29.0:**
  - **What depends on it:**
    - R2: the code is lost but `isError` is true.
    - R4: no masking of exception text.
    - R5: code 0 with `str(e)` for `get_prompt`.
    - R7: no stdout protection.
    - The R6 alias difference doesn't matter here because nothing uses it.
  - **Why unverified:** the rules checked these against 1.30.0, but the lock file resolves to 1.29.0. `pip install .` would pick the newest 1.x instead. There is no `.venv` in the server folder, so I couldn't read the installed SDK source.
- **R7 through readabilipy:** `server.py:36-38` calls `simple_json_from_html_string(html, use_readability=True)`, which runs Node.js as a subprocess when `node` is on PATH. I couldn't check whether that child process shares the stdio transport's stdout or ever writes to it, because readabilipy isn't installed. If it does, this is **R7 High on 1.x**.
- **Finding 4 severity:** it would rise to High if httpx exception text can include proxy credentials from `--proxy-url http://user:pass@…`. I believe httpx hides the password in URL output, but I couldn't confirm that here.

---

**Next steps:** I haven't changed any files. If you want, I can explain any finding in more detail, or draft a fix for one. The most useful places to start are:
- **Findings 2 and 3:** adding top-level exception handling to `call_tool` and `get_prompt`.
- **The readabilipy stdout question:** checking it would require running `uv sync` to install dependencies.
