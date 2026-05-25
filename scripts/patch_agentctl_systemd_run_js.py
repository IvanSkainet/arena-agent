#!/usr/bin/env python3
from pathlib import Path
p=Path.home()/"arena-agent/bin/agentctl"
s=p.read_text()
old='''def run_js(script, args):
    node_path = os.path.join(ROOT, "js", "node_modules")
    env = os.environ.copy()
    env["NODE_PATH"] = node_path
    cmd = ["node", os.path.join(SE, script)] + args
    try:
        subprocess.run(cmd, env=env, cwd=os.path.join(ROOT, "js"), check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
'''
new='''def run_js(script, args):
    # Browser/GUI tools must not inherit the hardened bridge service cgroup.
    # When called through the bridge, Chromium may SIGTRAP if launched directly.
    # Running JS tools via a transient user systemd scope gives them a normal
    # user-session environment while preserving stdout/stderr for the caller.
    node_path = os.path.join(ROOT, "js", "node_modules")
    script_path = os.path.join(SE, script)
    env = os.environ.copy(); env["NODE_PATH"] = node_path
    direct = ["node", script_path] + args
    use_systemd = shutil.which("systemd-run") and not os.environ.get("ARENA_AGENT_NO_SYSTEMD_RUN")
    if use_systemd:
        cmd = ["systemd-run", "--user", "--quiet", "--wait", "--collect", "--pipe", "--same-dir", "env", f"NODE_PATH={node_path}", "node", script_path] + args
        try:
            subprocess.run(cmd, env=env, cwd=os.path.join(ROOT, "js"), check=True)
            return
        except subprocess.CalledProcessError:
            # Fallback to direct execution for non-systemd environments.
            pass
    try:
        subprocess.run(direct, env=env, cwd=os.path.join(ROOT, "js"), check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
'''
if old not in s:
    raise SystemExit('run_js block not found')
s=s.replace(old,new)
# ensure shutil import
if 'import sys, os, subprocess, shutil' not in s:
    s=s.replace('import sys, os, subprocess', 'import sys, os, subprocess, shutil')
p.write_text(s); p.chmod(0o700)
print('patched agentctl run_js via systemd-run')
