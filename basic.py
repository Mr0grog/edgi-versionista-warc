from warcio.capture_http import capture_http
from warcio import WARCWriter
import requests

with open('example.warc', 'wb') as fh:
    warc_writer = WARCWriter(fh, gzip=False, warc_version='1.1')
    with capture_http(warc_writer, warc_version='1.1'):
        requests.get('https://google.com/.')
