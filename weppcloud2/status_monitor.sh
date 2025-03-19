#!/bin/bash
# report_connections.sh
# This script reports the number of ESTABLISHED and CLOSE_WAIT connections on port 9002.

PORT=9002

# Parse command line options
while getopts "p:" opt; do
    case $opt in
        p)
            PORT=$OPTARG
            ;;
        \?)
            echo "Usage: $0 [-p port]" >&2
            exit 1
            ;;
    esac
done


while true; do
    # Count established connections on the specified port
    ESTABLISHED_COUNT=$(netstat -antp 2>/dev/null | grep ":$PORT" | grep ESTABLISHED | wc -l)

    # Count close_wait connections on the specified port
    CLOSE_WAIT_COUNT=$(netstat -antp 2>/dev/null | grep ":$PORT" | grep CLOSE_WAIT | wc -l)

    clear
    echo "Port: $PORT"
    echo "ESTABLISHED connections: $ESTABLISHED_COUNT"
    echo "CLOSE_WAIT connections: $CLOSE_WAIT_COUNT"

    sleep 3
done
