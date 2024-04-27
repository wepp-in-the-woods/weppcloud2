import requests
import os
from os.path import join as _join
import sys
import socket
import asyncio
import websockets
from websockets.exceptions import WebSocketException

_thisdir = os.path.dirname(__file__)
sys.path.append(_join(_thisdir, '../'))
from discord_client import send_discord_message

fqdn = socket.getfqdn()


services = [
    ('weppcloud', 'https://wepp.cloud/weppcloud/health'),
    ('preflight', 'wss://wepp.cloud/weppcloud-microservices/preflight/heath'),
    ('status'   , 'wss://wepp.cloud/weppcloud-microservices/status/health'),
    ('wmesque'  , 'https://wepp.cloud/webservices/wmesque/health'),
    ('metquery' , 'https://wepp.cloud/webservices/metquery/health'),
    ('cligen' , 'https://wepp.cloud/webservices/cligen/health'),
]


async def make_ws_request(uri, retries=3):
    for attempt in range(retries):
        try:
            async with websockets.connect(uri, timeout=10) as websocket:
                # Optionally send a message if needed
                # await websocket.send("Your message here")

                # Receive a message
                response = await websocket.recv()
                return True
        except WebSocketException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1)  # wait for 1 second before retrying if not the last attempt
    return False


def make_http_request(url, retries=3):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses
            ms = int(response.elapsed.total_seconds() * 1000)
            return True
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
    return False


async def request_router(url, retries=3):
    if url.startswith('http'):
        return make_http_request(url, retries=retries)
    else:
        return await make_ws_request(url, retries=retries)

if __name__ == "__main__":
    stati = []
    for service, url in services:
        status = asyncio.run(request_router(url))
        stati.append((service, status))

    message = []
    message.append("```")  # Start of code block to ensure monospace font
    message.append("Service      Status")  # Column headers
    message.append("---------------------")  # Header separator
    for service, status in stati:
        emoji = ("\U0001F534", "\U0001F7E2")[status]
        # Format each line: pad the service name to a fixed length for alignment
        message.append(f"{service.ljust(16)} {emoji}")
    message.append("```")  # End of code block

    # Join all parts of the message into a single string with newlines
    message = '\n'.join(message)

    if all([status for service, status in stati]):
        send_discord_message(message, "health")
    else:
        send_discord_message(message, "error")

