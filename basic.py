from warcio.capture_http import capture_http
from warcio import WARCWriter
# Not installed, but httpx doesn't work with capture_http.
import requests

with open('example.warc', 'wb') as fh:
    warc_writer = WARCWriter(fh, gzip=False, warc_version='1.1')
    with capture_http(warc_writer, warc_version='1.1'):
        requests.get('https://google.com/.')
