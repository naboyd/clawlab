/**
 * Clawlab MCP identity — forwards clawBind from the Control UI URL to ssh-ops MCP.
 *
 * The portal hub appends ?clawBind=<token> to the OpenClaw link. This plugin
 * stores that token and adds X-Claw-Mcp-Bind on outbound MCP HTTP calls so the
 * identity proxy can inject verified X-Auth-User / X-Auth-Role.
 */

let bindToken = (process.env.CLAW_MCP_BIND || "").trim();

function tokenFromUrl(url) {
  try {
    const u = new URL(url);
    return (u.searchParams.get("clawBind") || "").trim();
  } catch {
    return "";
  }
}

function patchFetch() {
  if (globalThis.__clawlabMcpIdentityPatched) return;
  globalThis.__clawlabMcpIdentityPatched = true;
  const orig = globalThis.fetch;
  if (typeof orig !== "function") return;

  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input?.url || "";
    const headers = new Headers(init.headers || {});
    if (bindToken && /:8767\b|mcp-identity|\/mcp\b/i.test(url)) {
      headers.set("X-Claw-Mcp-Bind", bindToken);
    }
    return orig(input, { ...init, headers });
  };
}

export default function register(api) {
  patchFetch();

  if (api?.on) {
    api.on("gateway.start", () => patchFetch());
    api.on("controlUi.url", (ctx) => {
      const t = tokenFromUrl(ctx?.url || "");
      if (t) bindToken = t;
    });
    api.on("mcp.beforeRequest", (ctx) => {
      if (bindToken && ctx?.headers) {
        ctx.headers["X-Claw-Mcp-Bind"] = bindToken;
      }
    });
  }

  // Fallback for builds without hook events: read bind token once at load.
  const startupUrl = process.env.CLAW_CONTROL_UI_URL || "";
  const fromEnv = tokenFromUrl(startupUrl);
  if (fromEnv) bindToken = fromEnv;
}
