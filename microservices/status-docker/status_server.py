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
DB = 2

shared_redis = None  # Global variable to hold the shared Redis connection


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        # Consider adding more checks for origin validation if needed
        return True

    def initialize(self):
        self.stop_event = asyncio.Event()

    async def open(self, args):
        global shared_redis

        args = os.path.split(args)[-1]  # Split the path and take the last part

        # Check if the args is "health"
        if args == "health":
            await self.write_message("OK")  # Send "OK" to the client
            self.close()  # Close the WebSocket connection
            return  # Stop further processing

        self.run_id, self.channel = args.split(':')

        WebSocketHandler.clients.add(self)
        self.last_pong = tornado.ioloop.IOLoop.current().time()

        print(f'run_id = {self.run_id}, channel = {self.channel}')

        await self.subscribe_to_redis()

        asyncio.ensure_future(self.proxy_message())

    async def proxy_message(self):
        while not self.stop_event.is_set():
            try:
                async with async_timeout.timeout(1):
                    message = await self.pubsub.get_message(ignore_subscribe_messages=True)
                    if message is not None:
#                        print(f"(Reader) Message Received: {message}")
                        data = message['data'].decode('utf-8')
                        self.write_message(
                            json.dumps({"type": "status", "data": data}))
                    await asyncio.sleep(0.001)
            except tornado.websocket.WebSocketClosedError as e:
                # If the connection is already closed, break the loop
                print(f'WebSocketClosedError in proxy_message: {e}')
                break

            except Exception as e:
                # Other truly unexpected errors
                print(f'Unexpected error in proxy_message: {e}')
                self.close()
                break  # Don’t loop forever if we intentionally closed

    async def subscribe_to_redis(self):
        global shared_redis

        self.pubsub = shared_redis.pubsub()
        await self.pubsub.subscribe(f"{self.run_id}:{self.channel}")

        print(f'subscribed to {self.run_id}:{self.channel}')

    async def unsubscribe_to_redis(self):
        global shared_redis

        if hasattr(self, 'pubsub'):
            await self.pubsub.unsubscribe(f"{self.run_id}:{self.channel}")
            await self.pubsub.close()  # Explicitly close the pubsub connection after unsubscribing

    async def on_message(self, message):
        try:
            payload = json.loads(message)
            if payload.get("type") == "pong":
                self.last_pong = tornado.ioloop.IOLoop.current().time()
        except json.JSONDecodeError:
            print("Error decoding message")

    def close(self):
        # This method initiates the teardown. We do minimal work here.
        # If you need to ensure the read loop stops, you can set stop_event here.
        if not self.stop_event.is_set():
            self.stop_event.set()
        super().close()

    def on_close(self):
        # The connection is actually closed now; do all final cleanup.
        if self in WebSocketHandler.clients:
            WebSocketHandler.clients.remove(self)

        asyncio.ensure_future(self.unsubscribe_to_redis())
        super().on_close()  # Make sure to call the parent’s on_close

    def ping_client(self):
        # Ensure client connection is alive before sending message
        if not self.ws_connection or not self.ws_connection.stream.socket:
            return 0
        #self.write_message(json.dumps({"type": "hangup"}))
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
            client.close()

def send_heartbeats_callback():
    tornado.ioloop.IOLoop.current().add_callback(WebSocketHandler.send_heartbeats)


class HealthCheckHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")


async def main():
    global shared_redis
    shared_redis = await aioredis.from_url(REDIS_URL, db=DB)  # Create shared Redis connection

    app = tornado.web.Application([
        (r"/health", HealthCheckHandler),
        (r"/(.*)", WebSocketHandler),
    ])
    app.listen(9002)
    tornado.ioloop.PeriodicCallback(send_heartbeats_callback, HEARTBEAT_INTERVAL).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, CLIENT_CHECK_INTERVAL).start()

    # Ensure Redis connection is closed properly when the application shuts down
    tornado.ioloop.IOLoop.current().add_callback(lambda: shared_redis.close())

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    asyncio.get_event_loop().run_forever()

