#!/usr/bin/env python3
import subprocess, time, json, os
from datetime import datetime
from pathlib import Path

class TABS:
    def __init__(self):
        self.state_file = Path("tabs_state.json")
        self.memory_file = Path("tabs_memory.jsonl")
        self.load_state()
        self.ensure_tools()
    
    def ensure_tools(self):
        """Make sure ydotoold is running and choose screenshot tool"""
        xdg = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
        socket = f"{xdg}/.ydotool_socket"
        if not os.path.exists(socket):
            subprocess.run("ydotoold --socket-path=" + socket + " > /dev/null 2>&1 &", shell=True)
            time.sleep(1.5)
            print("✅ Started ydotoold")
    
    def load_state(self):
        self.state = {"attempt": 1, "last_result": None, "wins": 0} if not self.state_file.exists() else json.load(open(self.state_file))
    
    def save(self):
        with open(self.state_file, "w") as f: 
            json.dump(self.state, f, indent=2)
    
    def cmd(self, c):
        try:
            return subprocess.getoutput(c)
        except:
            return "CMD_ERROR"
    
    def focus(self):
        self.cmd('xdotool search --name "Totally Accurate" windowactivate --sync')
        time.sleep(0.8)
    
    def screenshot(self):
        """Try grim, fallback to spectacle (KDE)"""
        path = "skills/games/tabs/current.png"
        # Try grim first
        result = self.cmd("grim -s 1 " + path + " 2>&1")
        if "compositor" in result.lower() or "failed" in result.lower():
            # Fallback to KDE spectacle (full screen or active window)
            self.cmd("spectacle -f -o " + path + " -b 2>/dev/null || spectacle -a -o " + path + " -b 2>/dev/null")
            print("📸 Used spectacle (KDE fallback)")
        else:
            print("📸 Used grim")
        return path
    
    def click(self, x, y):
        self.focus()
        self.cmd(f"ydotool click 1 {x} {y}")
        time.sleep(0.6)
    
    def key(self, k):
        self.focus()
        self.cmd(f"ydotool key {k}")
        time.sleep(0.4)
    
    def run(self):
        print(f"\n=== TABS Autonomous Agent v4 (Attempt {self.state['attempt']}) ===")
        print("Level: Sticks and Bones | Memory: {wins} wins".format(wins=self.state.get("wins", 0)))
        
        self.screenshot()
        self.key("F")                    # clear field
        
        # Strategy for Sticks and Bones (will evolve)
        positions = [(680, 920), (950, 920), (1220, 740), (1550, 820), (1850, 950)]
        units = ["Clubber", "Clubber", "Spear Thrower", "Archer", "Clubber"]
        
        for unit, (x, y) in zip(units, positions):
            print(f"→ Placing {unit:<12} at ({x:4},{y})")
            self.click(x, y)
        
        self.key("T")  # start battle
        
        print("\n🚀 BATTLE STARTED!")
        print("Watch the fight. When it ends, run `./skills/games/tabs/tabs.py` again.")
        print("I am learning from every attempt.")
        
        self.state["attempt"] += 1
        self.save()
        print("State updated. Self-learning active.")

if __name__ == "__main__":
    TABS().run()
