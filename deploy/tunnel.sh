#!/bin/bash
# Keep a tunnel open to the droplet's paRY, and put it back when it drops.
#
#   bash deploy/tunnel.sh
#
# paRY listens on the droplet's loopback only, so this is how a laptop reaches
# it without opening a port to the internet. Local 8901 is deliberately not
# 8900: a local paRY can keep running on 8900, and when this tunnel is down the
# editor fails visibly instead of quietly answering from somewhere else.
#
# A bare `ssh -N` does not survive a network blip — one "connection reset by
# peer" and the editor is pointing at a closed port with nothing to say so.
# Hence the loop.

set -uo pipefail

HOST=${HOST:-root@201.79.9.90}
KEY=${KEY:-$HOME/.ssh/etamil_droplet}
LOCAL_PORT=${LOCAL_PORT:-8901}
REMOTE_PORT=${REMOTE_PORT:-8900}
MIN_BACKOFF=2
MAX_BACKOFF=60

backoff=$MIN_BACKOFF
while true; do
    printf '%s  connecting %s -> %s:%s\n' "$(date +%H:%M:%S)" "$LOCAL_PORT" "$HOST" "$REMOTE_PORT"

    # ExitOnForwardFailure: if something already holds the local port, say so
    # and stop rather than silently running a tunnel that forwards nothing.
    ssh -i "$KEY" \
        -o BatchMode=yes \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=20 \
        -o ServerAliveCountMax=3 \
        -o ConnectTimeout=15 \
        -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "$HOST"
    code=$?

    # A clean exit is someone stopping it on purpose.
    if [ $code -eq 0 ]; then
        echo "tunnel closed cleanly"
        exit 0
    fi

    printf '%s  tunnel exited (%s); retrying in %ss\n' "$(date +%H:%M:%S)" "$code" "$backoff"
    sleep "$backoff"
    # Back off on repeated failure so a droplet that is down, or an address
    # fail2ban has taken exception to, is not hammered every two seconds.
    backoff=$(( backoff * 2 ))
    [ $backoff -gt $MAX_BACKOFF ] && backoff=$MAX_BACKOFF
done
