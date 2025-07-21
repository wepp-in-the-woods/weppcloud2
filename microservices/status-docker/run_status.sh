#!/usr/bin/env bash
cd /workdir/weppcloud2/microservices/status-docker
until python status_server.py; do
    code=$?
    echo "$(date)  status_server exited with code $code – restarting…" >&2
    sleep 2            # back-off so you don’t spin
done