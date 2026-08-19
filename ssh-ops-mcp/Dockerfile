FROM python:3.12-slim

# Non-interactive, no bytecode cruft, unbuffered logs for MCP stdio.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Data lives on a mounted volume: hosts.yaml, .env, master.key, audit log.
ENV SSH_OPS_CONFIG=/data/hosts.yaml \
    SSH_OPS_ENV=/data/.env \
    SSH_OPS_KEYFILE=/data/master.key \
    SSH_OPS_GUI_HOST=0.0.0.0 \
    SSH_OPS_GUI_PORT=8765 \
    SSH_OPS_IOS_XE_POLICY=/data/ios-xe-policy.yaml

WORKDIR /app

# openssh-client provides ssh-keyscan for populating known_hosts if needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py secrets_store.py webgui.py inventory.py network_discovery.py discovery_import.py credential_test.py claw_auth_middleware.py claw_user_lookup.py mcp_bind.py mcp_tokens.py mcp_identity.py rbac.py mcp_identity_proxy.py portal_mount.py change_store.py change_policy.py change_approval.py ios_change.py ios_xe_policy.py ios_config_archive.py verify_spec.py network_apply.py change_engine.py change_notify.py webex_approval.py change_actor.py dhcp_change.py dhcp_sidecar_client.py entrypoint.sh ./
COPY ios-xe-policy.yaml /app/ios-xe-policy.yaml
RUN chmod +x entrypoint.sh \
    && mkdir -p /data

EXPOSE 8765

# Liveness: hit /healthz using stdlib (no curl in slim). Only meaningful in
# gui mode; harmless otherwise.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/healthz'%os.environ.get('SSH_OPS_GUI_PORT','8765'); \
sys.exit(0 if urllib.request.urlopen(url,timeout=4).status==200 else 1)" \
    || exit 1

ENTRYPOINT ["./entrypoint.sh"]
# Default mode: the web GUI. Override with "mcp" for the MCP server (stdio).
CMD ["gui"]
