from argparse import ArgumentParser
import logging
from pathlib import Path
from dateutil.parser import parse as parse_timestamp
from .versionista_warc import main
from .warctools import GIGABYTE


def cli() -> None:
    parser = ArgumentParser(description="Create WARC files to store captures of Versionista data from EDGI's Web Monitoring Database")
    parser.add_argument('--uncompressed', action='store_true', help='Create uncompressed `.warc` files instead of gzipped `.warc.gz` files')
    parser.add_argument('--limit', type=int, help='Archive up to this many records from Web Monitoring DB')
    parser.add_argument('--size', type=float, default=7.95, help='Generate WARC up to about this many gigabytes each')
    parser.add_argument('--from', type=parse_timestamp, help='Start from this timestamp (ISO format)')
    parser.add_argument('path', help=(
        'Path to generate WARC files at. If the path is `out/archive`, WARC files will be built at paths like'
        '`out/archive-YYYY-MM-DDThhmmss.warc.gz`'
    ))
    configuration = parser.parse_args()

    path = Path(configuration.path)
    if path.is_dir():
        path = path
        name = 'edgi-wm-versionista'
    else:
        path = path.parent
        name = path.name

    path.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(path / 'log.txt'), level=logging.WARNING)
    logging.getLogger(__name__.split('.')[0]).setLevel(logging.INFO)

    main(
        path=str(path),
        name=name,
        gzip=(not configuration.uncompressed),
        limit=configuration.limit,
        warc_size=int(configuration.size * GIGABYTE),
        start_date=getattr(configuration, 'from')
    )


if __name__ == '__main__':
    cli()
