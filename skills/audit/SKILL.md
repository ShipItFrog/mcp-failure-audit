---
name: audit
description: Audit an MCP server's source code for failure-handling defects — errors returned as "successful" results, exceptions the model never sees, stdout writes that corrupt the stdio transport, and hardcoded secrets or machine-specific paths. Use when the user asks to audit, review, or check an MCP server for silent failures or error handling.
argument-hint: "[path to an MCP server project or file]"
---

# MCP failure-handling audit

You are running a read-only audit of an MCP server. You never modify the user's code.

## Steps

1. **Find the target.** Use `$ARGUMENTS` as the path. If it is empty, ask the user which MCP server project or file to audit. Do not guess.
2. **Hand the audit to the auditor subagent.** Launch the `mcp-failure-audit:auditor` agent with the target path. It reads the rule set from `${CLAUDE_PLUGIN_ROOT}/skills/audit/rules.md` on its own.
3. **Relay the report exactly.** Present the auditor's report to the user as-is: findings ranked by severity, the rules checked and found clean, and anything it could not verify. Do not add findings the auditor did not report, and do not drop "could not verify" items.
4. **Offer next steps, don't take them.** You may offer to explain a finding or draft a fix, but do not edit files unless the user explicitly asks.
