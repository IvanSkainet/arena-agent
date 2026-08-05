"""Desktop manager input commands."""
from __future__ import annotations

from arena.desktop.cli.common import (
    argparse,
    have,
    j,
    os,
    random,
    run,
    subprocess,
    sys,
    time,
)
from arena.desktop.cli.focus import _ensure_wm, _focus_active_window


def ensure_ydotool():
    if not have('ydotool'):
        return False
    if run('pgrep -x ydotoold').returncode!=0 and have('ydotoold'):
        sock=os.environ.get('XDG_RUNTIME_DIR','/run/user/1000')+'/.ydotool_socket'
        # The suppression below used to sit on the `time.sleep` line, one row
        # past the call it was meant to cover -- so it silenced nothing and
        # bandit kept flagging the Popen. Moved onto the actual call.
        subprocess.Popen(f'ydotoold --socket-path={shq(sock)} >/tmp/ydotoold.log 2>&1',shell=True)  # nosec B602,B604 -- shq() escapes the socket path; redirection to a log requires a shell; XDG_RUNTIME_DIR is system-managed, not attacker-writable in a legitimate desktop session.  # nosemgrep: subprocess-shell-true,dangerous-subprocess-use-tainted-env-args -- same rationale as the bandit nosec on this line
        time.sleep(.5)
    return True

# The five buttons ydotool/xdotool agree on: left, middle, right and the
# two scroll-wheel pseudo-buttons. Anything else is a caller mistake, and
# before v4.163.0 it was also a shell injection (bug #53).
_MOUSE_BUTTONS = {1, 2, 3, 4, 5}


def move(args):
    if not ensure_ydotool():
        j({'ok':False,'error':'ydotool missing'})
        sys.exit(1)
    # int() here is what kept `move` safe while `click` was injectable --
    # but it raised ValueError instead of answering, so a bad coordinate
    # crashed the CLI with a traceback rather than a usable message.
    try:
        x, y = int(args.x), int(args.y)
        steps = max(1, int(args.steps))
    except (TypeError, ValueError):
        j({'ok': False,
           'error': f'x, y and steps must be integers, got '
                    f'{args.x!r}, {args.y!r}, {args.steps!r}'})
        sys.exit(1)
    sx=max(0,x-random.randint(150,350))
    sy=max(0,y+random.randint(80,240))
    for i in range(1,steps+1):
        t=i/steps
        e=1-(1-t)**3
        cx=int(sx+(x-sx)*e)
        cy=int(sy+(y-sy)*e)
        run(f'ydotool mousemove -a -x {cx} -y {cy}',timeout=2)
        time.sleep(float(args.delay))
    j({'ok':True,'x':x,'y':y,'steps':steps})

def click(args):
    # v4.163.0 (bug #53): x, y and --button reached a shell as raw text.
    # `move()` happens to be safe because it runs int() over its inputs
    # first, but click passed args.x straight into an xdotool command
    # line and never validated --button at all. Reproduced:
    #
    #   --button "1; touch /tmp/PWNED"  ->  the file was created.
    #
    # Coordinates are numbers and the button is one of five ints, so the
    # fix is to say so. Parsing beats quoting here: a coordinate that is
    # not a number is a bug in the caller, not something to escape and
    # pass along.
    _ensure_wm()
    try:
        x, y = int(args.x), int(args.y)
    except (TypeError, ValueError):
        j({'ok': False, 'error': f'x and y must be integers, got {args.x!r}, {args.y!r}'})
        sys.exit(1)
    try:
        btn = int(args.button)
    except (TypeError, ValueError):
        j({'ok': False, 'error': f'button must be an integer, got {args.button!r}'})
        sys.exit(1)
    if btn not in _MOUSE_BUTTONS:
        j({'ok': False,
           'error': f'button must be one of {sorted(_MOUSE_BUTTONS)}, got {btn}'})
        sys.exit(1)

    move(argparse.Namespace(x=x,y=y,steps=args.steps,delay=args.delay))
    # On X11, also focus the window at click position before clicking
    if have('xdotool'):
        # Get window at position and focus it
        p = run('xdotool selectwindow 2>/dev/null', timeout=2)
        # Alternative: use mousemove + click which naturally focuses
        run(f'xdotool mousemove --sync {x} {y}', timeout=3)
        time.sleep(0.05)
    if have('ydotool'):
        p=run(f'ydotool click {btn}',timeout=3)
    elif have('xdotool'):
        p=run(f'xdotool click {btn}',timeout=3)
    else:
        j({'ok':False,'error':'no click tool'})
        sys.exit(1)
    j({'ok':p.returncode==0,'button':btn,'stderr':p.stderr})

def key(args):
    """Send a key event. Auto-starts WM and focuses target window first."""
    # Ensure WM is running for focus management
    _ensure_wm()

    # Try to focus the active window before sending keys
    _focus_active_window()

    if have('wtype'):
        p=run(f'wtype -k {shq(args.key)}',timeout=5)
    elif have('xdotool'):
        p=run(f'xdotool key {shq(args.key)}',timeout=5)
    elif ensure_ydotool():
        p=run(f'ydotool key {shq(args.key)}:1 {shq(args.key)}:0',timeout=5)
    else:
        j({'ok':False,'error':'no key tool'})
        sys.exit(1)
    j({'ok':p.returncode==0,'key':args.key,'stderr':p.stderr})

def type_text(args):
    text=args.text
    # Ensure WM is running for focus management
    _ensure_wm()
    _focus_active_window()

    if have('wl-copy') and ensure_ydotool():
        subprocess.run(['wl-copy'],input=text,text=True)
        time.sleep(.1)
        p=run('ydotool key 29:1 47:1 47:0 29:0',timeout=5)
    elif have('wtype'):
        p=subprocess.run(['wtype',text],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    else:
        j({'ok':False,'error':'no type tool'})
        sys.exit(1)
    j({'ok':p.returncode==0,'chars':len(text),'stderr':p.stderr})

def shq(s): return "'"+str(s).replace("'","'\\''")+"'"
