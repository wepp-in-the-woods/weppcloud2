import os
import json
import asyncio
import async_timeout
import tornado.ioloop
import tornado.websocket
import aioredis

# Constants
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost')
HEARTBEAT_INTERVAL = 30000  # in milliseconds
CLIENT_CHECK_INTERVAL = 5000  # in milliseconds
REDIS_KEY_PATTERN = '__keyspace@0__:*'


shared_redis = None  # Global variable to hold the shared Redis connection


def _try_int_parse(x):
    try:
        return int(x)
    except (ValueError, TypeError):
        return None


def _safe_gt(a, b):
    a = _try_int_parse(a)
    b = _try_int_parse(b)

    if a is None or b is None:
        return False

    return a > b


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = dict()

    def check_origin(self, origin):
        # Consider adding more checks for origin validation if needed
        return True

    async def open(self, args):
        global shared_redis

        self.run_id = args = os.path.split(args)[-1].strip()  # Split the path and take the last part

        # Check if the args is "health"
        if args == "health":
            await self.write_message("OK")  # Send "OK" to the client
            self.close()  # Close the WebSocket connection
            return  # Stop further processing

        self.stop_event = asyncio.Event()

        if args not in WebSocketHandler.clients:
            WebSocketHandler.clients[args] = {self}
        else:
            WebSocketHandler.clients[args].add(self)

        self.last_pong = tornado.ioloop.IOLoop.current().time()

        print(f"run_id = {self.run_id}")

        # Fetch the preflight checklist for the given run_id from Redis
        hashmap = await shared_redis.hgetall(self.run_id)
        hashmap = {k.decode('utf-8'): v.decode('utf-8') for k, v in hashmap.items()}
        preflight_d = preflight(hashmap)
        lock_d = lock_statuses(hashmap)

        # Send the checklist to the client
        await self.write_message(json.dumps(
            {"type": "preflight", 
             "checklist": preflight_d,
             "lock_statuses": lock_d}))

    async def on_message(self, message):
        try:
            payload = json.loads(message)
            if payload.get("type") == "pong":
                self.last_pong = tornado.ioloop.IOLoop.current().time()
        except json.JSONDecodeError:
            print("Error decoding message")

    def close(self):
        run_id = self.run_id
        # Remove the client from the clients set
        if run_id in WebSocketHandler.clients:
            if self in WebSocketHandler.clients[run_id]:
                WebSocketHandler.clients[run_id].remove(self)
            if len(WebSocketHandler.clients[run_id]) == 0:
                del WebSocketHandler.clients[run_id]
        super().close()

    def ping_client(self):
        # Ensure client connection is alive before sending message
        if not self.ws_connection or not self.ws_connection.stream.socket:
            return 0
        self.write_message(json.dumps({"type": "ping"}))
        return 1

    @classmethod
    async def send_heartbeats(cls):
        for run_id in cls.clients:
            for client in list(cls.clients[run_id]):
                client.ping_client()
                await asyncio.sleep(0.1)

    @classmethod
    def check_clients(cls):
        # Consider logging client checks for debugging purposes
        now = tornado.ioloop.IOLoop.current().time()

        # Identify stale clients
        stale_clients = set()

        for run_id in cls.clients:
            for client in cls.clients[run_id]:
                if (now - client.last_pong > 65) or \
                   (not client.ws_connection) or \
                   (not client.ws_connection.stream.socket):
                    stale_clients.add(client)

        # Close stale connections
        for client in stale_clients:
            print(f"Closing stale connection with {client.run_id}")
            client.close()

    @classmethod
    async def listen_to_redis(cls):
        global shared_redis
        pubsub = shared_redis.pubsub()
        await pubsub.psubscribe(REDIS_KEY_PATTERN)
        future = asyncio.ensure_future(on_hset(pubsub, shared_redis, cls.clients))
        await future


def lock_statuses(prep: dict) -> dict:
    d = {}
    d['watershed'] = prep.get('locked:watershed', False) == 'true'
    d['climate'] = prep.get('locked:climate', False) == 'true'
    d['wepp'] = prep.get('locked:wepp', False) == 'true'
    d['soils'] = prep.get('locked:soils', False) == 'true'
    d['landuse'] = prep.get('locked:landuse', False) == 'true'
    d['disturbed'] = prep.get('locked:disturbed', False) == 'true'
    return d

def preflight(prep: dict) -> dict:
    """
    Runs preflight check for running wepp

    Parameters:
    - prep (dict): redis hashmap of preflight parameters

    Returns:
    - dict: preflight checklist
    """

    d = {}

    d['sbs_map'] = prep.get('attrs:has_sbs', 'false') == 'true'
    d['channels'] = 'timestamps:build_channels' in prep
    d['outlet'] = _safe_gt(prep.get('timestamps:set_outlet'), prep.get('timestamps:build_channels'))
    d['subcatchments'] = _safe_gt(prep.get('timestamps:abstract_watershed'), prep.get('timestamps:build_channels'))
    d['landuse'] = _safe_gt(prep.get('timestamps:build_landuse'), prep.get('timestamps:abstract_watershed'))
    d['soils'] = _safe_gt(prep.get('timestamps:build_soils'), prep.get('timestamps:abstract_watershed')) and \
                 _safe_gt(prep.get('timestamps:build_soils'), prep.get('timestamps:build_landuse'))
    d['climate'] = _safe_gt(prep.get('timestamps:build_climate'), prep.get('timestamps:abstract_watershed'))
    d['rap_ts'] = _safe_gt(prep.get('timestamps:build_rap_ts'), prep.get('timestamps:build_climate'))
    d['wepp'] = _safe_gt(prep.get('timestamps:run_wepp'), prep.get('timestamps:build_landuse')) and \
                _safe_gt(prep.get('timestamps:run_wepp'), prep.get('timestamps:build_soils')) and \
                _safe_gt(prep.get('timestamps:run_wepp'), prep.get('timestamps:build_climate'))
    d['observed'] = _safe_gt(prep.get('timestamps:run_observed'), prep.get('timestamps:build_landuse')) and \
                    _safe_gt(prep.get('timestamps:run_observed'), prep.get('timestamps:build_soils')) and \
                    _safe_gt(prep.get('timestamps:run_observed'), prep.get('timestamps:build_climate')) and \
                    _safe_gt(prep.get('timestamps:run_observed'), prep.get('timestamps:run_wepp'))
    d['debris'] = _safe_gt(prep.get('timestamps:run_debris'), prep.get('timestamps:build_landuse')) and \
                  _safe_gt(prep.get('timestamps:run_debris'), prep.get('timestamps:build_soils')) and \
                  _safe_gt(prep.get('timestamps:run_debris'), prep.get('timestamps:build_climate')) and \
                  _safe_gt(prep.get('timestamps:run_debris'), prep.get('timestamps:run_wepp'))
    d['watar'] = _safe_gt(prep.get('timestamps:run_watar'), prep.get('timestamps:build_landuse')) and \
                 _safe_gt(prep.get('timestamps:run_watar'), prep.get('timestamps:build_soils')) and \
                 _safe_gt(prep.get('timestamps:run_watar'), prep.get('timestamps:build_climate')) and \
                 _safe_gt(prep.get('timestamps:run_watar'), prep.get('timestamps:run_wepp'))

    return d


async def on_hset(channel: aioredis.client.PubSub, redis, clients):
    while True:
        try:
            async with async_timeout.timeout(5):
                message = await channel.get_message(ignore_subscribe_messages=True)
                if message is not None:
                    run_id = message['channel'].split(b':')[-1].decode('utf-8')
                    if run_id in clients:
                        hashmap = await redis.hgetall(run_id)
                        hashmap = {k.decode('utf-8'): v.decode('utf-8') for k, v in hashmap.items()}
                        preflight_d = preflight(hashmap)
                        print(preflight_d)
                        for client in list(clients[run_id]):
                            print(f'send to {run_id}')
                            try:
                                await client.write_message(
                                    json.dumps({"type": "preflight", "checklist": preflight_d}))
                            except tornado.websocket.WebSocketClosedError:
                                pass

                await asyncio.sleep(0.001)
        except asyncio.TimeoutError:
            print('on_hset asyncio timeout error')
            pass

def send_heartbeats_callback():
    tornado.ioloop.IOLoop.current().add_callback(WebSocketHandler.send_heartbeats)

class HealthCheckHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")

async def main():
    global shared_redis
    shared_redis = await aioredis.from_url(REDIS_URL, db=0)  # Create shared Redis connection

    app = tornado.web.Application([
        (r"/health", HealthCheckHandler),
        (r"/(.*)", WebSocketHandler),
    ])
    app.listen(9001)
    tornado.ioloop.PeriodicCallback(send_heartbeats_callback, HEARTBEAT_INTERVAL).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, CLIENT_CHECK_INTERVAL).start()
    await WebSocketHandler.listen_to_redis()

if __name__ == "__main__":
    tornado.ioloop.IOLoop.current().run_sync(main)


