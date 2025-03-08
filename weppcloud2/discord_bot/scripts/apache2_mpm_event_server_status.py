#! /usr/bin/python3

# Author: Roger Lew
# Email: rogerlew@gmail.com
# Date: 4/30/2024
# Public Domain (The UnLicense)


import requests
import html2text
import dateutil
from dateutil import parser


def _date_str_to_isoformat(date_str):
    date_obj = dateutil.parser.parse(date_str)
    iso_format_date = date_obj.astimezone(dateutil.tz.UTC).isoformat()
    return iso_format_date


def _try_parse(x):
    try:
        v = float(x)
        i = int(v)

        if v == i:
            return i
        return v
    except ValueError:
        pass
    
    try:
        return _date_str_to_isoformat(x)
    except ValueError:
        pass

    return x


def apache2_get_server_status(url='http://localhost/server-status'):
    """
    Fetches and parses the Apache HTTP Server status page to extract server statistics,
    specifically tailored for servers using the MPM_Event module. This function retrieves
    the server status page from the provided URL, parses the HTML content to extract
    relevant server metrics, and attempts to parse these metrics into appropriate data types
    (e.g., integers, floats, ISO-formatted dates).

    The function handles the server-status page structure typical of MPM_Event, parsing the first
    36 lines for general stats and specifically extracting values related to request handling and
    worker statuses.

    Parameters:
    - url (str): The URL of the Apache server status page. Default is 'http://localhost/server-status'.

    Returns:
    - dict: A dictionary with server statistics where keys are the metric names and values are the
            parsed metric values, converted to the most appropriate data type (int, float, or str).

    Raises:
    - requests.exceptions.RequestException: For issues like network problems, or non-200 HTTP responses.
    - ValueError: If there are issues in parsing numeric or date values.

    Example usage:
    >>> server_stats = apache2_get_server_status()
    >>> print(server_stats)
    {'CPU Usage': 'u25 s12.48 cu0 cs0',
     'CPU load': '.096%',
     'Current Time': '2024-04-30T16:42:59+00:00',
     'Parent Server Config. Generation': 3,
     'Parent Server MPM Generation': 2,
     'Restart Time': '2024-04-30T05:52:06+00:00',
     'Server Built': '2023-03-09T01:34:33+00:00',
     'Server MPM': 'event',
     'Server Version': 'Apache/2.4.29 (Ubuntu) OpenSSL/1.1.1 mod_wsgi/4.5.17',
     'Server load': '2002-01-01T08:00:00+00:00',
     'Server uptime': '2024-04-30T17:50:53+00:00',
     'Total Traffic': '175.7 MB',
     'Total accesses': 6844,
     'idle workers': 44,
     'kB/request': 26.3,
     'requests currently being processed': 31,
     'requests/sec': 0.175}
    """
    r = requests.get(url)
    text_maker = html2text.HTML2Text()
    text_maker.ignore_links = True
    txt = text_maker.handle(r.text)

    lines = [item for l in txt.split('\n')[:36] for item in (l.split(' -') if ' -' in l else [l])]
    kv_strings = [l.split(': ') for l in lines if ': ' in l]
    stats = {k.strip(): v.strip() for k, v in kv_strings}

    more_stats_vk = [lines[27], lines[29], lines[31]] + lines[33].split(',')
    more_stats_vk = [vk.split() for vk in more_stats_vk]
    stats.update({' '.join(vk[1:]): vk[0] for vk in more_stats_vk})

    return {k: _try_parse(v) for k, v in stats.items()}


if __name__ == "__main__":
    from pprint import pprint
    stats = apache2_get_server_status()
    pprint(stats)

