import requests
import os
from os.path import join as _join
import sys
import socket
import asyncio
import websockets
from websockets.exceptions import WebSocketException
import time 


class Timer:
    def __init__(self):
        self.t0 = time.monotonic_ns()


    def elapsed_ms(self):
        return int((time.monotonic_ns() - self.t0) * 1E-6)


_thisdir = os.path.dirname(__file__)
sys.path.append(_join(_thisdir, '../'))
from discord_client import send_discord_message

fqdn = socket.getfqdn()

GET = 'GET'
POST = 'POST'
USER_AGENT = 'WeppCloudQos'

headers = {
    'User-Agent': USER_AGENT,
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Origin': 'https://wepp.cloud/',
    'Referer': 'https://wepp.cloud/weppcloud/',
}

prism_headers = {
    'User-Agent': USER_AGENT,
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://wepp.cloud/',
    'Referer': 'https://wepp.cloud/weppcloud/',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'X-Requested-With': 'XMLHttpRequest',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin'
}
prism_data =  'lon=-123.0000&lat=45.0000&proc=location_data'


services = [
    ('wepp.cloud'        , 'weppcloud' , 'https://wepp.cloud/weppcloud/health', GET, None, headers),
#    ('wepp.cloud'        , 'preflight' , 'wss://wepp.cloud/weppcloud-microservices/preflight/heath', GET, None, headers),
    ('wepp.cloud'        , 'status'    , 'wss://wepp.cloud/weppcloud-microservices/status/health', GET, None, headers),
    ('dev.wepp.cloud'    , 'weppcloud' , 'https://dev.wepp.cloud/weppcloud/health', GET, None, headers),
    ('dev.wepp.cloud'    , 'preflight' , 'wss://dev.wepp.cloud/weppcloud-microservices/preflight/health', GET, None, headers),
    ('dev.wepp.cloud'    , 'status'    , 'wss://dev.wepp.cloud/weppcloud-microservices/status/health', GET, None, headers),
    ('wepp.cloud'        , 'wmesque'   , 'https://wepp.cloud/webservices/wmesque/health', GET, None, headers),
    ('wepp.cloud'        , 'metquery'  , 'https://wepp.cloud/webservices/metquery/health', GET, None, headers),
    ('wepp.cloud'        , 'cligen'    , 'https://wepp.cloud/webservices/cligen/health', GET, None, headers),
    ('climate-dev'       , 'gridmet'   , 'https://climate-dev.nkn.uidaho.edu/Services/', GET, None, headers),
    ('daymet.ornl'       , 'daymet'    , 'https://daymet.ornl.gov/single-pixel/api#/data', GET, None, headers),
    ('prism.oregonstate' , 'prism'     , 'https://www.prism.oregonstate.edu/explorer/dataexplorer/rpc.php', POST, prism_data, prism_headers),
]


async def make_ws_request(uri, retries=3, headers=None):
    for attempt in range(retries):
        try:
            timer = Timer()
            async with websockets.connect(uri, timeout=10, extra_headers=headers) as websocket:                
                response = await websocket.recv()
                return True, timer.elapsed_ms()
        except:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # wait for 1 second before retrying if not the last attempt
    return False, None


def make_http_request(url, retries=3, method=None, headers=None, data=None):
    for attempt in range(retries):
        try:
            timer = Timer()
            if method == POST:
                response = requests.post(url, timeout=10, headers=headers, data=data)
            else:
                response = requests.get(url, timeout=10, headers=headers)
#            print(response.text)
            response.raise_for_status()  # Raises an HTTPError for bad responses
            return True, timer.elapsed_ms()
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
    return False, None


async def request_router(url, retries=3, method=None, data=None, headers=None):
    if url.startswith('http'):
        return make_http_request(url, retries=retries, method=method, headers=headers, data=data)
    else:
        return await make_ws_request(url, retries=retries, headers=None)


if __name__ == "__main__":
    from datetime import datetime
    import json

    allAvailable = True
    message = []
    message.append("```")  # Start of code block to ensure monospace font
    message.append("Host              Service        ms")  # Column headers
    message.append("─" * 36 ) # U+2500 Header separator

    doc = {
        "DateTime": datetime.now().isoformat(),
        "Services": [],
        "Metadata": {
            "checkedBy": fqdn
        }
    }

    for service in services:
        print(service)
        host, service, url, method, data, headers = service
        isAvailable, ms = asyncio.run(request_router(url, retries=3, method=method, headers=headers, data=data))
        doc['Services'].append(dict(host=host, service=service, isAvailable=isAvailable, ms=ms))

        emoji = ("\U0001F534", "\U0001F7E2")[isAvailable]
        
        if not isAvailable:
            allAvailable = False

        if ms is None:
            ms_str = ''
        else:
            ms_str = str(ms)

        message.append(f"{host:<17} {emoji} {service:<9} {ms_str:>5}")
    message.append("```")  # End of code block
    message = '\n'.join(message)
    print(message)
    send_discord_message(message, ('error', 'health')[allAvailable])

    doc['allAvailable'] = allAvailable


    import firebase_admin
    from firebase_admin import firestore, initialize_app, credentials

    cred = credentials.Certificate(_join(_thisdir, "weppcloud-stats-firebase-adminsdk-1j1n6-ca2cb090cd.json"))
    firebase_admin.initialize_app(cred)

    db = firestore.client()
    db.collection('health').add(doc)

    print(doc)

