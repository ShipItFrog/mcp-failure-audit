# mcp-failure-audit

A Claude Code plugin that audits MCP server code for **silent failures**: the bugs that don't crash anything, but make your server lie to the model.

> **Status: v0.1.0-dev.** The rule set is complete and checked against the real SDKs (1.30.0 and 2.2.0). In accuracy tests, the auditor found 56 of 56 planted defects with no false positives, and 17 of 18 known defects in two real servers, including one it helped find and fix in my own server. The clean-install test is next. See [TEST-LOG.md](TEST-LOG.md) for how every number was measured.

## Why

The most expensive MCP bugs are quiet ones. A tool catches an exception and returns `{"ok": false, "error": "..."}` as a normal result, and the model reads it as success. A stray `print()` corrupts the stdio stream. An API key is sitting in the source. None of these fail a quick demo, and all of them fail in production.

This plugin reads your server's source, works out which SDK and version it uses, and checks it against rules taken from the MCP specification and the official Python SDK docs. It reports each finding with the file, line, and quoted code, and it tells you which rules it checked and found clean.

## What it checks

The full list with sources is in [skills/audit/rules.md](skills/audit/rules.md). In short:

- Errors returned as "successful" results instead of raised as tool errors
- Exceptions that surface as protocol errors the model never sees
- Raw exception text leaking to the client
- Anything written to stdout on the stdio transport
- Hardcoded secrets and machine-specific paths
- Path traversal from tool arguments
- Transport-level issues for HTTP servers

**Supported:** Python servers built on the official `mcp` SDK, **both 1.x and 2.x** (rules are applied per detected version), plus the third-party `fastmcp` package where noted. TypeScript servers are not covered yet.

**It is read-only.** The auditor runs with read, search, and file-listing tools only. It cannot edit, delete, or execute anything in your project.

## Install

In a Claude Code session:

```
/plugin marketplace add ShipItFrog/mcp-failure-audit
/plugin install mcp-failure-audit@shipitfrog
```

Or from a terminal:

```
claude plugin marketplace add ShipItFrog/mcp-failure-audit
claude plugin install mcp-failure-audit@shipitfrog --scope user
```

Use `--scope project` instead if you want everyone who works in a repository to get the plugin.

## Use

```
/mcp-failure-audit:audit path/to/your/mcp-server
```

## Update and uninstall

Third-party marketplaces don't auto-update by default. You can turn auto-update on under `/plugin` → Marketplaces, or update manually from a terminal:

```
claude plugin marketplace update shipitfrog
claude plugin update mcp-failure-audit@shipitfrog
```

Restart the session (or run `/reload-plugins`) afterward.

To remove it:

```
claude plugin uninstall mcp-failure-audit@shipitfrog
claude plugin marketplace remove shipitfrog
```

## Tested with

- Claude Code 2.1.284 on Windows 11

## License

MIT — see [LICENSE](LICENSE).
