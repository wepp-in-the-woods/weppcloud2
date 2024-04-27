import requests
import os
from os.path import join as _join
import sys
import socket

_thisdir = os.path.dirname(__file__)
sys.path.append(_join(_thisdir, '../'))
from discord_client import send_discord_message

fqdn = socket.getfqdn()

def health_check(url, retries=3):
    global fqdn

    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses
            send_discord_message(f"Success: {fqdn} received response on attempt {attempt + 1}", "health")
            print(response.status_code)
            return response
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
    send_discord_message(f"Error: {fqdn} railed to get a response after 3 attempts.", "error")
    return response

if __name__ == "__main__":
    health_check('https://wepp.cloud/weppcloud/health')

