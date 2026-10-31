# XTeink Helper

One container, two tools for the XTeink e-reader / Calibre workflow:

- **`/`** — [CrossPoint PXC converter](https://github.com/zgredex/crosspoint-pxc-converter): turns images and Game Boy captures into `.pxc`/`.bmp` sleep-screen wallpapers. X3 (528×792) is the default device.
- **`/remover`** — OceanofPDFs watermark remover: drop in `.epub` files, watermarks get stripped, cleaned files are queued into Calibre-Web-Automated's ingest folder and (if `BOOKORBIT_LIBRARY_DIR` is set) copied straight into BookOrbit's epubs library folder too.

Replaces the standalone `oceanofpdfs-remover` container.

## Build & run

```bash
docker compose up -d --build
```

The frontend is built from `../crosspoint-pxc-converter` at image-build time (wired in as
the `frontend-src` additional build context in `docker-compose.yml`) — its source isn't
duplicated here, so pulling upstream changes into that sibling directory and rebuilding
picks them up automatically.

Runs on port `8085`. Configure via environment variables in `docker-compose.yml`:

- `INGEST_DIR` — path inside the container to drop cleaned EPUBs (default
  `/cwa-book-ingest`, mounted from the host's CWA ingest folder)
- `BOOKORBIT_LIBRARY_DIR` — optional; path inside the container to also copy
  cleaned EPUBs, mounted from BookOrbit's epubs library folder
  (`~/bookorbit/books/epubs` — the same folder BookOrbit's library scanner/
  watcher covers, so no manual Book Dock review step). Unset skips the
  BookOrbit copy.
- `MAX_UPLOAD_MB` — max EPUB upload size (default `500`)

No authentication — intended to run on a private/Tailscale-only network.

## Why one container

Both tools are small, low-traffic, no-auth homelab utilities used together (convert a
wallpaper, clean a book) — one FastAPI (uvicorn) process serving a static SPA plus one upload route
is simpler to run and monitor than two.
