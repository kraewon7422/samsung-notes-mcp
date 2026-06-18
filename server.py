#!/usr/bin/env python3
"""Samsung Notes MCP Server — local, read-only.

Reads the Samsung Notes for Windows database directly:
  %LOCALAPPDATA%\\Packages\\SAMSUNGELECTRONICSCoLtd.SamsungNotes_*\\LocalState

Notes written on a Galaxy phone/tablet arrive here automatically via
Samsung Cloud sync, so this server sees those too. No cloud API, no auth.

Strictly read-only: Storage.sqlite is snapshotted to a temp copy before
every read, so the live database is never opened or locked, and note
files are never modified.

Known limitation: page images in the wdoc folders are the imported PDF /
photo backgrounds. Your own pen strokes are stored separately in a binary
format and only appear rendered in the note's first-page thumbnail
(samsung_notes_get_thumbnail).
"""

import json
import os
import re
import shutil
import sqlite3
import tempfile
from io import BytesIO
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

APP_PACKAGE_GLOB = "SAMSUNGELECTRONICSCoLtd.SamsungNotes_*"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

mcp = FastMCP("samsung_notes")

# ──────────────────────────────────────────────
# Database access (snapshot, never the live file)
# ──────────────────────────────────────────────

def _local_state_dir() -> Path:
    packages = Path(os.environ["LOCALAPPDATA"]) / "Packages"
    matches = sorted(packages.glob(APP_PACKAGE_GLOB))
    if not matches:
        raise RuntimeError(
            "Samsung Notes for Windows not found under %LOCALAPPDATA%\\Packages. "
            "Install it from the Microsoft Store and sign in with your Samsung account."
        )
    return matches[0] / "LocalState"


# Per-process snapshot: Claude Desktop, Claude Code and the HTTP server may
# run this module simultaneously — sharing one snapshot file would let one
# process overwrite it mid-read in another.
_SNAPSHOT = Path(tempfile.gettempdir()) / f"samsung_notes_mcp_snapshot_{os.getpid()}.sqlite"
_snapshot_stamp: float = -1.0


def _cleanup_stale_snapshots() -> None:
    """Delete snapshots left by dead processes (live ones are file-locked
    on Windows and simply refuse deletion)."""
    for p in Path(tempfile.gettempdir()).glob("samsung_notes_mcp_snapshot_*.sqlite*"):
        if not p.name.startswith(_SNAPSHOT.name):
            try:
                p.unlink()
            except OSError:
                pass


_cleanup_stale_snapshots()


def _connect() -> sqlite3.Connection:
    """Open a connection to a temp snapshot of Storage.sqlite.

    The live DB (plus its -wal/-shm journals) is copied first, so the
    Samsung Notes app never sees a lock from us. The copy is refreshed
    only when the source has changed.
    """
    global _snapshot_stamp
    src = _local_state_dir() / "Storage.sqlite"
    if not src.exists():
        raise RuntimeError(f"Database not found: {src}")

    stamp = max(
        p.stat().st_mtime
        for p in (src, src.with_suffix(".sqlite-wal"), src.with_suffix(".sqlite-shm"))
        if p.exists()
    )
    if stamp != _snapshot_stamp or not _SNAPSHOT.exists():
        for suffix in ("", "-wal", "-shm"):
            s = Path(str(src) + suffix)
            d = Path(str(_SNAPSHOT) + suffix)
            if s.exists():
                shutil.copy2(s, d)
            elif d.exists():
                d.unlink()
        _snapshot_stamp = stamp

    con = sqlite3.connect(_SNAPSHOT)
    con.row_factory = sqlite3.Row
    return con


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")


def _clean(s: str | None) -> str:
    """Strip zero-width characters Samsung Notes embeds in names."""
    return _INVISIBLE.sub("", s or "").strip()


def _like(s: str) -> str:
    """Escape SQL LIKE wildcards in user input (use with ESCAPE '\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _date(ms: int | None) -> str:
    if not ms:
        return ""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _folder_names(con: sqlite3.Connection) -> dict[str, str]:
    """Map folder UUID -> full path like 'Parent/Child'."""
    rows = con.execute(
        "select UUID, ParentUUID, DisplayName from CategoryTreeDB where IsDeleted=0"
    ).fetchall()
    by_uuid = {r["UUID"]: (r["ParentUUID"], _clean(r["DisplayName"]) or "(unnamed)") for r in rows}

    def path(uuid: str, depth: int = 0) -> str:
        if uuid not in by_uuid or depth > 10:
            return ""
        parent, name = by_uuid[uuid]
        parent_path = path(parent, depth + 1) if parent in by_uuid else ""
        return f"{parent_path}/{name}" if parent_path else name

    return {uuid: path(uuid) for uuid in by_uuid}


def _resolve_note(con: sqlite3.Connection, note_id: str) -> sqlite3.Row:
    """Find a note by UUID, or by unique title substring as a fallback."""
    row = con.execute(
        "select * from NoteDB where UUID=? and DeletedStatus=0", (note_id,)
    ).fetchone()
    if row:
        return row
    rows = con.execute(
        "select * from NoteDB where DeletedStatus=0 and Title like ? escape '\\' "
        "order by LastModifiedAt desc",
        (f"%{_like(note_id)}%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise ValueError(f"No note found with UUID or title matching {note_id!r}.")
    titles = [f"{r['Title']} (id={r['UUID']})" for r in rows[:10]]
    raise ValueError(
        f"Title {note_id!r} matches {len(rows)} notes — pass the UUID instead:\n" + "\n".join(titles)
    )


_PAGE_PREFIX = re.compile(r"^(\d+)@")


def _note_images(note_dir: Path) -> list[Path]:
    """Page/media images inside a note's wdoc folder, in page order.

    Files are named '<index>@files_<timestamp>.jpg'; the numeric prefix is
    the page order. Older notes keep media at the top level, newer ones in
    a 'media' subfolder.
    """
    if not note_dir.is_dir():
        return []
    candidates = list(note_dir.iterdir())
    media = note_dir / "media"
    if media.is_dir():
        candidates += list(media.iterdir())
    imgs = [p for p in candidates if p.suffix.lower() in IMAGE_EXTS]

    def order(p: Path) -> tuple[int, str]:
        m = _PAGE_PREFIX.match(p.name)
        return (int(m.group(1)) if m else 10**9, p.name)

    return sorted(imgs, key=order)


def _ordered_page_uuids(con: sqlite3.Connection, document_uuid: str) -> list[str]:
    """Page UUIDs of a note in true page order.

    PageDB.documentUUID groups a note's pages; the literal `index` column is
    unused (always 0), but ascending `_id` matches Samsung's own page order
    file (pageIdInfo.dat), so we order by that. Deleted pages are skipped.
    """
    return [
        row["UUID"]
        for row in con.execute(
            'select UUID from PageDB where documentUUID=? and isDeleted=0 order by _id',
            (document_uuid,),
        ).fetchall()
    ]


def _page_render_path(note_uuid: str, page_uuid: str) -> Path | None:
    """The app-rendered image (handwriting included) for a single page, if cached.

    Samsung Notes renders each page a user opens/scrolls in the Windows app to
    Thumbnail\\<note-uuid>\\<n>\\<page-uuid>.jpeg (the <n> sub-tier is '0' in
    practice; we glob it for safety). Pages never viewed on this PC have no such
    file. When several tiers exist, the largest file is the best-resolution one.
    """
    base = _local_state_dir() / "Thumbnail" / note_uuid
    if not base.is_dir():
        return None
    hits = [p for p in base.glob(f"*/{page_uuid}.jpeg") if p.is_file()]
    hits += [p for p in base.glob(f"{page_uuid}.jpeg") if p.is_file()]
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_size)


def _resolve_page_render(con: sqlite3.Connection, r: sqlite3.Row, page: int) -> Path | None:
    """Path to the rendered handwriting image for 0-based `page`, or None if that
    page has not been rendered by the app yet. Page 0 falls back to the note's
    high-res first-page thumbnail. Raises ValueError if `page` is out of range."""
    pages = _ordered_page_uuids(con, r["UUID"])
    thumb = r["ThumbnailPath"]
    if not pages:
        # Older single-page notes have no PageDB rows; treat as one page.
        if page == 0 and thumb and Path(thumb).exists():
            return Path(thumb)
        if page == 0:
            return None
        raise ValueError(f"Note {r['Title']!r} has 1 page (page must be 0).")
    if not 0 <= page < len(pages):
        raise ValueError(f"page must be 0..{len(pages) - 1} (note has {len(pages)} pages).")
    rendered = _page_render_path(r["UUID"], pages[page])
    if rendered:
        return rendered
    if page == 0 and thumb and Path(thumb).exists():
        return Path(thumb)
    return None


def _note_pdfs(note_dir: Path) -> list[Path]:
    """Original PDF files imported into a note (stored under media/)."""
    if not note_dir.is_dir():
        return []
    candidates = list(note_dir.iterdir())
    media = note_dir / "media"
    if media.is_dir():
        candidates += list(media.iterdir())
    return sorted(p for p in candidates if p.suffix.lower() == ".pdf")


def _scaled_jpeg(path: Path, max_width: int) -> Image:
    img = PILImage.open(path)
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return Image(data=buf.getvalue(), format="jpeg")


_TEXT_LIMIT = 20_000  # chars per field; imported-PDF text can reach megabytes


def _texts(row: sqlite3.Row) -> dict:
    """All readable text a note carries, by source (truncated if huge)."""
    out = {}
    for key, col in [
        ("typed_text", "StrippedContent"),
        ("pdf_text", "PDFTextContents"),
        ("textbox_text", "InsertedTextboxContents"),
        ("handwriting_text", "StrokeTextContents"),
    ]:
        v = (row[col] or "").strip()
        if v.strip("/ \n\r\t"):
            if len(v) > _TEXT_LIMIT:
                v = v[:_TEXT_LIMIT] + f"\n…[truncated — {len(v):,} chars total]"
            out[key] = v
    return out


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_list_folders() -> str:
    """List all Samsung Notes folders with their note counts."""
    con = _connect()
    try:
        names = _folder_names(con)
        counts = dict(
            con.execute(
                "select CategoryUUID, count(*) from NoteDB where DeletedStatus=0 group by CategoryUUID"
            ).fetchall()
        )
        folders = sorted(
            ({"folder": path, "uuid": uuid, "notes": counts.get(uuid, 0)} for uuid, path in names.items()),
            key=lambda f: f["folder"].lower(),
        )
        return _json({"folder_count": len(folders), "folders": folders})
    finally:
        con.close()


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_list_notes(folder: str = "", top: int = 50) -> str:
    """List notes, newest first.

    Args:
        folder: folder name (e.g. "수학") or folder UUID; empty = all folders
        top: max results (default 50, max 200)
    """
    top = max(1, min(top, 200))
    con = _connect()
    try:
        names = _folder_names(con)
        where, params = "DeletedStatus=0", []
        if folder:
            matches = [u for u, p in names.items() if folder == u or folder.lower() in p.lower()]
            if not matches:
                return _json({"error": f"No folder matching {folder!r}", "available": sorted(names.values())})
            where += f" and CategoryUUID in ({','.join('?' * len(matches))})"
            params += matches
        rows = con.execute(
            f"""select UUID, Title, CategoryUUID, CreatedAt, LastModifiedAt, IsFavorite, IsLocked
                from NoteDB where {where} order by LastModifiedAt desc limit ?""",
            params + [top],
        ).fetchall()
        notes = [
            {
                "id": r["UUID"],
                "title": _clean(r["Title"]) or "(untitled)",
                "folder": names.get(r["CategoryUUID"], ""),
                "modified": _date(r["LastModifiedAt"]),
                **({"favorite": True} if r["IsFavorite"] else {}),
                **({"locked": True} if r["IsLocked"] else {}),
            }
            for r in rows
        ]
        return _json({"note_count": len(notes), "notes": notes})
    finally:
        con.close()


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_recent(top: int = 10) -> str:
    """List the most recently modified notes.

    Args:
        top: max results (default 10, max 50)
    """
    return samsung_notes_list_notes("", max(1, min(top, 50)))


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_read_note(note_id: str) -> str:
    """Read a note: metadata plus all extractable text (typed text, text of
    imported PDFs, text boxes). For handwritten content use
    samsung_notes_get_thumbnail / samsung_notes_get_page_image.

    Args:
        note_id: note UUID (from list/search tools) or a unique title substring
    """
    con = _connect()
    try:
        r = _resolve_note(con, note_id)
        names = _folder_names(con)
        images = _note_images(Path(r["FilePath"])) if r["FilePath"] else []
        result = {
            "id": r["UUID"],
            "title": _clean(r["Title"]) or "(untitled)",
            "folder": names.get(r["CategoryUUID"], ""),
            "created": _date(r["CreatedAt"]),
            "modified": _date(r["LastModifiedAt"]),
            "page_image_count": len(images),
            **_texts(r),
        }
        if r["IsLocked"]:
            result["locked"] = True
        result["hint"] = (
            "For handwritten pages use samsung_notes_list_pages / "
            "samsung_notes_get_page (rendered WITH pen strokes, all pages). "
            "samsung_notes_get_page_image / samsung_notes_list_note_images return "
            "only imported PDF/photo backgrounds without strokes."
        )
        return _json(result)
    finally:
        con.close()


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_search(query: str, top: int = 20) -> str:
    """Search all notes by keyword across titles, typed text, PDF text and
    text boxes.

    Args:
        query: keyword to search for (e.g. "다항식", "회의록")
        top: max results (default 20, max 50)
    """
    top = max(1, min(top, 50))
    con = _connect()
    try:
        names = _folder_names(con)
        like = f"%{_like(query)}%"
        rows = con.execute(
            """select UUID, Title, CategoryUUID, LastModifiedAt,
                      (coalesce(StrippedContent,'') || ' ' || coalesce(PDFTextContents,'')
                       || ' ' || coalesce(InsertedTextboxContents,'')) as alltext
               from NoteDB
               where DeletedStatus=0 and (Title like ? escape '\\' or StrippedContent like ? escape '\\'
                     or PDFTextContents like ? escape '\\' or InsertedTextboxContents like ? escape '\\')
               order by LastModifiedAt desc limit ?""",
            (like, like, like, like, top),
        ).fetchall()
        results = []
        for r in rows:
            item = {
                "id": r["UUID"],
                "title": _clean(r["Title"]) or "(untitled)",
                "folder": names.get(r["CategoryUUID"], ""),
                "modified": _date(r["LastModifiedAt"]),
            }
            text = r["alltext"]
            pos = text.lower().find(query.lower())
            if pos >= 0:
                item["match"] = "…" + text[max(0, pos - 40) : pos + 60].replace("\n", " ") + "…"
            results.append(item)
        return _json({"query": query, "result_count": len(results), "results": results})
    finally:
        con.close()


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_list_note_images(note_id: str) -> str:
    """List a note's page/media image files (paths on disk, page order).

    Args:
        note_id: note UUID or a unique title substring
    """
    con = _connect()
    try:
        r = _resolve_note(con, note_id)
        note_dir = Path(r["FilePath"]) if r["FilePath"] else None
        images = _note_images(note_dir) if note_dir else []
        pdfs = _note_pdfs(note_dir) if note_dir else []
        return _json(
            {
                "id": r["UUID"],
                "title": _clean(r["Title"]) or "(untitled)",
                "image_count": len(images),
                "images": [
                    {"page": i, "file": str(p), "size_kb": round(p.stat().st_size / 1024)}
                    for i, p in enumerate(images)
                ],
                "imported_pdfs": [str(p) for p in pdfs],
                "note": "These are imported PDF/photo backgrounds; pen strokes are not "
                        "rendered into them. For handwritten pages (all pages, with "
                        "strokes) use samsung_notes_list_pages / samsung_notes_get_page.",
            }
        )
    finally:
        con.close()


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_get_page_image(note_id: str, page: int = 0, max_width: int = 1024) -> Image:
    """Return one page/media image of a note, downscaled for viewing.

    Args:
        note_id: note UUID or a unique title substring
        page: 0-based page index (see samsung_notes_list_note_images)
        max_width: downscale to this width in px (default 1024)
    """
    con = _connect()
    try:
        r = _resolve_note(con, note_id)
    finally:
        con.close()
    images = _note_images(Path(r["FilePath"])) if r["FilePath"] else []
    if not images:
        raise ValueError(f"Note {r['Title']!r} has no page images.")
    if not 0 <= page < len(images):
        raise ValueError(f"page must be 0..{len(images) - 1} (note has {len(images)} images).")
    return _scaled_jpeg(images[page], max(64, min(max_width, 2048)))


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_get_thumbnail(note_id: str, max_width: int = 1024) -> Image:
    """Return the note's first-page thumbnail as rendered by the app —
    this includes pen strokes / handwriting.

    Args:
        note_id: note UUID or a unique title substring
        max_width: downscale to this width in px (default 1024)
    """
    con = _connect()
    try:
        r = _resolve_note(con, note_id)
    finally:
        con.close()
    path = r["ThumbnailPath"]
    if not path or not Path(path).exists():
        raise ValueError(f"Note {r['Title']!r} has no rendered thumbnail.")
    return _scaled_jpeg(Path(path), max(64, min(max_width, 2048)))


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_list_pages(note_id: str) -> str:
    """List a note's pages in order and whether each one's handwriting image is
    available right now.

    Unlike the imported backgrounds from samsung_notes_list_note_images, these
    are the app's per-page renders WITH your pen strokes. The catch: Samsung
    Notes only creates a page's render after you open that note and scroll past
    the page in the Samsung Notes Windows app. Pages you have never viewed on
    this PC show available=false until you do.

    Use samsung_notes_get_page(note_id, page) to fetch an available page.

    Args:
        note_id: note UUID or a unique title substring
    """
    con = _connect()
    try:
        r = _resolve_note(con, note_id)
        names = _folder_names(con)
        page_uuids = _ordered_page_uuids(con, r["UUID"])
        if not page_uuids:
            # Single-page note with no PageDB rows: the first-page thumbnail is it.
            has_thumb = bool(r["ThumbnailPath"] and Path(r["ThumbnailPath"]).exists())
            pages = [{"page": 0, "available": has_thumb}]
        else:
            pages = [
                {"page": i, "available": _page_render_path(r["UUID"], pu) is not None}
                for i, pu in enumerate(page_uuids)
            ]
            # Page 0 always falls back to the high-res first-page thumbnail.
            if pages and not pages[0]["available"] and r["ThumbnailPath"] and Path(r["ThumbnailPath"]).exists():
                pages[0]["available"] = True
        available = sum(p["available"] for p in pages)
        result = {
            "id": r["UUID"],
            "title": _clean(r["Title"]) or "(untitled)",
            "folder": names.get(r["CategoryUUID"], ""),
            "page_count": len(pages),
            "handwriting_images_available": available,
            "pages": pages,
        }
        if available < len(pages):
            result["hint"] = (
                f"{len(pages) - available} page(s) are not rendered yet. Open this "
                "note in Samsung Notes on Windows and scroll through every page "
                "once, then they become available. Then use "
                "samsung_notes_get_page(note_id, page)."
            )
        else:
            result["hint"] = "Use samsung_notes_get_page(note_id, page) to view any page."
        return _json(result)
    finally:
        con.close()


@mcp.tool(annotations={"readOnlyHint": True})
def samsung_notes_get_page(note_id: str, page: int = 0, max_width: int = 1024) -> Image:
    """Return one page of a note as rendered by the app, INCLUDING handwriting /
    pen strokes — the way to read handwritten pages beyond the first.

    Page order matches samsung_notes_list_pages. A page is only available after
    it has been opened/scrolled in the Samsung Notes Windows app; if it has not
    been rendered yet this raises an error telling you to do that. Page 0 falls
    back to the note's first-page thumbnail.

    Note: these per-page renders are modest resolution (~286 px wide) — that is
    all Samsung caches — so max_width only downscales, never upscales.

    Args:
        note_id: note UUID or a unique title substring
        page: 0-based page index (see samsung_notes_list_pages)
        max_width: downscale to this width in px (default 1024)
    """
    con = _connect()
    try:
        r = _resolve_note(con, note_id)
        path = _resolve_page_render(con, r, page)
    finally:
        con.close()
    if path is None:
        raise ValueError(
            f"Page {page} of {r['Title']!r} has not been rendered yet. Open this "
            "note in Samsung Notes on Windows and scroll through to that page "
            "once, then try again. (samsung_notes_list_pages shows which pages "
            "are ready.)"
        )
    return _scaled_jpeg(path, max(64, min(max_width, 2048)))


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Samsung Notes MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve over streamable HTTP for remote access (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8788, help="HTTP port (default 8788)")
    args = parser.parse_args()

    if args.http:
        # Under pythonw (no console, e.g. the auto-start scheduled task)
        # stdout/stderr are None — route them to a log file instead.
        if sys.stdout is None or sys.stderr is None:
            _log = open(
                Path(__file__).resolve().parent / "server.log",
                "a", encoding="utf-8", buffering=1,
            )
            sys.stdout = sys.stdout or _log
            sys.stderr = sys.stderr or _log

        # The URL path contains a long random secret: it is the access
        # control for remote use. Generated once, kept out of git.
        secret_file = Path(__file__).resolve().parent / "http_secret.txt"
        if not secret_file.exists():
            import secrets

            secret_file.write_text(secrets.token_urlsafe(48), encoding="ascii")
        secret = secret_file.read_text(encoding="ascii").strip()

        mcp.settings.host = "127.0.0.1"  # only the tunnel can reach it
        mcp.settings.port = args.port
        mcp.settings.streamable_http_path = f"/{secret}/mcp"
        mcp.settings.stateless_http = True

        # Allow requests arriving via the Tailscale Funnel hostname
        # (the SDK's DNS-rebinding protection otherwise rejects them, 421).
        import subprocess
        import time

        from mcp.server.transport_security import TransportSecuritySettings

        # Allow requests arriving via this PC's Tailscale Funnel hostname; the
        # SDK's DNS-rebinding protection otherwise rejects them with 421. The
        # hostname is discovered from `tailscale status` below, with retries for
        # a Tailscale that is slow to start at logon. If you still hit a
        # persistent 421 (Tailscale never ready in time), hardcode your own
        # Funnel host here too, e.g.:
        #   allowed = ["127.0.0.1:*", "localhost:*",
        #              "myhost.tailXXXX.ts.net", "myhost.tailXXXX.ts.net:*"]
        allowed = ["127.0.0.1:*", "localhost:*"]
        tailscale = r"C:\Program Files\Tailscale\tailscale.exe"
        if not Path(tailscale).exists():
            tailscale = shutil.which("tailscale") or tailscale
        # The scheduled task starts at logon, often before Tailscale is ready, so
        # `status --json` returns no DNSName, the Funnel hostname never gets added
        # to allowed_hosts, and every remote request is rejected with 421 until a
        # manual restart. Retry for ~30s until the name appears instead of giving
        # up on the first attempt.
        dns_name = None
        for attempt in range(10):
            try:
                status = json.loads(
                    subprocess.run(
                        [tailscale, "status", "--json"],
                        capture_output=True, timeout=15,
                        # explicit utf-8: Korean Windows would otherwise decode as cp949
                        encoding="utf-8", errors="replace",
                    ).stdout
                )
                dns_name = (status.get("Self") or {}).get("DNSName", "").rstrip(".")
            except Exception as e:
                print(f"warning: Tailscale status failed ({e})", file=sys.stderr, flush=True)
                dns_name = None
            if dns_name:
                allowed += [dns_name, f"{dns_name}:*"]
                print(f"Tailscale DNS name allowed: {dns_name}", file=sys.stderr, flush=True)
                break
            print(
                f"Tailscale not ready (attempt {attempt + 1}/10); retrying in 3s...",
                file=sys.stderr, flush=True,
            )
            time.sleep(3)
        else:
            print(
                "warning: gave up waiting for Tailscale DNS name; remote Funnel "
                "access will be rejected (421) until the task is restarted",
                file=sys.stderr, flush=True,
            )
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed
        )
        print(
            f"Serving on http://127.0.0.1:{args.port}/{secret}/mcp",
            file=sys.stderr,
            flush=True,
        )
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
