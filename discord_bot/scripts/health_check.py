import requests
import os
from os.path import join as _join
import sys

_thisdir = os.path.dirname(__file__)
sys.path.append(_join(_thisdir, '../'))
from discord_client import send_discord_message


def health_check(url, retries=3):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses
            send_discord_message(f"Success: Received response on attempt {attempt + 1}", "health")
            return response
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
    send_discord_message("Failed to get a response after 3 attempts.", "error")
    return response

if __name__ == "__main__":
    health_check('https://wepp.cloud')
