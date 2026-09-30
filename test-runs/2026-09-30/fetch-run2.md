I audited the fetch server at `src/fetch` and changed nothing. There are no High findings: 3 are Medium, 2 are Low, and 1 more issue falls outside the rule set. One gap matters most: I couldn't check what the readabilipy library writes to stdout. If it writes anything there, that is a High finding that would lose server responses (details under "Could not verify").

## What the server is

- **Entry point:** `src/mcp_server_fetch/server.py` creates the server at line 193 and starts it at line 287. `__init__.py` and `__main__.py` just launch it. I left out the files under `tests/`.
- **Transport:** stdio only.
- **SDK:** the official `mcp` package, version 1.x, low-level `Server` API (not FastMCP). The imports and handler decorators all match 1.x.
- **Version pin:** `pyproject.toml:21` has `mcp>=1.29.0,<2`, which matches the code. The lock file (`uv.lock:541-542`) installs 1.29.0, and the Docker image uses that locked version. `pip install` and `uvx` get the newest 1.x. The rules were checked against 1.30.0.

## Findings

**1. Medium — R1 — `server.py:40`**
`return "<error>Page failed to be simplified from HTML</error>"`
- When a page has no readable article content (common on JavaScript-heavy pages), this string is returned as the page content. The model gets `Contents of <url>:\n<error>Page failed to be simplified from HTML</error>` marked as a success (`isError: false`). Nothing tells it that retrying with `raw=true` would work.
- The prompt path (`:265`, `:281`) shows the same string to the user as if it were the page.
- **Fix:** raise an error instead, using the same exception type as the other fetch failures, with a message like "Page could not be simplified to markdown; call fetch again with raw=true". Both callers already handle that. Or fall back to the raw content with a note saying so.

**2. Medium — R4 — `server.py:128`**
`raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"))`
- The model gets the raw text of the network error: OS error messages, TLS certificate details, proxy status lines. The README says the server can reach internal addresses (`README.md:11-12`). Telling "connection refused" apart from "timed out" or a TLS failure makes it easier to probe internal hosts and ports.
- The tool handler (`:224`) has no catch-all, so any other exception also reaches the model word for word. Examples:
  - errors from readabilipy or markdownify while converting the page
  - a bad `--proxy-url` failing when the HTTP client is created (`:75`, `:119`, both outside the `try`)
- **Fix:**
  - Log the detail to stderr (`logger.warning("fetch %s failed: %r", url, e)`) and send a short summary such as `f"Failed to fetch {url}: connection error"`.
  - In the tool handler, add `except McpError: raise`, then `except Exception:` that logs the error and raises "Internal error; see server logs".

**3. Medium — R5 — `server.py:258`, `:267`**
`async def get_prompt(...)` … `except McpError as e:`
- In 1.x the SDK doesn't catch errors from prompt handlers, and this handler only catches `McpError`. Anything else goes back to the client as a protocol error (code 0) with the raw exception text, instead of the handler's own "Failed to fetch" message.
- **How it happens:** the tool validates its URL, but the prompt doesn't. A malformed URL typed by the user raises httpx's `InvalidURL`, which neither `except` clause catches (`:127`, `:267`). Errors from the page conversion step escape the same way.
- **Fix:**
  - Validate the URL first with `Fetch(url=arguments["url"])`, and raise an `INVALID_PARAMS` error if it fails.
  - After the existing `except McpError`, add `except Exception:` that logs the error and returns a `GetPromptResult` with a safe "Failed to fetch" message.

**4. Low — R3 — `server.py:224`**
`async def call_tool(name, arguments: dict) -> list[TextContent]:`
- The handler never checks `name`. In 1.x, a call to a tool that was never listed skips input checking (the SDK only logs a warning) and still reaches this handler. The handler runs a fetch and reports success, so calling a tool that doesn't exist works instead of failing.
- It's Low because the only effect is running the server's one real tool; no failure is hidden. `get_prompt` (`:258`) ignores `name` the same way.
- **Fix:** raise an error for any name other than `"fetch"`, in both handlers.

**5. Low — R2 — `server.py:228` (also `:232`, `:83`, `:88`, `:100`, `:128`, `:130`)**
`raise McpError(ErrorData(code=INVALID_PARAMS, message=str(e)))`
- The model still sees these errors (marked `isError: true` with the message), but the error code (`INVALID_PARAMS` vs `INTERNAL_ERROR`) is lost. There's no practical harm today.
- **Fix:** raise `ToolError` (`from mcp.server.fastmcp.exceptions import ToolError`) or a local exception class from the helpers, and catch that type in `get_prompt` (`:267`). This matters mostly for the planned move to SDK 2.x (`README.md:9`).

**Not covered by the rules: a failing robots.txt allows the fetch — `server.py:92-94`**
- When the site's robots.txt returns a server error (5xx), that error page is read as if it were robots.txt. That usually gives no rules, so the fetch goes ahead. A connection failure, by contrast, blocks the fetch (`:82-86`).
- RFC 9309 §2.3.1.4 says that when robots.txt returns a 5xx, the crawler should assume everything is disallowed.

## Checked and clean

- **R15:** the version pin matches the 1.x code.
- **R1, other returns:** "No more content available" (`:241-242`, `:245-246`) is a deliberate end-of-content signal, not a hidden error.
- **R3, arguments:** the tool is listed, the SDK's default input checking is on, and the `Fetch` model is typed. Bad input raises an error, which the model sees.
- **R5, list handlers:** `list_tools` (`:198`) and `list_prompts` (`:210`) have no `try`, but they only build fixed lists and can't realistically fail.
- **R6:** no hand-built tool results anywhere.
- **R7:** I read all three modules in full. The server's own code never writes to stdout (no `print`, no stdout logging, no subprocess). The open question is readabilipy, below.
- **R9:** no credentials in the code. The user-agent strings (`:23-24`) aren't secrets, and the proxy URL comes from the command line.
- **R10:** no paths into a developer's home folder.
- **R11:** no file paths are built from arguments, and the HTTP client can't open `file://` URLs. Reaching internal addresses is a separate, documented risk (`README.md:11-12`).
- **Not applicable:** R8 and R14 apply only to SDK 2.x, R12 only to HTTP servers, and R13 only to servers with resources.

## Could not verify

1. **SDK 1.29.0 vs. the 1.30.0 baseline.** No environment is installed, so there was no SDK source to check. Findings 2–5 rely on 1.x behavior that the rules checked only on 1.30.0:
   - tool errors reach the model as `isError: true` with the text unchanged (R2, R4)
   - prompt errors aren't caught, so they go out as code 0 (R5)
   - nothing stops code from writing to stdout (R7)
   - a call to an unlisted tool skips input checking (R3); this one isn't in the rules' checked list either
2. **readabilipy and stdout (R7).** readabilipy runs Node.js when it's installed (`README.md:33`), via `simple_json_from_html_string(html, use_readability=True)` at `:36-38`. If that process shares the server's stdout, or readabilipy prints anything there, it corrupts the stdio stream and responses are lost. That would be **R7 High**. readabilipy isn't installed here, so its source still needs checking.
3. **What readabilipy and markdownify errors say.** Finding 2 means their error text reaches the model word for word. I couldn't check whether it includes things like temp-file paths or command lines.
4. **The proxy URL in error messages.** I couldn't check whether any httpx error text can include the `--proxy-url`. If it can and that URL contains credentials, finding 2 becomes High.

I can explain any finding in more detail, draft a fix for one, or check whether readabilipy writes to stdout (item 2 above). I'll only edit files if you ask.
