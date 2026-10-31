"""XTeink Helper: serves the CrossPoint PXC converter (static SPA) at "/", with the
OceanofPDFs watermark-remover as a tab inside the same page backed by a small
JSON API under "/remover/*"."""

import os
import shutil
import tempfile
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from main import process_epub

INGEST_DIR = Path(os.environ.get("INGEST_DIR", "/cwa-book-ingest"))
BOOKORBIT_LIBRARY_DIR = os.environ.get("BOOKORBIT_LIBRARY_DIR")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
HISTORY_LIMIT = 100
STATIC_DIR = Path(__file__).parent / "static"

MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# In-memory activity log, newest first. No DB — this is a single-container,
# no-auth homelab tool, so history doesn't need to survive a restart.
history: deque = deque(maxlen=HISTORY_LIMIT)


def unique_destination(directory: Path, filename: str) -> Path:
    dest = directory / filename
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    n = 1
    while True:
        candidate = directory / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def log(name: str, ok: bool, message: str) -> None:
    history.appendleft(
        {
            "name": name,
            "ok": ok,
            "message": message,
            "time": datetime.now().strftime("%b %d, %H:%M"),
        }
    )


@app.middleware("http")
async def upload_limit_and_isolation_headers(request: Request, call_next):
    # Reject oversized uploads up front from Content-Length (FastAPI has no
    # equivalent of Flask's MAX_CONTENT_LENGTH).
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
        response = JSONResponse({"error": "upload too large"}, status_code=413)
    else:
        response = await call_next(request)
    # CrossPoint's dither pipeline runs in a Web Worker over a SharedArrayBuffer,
    # which browsers only allow inside a cross-origin-isolated context.
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response


# --- OceanofPDFs watermark remover: JSON API consumed by the remover tab ---


@app.get("/remover")
def remover_redirect():
    return RedirectResponse("/#remover", status_code=302)


@app.get("/remover/history")
def remover_history():
    return {"history": list(history)}


# Plain (non-async) def so FastAPI runs the blocking EPUB processing in its threadpool.
@app.post("/remover/upload")
def remover_upload(book: Annotated[list[UploadFile] | None, File()] = None):
    files = [f for f in book or [] if f.filename]

    if not BOOKORBIT_LIBRARY_DIR:
        INGEST_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            name = Path(f.filename).name
            if not name.lower().endswith(".epub"):
                log(name, False, "not an .epub file, skipped")
                continue

            work_path = Path(tmp) / name
            with work_path.open("wb") as out:
                shutil.copyfileobj(f.file, out)

            try:
                _, hits = process_epub(work_path, dry_run=False)
            except zipfile.BadZipFile:
                log(name, False, "not a valid EPUB (bad zip)")
                continue
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the batch
                log(name, False, f"failed: {e}")
                continue

            if BOOKORBIT_LIBRARY_DIR:
                library_dir = Path(BOOKORBIT_LIBRARY_DIR)
                library_dir.mkdir(parents=True, exist_ok=True)
                dest = unique_destination(library_dir, name)
                queued_to = "BookOrbit import"
            else:
                dest = unique_destination(INGEST_DIR, name)
                queued_to = "Calibre import"
            shutil.move(str(work_path), dest)
            note = f"cleaned {hits} watermark hit(s)" if hits else "no watermarks found"
            log(name, True, f"{note} — queued for {queued_to}")

    return {"history": list(history)}


@app.get("/health")
def health():
    return {"status": "ok"}


# --- CrossPoint PXC converter: static SPA served from ./static (vite build output).
# The OceanofPDFs remover lives inside this same page as a tab (see removerTab.ts).
# Registered last: the catch-all would otherwise shadow the routes above. ---


@app.api_route("/{filename:path}", methods=["GET", "HEAD"])
def converter_static(filename: str):
    static_root = STATIC_DIR.resolve()
    file_path = (static_root / filename).resolve()
    if file_path.is_relative_to(static_root) and file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(static_root / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8085)
