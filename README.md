# Make a WARC from Versionista Data in the EDGI WM DB

Use [Rye][] to manage this project.

1. Setup:

    ```sh
    rye sync
    ```

2. Run script:

    ```sh
    rye run python write_custom_warc.py
    ```


## Notes

WARC-Record-ID: warcio can invent one, but maybe make a custom one? Understand URN possibilities better.

Remember to formulate multiple responses when `source_metadata.redirects` is populated. Last item is the actual URL we were redirected to.

Format a `metadata` record from the `source_metadata` field. What goes in it?


## Questions

- Wayback CDX uses SHA-1 base32 hashes; should we use same for WARC-Block-Digest?
