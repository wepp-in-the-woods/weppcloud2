# Preflight Tornado WebSocket Server

## Overview

Preflight is a WebSocket server implemented using Python's Tornado framework and Redis. It allows multiple clients to connect via WebSockets and receives updates based on Redis HSET events. 

## Features

- **WebSocket Management**: Handles multiple WebSocket connections, sending heartbeat pings, and checking for client responsiveness.
- **Redis Subscription**: Listens for HSET events on Redis and forwards relevant data to connected WebSocket clients based on their `run_id`.
- **Asynchronous Operations**: Uses Python's asyncio and Tornado's asynchronous capabilities to handle WebSocket connections and interact with Redis in a non-blocking manner.

## Prerequisites

- Python 3.7+
- Tornado
- aioredis
- Redis Server

## Configuration

### Redis Configuration

Ensure that the following line is present and uncommented in your `redis.conf` file to enable keyspace notifications:

```conf
notify-keyspace-events Ksh

### Notes for Future Development

For Python versions 3.7+, consider replacing `asyncio.ensure_future()` with `asyncio.create_task()`
for creating asynchronous tasks, as it is more idiomatic and readable.

