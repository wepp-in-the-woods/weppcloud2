import tornado.ioloop
import tornado.websocket
import json
import os
import datetime
import redis
import asyncio


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
        print('listenting to redis')
        # Set up Redis client
        r = redis.Redis(host='localhost', port=6379, db=0)
        p = r.pubsub(ignore_subscribe_messages=True)
        
        # Subscribe to the relevant Redis channel
        p.subscribe('your_redis_channel')
        
        # Asyncio event loop to listen to Redis and not block Tornado
        loop = asyncio.get_event_loop()

        # Listen for messages
        while True:
            message = await loop.run_in_executor(None, p.get_message)
            if message:
                # Check if the message is a keyspace notification
                if message['type'] == 'pmessage':
                    # Extract the key name from the channel name
                    run_id = message['channel'].split(b':')[-1].decode('utf-8')
                    # Use hgetall to get all key-value pairs from the hash
                    key_value_pairs = r.hgetall(run_id)
                    # Decode the bytes to string for easier use (if applicable)
                    key_value_pairs_decoded = {
                        k.decode('utf-8'): v.decode('utf-8') for k, v in key_value_pairs.items()}
                    print(f"run_id: {run_id}, preflight_hashmap: {key_value_pairs_decoded}")

                    self.write_message(
                        json.dumps({"type": "preflight", "hashmap": key_value_pairs_decoded}))

                    await asyncio.sleep(0.001)  # Prevent busy-waiting

        print('exiting listen to redis')

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

