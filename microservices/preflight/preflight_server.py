import tornado.ioloop
import tornado.web
import tornado.websocket
import json

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        # Allow WebSocket connections from anywhere.
        return True
    
    def open(self):
        # Add client to the clients set.
        self.clients.add(self)
    
    def on_message(self, message):
        # Handle incoming messages from the client.
        payload = json.loads(message)
        if payload.get("type") == "pong":
            print("Received pong from client.")
        elif payload.get("type") == "run_id":
            self.run_id = payload.get("data")
            # TODO: Handle client registration.
    
    def on_close(self):
        # Remove client from the clients set.
        self.clients.remove(self)
    
    def ping_client(self):
        # Send a ping to the client.
        self.write_message(json.dumps({"type": "ping"}))

    @classmethod
    def send_heartbeats(cls):
        for client in cls.clients:
            client.ping_client()

# Set up the Tornado application.
app = tornado.web.Application([
    (r"/websocket", WebSocketHandler),
])

if __name__ == "__main__":
    app.listen(9001)
    # Set up a periodic callback to send heartbeats every 30 seconds.
    tornado.ioloop.PeriodicCallback(WebSocketHandler.send_heartbeats, 30000).start()
    tornado.ioloop.IOLoop.current().start()

