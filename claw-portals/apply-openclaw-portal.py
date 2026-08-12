#!/usr/bin/env python3
"""Set OpenClaw Control UI basePath for unified portal /openclaw/ subpath."""
from __future__ import annotations

import json
import os
import shutil
import sys

PORT = os.environ.get("PORT_PORTAL", "8443")
DOMAIN = os.environ.get("DOMAIN", "lab.example.com")

p = os.path.expanduser("~/.openclaw/openclaw.json")
if not os.path.isfile(p):
    sys.exit(f"Missing {p}")

with open(p, encoding="utf-8") as fh:
    cfg = json.load(fh)

gw = cfg.setdefault("gateway", {})
ui = gw.setdefault("controlUi", {})
ui["basePath"] = "/openclaw"

origins = {
    f"https://{DOMAIN}:{PORT}",
    f"https://192.168.1.10:{PORT}",
    f"https://lab-host:{PORT}",
}
existing = set(ui.get("allowedOrigins") or [])
ui["allowedOrigins"] = sorted(origins | existing)

shutil.copy(p, p + ".pre-portal-basepath.bak")
with open(p, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2)

print("Set gateway.controlUi.basePath=/openclaw")
print("allowedOrigins:", ", ".join(ui["allowedOrigins"]))
print("Backup:", p + ".pre-portal-basepath.bak")
print("Restart: systemctl --user restart openclaw-gateway")
