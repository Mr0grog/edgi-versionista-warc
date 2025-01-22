# Make a WARC from Versionista Data in the EDGI WM DB

This is pretty much a one-off script to generate WARCs for permanent archival with our old data from Versionista. We don’t expect to need to run this again, but there may be a bunch of useful bits and bobs here for reference. The code here is not as nice or clean as it could be.

We use [uv][] to manage this project.

1. Setup:

    ```sh
    uv sync
    ```

2. Run script to output WARCs at paths like `archive/edgi-wm-versionista--2018-02-13T012233.warg.gz` (warnings and other logs will be written to `archive/log.txt`; you can tail that file to see live notices):

    ```sh
    uv run edgi-versionista-warc.py --limit 100 archive/
    ```

    Use `--help` to see options.


## Notes

WARC spec: https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1-annotated/

Implementation Guidelines: https://iipc.github.io/warc-specifications/guidelines/warc-implementation-guidelines/

`WARC-Record-ID`: warcio can invent one, but we’ve set custom ones based on our API and data structure (so they include the ID of version records, but are structured as a URN).

Remember to formulate multiple responses when `source_metadata.redirects` is populated. Last item is the actual URL we were redirected to. Also `source_metadata.redirect_url`.

Format a `metadata` record from the `source_metadata` field with additional info.

We have some FTP directories and files we monitored; those need a different kind of WARC record.

Need a lot of extra code to manage a set of WARC files so they don’t get too big. Unfortunately warcio doesn’t do this.

There were a lot of records with missing status codes (I expected this to be only 50k at most out of our 845k total, but it turns out to be more like 340k!), so this includes a port of [the algorithm that guesses the effective status code in web-monitoring-db](https://github.com/edgi-govdata-archiving/web-monitoring-db/blob/e5b6693102adc2fcec6c2b7fabe0d17c0c3ec4e7/app/models/version.rb#L203-L234).


## Questions

- Wayback CDX uses SHA-1 base32 hashes; should we use same for WARC-Block-Digest? *(Answer: yes; it's built-in to warcio and that's fine enough)*


[uv]: https://docs.astral.sh/uv/
