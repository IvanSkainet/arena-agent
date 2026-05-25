#!/usr/bin/env python3
from pathlib import Path
p=Path.home()/'arena-agent/bin/agentctl'
s=p.read_text()
# Fix backup implementation
old='''    elif ns in ["backup", "bak"]:\n        sub = args[0] if args else "run"\n        if sub == "run":\n            subprocess.run(["bash", "/tmp/do_backup.sh"])\n        else:\n            subprocess.run("ls -lh ~/arena-agent/backups 2>/dev/null || true", shell=True)\n'''
new='''    elif ns in ["backup", "bak"]:\n        sub = args[0] if args else "run"\n        if sub in ["run", "create"]:\n            run_cmd("backup_tool.py", [])\n        else:\n            subprocess.run("ls -lh ~/arena-agent/backups 2>/dev/null || true", shell=True)\n'''
if old in s:
    s=s.replace(old,new)
# Add compatibility aliases before final else
marker='''    elif ns == "status": run_cmd("agentctl_extras.py", ["status"])\n    elif ns == "remember": run_cmd("memory.py", ["remember"] + args)\n    \n    else:\n'''
compat='''    elif ns == "status": run_cmd("agentctl_extras.py", ["status"])\n    elif ns == "remember": run_cmd("memory.py", ["remember"] + args)\n    elif ns in ["memory-remember", "mem-set"]:\n        run_cmd("memory.py", ["remember"] + args)\n    elif ns in ["memory-recall", "mem-get"]:\n        run_cmd("memory.py", ["recall"] + args)\n    elif ns == "recovery-update":\n        run_cmd("recovery_prompt.py", [])\n    elif ns == "recovery-print":\n        f=os.path.join(ROOT, "memory", "RECOVERY_PROMPT_RU.md")\n        print(open(f, encoding="utf-8").read() if os.path.exists(f) else "missing recovery prompt")\n    elif ns == "backups":\n        subprocess.run("ls -lh ~/arena-agent/backups 2>/dev/null || true", shell=True)\n    elif ns == "report-status":\n        subprocess.run([os.path.join(ROOT, "bin", "agentctl"), "report", "status"] + args)\n    \n    else:\n'''
if marker in s:
    s=s.replace(marker, compat)
elif 'memory-remember' not in s:
    raise SystemExit('alias marker not found')
# Improve help text minimally
s=s.replace('mcp     install|list|call|tools           MCP client', 'mcp     install|list|call|tools|stream-* MCP client + Streamable HTTP')
s=s.replace('backup  run|ls                            Backups', 'backup  run|ls                            Backups (compat: backups)')
p.write_text(s); p.chmod(0o700)
print('patched agentctl core aliases and backup')
