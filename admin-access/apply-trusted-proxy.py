#!/usr/bin/env python3
# Safely enable trusted-proxy auth in ~/.openclaw/openclaw.json.
# Preserves the existing gateway.auth.password (used by DefenseClaw + CLI);
# only ADDS the trusted-proxy + controlUi settings. Backs up first.
import json, os, sys, shutil

p = os.path.expanduser("~/.openclaw/openclaw.json")
c = json.load(open(p))
gw = c.setdefault("gateway", {})
auth = gw.setdefault("auth", {})

if not auth.get("password"):
    sys.exit("Refusing: gateway.auth.password is missing — DefenseClaw would lose access. Aborting.")

shutil.copy(p, p + ".pre-trustedproxy.bak")

gw["bind"] = "loopback"
gw["trustedProxies"] = ["127.0.0.1"]
auth["mode"] = "trusted-proxy"
auth["trustedProxy"] = {
    "userHeader": "x-forwarded-user",
    "requiredHeaders": ["x-forwarded-proto", "x-forwarded-host"],
    "allowUsers": [],
    "allowLoopback": True,
}
# password preserved as-is
gw.setdefault("controlUi", {})["allowedOrigins"] = [
    f"https://{os.environ.get('DOMAIN', 'icecream.naboydciscolab.com')}:8443",
    "https://192.168.128.93:8443",
    "https://icecream:8443",
]
gw["controlUi"]["basePath"] = "/openclaw"

json.dump(c, open(p, "w"), indent=2)
print("trusted-proxy enabled; password preserved; backup:", p + ".pre-trustedproxy.bak")
print("mode =", auth["mode"], "| allowLoopback =", auth["trustedProxy"]["allowLoopback"])
print("controlUi.basePath =", gw["controlUi"]["basePath"])
