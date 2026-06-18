# v3.2.3 — fs.search + fs.grep MCP tools

New filesystem search tools for AI agents — search file contents by regex pattern, with glob filter, context lines, and case-insensitive mode.

## 🆕 Added

### MCP `fs.search`
Search file contents by regex pattern. Returns matches with file path, line number, and line content.

**Schema:**
```json
{
  "path": "/home/user/project",
  "pattern": "TODO|FIXME",
  "glob": "*.py",
  "max_results": 50,
  "context": 2,
  "ignore_case": false
}
```

### MCP `fs.grep`
Alias for `fs.search` — same behavior, familiar name.

## 🔒 Security
- Path must be inside home directory (path traversal blocked)
- Sensitive files skipped (token.txt, .env, SSH keys, users.json)
- Hidden directories skipped (.git, __pycache__, node_modules, .venv)
- File size limit: 512KB per file
- Max 500 files scanned, max 200 results returned

## 📊 Validation
- **498 tests pass** (was 481, +17 new)
- Bridge /v1/doctor: 10/10

## 📦 Upgrade
`cd ~/arena-bridge && git pull && ./install.sh`

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.2...v3.2.3
