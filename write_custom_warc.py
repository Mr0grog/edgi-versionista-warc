from http import HTTPStatus
import importlib.metadata
from io import BytesIO
import json
from pathlib import Path
import httpx
from warcio import WARCWriter, StatusAndHeaders


filename = 'example.custom.warc'

example_data = json.loads(
    (Path(__file__).parent / 'example_record.json').read_text()
)

BAD_HEADERS = set([
    'age', 'date', 'vary', 'expires', 'x-cachee', 'connection', 'accept-ranges', 'cache-control', 'transfer-encoding'
])


def status_text(code):
    status = HTTPStatus(code)
    return f'{status.value} {status.phrase}'


def create_version_records(warc, version):
    records = []

    history = [version['url']]
    if 'redirects'  in version['source_metadata']:
        history.extend(version['source_metadata']['redirects'])

    final_url = history[-1]
    for index, url in enumerate(history):
        if url == final_url:
            # FIXME: set `Date` with email.utils.formatdate(timestamp, usegmt=True)
            recorded_headers = {}
            if version['media_type']:
                recorded_headers['Content-Type'] = version['media_type']
            if version['headers']:
                for key, value in version['headers']:
                    if key.lower() not in BAD_HEADERS:
                        recorded_headers[key] = value
            http_headers = StatusAndHeaders(status_text(version['status']), recorded_headers.items(), protocol='HTTP/1.1')
            # Note this needs to be an IO object, so if we have bytes, use io.BytesIO(bytes)
            payload = BytesIO(httpx.get(version['body_url']).content)
        else:
            http_headers = StatusAndHeaders(status_text(302), (('Location', history[index + 1]),), protocol='HTTP/1.1')
            payload = None

        # FIXME: Consider using warcit's WARC-Source-URI for the Versionista URL
        record_id = f'<https://api.monitoring.envirodatagov.org/api/v0/versions/{version["uuid"]}/responses/{index}>'
        records.append(warc.create_warc_record(
            url,
            'response',
            payload=payload,
            http_headers=http_headers,
            warc_headers_dict={'WARC-Record-ID': record_id, 'WARC-Date': version['capture_time']}
        ))
        # FIXME: add a metadata record?
        # DCMI isVersionOf with page URL? https://www.dublincore.org/specifications/dublin-core/dcmi-terms/#http://purl.org/dc/terms/isVersionOf

    return records


with open(filename, 'wb') as fh:
    writer = WARCWriter(fh, gzip=False, warc_version='1.1')

    record = writer.create_warcinfo_record(filename, {
        # Or `import pkg_resources; pkg_resources.get_distribution('warcio').version
        'software': f'warcio/{importlib.metadata.version("warcio")}',
        'description': 'Test manually created WARC'
    })
    writer.write_record(record)

    for record in create_version_records(writer, example_data):
        writer.write_record(record)
