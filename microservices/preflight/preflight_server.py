import tornado.ioloop
import tornado.websocket
import json
import os
import datetime
import aioredis
import asyncio
import async_timeout


# in order to listen to notification need to set the following in /etc/redis/redis.conf
# notification-keyspace-events Ksh

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        return True
    
    def open(self, run_id):
        self.clients.add(self)
        self.run_id = run_id
        self.last_pong = datetime.datetime.utcnow()  # Add a property to track the last pong
    
    def on_message(self, message):
        payload = json.loads(message)
        if payload.get("type") == "pong":
            self.last_pong = datetime.datetime.utcnow()  # Update last pong when a pong is received
        elif payload.get("type") == "init":
            pass
    
    def on_close(self):
        self.clients.remove(self)
    
    def ping_client(self):
        self.write_message(json.dumps({"type": "ping"}))

    @classmethod
    def send_heartbeats(cls):
        for client in cls.clients:
            client.ping_client()

    @classmethod
    def check_clients(cls):
        now = datetime.datetime.utcnow()
        for client in cls.clients:
            # If the last pong is older than 35 seconds, close the connection
            if (now - client.last_pong).total_seconds() > 35:
                print("Closing stale connection")
                client.close()


    @classmethod
    async def listen_to_redis(cls):
        redis = await aioredis.from_url('redis://localhost', db=0)
        pubsub = redis.pubsub()
        await pubsub.psubscribe('__keyspace@0__:*')
        future = asyncio.ensure_future(on_hset(pubsub, redis, cls.clients))
        await future


async def on_hset(channel: aioredis.client.PubSub, redis, clients):
    while True:
        try:
            async with async_timeout.timeout(1):
                message = await channel.get_message(ignore_subscribe_messages=True)
                if message is not None:
                    run_id = message['channel'].split(b':')[-1].decode('utf-8')

                    hashmap = await redis.hgetall(run_id)
                    hashmap = {k.decode('utf-8'): v.decode('utf-8') for k, v in hashmap.items()}

                    for client in clients:
                        if client.run_id == run_id:
                            await client.write_message(
                                json.dumps({"type": "preflight", "hashmap": hashmap}))


                await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            pass


async def main():
    app = tornado.web.Application([
        (r"/(.*)", WebSocketHandler),
    ])

    app.listen(9001)
    tornado.ioloop.PeriodicCallback(WebSocketHandler.send_heartbeats, 30000).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, 5000).start()  # Check clients every 5 seconds

    await WebSocketHandler.listen_to_redis()

if __name__ == "__main__":
    tornado.ioloop.IOLoop.current().run_sync(main)

