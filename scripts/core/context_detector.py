#!/usr/bin/env python3
"""
Context-Aware Adapter System (SiteAdapters / Context Detectors)
Analyzes CWD to intelligently load specific tools/extensions.
"""
from __future__ import annotations
import os
import json
from pathlib import Path

class ContextDetector:
    @staticmethod
    def detect(cwd: str) -> list[str]:
        features = []
        p = Path(cwd)
        
        # Git context
        if (p / ".git").exists() or (p / "../.git").exists() or (p / "../../.git").exists():
            features.append("git")
            
        # Node/JS context
        if (p / "package.json").exists() or (p / "node_modules").exists():
            features.append("node")
            
        # Python context
        if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists() or (p / ".venv").exists():
            features.append("python")
            
        # C/C++ context
        if (p / "CMakeLists.txt").exists() or (p / "Makefile").exists() or list(p.glob("*.c")) or list(p.glob("*.cpp")):
            features.append("c_cpp")
            
        return features

def get_context_tools(cwd: str = None) -> str:
    """Returns instructions/hints based on detected context."""
    if not cwd: cwd = os.getcwd()
    features = ContextDetector.detect(cwd)
    
    if not features:
        return "No specific project context detected."
        
    hints = [f"Detected project types: {', '.join(features)}."]
    if "git" in features:
        hints.append("Git Tools available: Use 'git status', 'git diff' to explore.")
    if "node" in features:
        hints.append("Node.js context: Consider using 'npm run test' or 'npm run build'.")
    if "python" in features:
        hints.append("Python context: Check for '.venv', use 'pytest' for testing.")
        
    return "\n".join(hints)

if __name__ == "__main__":
    import sys
    cwd = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(get_context_tools(cwd))
