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
    clients = set()

    def check_origin(self, origin):
        # Consider adding more checks for origin validation if needed
        return True
    
    async def open(self, run_id):
        global shared_redis
        
        self.clients.add(self)
        self.run_id = os.path.split(run_id)[-1]
        self.last_pong = tornado.ioloop.IOLoop.current().time()

        print(f"run_id = {self.run_id}")

        # Fetch the preflight checklist for the given run_id from Redis
        hashmap = await shared_redis.hgetall(self.run_id)
        hashmap = {k.decode('utf-8'): v.decode('utf-8') for k, v in hashmap.items()}
        preflight_d = preflight(hashmap)
        
        # Send the checklist to the client
        await self.write_message(json.dumps({"type": "preflight", "checklist": preflight_d}))
    
    async def on_message(self, message):
        try:
            payload = json.loads(message)
            if payload.get("type") == "pong":
                self.last_pong = tornado.ioloop.IOLoop.current().time()
        except json.JSONDecodeError:
            print("Error decoding message")
    
    def close(self):
        # Remove the client from the clients set
        if self in self.clients:
            self.clients.remove(self)
    
    def ping_client(self):
        # Ensure client connection is alive before sending message
        if not self.ws_connection or not self.ws_connection.stream.socket:
            return 0
        self.write_message(json.dumps({"type": "ping"}))
        return 1


    @classmethod
    async def send_heartbeats(cls):
        for client in list(cls.clients):
            client.ping_client()
            await asyncio.sleep(0.1)

    @classmethod
    def check_clients(cls):
        # Consider logging client checks for debugging purposes
        now = tornado.ioloop.IOLoop.current().time()

        # Identify stale clients
        stale_clients = set()

        for client in cls.clients:
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
            async with async_timeout.timeout(1):
                message = await channel.get_message(ignore_subscribe_messages=True)
                if message is not None:
                    run_id = message['channel'].split(b':')[-1].decode('utf-8')
                    hashmap = await redis.hgetall(run_id)
                    hashmap = {k.decode('utf-8'): v.decode('utf-8') for k, v in hashmap.items()}
                    preflight_d = preflight(hashmap)
                    print(preflight_d)
                    for client in clients:
                        print(client.run_id == run_id, client.run_id, run_id)
                        if client.run_id == run_id:
                            print(f'send to {run_id}')
                            await client.write_message(
                                json.dumps({"type": "preflight", "checklist": preflight_d}))
                await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            # Consider logging timeout error for debugging purposes
            pass


def send_heartbeats_callback():
    tornado.ioloop.IOLoop.current().add_callback(WebSocketHandler.send_heartbeats)

async def main():
    global shared_redis
    shared_redis = await aioredis.from_url(REDIS_URL, db=0)  # Create shared Redis connection
    
    app = tornado.web.Application([
        (r"/(.*)", WebSocketHandler),
    ])
    app.listen(9001)
    tornado.ioloop.PeriodicCallback(send_heartbeats_callback, HEARTBEAT_INTERVAL).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, CLIENT_CHECK_INTERVAL).start()
    await WebSocketHandler.listen_to_redis()

if __name__ == "__main__":
    tornado.ioloop.IOLoop.current().run_sync(main)


