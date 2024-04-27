import requests
import os
from os.path import join as _join

_thisdir = os.path.dirname(__file__)


with open(_join(_thisdir, '.bot_token')) as fp:
    BOT_TOKEN = fp.read().strip()


def send_discord_message(message, channel=None):
    global BOT_TOKEN
    channel_id = {"health": "1233625174226636831",
                  "error":  "1233625200457809940"}\
                       .get(channel, "1233625118287200308") # default to general

    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "content": message
    }
    response = requests.post(url, json=data, headers=headers)
    return response


if __name__ == "__main__":
    import sys
    print(send_discord_message(sys.argv[-1]).text)
