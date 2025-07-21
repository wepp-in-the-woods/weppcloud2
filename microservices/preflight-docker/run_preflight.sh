#!/usr/bin/env bash
cd /workdir/weppcloud2/microservices/preflight-docker
until python preflight_server.py; do
    code=$?
    echo "$(date)  preflight_server exited with code $code – restarting…" >&2
    sleep 2            # back-off so you don’t spin
done