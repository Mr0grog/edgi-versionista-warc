from collections import Counter
import hashlib
from http import HTTPStatus
import importlib.metadata
from io import BytesIO
from itertools import islice
import logging
from textwrap import dedent
import httpx
from tqdm import tqdm
from warcio import WARCWriter, StatusAndHeaders
import web_monitoring_db


logger = logging.getLogger()

BAD_HEADERS = set([
    'age', 'date', 'vary', 'expires', 'x-cachee', 'connection', 'accept-ranges', 'cache-control', 'transfer-encoding'
])


class BadDataError(Exception):
    reason = 'Bad_data'
    version_id = ''

    def __init__(self, version_id, message=None, reason=None):
        self.version_id = version_id
        self.reason = reason or self.reason
        super().__init__(f'{message or self.reason} (version={version_id})')


class MissingBodyError(BadDataError):
    reason = 'Body_never_saved'


def status_text(code):
    status = HTTPStatus(code)
    return f'{status.value} {status.phrase}'


def load_response_body(version):
    body_response = httpx.get(version['body_url'])
    if body_response.status_code == 404:
        raise MissingBodyError(version['uuid'])

    actual_hash = hashlib.sha256(body_response.content).hexdigest()
    if actual_hash != version['body_hash']:
        detail = f'  Expected: {version["body_hash"]}\n  Actual:   {actual_hash}'
        raise AssertionError(f'Saved body does not match expected hash for version {version["uuid"]}\n{detail}')

    return body_response.content


def create_version_records(warc, version):
    records = []
    version_id = version['uuid']

    if version['status'] is None:
        raise BadDataError(version_id, reason='Missing_status')

    if version['body_url'] is None:
        raise MissingBodyError(version_id)

    history = [version['url']]
    if version['source_metadata'].get('redirects'):
        history.extend(version['source_metadata']['redirects'])

    final_url = history[-1]
    for index, url in enumerate(history):
        if url == final_url:
            # FIXME: set `Date` with email.utils.formatdate(timestamp, usegmt=True)
            recorded_headers = {}
            if version['media_type']:
                recorded_headers['Content-Type'] = version['media_type']
            if version['headers']:
                for key, value in version['headers'].items():
                    if key.lower() not in BAD_HEADERS:
                        recorded_headers[key] = value
            http_headers = StatusAndHeaders(status_text(version['status']), recorded_headers.items(), protocol='HTTP/1.1')
            # Note this needs to be an IO object, so if we have bytes, use io.BytesIO(bytes)
            payload = BytesIO(load_response_body(version))
        else:
            http_headers = StatusAndHeaders(status_text(302), (('Location', history[index + 1]),), protocol='HTTP/1.1')
            payload = None

        # FIXME: Consider using warcit's WARC-Source-URI for the Versionista URL
        record_id = f'<https://api.monitoring.envirodatagov.org/api/v0/versions/{version_id}/responses/{index}>'
        records.append(warc.create_warc_record(
            url,
            'response',
            payload=payload,
            http_headers=http_headers,
            warc_headers_dict={'WARC-Record-ID': record_id, 'WARC-Date': version['capture_time'].isoformat()}
        ))
        # FIXME: add a metadata record?
        # DCMI isVersionOf with page URL? https://www.dublincore.org/specifications/dublin-core/dcmi-terms/#http://purl.org/dc/terms/isVersionOf

    return records


def main(skip_errors=False, start=0, limit=0, name='versionista'):
    logging.basicConfig(level=logging.WARNING)

    chunk_size = min(1000, limit)
    db_client = web_monitoring_db.Client.from_env()

    skipped = Counter()

    filename = f'{name}.warc.gz'
    with open(filename, 'wb') as fh:
        writer = WARCWriter(fh, gzip=True, warc_version='1.1')

        # Lots more that should probably go here, see spec §10.1
        # https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1-annotated/#example-of-warcinfo-record
        record = writer.create_warcinfo_record(filename, {
            # Or `import pkg_resources; pkg_resources.get_distribution('warcio').version
            'software': f'warcio/{importlib.metadata.version("warcio")}',
            'description': dedent("""\
                Test manually created WARC""").replace('\n', ' ')
        })
        writer.write_record(record)

        versions = db_client.get_versions(source_type='versionista', chunk_size=chunk_size)
        if limit:
            versions = islice(versions, start, limit)
        for version in tqdm(versions, unit='versions'):
            try:
                records = create_version_records(writer, version)
            except BadDataError as error:
                logger.warning(str(error))
                skipped[error.reason] += 1
            except Exception as error:
                logger.error(f'Error processing version {version.get("uuid")}')
                logger.exception(error)
                if not skip_errors:
                    return

            for record in records:
                writer.write_record(record)

    print(f'Skipped {skipped.total()} Versionista versions:')
    for reason, count in skipped.items():
        print(f'  {reason.ljust(25, ".")} {str(count).rjust(5)}')


if __name__ == '__main__':
    main(skip_errors=False, limit=5000, name='edgi_wm_versionista')
