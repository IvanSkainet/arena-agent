"""Desktop manager input commands."""
from __future__ import annotations

from arena.desktop.cli.common import *  # noqa: F401,F403
from arena.desktop.cli.focus import _ensure_wm, _focus_active_window, _focus_window_at

def ensure_ydotool():
    if not have('ydotool'): return False
    if run('pgrep -x ydotoold').returncode!=0 and have('ydotoold'):
        sock=os.environ.get('XDG_RUNTIME_DIR','/run/user/1000')+'/.ydotool_socket'; subprocess.Popen(f'ydotoold --socket-path={shq(sock)} >/tmp/ydotoold.log 2>&1',shell=True); time.sleep(.5)  # nosec B602 # nosemgrep: subprocess-shell-true,dangerous-subprocess-use-tainted-env-args -- shq() escapes the socket path; redirection to log requires shell; XDG_RUNTIME_DIR is a system-managed env var not attacker-writable in a legit desktop session
    return True

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
