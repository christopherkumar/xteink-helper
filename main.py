"""Remove OceanofPDFs.com watermarks from PDF or EPUB files."""

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

URI_MATCH = "oceanofpdfs.com"
TEXT_PATTERN = re.compile(r"(?i)o\s*c\s*e\s*a\s*n\s*o\s*f\s*p\s*d\s*f\s*s?\s*\.\s*c\s*o\s*m")
ANCHOR_PATTERN = re.compile(
    r'<a\b[^>]*href="[^"]*oceanofpdfs\.com[^"]*"[^>]*>.*?</a>',
    re.IGNORECASE | re.DOTALL,
)
EPUB_TEXT_EXTENSIONS = {".xhtml", ".html", ".htm", ".opf", ".ncx"}


def preserve_times(path: Path, atime: float, mtime: float) -> None:
    try:
        os.utime(path, (atime, mtime))
    except OSError:
        pass


def process_pdf(pdf_path: Path, dry_run: bool) -> tuple[bool, int]:
    """Redact watermark text and strip watermark links from a PDF. Returns (changed, hits)."""
    hits = 0
    doc = pymupdf.open(pdf_path)
    try:
        for page in doc:
            for link in page.get_links():
                uri = link.get("uri", "")
                if uri and URI_MATCH in uri.lower():
                    page.delete_link(link)
                    hits += 1

            text = page.get_text("text")
            if not text or not TEXT_PATTERN.search(text):
                continue

            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        span_text = span.get("text", "")
                        if span_text and TEXT_PATTERN.search(span_text):
                            page.add_redact_annot(pymupdf.Rect(span["bbox"]), fill=(1, 1, 1))
                            hits += 1
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

        if hits == 0 or dry_run:
            return hits > 0, hits

        stat = pdf_path.stat()
        temp_path = pdf_path.with_suffix(pdf_path.suffix + ".tmp")
        doc.save(temp_path, garbage=4, deflate=True, clean=True)
        doc.close()
        shutil.move(temp_path, pdf_path)
        preserve_times(pdf_path, stat.st_atime, stat.st_mtime)
        return True, hits
    finally:
        if not doc.is_closed:
            doc.close()


def process_epub(epub_path: Path, dry_run: bool) -> tuple[bool, int]:
    """Strip watermark links and text from an EPUB's HTML/XHTML content. Returns (changed, hits)."""
    hits = 0
    changed_entries: dict[str, bytes] = {}

    with zipfile.ZipFile(epub_path, "r") as zin:
        for info in zin.infolist():
            if Path(info.filename).suffix.lower() not in EPUB_TEXT_EXTENSIONS:
                continue

            raw = zin.read(info.filename)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue

            new_text, anchor_hits = ANCHOR_PATTERN.subn("", text)
            new_text, text_hits = TEXT_PATTERN.subn("", new_text)
            entry_hits = anchor_hits + text_hits

            if entry_hits:
                hits += entry_hits
                changed_entries[info.filename] = new_text.encode("utf-8")

    if hits == 0 or dry_run:
        return hits > 0, hits

    stat = epub_path.stat()
    temp_path = epub_path.with_suffix(epub_path.suffix + ".tmp")

    with zipfile.ZipFile(epub_path, "r") as zin, zipfile.ZipFile(
        temp_path, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = changed_entries.get(info.filename, zin.read(info.filename))
            zout.writestr(info, data)

    shutil.move(temp_path, epub_path)
    preserve_times(epub_path, stat.st_atime, stat.st_mtime)
    return True, hits


def collect_files(target: Path, extension: str) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() == extension else []
    return sorted(p for p in target.rglob(f"*{extension}") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove OceanofPDFs.com watermarks from PDF or EPUB files."
    )
    fmt_group = parser.add_mutually_exclusive_group(required=True)
    fmt_group.add_argument("--pdf", action="store_true", help="Process PDF files")
    fmt_group.add_argument("--epub", action="store_true", help="Process EPUB files")
    parser.add_argument("path", type=Path, help="File or directory to process")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without modifying files"
    )
    args = parser.parse_args()

    target = args.path.expanduser()
    if not target.exists():
        print(f"Error: path not found: {target}", file=sys.stderr)
        return 1

    if args.pdf:
        extension, processor = ".pdf", process_pdf
    else:
        extension, processor = ".epub", process_epub

    files = collect_files(target, extension)
    if not files:
        print(f"No {extension} files found at {target}")
        return 0

    cleaned = failed = 0
    for file_path in files:
        try:
            changed, hits = processor(file_path, args.dry_run)
        except Exception as e:
            failed += 1
            print(f"FAILED: {file_path} | {e}")
            continue

        if changed:
            cleaned += 1
            verb = "Would clean" if args.dry_run else "Cleaned"
            print(f"{verb}: {file_path} (hits={hits})")

    label = "DRY RUN" if args.dry_run else "DONE"
    print(f"\n{label}: {len(files)} scanned | {cleaned} cleaned | {failed} failed")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
