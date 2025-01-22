#!/usr/bin/env python
from argparse import ArgumentParser
from pathlib import Path
from datetime import datetime, timezone
import importlib.metadata
import sys
from warcio import WARCWriter
from edgi_versionista_warc.versionista_warc import format_datetime_iso
from edgi_versionista_warc.warctools import WARC_VERSION


def cli() -> None:
    parser = ArgumentParser(description="Create a WARC containing log file from the `edgi-versionista-warc` script")
    parser.add_argument('--uncompressed', action='store_true', help='Create uncompressed `.warc` files instead of gzipped `.warc.gz` files')
    parser.add_argument('path', help='Path to directory or log file to build WARC for')
    configuration = parser.parse_args()

    gzip = not configuration.uncompressed

    log_path = Path(configuration.path)
    if log_path.is_dir():
        log_path = log_path / 'log.txt'
    if not log_path.exists():
        print(f'No log file found at {log_path}')
        sys.exit(1)

    log_time = datetime.fromtimestamp(log_path.stat().st_ctime).astimezone(timezone.utc)
    warc_suffix = f'--{log_time.strftime('%Y-%m-%dT%H%M%S')}.warc'
    if gzip:
        warc_suffix += '.gz'

    warc_name = f'{log_path.stem}{warc_suffix}'
    warc_path = log_path.parent / f'{log_path.stem}{warc_suffix}'
    with warc_path.open('wb') as warcfile:
        warc = WARCWriter(warcfile, gzip=gzip, warc_version=WARC_VERSION)

        warc.write_record(warc.create_warcinfo_record(warc_name, {
            'software': f'warcio/{importlib.metadata.version("warcio")}',
            'format': f'WARC file version {WARC_VERSION}',
            'operator': '"Environmental Data & Governance Initiative" <contact@envirodatagov.org>',
            'description': (
                "Log file listing notices and warnings when generating WARCs of web content captured by EDGI's "
                'Web Monitoring project using Versionista (https://versionista.com).'
            )
        }))

        with log_path.open('rb') as logfile:
            warc.write_record(warc.create_warc_record(
                None,
                'resource',
                warc_headers_dict={
                    'WARC-Date': format_datetime_iso(log_time),
                    'Content-Type': 'text/plain'
                },
                payload=logfile
            ))

    print(f'Wrote WARC file to {warc_path}')


if __name__ == '__main__':
    cli()
