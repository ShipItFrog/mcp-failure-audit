# Test log

Everything this plugin claims should be traceable to a row in this file. Rows marked **pending** have not been run yet.

## Environment

| Item | Value |
|---|---|
| Claude Code | 2.1.284 |
| OS | Windows 11 |
| Plugin version | 0.1.1 (accuracy runs in section 3: 0.1.0-dev) |

## 1. Packaging and install paths

| # | Path | How it was tested | Result | Notes |
|---|---|---|---|---|
| P1 | `claude plugin validate --strict` on both manifests | local, 2026-09-30 | pass | Run on the repo root, `validate` only checks `marketplace.json`. The plugin manifest has to be validated separately: `claude plugin validate .claude-plugin/plugin.json --strict`. Both pass. |
| P1b | `claude plugin tag . --dry-run` (plugin.json and marketplace entry agree) | local, 2026-09-30 | pass | Would tag `mcp-failure-audit--v0.1.0`. |
| P2 | Load for development with `--plugin-dir` | local, 2026-09-30 | pass | `plugin details` lists 1 skill (`audit`) and 1 agent (`auditor`); always-on cost about 199 tokens. Invoked 8 times non-interactively (section 3). |
| P3 | Fresh install from GitHub in a clean config directory, using the README's commands | new empty `CLAUDE_CONFIG_DIR`, fresh login, 2026-09-30 | pass | `marketplace add ShipItFrog/mcp-failure-audit` and `install mcp-failure-audit@shipitfrog --scope user` both succeeded; `plugin details` shows 1 skill and 1 agent. The user's normal Claude Code config (`~/.claude.json`, plugin registry) was untouched. |
| P4 | Installed plugin runs a real audit | clean install | **fail on 0.1.0 → fixed in 0.1.1** | On 0.1.0 the auditor could not read its own rule file: installed plugins live in the config's plugin cache, outside the audited project, so the read was denied (it would prompt the user in interactive mode). The `--plugin-dir` runs in section 3 passed `--add-dir` for the plugin folder, which hid this. 0.1.1 builds the rules into the agent's instructions: 0 permission denials, and the 1.x fixture scored 13/13 with 0 false positives. |
| P5 | Update to a new version | clean install, 2026-09-30 | pass | With 0.1.0 installed, pushed 0.1.1 (tag `mcp-failure-audit--v0.1.1`), then `marketplace update` + `plugin update` → "updated from 0.1.0 to 0.1.1". On an unchanged version, `update` reports "already at the latest version". |
| P6 | Uninstall and remove the marketplace | clean install, 2026-09-30 | pass | `plugin uninstall` and `marketplace remove` both succeeded; `plugin list` shows no plugins. |

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

## 3. Audit accuracy (2026-09-30)

### How the runs were done

- **Invocation:** `claude -p "/mcp-failure-audit:audit ." --plugin-dir <plugin> --add-dir <plugin>`, run from the target folder. `<plugin>` was a copy holding only the plugin files, so the auditor could not see the answer key. Claude Code 2.1.284, default model, **two runs per target**. Note: `--add-dir` gave the auditor read access to the plugin folder, which a real install does not have; that hid the P4 failure fixed in 0.1.1. The rule text itself was the same, and the clean-install run of 0.1.1 is scored in the same table.
- **Fixtures** were audited as label-stripped copies made by `fixtures/make_blind.py`: comments and module docstrings removed, neutral file and server names, written outside the repo.
- **Scoring:** fixture runs against `fixtures/EXPECTED.md`. On the real servers, every finding was checked against the source and the installed SDK by **two independent verifiers**. Each real server also got an **independent audit** by a reviewer who never saw the plugin's reports, to catch misses.
- **Raw reports:** `test-runs/2026-09-30/` (local paths scrubbed; a trailing environment notice unrelated to the audit removed).
- **Cost:** 8 runs, US$8.08 in total, 2 to 6.5 minutes each.

### Results

| Target | Run | Defects to find | Found | False positives | Notes |
|---|---|---|---|---|---|
| Fixture, SDK 1.x | 1 | 13 | 13 | 0 | All severities in range; all 3 decoys left alone |
| | 2 | 13 | 13 | 0 | Same |
| Fixture, SDK 2.x + low-level | 1 | 15 | 15 | 0 | All 7 decoys left alone (one flagged at Low, which the key allows) |
| | 2 | 15 | 15 | 0 | Same |
| **mcp-flashcards** (mine, SDK 1.x) | 1 | 4 | 4 | 0 | |
| | 2 | 4 | 4 | 0 | Reported two of them as one finding |
| **fetch** (third party, SDK 1.x low-level) | 1 | 5 | 5 | 0 | Plus 1 disputed (see below) |
| | 2 | 5 | 4 | 1 | Missed the R4 finding on `call_tool` |
| Fixture, SDK 1.x — **installed 0.1.1**, clean config, no extra permissions | 1 | 13 | 13 | 0 | All 3 decoys left alone (see P4) |

**Fixtures:** 56 of 56 expected findings across the four `--plugin-dir` runs, plus 13 of 13 from the clean install. 0 false positives, and no decoy flagged above the allowed severity.
**Real servers:** 17 of 18 known defects across four runs. Of 18 rated findings, 16 were confirmed by both verifiers, 1 was a false positive, and 1 is disputed.

### Target A: mcp-flashcards — found, fixed, verified

Both runs found, and both verifiers confirmed:

- **R1 High:** if `cards.json` wasn't valid JSON, the server moved it aside and answered with an empty deck and `isError: false`, so the model would report the cards as gone. A UTF-8 byte-order mark alone triggered it: files saved by PowerShell 5.1 or some Windows editors start with one, and Python's JSON parser rejects it.
- **R1 Medium:** `grade_card` / `delete_card` with an unknown id returned `{"ok": false}` as a successful result.
- **R4 Medium:** file errors reached the model with full local paths.

I reproduced each one by driving the server over stdio, fixed them (mcp-flashcards commit `89d87fa`), and re-ran the same scenarios: BOM, corrupt JSON, unreadable file, unknown id. All of them now return a tool error and leave the file untouched, and a valid file still loads. An older copy of the server that I use day to day had a worse variant: it also treated a locked file as an empty deck, so the next save could overwrite the real cards. The same fix went there.

### Target B: `fetch` from modelcontextprotocol/servers (commit `f46d957`)

Findings confirmed by both verifiers and by the independent audit:

- **R1 Medium** (`server.py:40`): when HTML can't be simplified, the failure text is returned as ordinary page content with `isError: false`.
- **R4 Medium** (`server.py:224`): the tool does HTTP work and runs readabilipy with no top-level handler, so unexpected exception text reaches the model verbatim on SDK 1.x.
- **R4 Medium** (`server.py:128`): `repr()` of the httpx exception is put into the error message.
- **R5 Medium** (`server.py:258`): the `get_prompt` handler only catches `McpError`, so an invalid URL escapes as JSON-RPC error code 0 with the raw text.
- **R2 Low** (7 sites): `McpError` raised inside the tool path. On 1.x the error code is lost; after a migration to 2.x these would become protocol errors.

Disputed (run 1): **R3** on `start_index` past the end of the content, which returns `<error>No more content available.</error>` as a normal result. One verifier called it a false positive, because it is the tool's own pagination cursor rather than an input check. The other verifier was unsure, and the independent audit reported it the same way the plugin did. I'm counting it as neither.

False positive (run 2): **R3** "an unlisted tool name skips validation". `list_tools` is registered, so 1.x validates input, and the rule doesn't apply.

The auditor also noticed that the lock file pins `mcp` 1.29.0, not the 1.30.0 baseline, and listed the version-dependent behavior under "Could not verify" instead of asserting it. That is the intended behavior.

## 4. Known limitations and what breaks

- **Run-to-run variance.** One of the two `fetch` runs missed a finding and added a false positive. For an audit that matters, run it twice and merge the results; each extra run costs about US$1.
- **Findings are sometimes merged, and counts can be off.** Two defects of the same kind in different tools can come back as one finding. In the clean-install run, the auditor's summary line said 11 findings while its list had 13; the skill flagged the mismatch when relaying the report. Trust the list, not the summary line.
- **Cost per audit.** Since 0.1.1 the rules are part of the auditor's instructions, which adds about 10,500 tokens each time an audit runs (on top of reading the target's code). The always-on cost in every session is unchanged at about 200 tokens.
- **Report language follows the project's Claude Code instructions.** Both mcp-flashcards runs came back in Chinese, because that folder sits under a directory whose `CLAUDE.md` asks for Chinese replies. The other six runs, started from folders without such instructions, were in English.
- **Verified SDK versions:** runtime claims were checked on `mcp` 1.30.0 and 2.2.0. For other versions the auditor lists version-dependent behavior under "Could not verify".
- **Not covered yet:** TypeScript servers. R12 (HTTP transport) has no runtime fixture; it rests on reading the SDK source only. The R14 race is also source-only, because a single-call probe can't show it.
- **Validation blind spot (packaging):** in a one-plugin repo that is also its own marketplace, `claude plugin validate .` reports "Validation passed" after checking only the marketplace manifest. A broken `plugin.json` would not be caught by that command alone. Mitigation: validate both manifests (see P1).
