# Samsung Notes MCP

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)
![Read-only](https://img.shields.io/badge/access-read--only-success)

**Give Claude read access to your Samsung Notes — typed text, PDFs, voice memos, and your actual handwriting.**

Samsung Notes has no public API, and the old OneNote/Microsoft Graph sync route is gone.
This [MCP](https://modelcontextprotocol.io) server reads the local database of the
**Samsung Notes for Windows** app instead, so anything that syncs to your PC — including
notes you wrote with an S Pen on a Galaxy tablet or phone — becomes something Claude can
search, read, and *look at*.

> **You:** "Open my physics note and check my working on page 5."
> **Claude:** *renders page 5 from your pen strokes, reads the equations, and points out where the sign flipped.*

- 🔒 **Local & private** — no cloud service, no account, no telemetry. The server only talks to the Claude client on your machine.
- 🛡️ **Read-only by design** — the note database is snapshot-copied before every read; Samsung's files are never opened for writing.
- ✍️ **Handwriting included** — every page is redrawn from its stroke data at up to 2048 px, even pages you've never opened on the PC.
- 🔌 **Works with** Claude Desktop, Claude Code, and (optionally) claude.ai on the web or a tablet.

---

## Contents

- [Quick start](#quick-start)
- [Manual install (for developers)](#manual-install-for-developers)
- [What you can ask](#what-you-can-ask)
- [Tools](#tools)
- [How it works](#how-it-works)
- [Remote access (claude.ai web / tablet)](#remote-access-claudeai-web--tablet)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [Credits](#credits)
- [License](#license)

---

## Quick start

**You need:**

| Requirement | Why |
|---|---|
| Windows 10 or 11 | Samsung Notes for PC only exists on Windows |
| [Samsung Notes](https://apps.microsoft.com/search?query=samsung+notes) from the Microsoft Store, signed in, notes synced | It's the data source |
| [Claude Desktop or Claude Code](https://claude.ai/download) | The client that calls the tools |
| Python 3.10+ | The installer installs it for you if missing |
| Node.js 18+ *(recommended)* | Draws handwritten pages — `winget install OpenJS.NodeJS.LTS` |

**Then:**

1. Download this repo (**Code → Download ZIP**, or `git clone`) and unzip it somewhere permanent.
2. Double-click **`install.bat`**. *(SmartScreen warning? → **More info → Run anyway**.)*
3. Wait for **"Setup complete"**, then restart Claude Desktop / open a new Claude Code session.
4. Ask Claude: *"Show my Samsung Notes folders."*

The installer creates a project-local `.venv`, installs the Python packages, runs
`npm install` for the renderer (if Node.js is present), checks that it can see your notes,
and registers the server as `samsung-notes` in both Claude Desktop and Claude Code.
Your existing Claude Desktop config is backed up first.

## Manual install (for developers)

Prefer to see every step? This is all `install.bat` does:

```powershell
git clone https://github.com/kraewon7422/samsung-notes-mcp.git
cd samsung-notes-mcp

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp[cli]<2" pillow av pymupdf

# optional, but needed for full handwriting rendering
cd render; npm install; cd ..

# smoke test — should print your folder count
.\.venv\Scripts\python.exe -c "import server, json; print(json.loads(server.samsung_notes_list_folders())['folder_count'])"
```

> `mcp<2` is pinned on purpose: the server uses the v1 `FastMCP` API, which mcp 2.x renamed.

**Register with Claude Code:**

```powershell
claude mcp add --scope user samsung-notes -- "$PWD\.venv\Scripts\python.exe" "$PWD\server.py"
```

**Register with Claude Desktop** — add this to `%APPDATA%\Claude\claude_desktop_config.json`
(use your own absolute paths, with doubled backslashes):

```json
{
  "mcpServers": {
    "samsung-notes": {
      "command": "C:\\path\\to\\samsung-notes-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\samsung-notes-mcp\\server.py"]
    }
  }
}
```

Any other MCP client works the same way: it's a standard stdio server.

## What you can ask

You never call tools by name — just talk to Claude.

| Goal | Try saying |
|---|---|
| Browse | "What folders do I have in Samsung Notes?" · "List the notes in my Math folder" |
| Catch up | "What did I edit this week?" |
| Find | "Search my notes for *photosynthesis*" |
| Read | "Read my *Project kickoff* note and summarise the action items" |
| See handwriting | "Show me page 3 of my lecture note" |
| Get feedback | "Go through my practice problems on page 2 and mark anything wrong" |
| Voice memos | "Does the meeting note have recordings? How long are they?" |

## Tools

11 tools, every one annotated `readOnlyHint: true`.

| Tool | Returns |
|---|---|
| `samsung_notes_list_folders` | All folders with note counts |
| `samsung_notes_list_notes` | Notes in a folder (or everywhere), newest first |
| `samsung_notes_recent` | Most recently modified notes |
| `samsung_notes_search` | Keyword matches across titles and body text |
| `samsung_notes_read_note` | Metadata, typed text, text boxes, embedded PDF text, recording count |
| `samsung_notes_list_pages` | The note's non-blank pages, in order |
| `samsung_notes_get_page` | One page as an image **with your handwriting**, up to 2048 px wide |
| `samsung_notes_get_thumbnail` | The app's own first-page preview (fast, low-res) |
| `samsung_notes_list_note_images` | Imported PDF / photo page backgrounds |
| `samsung_notes_get_page_image` | One of those backgrounds (no pen strokes) |
| `samsung_notes_list_recordings` | Attached voice recordings: path, size, duration |

## How it works

```
 Galaxy tablet / phone ──Samsung Cloud──▶ Samsung Notes for Windows
                                                   │
          %LOCALAPPDATA%\Packages\SAMSUNGELECTRONICSCoLtd.SamsungNotes_*\LocalState
                   ├─ Storage.sqlite     note list, folders, typed text
                   └─ wdoc\<note-uuid>\  pen strokes, pages, PDFs, images, audio
                                                   │  (read-only snapshot)
                                                   ▼
                                              server.py ─── stdio ──▶ Claude Desktop / Claude Code
                                                   │      └─ --http ─▶ claude.ai (optional, see below)
                                                   ▼
                              render/render.mjs (Node + sdocx WASM) ──SVG──▶ pymupdf ──▶ PNG/JPEG
```

- **Text & metadata** come from `Storage.sqlite`. The live file is copied to `%TEMP%` before
  each query, so the Samsung Notes app never sees a lock.
- **Handwriting.** A note's `wdoc\<uuid>\` folder holds the same files as an exported
  `.sdocx` (which is just a zip of them). The server zips a temporary copy and hands it to
  `render/render.mjs`, which uses the [sdocx](https://github.com/twangodev/sdocx) WebAssembly
  library to draw the page as SVG; `pymupdf` rasterises it for Claude.
  Tablet notes often use a wider canvas (e.g. 1600 px) than the declared page (1080 px), so
  the renderer grows the viewport to fit every stroke instead of clipping it.
- **Page order** comes from the `PageDB` table, or from `pageIdInfo.dat` for notes that have
  no `PageDB` rows (common for notes created on a phone or tablet).
- **No Node.js?** `get_page` falls back to the app's own low-res page cache
  (`Thumbnail\<note-uuid>\…\<page-uuid>.jpeg`, ~286 px). Newer app versions may not write
  that cache, so in practice only the first-page thumbnail is guaranteed.
- **Voice recordings** are the `.m4a` files in `wdoc\<uuid>\media\`; durations are read with
  [PyAV](https://github.com/PyAV-Org/PyAV).

The whole server is a single file — [`server.py`](server.py) — if you want to read it end to end.

## Remote access (claude.ai web / tablet)

*Optional and off by default.* To reach your notes from claude.ai or the Claude app on a
tablet, run the server in HTTP mode and expose it through a tunnel you control.
Example with [Tailscale Funnel](https://tailscale.com/kb/1223/funnel):

```powershell
.\.venv\Scripts\python.exe server.py --http        # listens on 127.0.0.1:8788 (--port to change)
tailscale funnel --bg 8788
```

On first start the server generates a random secret and saves it to `http_secret.txt`
(gitignored). Add this as a custom connector in **claude.ai → Settings → Connectors**:

```
https://<your-funnel-host>/<contents of http_secret.txt>/mcp
```

> ⚠️ **That URL is a password.** Anyone who has it can read your notes. To rotate it, delete
> `http_secret.txt`, restart the server, and re-add the connector.

If you get **HTTP 421** through the tunnel, the server didn't recognise your hostname
(MCP's DNS-rebinding protection). It tries to detect your Tailscale name at startup; if
Tailscale starts slowly at boot, add your host to the `allowed` list in `server.py`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Claude doesn't see the tools | Restart Claude Desktop / start a new Claude Code session. Check `claude mcp list`. |
| "Samsung Notes is not installed" | Install it from the Microsoft Store and sign in. |
| New notes are missing | Open Samsung Notes on the PC once so it syncs. |
| "That page isn't ready yet" | The renderer isn't set up — install Node.js, then re-run `install.bat`. |
| A page takes a while | Large notes can take 10–20 s to render the first time; that's the WASM renderer working. |
| Setup stops right after installing Python | Run `install.bat` again (the new Python isn't on `PATH` until a fresh shell). |
| `ImportError: cannot import name 'FastMCP'` | You have mcp 2.x — reinstall with `pip install "mcp[cli]<2"`. |
| Anything else | Open the folder in Claude Code and ask it to debug — [`CLAUDE.md`](CLAUDE.md) has the internals. |

## Limitations

- **Windows only**, because that's where Samsung Notes for PC lives. Notes appear as of the app's last sync.
- **Handwriting isn't OCR'd.** Claude reads the rendered page as an image (which works well for
  equations and diagrams). PDF text inside notes *is* extracted.
- **sdocx is reverse-engineered.** Strokes are accurate, but page templates (ruled lines, grids)
  aren't drawn and unusual objects may be skipped. Blank pages are left out.
- **Locked notes** are listed, but their content is encrypted and can't be read.
- **Voice recordings** are listed, not transcribed.

## Contributing

Issues and pull requests are welcome! Useful things to know:

- The Samsung Notes on-disk format is undocumented. If you find a note that renders wrong,
  an issue with the app version and a description of the page (no private content needed) helps a lot.
- Keep it **read-only**. Nothing should ever write to Samsung's package folder.
- Keep **stdio mode** working; most people never use `--http`.
- [`CLAUDE.md`](CLAUDE.md) documents the internals and hard-won gotchas — handy for humans and coding agents alike.
- Quick sanity check after a change: every tool is a plain function, e.g.
  `.\.venv\Scripts\python.exe -c "import server; print(server.samsung_notes_recent(3))"`.

## Credits

- Full-page handwriting rendering, phone/tablet page ordering, voice-recording support and the
  English translation were contributed by **[@SurajBhari](https://github.com/SurajBhari)** — thank you! 🙏
- Handwriting is drawn by **[sdocx](https://github.com/twangodev/sdocx)** by
  [@twangodev](https://github.com/twangodev), a reverse-engineered Samsung Notes renderer.
- Built on the [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk).

## License

[MIT](LICENSE) © kraewon7422

Third-party components are installed from their own registries, not bundled here, and keep
their own licences: [`@twango/sdocx`](https://www.npmjs.com/package/@twango/sdocx) is GPL-3.0
(run as a separate process), [PyMuPDF](https://pymupdf.readthedocs.io) is AGPL-3.0.
