import tornado.ioloop
import tornado.websocket
import aioredis
import asyncio
import json

# Constants
REDIS_URL = 'redis://localhost'
DB = 2


class HeartbeatMixin:
    async def open(self):
        self.last_pong = datetime.datetime.utcnow()

    async def ping_client(self):
        try:
            await self.write_message(json.dumps({"type": "ping"}))
        except tornado.websocket.WebSocketClosedError:
            pass  # handle client disconnecting abruptly

    @classmethod
    def send_heartbeats(cls):
        for client in cls.clients:
            asyncio.ensure_future(client.ping_client())

    @classmethod
    def check_clients(cls):
        now = tornado.ioloop.IOLoop.current().time()
        for client in cls.clients:
            if now - client.last_pong > 35:  # seconds
                print("Closing stale connection")
                client.close()

    async def on_message(self, message):
        payload = json.loads(message)
        if payload.get("type") == "pong":
            self.last_pong = datetime.datetime.utcnow()
    

class WebSocketHandler(tornado.websocket.WebSocketHandler, HeartbeatMixin):
    clients = set()

    def check_origin(self, origin):
        return True

    async def open(self, run_id, channel):
        await super().on_open()

        self.run_id = run_id
        self.channel = channel
        self.last_pong = tornado.ioloop.IOLoop.current().time()  # track the last pong time
        await self.connect_to_redis()
        self.clients.add(self)
        asyncio.ensure_future(self.listen_to_redis())

    async def connect_to_redis(self):
        backoff = 1
        max_backoff = 64
        while True:
            try:
                self.redis = await aioredis.create_redis(REDIS_URL, db=DB)
                break
            except Exception as e:
                print(f"Error connecting to Redis: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def listen_to_redis(self):
        channel, = await self.redis.subscribe(self.channel)
        try:
            async for msg in channel.iter(encoding='utf-8'):
                await self.write_message(json.dumps({"type": "status_update", "data": msg}))
        except tornado.websocket.WebSocketClosedError:
            pass
        finally:
            await self.redis.unsubscribe(self.channel)
            self.redis.close()
            await self.redis.wait_closed()
            self.clients.remove(self)

    async def on_message(self, message):
        await super().on_message(message)

    def on_close(self):
        pass  # cleanup is handled in listen_to_redis finally block


async def main():
    app = tornado.web.Application([
        (r"/(.*)/(.*)", WebSocketHandler),
    ])
    app.listen(9002)

    # Setting up heartbeat and client check callbacks
    tornado.ioloop.PeriodicCallback(WebSocketHandler.send_heartbeats, 30000).start()  # every 30 seconds
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, 5000).start()  # every 5 seconds


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    asyncio.get_event_loop().run_forever()

