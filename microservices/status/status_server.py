import tornado.ioloop
import tornado.websocket
import aioredis
import asyncio
import async_timeout
import json

# Constants
REDIS_URL = 'redis://localhost'
DB = 2


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    async def open(self, run_id, channel):
        self.run_id = run_id
        self.channel = channel
        self.last_pong = tornado.ioloop.IOLoop.current().time()
        await self.connect_to_redis()
        self.clients.add(self)
        asyncio.ensure_future(self.listen_to_redis())

        print(run_id, channel)

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
        # Consider logging client checks for debugging purposes
        now = tornado.ioloop.IOLoop.current().time()
        for client in cls.clients:
            if (now - client.last_pong).total_seconds() > 35:
                print("Closing stale connection")
                client.close()

    def check_origin(self, origin):
        return True

    async def connect_to_redis(self):
        backoff = 1
        max_backoff = 64
        while True:
            try:
                self.redis = await aioredis.from_url(REDIS_URL, db=DB)
                break
            except Exception as e:
                print(f"Error connecting to Redis: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def proxy_message(self, channel: aioredis.client.PubSub):
        while True:
            try:
                async with async_timeout.timeout(1):
                    message = await channel.get_message(ignore_subscribe_messages=True)
                    if message is not None:
                        print(f"(Reader) Message Received: {message}")
                        data = message['data'].decode('utf-8')
                        self.write_message(
                            json.dumps({"type": "status", "data": data}))
                    await asyncio.sleep(0.001)
            except asyncio.TimeoutError:
                pass

    async def listen_to_redis(self):
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe(f"{self.run_id}:{self.channel}")
        future = asyncio.ensure_future(self.proxy_message(self.pubsub))
        await future

    async def on_message(self, message):
        try:
            payload = json.loads(message)
            if payload.get("type") == "pong":
                self.last_pong = tornado.ioloop.IOLoop.current().time()
        except json.JSONDecodeError:
            print("Error decoding message")
            
    async def on_close(self):
        print(f"Connection closed for run_id: {self.run_id}, channel: {self.channel}")
        
        # Remove the client from the clients set
        if self in self.clients:
            self.clients.remove(self)

        # Unsubscribe from the channel and close the Redis connection
        if hasattr(self, 'pubsub'):
            await self.pubsub.unsubscribe(f"{self.run_id}:{self.channel}")
            self.redis.close()
            await self.redis.wait_closed()


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

