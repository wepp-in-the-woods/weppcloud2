import os
import json
import asyncio
import datetime
import async_timeout
import tornado.ioloop
import tornado.websocket
import aioredis

# Constants
REDIS_URL = 'redis://localhost'
HEARTBEAT_INTERVAL = 30000  # in milliseconds
CLIENT_CHECK_INTERVAL = 5000  # in milliseconds
REDIS_KEY_PATTERN = '__keyspace@0__:*'


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
    
    def open(self, run_id):
        self.clients.add(self)
        self.run_id = os.path.split(run_id)[-1]
        self.last_pong = datetime.datetime.utcnow()
    
    def on_message(self, message):
        payload = json.loads(message)
        # Consider adding validation for received payload
        if payload.get("type") == "pong":
            self.last_pong = datetime.datetime.utcnow()
    
    def on_close(self):
        self.clients.remove(self)
    
    def ping_client(self):
        # Ensure client connection is alive before sending message
        if not self.ws_connection or not self.ws_connection.stream.socket:
            self.clients.remove(self)
            return
        self.write_message(json.dumps({"type": "ping"}))

    @classmethod
    def send_heartbeats(cls):
        for client in cls.clients:
            client.ping_client()

    @classmethod
    def check_clients(cls):
        # Consider logging client checks for debugging purposes
        now = datetime.datetime.utcnow()
        for client in cls.clients:
            if (now - client.last_pong).total_seconds() > 35:
                print("Closing stale connection")
                client.close()

    @classmethod
    async def listen_to_redis(cls):
        redis = await aioredis.from_url(REDIS_URL, db=0)
        pubsub = redis.pubsub()
        await pubsub.psubscribe(REDIS_KEY_PATTERN)
        future = asyncio.ensure_future(on_hset(pubsub, redis, cls.clients))
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

    d['sbs_map'] = 'has_sbs' in prep
    d['channels'] = 'build_channels' in prep
    d['outlet'] = _safe_gt(prep.get('set_outlet'), prep.get('build_channels'))
    d['subcatchments'] = _safe_gt(prep.get('abstract_watershed'), prep.get('build_channels'))
    d['landuse'] = _safe_gt(prep.get('build_landuse'), prep.get('abstract_watershed'))
    d['soils'] = _safe_gt(prep.get('build_soils'), prep.get('abstract_watershed')) and \
                 _safe_gt(prep.get('build_soils'), prep.get('build_landuse'))
    d['climate'] = _safe_gt(prep.get('build_climate'), prep.get('abstract_watershed'))
    d['wepp'] = _safe_gt(prep.get('run_wepp'), prep.get('build_landuse')) and \
                _safe_gt(prep.get('run_wepp'), prep.get('build_soils')) and \
                _safe_gt(prep.get('run_wepp'), prep.get('build_climate'))
    d['observed'] = _safe_gt(prep.get('run_observed'), prep.get('build_landuse')) and \
                    _safe_gt(prep.get('run_observed'), prep.get('build_soils')) and \
                    _safe_gt(prep.get('run_observed'), prep.get('build_climate')) and \
                    _safe_gt(prep.get('run_observed'), prep.get('run_wepp'))
    d['debris'] = _safe_gt(prep.get('run_debris'), prep.get('build_landuse')) and \
                  _safe_gt(prep.get('run_debris'), prep.get('build_soils')) and \
                  _safe_gt(prep.get('run_debris'), prep.get('build_climate')) and \
                  _safe_gt(prep.get('run_debris'), prep.get('run_wepp'))
    d['watar'] = _safe_gt(prep.get('run_watar'), prep.get('build_landuse')) and \
                 _safe_gt(prep.get('run_watar'), prep.get('build_soils')) and \
                 _safe_gt(prep.get('run_watar'), prep.get('build_climate')) and \
                 _safe_gt(prep.get('run_watar'), prep.get('run_wepp'))

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


async def main():
    app = tornado.web.Application([
        (r"/(.*)", WebSocketHandler),
    ])
    app.listen(9001)
    tornado.ioloop.PeriodicCallback(WebSocketHandler.send_heartbeats, HEARTBEAT_INTERVAL).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, CLIENT_CHECK_INTERVAL).start()
    await WebSocketHandler.listen_to_redis()

if __name__ == "__main__":
    tornado.ioloop.IOLoop.current().run_sync(main)

