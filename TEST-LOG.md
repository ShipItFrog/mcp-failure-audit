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
| P1 | `claude plugin validate . --strict` | local | pending | |
| P2 | Load for development with `--plugin-dir` | local | pending | |
| P3 | Fresh install from GitHub in a clean config directory | clean `CLAUDE_CONFIG_DIR` | pending | |
| P4 | Skill invokes the auditor subagent | clean install | pending | |
| P5 | Update to a new version | clean install | pending | |
| P6 | Uninstall and remove the marketplace | clean install | pending | |

## 2. Audit accuracy

### Target A: mcp-flashcards (my own server, SDK 1.x)

| Rule | Expected | Found by plugin | Verdict (true positive / false positive / missed) |
|---|---|---|---|
| | | | pending |

### Target B: a third-party public MCP server (not designed by me)

| Rule | Expected | Found by plugin | Verdict |
|---|---|---|---|
| | | | pending |

## 3. Known limitations and what breaks

pending
