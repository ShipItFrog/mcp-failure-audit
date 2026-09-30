# Test log

Everything this plugin claims should be traceable to a row in this file. Rows marked **pending** have not been run yet.

## Environment

| Item | Value |
|---|---|
| Claude Code | 2.1.284 |
| OS | Windows 11 |
| Plugin version | 0.1.0-dev |

## 1. Packaging and install paths

| # | Path | How it was tested | Result | Notes |
|---|---|---|---|---|
| P1 | `claude plugin validate --strict` on both manifests | local, 2026-09-30 | pass | Run on the repo root, `validate` only checks `marketplace.json`. The plugin manifest has to be validated separately: `claude plugin validate .claude-plugin/plugin.json --strict`. Both pass. |
| P1b | `claude plugin tag . --dry-run` (plugin.json and marketplace entry agree) | local, 2026-09-30 | pass | Would tag `mcp-failure-audit--v0.1.0`. |
| P2 | Load for development with `--plugin-dir` | local, 2026-09-30 | partial | `claude --plugin-dir . plugin details mcp-failure-audit` lists 1 skill (`audit`) and 1 agent (`auditor`); always-on cost about 199 tokens. The skill has not been invoked yet. |
| P3 | Fresh install from GitHub in a clean config directory | clean `CLAUDE_CONFIG_DIR` | pending | |
| P4 | Skill invokes the auditor subagent | clean install | pending | |
| P5 | Update to a new version | clean install | pending | |
| P6 | Uninstall and remove the marketplace | clean install | pending | |

## 2. Rule evidence (runtime behavior of the SDKs)

Each rule's runtime claim was checked against the installed SDK source (1.30.0 and 2.2.0) and, where possible, by running deliberately broken fixture servers and recording the raw JSON-RPC traffic with `fixtures/probe.py` (standard library only; no SDK on the client side). Answer key: `fixtures/EXPECTED.md`. Raw results: `fixtures/*/probe-results*.json`. The rule text and answer key were then reviewed by four independent reviewers (source accuracy, probe evidence, fixture consistency, auditor usability); 55 of their 56 issues were fixed before this commit; the remaining one (fixtures label their own defects, so accuracy runs must use label-stripped copies) is a requirement on the accuracy tests in section 3.

| Finding | 1.30.0 | 2.2.0 |
|---|---|---|
| Tool returns `{"ok": False, "error": ...}` | `isError=false` | `isError=false` |
| `CallToolResult(is_error=True)` (2.x spelling) | flag silently dropped → `isError=false` | works |
| Reading `result.isError` | works | tool fails on every call |
| Uncaught exception with internal details | details sent to the model | masked |
| `ToolError(f"...{e}")` | details sent | details sent |
| `raise MCPError`/`McpError` in a tool | tool error, code lost | JSON-RPC error, no tool result |
| `print()` of ~9 KB inside a tool (stdio) | **response lost; client timed out** | no effect during the session |
| Low-level `on_call_tool` raises `KeyError` | — | JSON-RPC error code 0 with raw text |
| Missing resource returned as `""` | success, 1 empty item | success, 1 empty item |

## 3. Audit accuracy

### Target A: mcp-flashcards (my own server, SDK 1.x)

| Rule | Expected | Found by plugin | Verdict (true positive / false positive / missed) |
|---|---|---|---|
| | | | pending |

### Target B: a third-party public MCP server (not designed by me)

| Rule | Expected | Found by plugin | Verdict |
|---|---|---|---|
| | | | pending |

## 4. Known limitations and what breaks

- **Validation blind spot (packaging):** in a one-plugin repo that is also its own marketplace, `claude plugin validate .` reports "Validation passed" after checking only the marketplace manifest. A broken `plugin.json` would not be caught by that command alone. Mitigation: validate both manifests (see P1).
- Audit accuracy: pending.
