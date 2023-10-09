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
        
        # Create an Event to signal when the coroutine should stop
        self.stop_event = asyncio.Event()
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
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"Unexpected error in proxy_message: {e}")
                break  # or decide how you want to handle unexpected errors

    async def subscribe_to_redis(self):
        global shared_redis

        self.pubsub = shared_redis.pubsub()
        await self.pubsub.subscribe(f"{self.run_id}:{self.channel}")

        print(f'subscribed to {self.run_id}:{self.channel}')

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
                    
            # Set the stop event to signal to proxy_message to exit
            self.stop_event.set()
            
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

def send_heartbeats_callback():
    tornado.ioloop.IOLoop.current().add_callback(WebSocketHandler.send_heartbeats)


async def main():
    global shared_redis
    shared_redis = await aioredis.from_url(REDIS_URL, db=DB)  # Create shared Redis connection
    
    app = tornado.web.Application([
        (r"/(.*)", WebSocketHandler),
    ])
    app.listen(9002)
    tornado.ioloop.PeriodicCallback(send_heartbeats_callback, HEARTBEAT_INTERVAL).start()
    tornado.ioloop.PeriodicCallback(WebSocketHandler.check_clients, CLIENT_CHECK_INTERVAL).start()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
    asyncio.get_event_loop().run_forever()
