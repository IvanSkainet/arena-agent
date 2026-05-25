import sys, os, subprocess, urllib.request, zipfile, io
from pathlib import Path
REPO_DIR = Path(os.environ.get("ARENA_AGENT_HOME", Path.home()/"arena-agent")) / "tools" / "superpowers"
cmd = sys.argv[1] if len(sys.argv)>1 else "list"

if cmd == "sync":
    REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    git_bin = shutil.which("git")
    if git_bin:
        if not REPO_DIR.exists():
            subprocess.run(f"git clone https://github.com/obra/superpowers.git {REPO_DIR}", shell=True)
        else:
            subprocess.run(f"cd {REPO_DIR} && git pull", shell=True)
    else:
        print("[NOTICE] Git not found. Downloading Superpowers zip directly from GitHub...")
        zip_url = "https://github.com/obra/superpowers/archive/refs/heads/main.zip"
        try:
            req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                zip_data = response.read()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
                temp_extract = REPO_DIR.parent / "superpowers_temp"
                if temp_extract.exists():
                    shutil.rmtree(temp_extract)
                zip_ref.extractall(REPO_DIR.parent)
                main_folder = REPO_DIR.parent / "superpowers-main"
                if main_folder.exists():
                    if REPO_DIR.exists():
                        shutil.rmtree(REPO_DIR)
                    os.rename(main_folder, REPO_DIR)
                    print("[OK] Superpowers successfully downloaded and extracted to " + str(REPO_DIR))
                else:
                    print("[ERROR] Extracted folder structure not found.")
        except Exception as e:
            print(f"[ERROR] Failed to download zip: {e}", file=sys.stderr)
            sys.exit(1)
elif cmd == "list":
    if not REPO_DIR.exists(): 
        print("Run 'agentctl sp sync' first.")
        sys.exit(0)
    for f in sorted(REPO_DIR.rglob("*.md")):
        if ".github" not in str(f) and ".git" not in str(f):
            print(f.relative_to(REPO_DIR))
elif cmd == "show":
    if len(sys.argv) < 3: 
        print("Provide a skill name")
        sys.exit(1)
    target = sys.argv[2]
    if not target.endswith(".md"): target += ".md"
    p = REPO_DIR / target
    if p.exists(): 
        print(p.read_text())
    else: 
        print(f"Not found: {target}")
