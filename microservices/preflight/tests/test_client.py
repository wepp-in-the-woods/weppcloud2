import websocket
import time

# Create a WebSocket connection
ws = websocket.WebSocket()
ws.connect("ws://localhost:3030/socket")

# Send a message
ws.send("debonair-store")

# Wait for a bit
time.sleep(1)

# Close the connection
ws.close()

print('success')
