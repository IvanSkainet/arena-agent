import sys, subprocess
cmd = sys.argv[1] if len(sys.argv)>1 else "list"

try:
    if cmd == "start":
        sess = sys.argv[2]
        prog = " ".join(sys.argv[3:])
        subprocess.run(["tmux", "new-session", "-d", "-s", sess, prog])
        print(f"Started tmux session: {sess}")
    elif cmd == "send":
        sess = sys.argv[2]
        keys = sys.argv[3:]
        # Send literal keys
        subprocess.run(["tmux", "send-keys", "-t", sess] + keys + ["C-m"])
        print(f"Sent keys to {sess}")
    elif cmd == "capture":
        sess = sys.argv[2]
        lines = int(sys.argv[3]) if len(sys.argv)>3 else 50
        out = subprocess.run(["tmux", "capture-pane", "-t", sess, "-p"], capture_output=True, text=True).stdout
        print("\n".join(out.splitlines()[-lines:]))
    elif cmd == "kill":
        sess = sys.argv[2]
        subprocess.run(["tmux", "kill-session", "-t", sess])
        print(f"Killed session: {sess}")
    elif cmd == "list":
        subprocess.run(["tmux", "ls"])
except Exception as e:
    print(f"Tmux error: {e}")
