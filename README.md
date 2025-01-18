# Make a WARC from Versionista Data in the EDGI WM DB

Use [uv][] to manage this project.

1. Setup:

    ```sh
    uv sync
    ```

2. Run script to output WARCs at paths like `out/archive-2018-02-13T012233.warg.gz`:

    ```sh
    uv run edgi-versionista-warc.py out/archive --limit 100
    ```

    Use `--help` to see options.


## Notes

WARC-Record-ID: warcio can invent one, but maybe make a custom one? Understand URN possibilities better.

Remember to formulate multiple responses when `source_metadata.redirects` is populated. Last item is the actual URL we were redirected to.

Format a `metadata` record from the `source_metadata` field. What goes in it?


## Questions

- Wayback CDX uses SHA-1 base32 hashes; should we use same for WARC-Block-Digest?


[uv]: https://docs.astral.sh/uv/
