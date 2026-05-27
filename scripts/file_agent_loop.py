import os
import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", os.path.expanduser("~/arena-bridge")))
INBOX = ROOT / "memory" / "last_query.txt"
RESPONSE = ROOT / "memory" / "last_response.txt"
HISTORY = ROOT / "memory" / "history.txt"

def main():
    print("=== File-Based CLI Agent Loop (Lottarend-Style) ===")
    print(f"Monitoring query file: {INBOX}")
    print(f"Writing responses to: {RESPONSE}")
    print(f"Chat history is logged in: {HISTORY}")
    
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    if not INBOX.exists():
        INBOX.write_text("# Write your command here, e.g. dir or agentctl sys status", encoding="utf-8")
        
    last_mtime = INBOX.stat().st_mtime
    
    while True:
        try:
            time.sleep(1)
            if INBOX.exists():
                current_mtime = INBOX.stat().st_mtime
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    query = INBOX.read_text(encoding="utf-8").strip()
                    if not query or query.startswith("#"):
                        continue
                        
                    print(f"\n[RECEIVED] {query}")
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    with open(HISTORY, "a", encoding="utf-8") as h:
                        h.write(f"[{timestamp}] Q: {query}\n")
                        
                    # Execute as command
                    res = subprocess.run(query, shell=True, capture_output=True, text=True)
                    response_text = f"=== COMMAND EXECUTION RESULT ===\nExit Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
                    
                    RESPONSE.write_text(response_text, encoding="utf-8")
                    
                    with open(HISTORY, "a", encoding="utf-8") as h:
                        h.write(f"[{timestamp}] R: (Exit Code {res.returncode}) {res.stdout.strip()[:200]}...\n\n")
                    print("[DONE] Response written.")
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error in watcher loop: {e}")

if __name__ == "__main__":
    main()
