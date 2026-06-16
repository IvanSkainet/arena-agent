"""Desktop manager screenshot/OCR/window listing commands."""
from __future__ import annotations

from arena.desktop.cli.common import *  # noqa: F401,F403
from arena.desktop.cli.focus import _detect_wm

def info(_):
    out={'ok':True,'os':sys.platform,'display':{k:os.environ.get(k) for k in ['XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR']},'tools':{c:have(c) for c in ['grim','spectacle','tesseract','ydotool','ydotoold','wtype','xdotool','qdbus6','wl-copy','wl-paste','magick','openbox','fluxbox','i3','mutter']}}
    # Check if a window manager is running
    wm_running = _detect_wm()
    out['window_manager'] = wm_running
    if have('qdbus6'):
        p=run('qdbus6 org.kde.KWin /KWin org.kde.KWin.activeOutputName'); out['active_output']=p.stdout.strip()
    if have('xrandr'):
        m=re.search(r'(\d+)x(\d+)', run("xrandr | grep '*' | head -1").stdout); 
        if m: out['screen']={'width':int(m.group(1)),'height':int(m.group(2))}
    if 'screen' not in out: out['screen']={'width':2560,'height':1440}
    j(out)

def shot(args):
    REPORTS.mkdir(parents=True,exist_ok=True); path=Path(args.path).expanduser() if args.path else REPORTS/f'desktop-shot-{stamp()}.png'; path.parent.mkdir(parents=True,exist_ok=True)
    methods=[]
    for cmd in [f'grim {shq(str(path))}', f'spectacle -b -n -o {shq(str(path))}', f'gnome-screenshot -f {shq(str(path))}']:
        if shutil.which(cmd.split()[0]):
            p=run(cmd,timeout=30); methods.append({'cmd':cmd,'exit':p.returncode,'stderr':p.stderr[-500:]})
            if p.returncode==0 and path.exists() and path.stat().st_size>0: j({'ok':True,'path':str(path),'bytes':path.stat().st_size,'method':cmd,'attempts':methods}); return
    j({'ok':False,'path':str(path),'attempts':methods}); sys.exit(1)

def ocr(args):
    img=Path(args.image).expanduser() if args.image else None
    if not img:
        tmp=REPORTS/f'ocr-shot-{stamp()}.png'; shot(argparse.Namespace(path=str(tmp))); img=tmp
    if not have('tesseract'): j({'ok':False,'error':'tesseract missing'}); sys.exit(1)
    p=run(f'tesseract {shq(str(img))} stdout -l {shq(args.lang)}',timeout=60)
    out=REPORTS/f'ocr-{stamp()}.txt'; out.write_text(p.stdout,encoding='utf-8')
    j({'ok':p.returncode==0,'image':str(img),'text_path':str(out),'text_preview':p.stdout[:4000],'stderr':p.stderr[-1000:]})

def windows(_):
    rows=[]
    if have('qdbus6'):
        p=run('qdbus6 org.kde.KWin /KWin org.kde.KWin.supportInformation',timeout=10); rows.append({'source':'kwin.supportInformation','summary_lines':[ln for ln in p.stdout.splitlines() if any(x in ln.lower() for x in ['activeview','geometry','compositing','xwayland'])][:80]})
    # X11 window list via xdotool (more detailed than process list)
    if have('xdotool'):
        p=run('xdotool search --onlyvisible --name "" 2>/dev/null | head -40', timeout=5)
        if p.returncode == 0 and p.stdout.strip():
            x11_wins = []
            for wid in p.stdout.strip().splitlines()[:20]:
                wp = run(f'xdotool getwindowname {wid} 2>/dev/null', timeout=2)
                name = wp.stdout.strip() if wp.returncode == 0 else f'window-{wid}'
                x11_wins.append({'id': wid, 'name': name})
            if x11_wins:
                rows.append({'source': 'xdotool', 'windows': x11_wins})
    ps=run("ps -eo pid,comm,args | grep -Ei 'steam|tabs|chromium|firefox|brave|kwin|gamescope' | grep -v grep | head -80")
    rows.append({'source':'processes','text':ps.stdout})
    j({'ok':True,'windows':rows})
