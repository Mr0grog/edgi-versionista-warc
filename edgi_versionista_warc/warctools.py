from collections import Counter, OrderedDict
from http import HTTPStatus
import importlib.metadata
from io import BytesIO, BufferedWriter
import logging
from pathlib import Path
from typing import Self
from dateutil.parser import parse as parse_timestamp
from warcio import WARCWriter
from warcio.warcwriter import BufferWARCWriter
from warcio.recordbuilder import RecordBuilder
from warcio.recordloader import ArcWarcRecord


logger = logging.getLogger(__name__)


GIGABYTE = 1024 * 1024 * 1024

WARC_VERSION = '1.1'


def status_text(code):
    status = HTTPStatus(code)
    return f'{status.value} {status.phrase}'


# Based on warcio's implementation:
# https://github.com/webrecorder/warcio/blob/6775fb9ea3505db144a145c5a8b3ba1dfb822ac1/warcio/recordbuilder.py#L46-L52
# This is... not really up-to-spec, but generally good enough.
def serialize_warc_fields(fields_dict: dict) -> BytesIO:
    output = BytesIO()
    for name, value in fields_dict.items():
        if not value:
            continue

        line = f'{name}: {value}\r\n'
        output.write(line.encode('utf-8'))

    return output


def create_metadata_record(writer: RecordBuilder, uri: str, header: dict, data: dict) -> ArcWarcRecord:
    payload = serialize_warc_fields(data)
    length = payload.tell()
    payload.seek(0)
    return writer.create_warc_record(
        uri,
        'metadata',
        warc_headers_dict=header,
        payload=payload,
        length=length
    )


class WarcSeries:
    """
    Writes a series of WARC files, starting new files when the previous ones
    pass a target size.

    This doesn't use any complex methods for managing data like record
    segmentation. If you expect to encounter giant files that could put you
    problematically past some limit (e.g. >= 1 GB), you'll need something
    fancier.
    """

    def __init__(self, path, name='archive', gzip=True, size=8 * GIGABYTE, info=None, revisit_cache_size=10_000):
        self._file: BufferedWriter | None = None
        self._writer: WARCWriter | None = None
        self._created_names = Counter()
        self._revisit_cache = OrderedDict()
        self._revisit_cache_size = revisit_cache_size
        self.size: int = size
        self.gzip: bool = gzip
        self.warcinfo: dict = info or {}
        self.path: Path = Path(path)
        self.base_name: str = name

    def close(self):
        self._close_writer()

    def write_records(self, records):
        writer = self._writer
        if not writer:
            record_time = parse_timestamp(records[0].rec_headers.get_header('WARC-Date'))
            writer = self._create_writer(record_time.strftime('--%Y-%m-%dT%H%M%S'))

        for record in records:
            writer.write_record(record)

        if self._file and self._file.tell() > self.size:
            self._close_writer()

    def cache_revisitable_record(self, record, key):
        if len(self._revisit_cache) >= self._revisit_cache_size:
            self._revisit_cache.popitem()

        headers = record.rec_headers
        self._revisit_cache[key] = {
            'id': headers.get_header('WARC-Record-ID'),
            'warc_digest': headers.get_header('WARC-Payload-Digest'),
            'uri': headers.get_header('WARC-Target-URI'),
            'date': headers.get_header('WARC-Date'),
        }

    def get_revisit(self, key) -> dict | None:
        return self._revisit_cache.get(key)

    @property
    def builder(self) -> RecordBuilder:
        if self._writer:
            return self._writer
        else:
            return BufferWARCWriter(warc_version=WARC_VERSION)

    def _close_writer(self) -> None:
        self._revisit_cache.clear()
        self._writer = None
        if self._file:
            self._file.close()
            self._file = None

    def _create_writer(self, suffix='') -> WARCWriter:
        self._close_writer()

        base_name = self.base_name + suffix
        self._created_names[base_name] += 1
        if self._created_names[base_name] > 1:
            base_name += f'-{self._created_names[base_name]}'

        file_name = f'{base_name}.warc'
        if self.gzip:
            file_name += '.gz'

        logger.info(f'Creating WARC: "{self.path / file_name}"')
        self.path.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path / file_name, 'wb')
        self._writer = WARCWriter(self._file, gzip=self.gzip, warc_version=WARC_VERSION)

        self._writer.write_record(self._writer.create_warcinfo_record(file_name, {
            'software': f'warcio/{importlib.metadata.version("warcio")}',
            'format': f'WARC file version {WARC_VERSION}',
            **self.warcinfo
        }))

        return self._writer

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
