#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, os, random, re, shutil, subprocess, sys, time
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home() / 'arena-bridge'))).expanduser(); REPORTS=ROOT/'reports'
def stamp(): return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
def run(cmd, timeout=20): return subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
def have(c): return shutil.which(c) is not None
def j(o): print(json.dumps(o,ensure_ascii=False,indent=2))
def info(_):
    out={'ok':True,'os':sys.platform,'display':{k:os.environ.get(k) for k in ['XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR']},'tools':{c:have(c) for c in ['grim','spectacle','tesseract','ydotool','ydotoold','wtype','xdotool','qdbus6','wl-copy','wl-paste','magick']}}
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
    ps=run("ps -eo pid,comm,args | grep -Ei 'steam|tabs|chromium|firefox|brave|kwin|gamescope' | grep -v grep | head -80")
    rows.append({'source':'processes','text':ps.stdout})
    j({'ok':True,'windows':rows})
def ensure_ydotool():
    if not have('ydotool'): return False
    if run('pgrep -x ydotoold').returncode!=0 and have('ydotoold'):
        sock=os.environ.get('XDG_RUNTIME_DIR','/run/user/1000')+'/.ydotool_socket'; subprocess.Popen(f'ydotoold --socket-path={shq(sock)} >/tmp/ydotoold.log 2>&1',shell=True); time.sleep(.5)
    return True
def move(args):
    if not ensure_ydotool(): j({'ok':False,'error':'ydotool missing'}); sys.exit(1)
    x,y=int(args.x),int(args.y); steps=max(1,int(args.steps)); sx=max(0,x-random.randint(150,350)); sy=max(0,y+random.randint(80,240))
    for i in range(1,steps+1):
        t=i/steps; e=1-(1-t)**3; cx=int(sx+(x-sx)*e); cy=int(sy+(y-sy)*e); run(f'ydotool mousemove -a -x {cx} -y {cy}',timeout=2); time.sleep(float(args.delay))
    j({'ok':True,'x':x,'y':y,'steps':steps})
def click(args):
    move(argparse.Namespace(x=args.x,y=args.y,steps=args.steps,delay=args.delay)); btn=args.button; p=run(f'ydotool click {btn}',timeout=3); j({'ok':p.returncode==0,'button':btn,'stderr':p.stderr})
def key(args):
    if have('wtype'): p=run(f'wtype -k {shq(args.key)}',timeout=5)
    elif have('xdotool'): p=run(f'xdotool key {shq(args.key)}',timeout=5)
    elif ensure_ydotool(): p=run(f'ydotool key {shq(args.key)}:1 {shq(args.key)}:0',timeout=5)
    else: j({'ok':False,'error':'no key tool'}); sys.exit(1)
    j({'ok':p.returncode==0,'key':args.key,'stderr':p.stderr})
def type_text(args):
    text=args.text
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
