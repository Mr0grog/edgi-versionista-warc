from collections import Counter
from datetime import timezone
import email.utils
import hashlib
from io import BytesIO
from itertools import islice
import logging
import re
from textwrap import dedent
import httpx
from tqdm import tqdm
from warcio import StatusAndHeaders
from warcio.recordloader import ArcWarcRecord
from .web_monitoring_db import Client as DbClient
from .warctools import GIGABYTE, WarcSeries, status_text, create_metadata_record


logger = logging.getLogger(__name__)

# Headers known to have been generated by Versionista, and not sourced from the
# original captured request.
BAD_HEADERS = set([
    'age', 'date', 'vary', 'expires', 'x-cachee', 'connection', 'accept-ranges', 'cache-control', 'transfer-encoding'
])

URL_LIKE = re.compile(r'^(https?|ftp)://')


class BadDataError(Exception):
    reason = 'Bad_data'
    version_id = ''

    def __init__(self, version_id, message=None, reason=None):
        self.version_id = version_id
        self.reason = reason or self.reason
        super().__init__(f'{message or self.reason} (version={version_id})')


class MissingStatusCode(BadDataError):
    reason = 'Missing_status'


class MissingBodyError(BadDataError):
    reason = 'Body_never_saved'


def format_datetime_http(time):
    # email.utils does not support the UTC object dateutil uses, so fix it.
    return email.utils.format_datetime(time.astimezone(timezone.utc), usegmt=True)


def format_datetime_iso(time):
    iso_time = time.isoformat()
    # Use compact representation for UTC
    if iso_time.endswith('+00:00'):
        no_tz_date = iso_time.split("+", 1)[0]
        iso_time = f'{no_tz_date}Z'
    return iso_time


body_loader = httpx.Client(transport=httpx.HTTPTransport(retries=3))


def load_response_body(version):
    body_response = body_loader.get(version['body_url'], params={'different': False}, follow_redirects=True)
    if body_response.status_code == 404:
        raise MissingBodyError(version['uuid'])

    body_response.raise_for_status()
    actual_hash = hashlib.sha256(body_response.content).hexdigest()
    if actual_hash != version['body_hash']:
        detail = f'  Expected: {version["body_hash"]}\n  Actual:   {actual_hash}'
        raise BadDataError(
            version['uuid'],
            f'Saved body does not match expected hash\n{detail}',
            reason='Mismatched_body_data'
        )

    return body_response.content


def create_version_records(warc: WarcSeries, version: dict) -> list[ArcWarcRecord]:
    records = []
    version_id = version['uuid']
    capture_time = version["capture_time"]

    if version['status'] is None:
        raise MissingStatusCode(version_id)

    if version['body_url'] is None:
        raise MissingBodyError(version_id)

    history = [version['url']]
    if version['source_metadata'].get('redirects'):
        for redirect in version['source_metadata']['redirects']:
            if not isinstance(redirect, str) or len(redirect) == 0:
                logger.warning(f'Version {version['uuid']} has null redirect')
            elif not URL_LIKE.match(redirect):
                logger.warning(f'Version {version['uuid']} has non-URL redirect: "{redirect}"')
            else:
                history.append(redirect)

    first_record_id = None
    previous_url = None
    final_url = history[-1]
    for index, url in enumerate(history):
        database_url = f'https://api.monitoring.envirodatagov.org/api/v0/versions/{version_id}'
        record_id = f'<{database_url}/responses/{index}>'
        warc_header = {
            'WARC-Record-ID': record_id,
            'WARC-Date': format_datetime_iso(capture_time),
            # This field is non-standard, and comes from warcit:
            #   https://github.com/webrecorder/warcit#warc-structure-and-format
            # We put the Versionista URL here and the WM database URL in the
            # metadata record.
            'WARC-Source-URI': version['source_metadata']['url'],
        }
        if index == 0:
            first_record_id = record_id
        else:
            warc_header['WARC-Concurrent-To'] = first_record_id

        recorded_headers = { 'Date': format_datetime_http(capture_time) }
        if url.lower().startswith('ftp://'):
            records.append(warc.builder.create_warc_record(
                url,
                'resource',
                warc_headers_dict=warc_header,
                warc_content_type=(version['media_type'] or 'application/octet-stream'),
                payload=BytesIO(load_response_body(version))
            ))
        elif url == final_url:
            if version['media_type']:
                recorded_headers['Content-Type'] = version['media_type']
            if version['headers']:
                for key, value in version['headers'].items():
                    if key.lower() not in BAD_HEADERS:
                        recorded_headers[key] = value
            http_headers = StatusAndHeaders(status_text(version['status']), recorded_headers.items(), protocol='HTTP/1.1')

            revisit = warc.get_revisit(version['body_hash'])
            if revisit:
                # For some reason this is not an option on create_revisit_record.
                warc_header['WARC-Refers-To'] = revisit['id']
                records.append(warc.builder.create_revisit_record(
                    url,
                    revisit['warc_digest'],
                    revisit['uri'],
                    revisit['date'],
                    http_headers=http_headers,
                    warc_headers_dict=warc_header
                ))
            else:
                record = warc.builder.create_warc_record(
                    url,
                    'response',
                    payload=BytesIO(load_response_body(version)),
                    http_headers=http_headers,
                    warc_headers_dict=warc_header
                )
                records.append(record)
                warc.cache_revisitable_record(record, version['body_hash'])
        else:
            recorded_headers['Location'] = history[index + 1]
            http_headers = StatusAndHeaders(status_text(302), recorded_headers.items(), protocol='HTTP/1.1')
            records.append(warc.builder.create_warc_record(
                url,
                'response',
                payload=None,
                http_headers=http_headers,
                warc_headers_dict=warc_header
            ))

        if not first_record_id:
            first_record_id = record_id

        records.append(create_metadata_record(
            warc.builder,
            url,
            header={
                'WARC-Date': format_datetime_iso(capture_time),
                'WARC-Refers-To': record_id,
                'WARC-Concurrent-To': first_record_id,
            },
            data={
                # Directly listed in WARC standard:
                'via': previous_url,
                'hopsFromSeed': 'R' * index,
                # Standardized via Dublin Core:
                'title': version['title'],
                'source': database_url
            }
        ))

        previous_url = url

    return records


def main(*, start=0, limit=0, path='.', name='edgi-wm-versionista', gzip=True, warc_size=int(7.95 * GIGABYTE)):
    limit = limit or 0

    # The magic number here is the current count of Versionista records.
    expected_records = 845_325
    chunk_size = 5_000
    if limit:
        expected_records = min(expected_records, limit)
        chunk_size = min(chunk_size, limit)

    db_client = DbClient.from_env()

    skipped = Counter()

    warc_builder = WarcSeries(path, name=name, gzip=gzip, size=warc_size, revisit_cache_size=100_000, info={
        'operator': '"Environmental Data & Governance Initiative" <contact@envirodatagov.org>',
        'description': dedent("""\
            Web content captured by EDGI's Web Monitoring project using
            Versionista (https://versionista.com). This WARC is synthesized
            from data that was originally archived extracted from
            Versionista via https://github.com/edgi-govdata-archiving/versionista-outputter
            and https://github.com/edgi-govdata-archiving/web-monitoring-versionista-scraper.""").replace('\n', ' ')
    })

    try:
        with warc_builder as warc:
            versions = db_client.get_versions(source_type='versionista', different=False, chunk_size=chunk_size)
            if limit:
                versions = islice(versions, start, limit)

            progress_bar = tqdm(versions, unit=' versions', total=expected_records, disable=None)
            for version in progress_bar:
                try:
                    warc.write_records(create_version_records(warc, version))
                except BadDataError as error:
                    logger.warning(str(error))
                    skipped[error.reason] += 1
                except Exception as error:
                    raise RuntimeError(f'Error processing version {version.get("uuid")}: {error}') from error

        # FIXME: Add resource record with logs:
        # https://iipc.github.io/warc-specifications/guidelines/warc-implementation-guidelines/#use-of-resource-records-for-processing-information

    finally:
        print(f'Skipped {skipped.total()} Versionista versions:')
        for reason, count in skipped.items():
            print(f'  {reason.ljust(25, ".")} {str(count).rjust(5)}')
