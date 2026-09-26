#!/bin/bash
# paRY — deploy to a server.
#
#   scp pary-src.tar deploy/run-deploy.sh deploy/pary.service root@HOST:/root/
#   ssh root@HOST 'bash /root/run-deploy.sh'
#
# Safe to re-run: every step checks before it acts.
#
# What it deliberately does NOT do:
#   - bind beyond loopback. paRY compiles source it is sent; serve/__main__.py
#     says binding wider is a decision that has to be typed out. Put nginx and
#     something that decides who may ask in front of it first.
#   - build the index. The index ships prebuilt because building it needs the
#     eTamil source repositories, which a serving box has no reason to hold.

set -euo pipefail
log() { printf '\n=== %s\n' "$*"; }

PAYLOAD=${PAYLOAD:-/root/pary-src.tar}
UNIT=${UNIT:-/root/pary.service}

# --- 1. the compiler --------------------------------------------------------
# paRY's whole claim is that the compiler decides what is correct. Without it
# every answer would be unverified, so this is a hard stop rather than a
# warning.
log "compiler"
if [ ! -x /usr/local/bin/etamil ]; then
    echo "  /usr/local/bin/etamil is missing. Install the release tarball first." >&2
    exit 1
fi
/usr/local/bin/etamil --version | head -1

# --- 2. user and directories ------------------------------------------------
log "user and directories"
id pary >/dev/null 2>&1 || adduser --system --group --home /opt/pary pary
install -d -o pary -g pary /opt/pary

# --- 3. the application -----------------------------------------------------
# Extracted every run: this is how a new index or a new answer engine reaches
# the box, and the service is stopped first so nothing reads a half-written
# tree.
log "application"
if [ ! -f "${PAYLOAD}" ]; then
    echo "  ${PAYLOAD} not found." >&2
    exit 1
fi
systemctl stop pary 2>/dev/null || true
tar -xf "${PAYLOAD}" -C /opt/pary
chown -R pary:pary /opt/pary
ls /opt/pary

# --- 4. dependencies --------------------------------------------------------
# Only what serving needs. The tokenizer and corpus tooling stay on whatever
# machine builds the index.
log "virtualenv"
if [ ! -x /opt/pary/.venv/bin/python ]; then
    python3 -m venv /opt/pary/.venv
fi
/opt/pary/.venv/bin/pip install --quiet --upgrade pip
/opt/pary/.venv/bin/pip install --quiet fastapi "uvicorn[standard]" tokenizers
chown -R pary:pary /opt/pary/.venv
/opt/pary/.venv/bin/python -c "import fastapi, uvicorn, tokenizers; print('  deps ok')"

# --- 5. the service ---------------------------------------------------------
log "service"
install -m 644 "${UNIT}" /etc/systemd/system/pary.service
systemctl daemon-reload
systemctl enable --now pary
sleep 4
systemctl is-active pary || true

log "listening"
ss -ltnp | grep 8900 || echo "  NOTHING ON 8900 — check: journalctl -u pary -n 40"

log "health"
curl -s -m 10 http://127.0.0.1:8900/health || echo "  no answer"
echo

cat <<'NEXT'

=== done. what remains ===

paRY answers on 127.0.0.1:8900 and nowhere else. Two ways to reach it:

  1. An SSH tunnel, which needs no decisions:
       ssh -N -L 8900:127.0.0.1:8900 root@HOST
     then leave the extension's pary.server at http://127.0.0.1:8900

  2. nginx + TLS on a hostname, which needs one: this endpoint accepts source
     and compiles it. `etamil --check` does not execute what it is given, so
     this is not arbitrary code execution — but it is still an unauthenticated
     stranger spending your CPU. Decide how callers are identified before the
     port is open, not after.

     The VS Code extension sends no credentials of its own (src/client.ts sets
     Content-Type and nothing else), so header auth needs an extension change.
NEXT
