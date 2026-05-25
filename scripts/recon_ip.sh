#!/usr/bin/env bash
set -euo pipefail
printf 'api.ipify: '; curl -fsSL https://api.ipify.org || true; echo
printf 'ifconfig.me: '; curl -fsSL https://ifconfig.me/ip || true; echo
printf '\nCloudflare trace:\n'; curl -fsSL https://www.cloudflare.com/cdn-cgi/trace | sed -n '1,30p' || true
