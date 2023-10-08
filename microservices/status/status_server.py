import os
import json
import asyncio
import async_timeout
import tornado.ioloop
import tornado.websocket
import aioredis

# Constants
REDIS_URL = 'redis://localhost'
HEARTBEAT_INTERVAL = 30000  # in milliseconds
CLIENT_CHECK_INTERVAL = 5000  # in milliseconds
DB = 2

shared_redis = None  # Global variable to hold the shared Redis connection


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        # Consider adding more checks for origin validation if needed
        return True
    
    async def open(self, args):
        global shared_redis

        args = os.path.split(args)[-1]
        self.run_id, self.channel = args.split(':')
        
        self.clients.add(self)
        self.last_pong = tornado.ioloop.IOLoop.current().time()

        print(f'run_id = {self.run_id}, channel = {self.channel}')

        await self.subscribe_to_redis()
    

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

    async def subscribe_to_redis(self):
        global shared_redis

        self.pubsub = shared_redis.pubsub()
        await self.pubsub.subscribe(f"{self.run_id}:{self.channel}")
        future = asyncio.ensure_future(self.proxy_message(self.pubsub))
        await future

    async def unsubscribe_to_redis(self):
        global shared_redis

        await self.pubsub.unsubscribe(f"{self.run_id}:{self.channel}")

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
    
        if hasattr(self, 'pubsub'):
            asyncio.ensure_future(self.unsubscribe_to_redis())

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
        now = tornado.ioloop.IOLoop.current().time()

        # Identify stale clients
        stale_clients = {client for client in cls.clients if now - client.last_pong > 35}
        
        # Close stale connections
        for client in stale_clients:
            print(f"Closing stale connection with {client.run_id}")
            client.close()  


async def main():
    global shared_redis
    shared_redis = await aioredis.from_url(REDIS_URL, db=DB)  # Create shared Redis connection
    
    app = tornado.web.Application([
        (r"/(.*)", WebSocketHandler),
    ])
    app.listen(9002)
    tornado.ioloop.PeriodicCallback(WebSocketHandler.send_heartbeats, HEARTBEAT_INTERVAL).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, CLIENT_CHECK_INTERVAL).start()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    asyncio.get_event_loop().run_forever()
