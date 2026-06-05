#!/usr/bin/env python3
"""Desktop Manager — screenshot, keyboard, mouse, window management.

v2.5.0 fixes:
  - Auto-start lightweight window manager (openbox/fluxbox) for focus management
  - Focus window before sending key events (xdotool windowfocus)
  - Click-to-focus pattern: click activates the window at that position
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, random, re, shutil, subprocess, sys, time
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home() / 'arena-bridge'))).expanduser(); REPORTS=ROOT/'reports'
def stamp(): return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
def run(cmd, timeout=20): return subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
def have(c): return shutil.which(c) is not None
def j(o): print(json.dumps(o,ensure_ascii=False,indent=2))
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
def ensure_ydotool():
    if not have('ydotool'): return False
    if run('pgrep -x ydotoold').returncode!=0 and have('ydotoold'):
        sock=os.environ.get('XDG_RUNTIME_DIR','/run/user/1000')+'/.ydotool_socket'; subprocess.Popen(f'ydotoold --socket-path={shq(sock)} >/tmp/ydotoold.log 2>&1',shell=True); time.sleep(.5)
    return True

# ---- Window Manager auto-start and focus management (v2.5.0) ----

_wm_started = False

def _detect_wm():
    """Detect if a window manager is currently running."""
    # Check EWMH compatibility hint — set by any EWMH-compliant WM
    if have('xdotool'):
        p = run('xdotool getwindowfocus 2>/dev/null', timeout=3)
        if p.returncode == 0 and p.stdout.strip():
            return 'ewmh_active'
    # Check for running WM processes
    for wm in ['openbox', 'fluxbox', 'i3', 'mutter', 'kwin_wayland', 'kwin_x11', 'gnome-shell', 'xfwm4']:
        p = run(f'pgrep -x {wm}', timeout=3)
        if p.returncode == 0:
            return wm
    return None

def _ensure_wm():
    """Auto-start a lightweight window manager if none is running.
    
    Without a WM, keyboard events from xdotool/ydotool don't reach
    application windows because no window has EWMH focus.
    """
    global _wm_started
    if _wm_started:
        return True
    
    wm = _detect_wm()
    if wm:
        _wm_started = True
        return True
    
    display = os.environ.get('DISPLAY', '')
    if not display:
        return False  # No display at all — can't start WM
    
    # Try openbox first (lightweight, most common in containers)
    for wm_cmd, wm_name in [
        ('openbox', 'openbox'),
        ('fluxbox', 'fluxbox'),
        ('i3', 'i3'),
        ('mutter', 'mutter'),
    ]:
        if have(wm_cmd):
            # Start WM in background — replace any existing WM
            subprocess.Popen(
                f'DISPLAY={shq(display)} {wm_cmd} &>/dev/null &',
                shell=True
            )
            time.sleep(1.5)  # Give WM time to start
            # Verify it started
            verify = _detect_wm()
            if verify:
                _wm_started = True
                return True
    
    return False

def _focus_window_at(x, y):
    """Focus the window at screen coordinates (x, y) using xdotool.
    
    This is critical for key events to reach the right application.
    On X11 without EWMH, xdotool key events go to the focused window,
    so we must focus the target window before sending keys.
    """
    if not have('xdotool'):
        return False
    
    # Method 1: Click-to-focus (most reliable on any WM)
    # Move mouse to position and click (left button) to activate window
    run(f'xdotool mousemove --sync {x} {y}', timeout=3)
    time.sleep(0.05)
    run(f'xdotool click 1', timeout=3)
    time.sleep(0.1)
    return True

def _focus_active_window():
    """Focus the currently active window using xdotool.
    
    This re-activates the focused window, which helps on some WMs
    where focus was lost.
    """
    if not have('xdotool'):
        return False
    p = run('xdotool getactivewindow 2>/dev/null', timeout=3)
    if p.returncode == 0 and p.stdout.strip():
        wid = p.stdout.strip().splitlines()[0]
        run(f'xdotool windowfocus {wid}', timeout=3)
        run(f'xdotool windowactivate {wid}', timeout=3)
        return True
    return False

def move(args):
    if not ensure_ydotool(): j({'ok':False,'error':'ydotool missing'}); sys.exit(1)
    x,y=int(args.x),int(args.y); steps=max(1,int(args.steps)); sx=max(0,x-random.randint(150,350)); sy=max(0,y+random.randint(80,240))
    for i in range(1,steps+1):
        t=i/steps; e=1-(1-t)**3; cx=int(sx+(x-sx)*e); cy=int(sy+(y-sy)*e); run(f'ydotool mousemove -a -x {cx} -y {cy}',timeout=2); time.sleep(float(args.delay))
    j({'ok':True,'x':x,'y':y,'steps':steps})

def click(args):
    # Ensure WM is running for proper click-to-focus behavior
    _ensure_wm()
    move(argparse.Namespace(x=args.x,y=args.y,steps=args.steps,delay=args.delay))
    # On X11, also focus the window at click position before clicking
    if have('xdotool'):
        # Get window at position and focus it
        p = run(f'xdotool selectwindow 2>/dev/null', timeout=2)
        # Alternative: use mousemove + click which naturally focuses
        run(f'xdotool mousemove --sync {args.x} {args.y}', timeout=3)
        time.sleep(0.05)
    btn=args.button
    if have('ydotool'):
        p=run(f'ydotool click {btn}',timeout=3)
    elif have('xdotool'):
        p=run(f'xdotool click {btn}',timeout=3)
    else: j({'ok':False,'error':'no click tool'}); sys.exit(1)
    j({'ok':p.returncode==0,'button':btn,'stderr':p.stderr})

def key(args):
    """Send a key event. Auto-starts WM and focuses target window first."""
    # Ensure WM is running for focus management
    _ensure_wm()
    
    # Try to focus the active window before sending keys
    _focus_active_window()
    
    if have('wtype'): p=run(f'wtype -k {shq(args.key)}',timeout=5)
    elif have('xdotool'): p=run(f'xdotool key {shq(args.key)}',timeout=5)
    elif ensure_ydotool(): p=run(f'ydotool key {shq(args.key)}:1 {shq(args.key)}:0',timeout=5)
    else: j({'ok':False,'error':'no key tool'}); sys.exit(1)
    j({'ok':p.returncode==0,'key':args.key,'stderr':p.stderr})

def type_text(args):
    text=args.text
    # Ensure WM is running for focus management
    _ensure_wm()
    _focus_active_window()
    
    if have('wl-copy') and ensure_ydotool():
        subprocess.run(['wl-copy'],input=text,text=True); time.sleep(.1); p=run('ydotool key 29:1 47:1 47:0 29:0',timeout=5)
    elif have('wtype'): p=subprocess.run(['wtype',text],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    else: j({'ok':False,'error':'no type tool'}); sys.exit(1)
    j({'ok':p.returncode==0,'chars':len(text),'stderr':p.stderr})
def shq(s): return "'"+str(s).replace("'","'\\''")+"'"
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('info').set_defaults(func=info)
    s=sub.add_parser('shot'); s.add_argument('path',nargs='?'); s.set_defaults(func=shot)
    s=sub.add_parser('ocr'); s.add_argument('image',nargs='?'); s.add_argument('--lang',default='eng+rus'); s.set_defaults(func=ocr)
    sub.add_parser('windows').set_defaults(func=windows)
    s=sub.add_parser('move'); s.add_argument('x'); s.add_argument('y'); s.add_argument('--steps',default=25); s.add_argument('--delay',default=.01); s.set_defaults(func=move)
    s=sub.add_parser('click'); s.add_argument('x'); s.add_argument('y'); s.add_argument('--button',default='1'); s.add_argument('--steps',default=25); s.add_argument('--delay',default=.01); s.set_defaults(func=click)
    s=sub.add_parser('key'); s.add_argument('key'); s.set_defaults(func=key)
    s=sub.add_parser('type'); s.add_argument('text'); s.set_defaults(func=type_text)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
