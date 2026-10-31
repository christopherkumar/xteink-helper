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

from flask import Flask, jsonify, redirect, request, send_from_directory

from main import process_epub

INGEST_DIR = Path(os.environ.get("INGEST_DIR", "/cwa-book-ingest"))
BOOKORBIT_LIBRARY_DIR = os.environ.get("BOOKORBIT_LIBRARY_DIR")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
HISTORY_LIMIT = 100
STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

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
    history.appendleft({
        "name": name,
        "ok": ok,
        "message": message,
        "time": datetime.now().strftime("%b %d, %H:%M"),
    })


@app.after_request
def add_isolation_headers(response):
    # CrossPoint's dither pipeline runs in a Web Worker over a SharedArrayBuffer,
    # which browsers only allow inside a cross-origin-isolated context.
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response


# --- CrossPoint PXC converter: static SPA served from ./static (vite build output).
# The OceanofPDFs remover lives inside this same page as a tab (see removerTab.ts). ---

@app.route("/")
def converter_index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/assets/<path:filename>")
def converter_assets(filename):
    return send_from_directory(STATIC_DIR / "assets", filename)


@app.route("/<path:filename>")
def converter_static(filename):
    file_path = STATIC_DIR / filename
    if file_path.is_file():
        return send_from_directory(STATIC_DIR, filename)
    return converter_index()


# --- OceanofPDFs watermark remover: JSON API consumed by the remover tab ---

@app.route("/remover")
def remover_redirect():
    return redirect("/#remover")


@app.route("/remover/history")
def remover_history():
    return jsonify(history=list(history))


@app.route("/remover/upload", methods=["POST"])
def remover_upload():
    files = [f for f in request.files.getlist("book") if f.filename]

    if not BOOKORBIT_LIBRARY_DIR:
        INGEST_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            name = Path(f.filename).name
            if not name.lower().endswith(".epub"):
                log(name, False, "not an .epub file, skipped")
                continue

            work_path = Path(tmp) / name
            f.save(work_path)

            try:
                _, hits = process_epub(work_path, dry_run=False)
            except zipfile.BadZipFile:
                log(name, False, "not a valid EPUB (bad zip)")
                continue
            except Exception as e:
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

    return jsonify(history=list(history))


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8085)
