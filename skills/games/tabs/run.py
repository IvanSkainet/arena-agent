#!/usr/bin/env python3
import sys, os, subprocess, json, base64, time

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def get_wid():
    return run("xdotool search --name 'Totally Accurate Battle Simulator' | head -1")

def main():
    if len(sys.argv) < 2: return
    action = sys.argv[1]
    
    # Fast Screenshot using grim (Wayland) or ffmpeg
    if action == "shot":
        out = "/tmp/tabs_live.jpg"
        # Grim is much faster on Wayland
        subprocess.run(f"grim -t jpeg -q 70 {out}", shell=True)
        # Downscale for token saving
        subprocess.run(f"ffmpeg -y -i {out} -vf scale=800:-1 /tmp/tabs_small.jpg", shell=True, capture_output=True)
        with open("/tmp/tabs_small.jpg", "rb") as f:
            print(base64.b64encode(f.read()).decode())

    # Execute batch of commands: unit:x:y,unit:x:y,key
    elif action == "batch":
        commands = sys.argv[2].split(",")
        wid = get_wid()
        if wid: run(f"xdotool windowactivate {wid}")
        
        for c in commands:
            parts = c.split(":")
            if len(parts) == 3: # unit:x:y
                u, x, y = parts
                mapping = {"1":"2","2":"3","3":"4","4":"5"} # Key mapping
                key = mapping.get(u, u)
                run(f"ydotool key {key}:1 {key}:0")
                time.sleep(0.05)
                run(f"ydotool mousemove -w {x} {y} click 1")
            elif len(parts) == 1: # just a key
                key = parts[0]
                kmap = {"T":"20","F":"33","Tab":"15"}
                code = kmap.get(key, key)
                run(f"ydotool key {code}:1 {code}:0")
            time.sleep(0.1)

if __name__ == "__main__":
    main()
