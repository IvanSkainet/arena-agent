#!/usr/bin/env bash
set -o pipefail
printf '### identity\n'; whoami; hostname; pwd; id
printf '\n### os\n'; uname -a; cat /etc/os-release 2>/dev/null || true
printf '\n### runtimes\n'
for c in python3 python node npm pnpm yarn bun deno uv pipx git rustc cargo go java javac dotnet ruby perl php; do
  command -v "$c" >/dev/null 2>&1 && { printf '%-10s ' "$c"; "$c" --version 2>&1 | head -1; }
done
printf '\n### package managers / containers\n'
for c in pacman yay paru flatpak docker podman distrobox; do
  command -v "$c" >/dev/null 2>&1 && { printf '%-10s ' "$c"; "$c" --version 2>&1 | head -1; }
done
printf '\n### browsers\n'
for c in chromium firefox brave google-chrome vivaldi librewolf; do
  command -v "$c" >/dev/null 2>&1 && { printf '%-14s ' "$c"; "$c" --version 2>&1 | head -1; }
done
printf '\n### display\n'; env | grep -E '^(XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP|WAYLAND_DISPLAY|DISPLAY)=' || true
printf '\n### gpu\n'; command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
printf '\n### disks\n'; df -hT | sed -n '1,60p'
printf '\n### memory\n'; free -h
printf '\n### network\n'; ip -brief addr 2>/dev/null || true
