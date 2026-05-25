#!/usr/bin/env python3
from pathlib import Path
p=Path.home()/"arena-agent/bin/agentctl"
s=p.read_text()
if 'mission ' not in s.split('Usage: agentctl.py')[0]:
    s=s.replace('  mcp     install|list|call|tools|stream-* MCP client + Streamable HTTP\n', '  mcp     install|list|call|tools|stream-* MCP client + Streamable HTTP\n  mission list|show|new|check|stress|roadmap Scenario framework\n')
if 'elif ns in ["mission"' not in s:
    marker='''    elif ns == "mcp":
        run_cmd("mcp_manager.py", args if args else ["list"])
        
    elif ns == "sp":
'''
    repl='''    elif ns == "mcp":
        run_cmd("mcp_manager.py", args if args else ["list"])
    elif ns in ["mission", "ms", "scenario"]:
        run_cmd("mission_manager.py", args if args else ["list"])
        
    elif ns == "sp":
'''
    if marker not in s: raise SystemExit('marker not found')
    s=s.replace(marker,repl)
p.write_text(s); p.chmod(0o700)
print('patched mission namespace')
