# CLAUDE.md — Samsung Notes MCP Server

## Project overview
- One line: read-only MCP server that lets Claude read Samsung Notes (typed text,
  PDFs, handwritten pages, voice-recording metadata) from the local Samsung Notes
  for Windows database. Many users are not developers — when helping one, explain
  things step by step and run commands for them.
- Language/runtime: Python 3.10+, single file `server.py` (deps: `mcp[cli]<2`, `pillow`, `av`, `pymupdf`; optional node + `render/`,
  installed into `.venv` by `setup.ps1` — mcp 2.x renamed FastMCP and breaks the import)
- Docs: `README.md` (user guide + technical notes). Installer: `install.bat` → `setup.ps1`

## Architecture
```
Galaxy Tab/phone → Samsung Cloud → Samsung Notes Windows app
  → %LOCALAPPDATA%\Packages\SAMSUNGELECTRONICSCoLtd.SamsungNotes_*\LocalState
      Storage.sqlite (note metadata + text)  +  wdoc\<uuid>\ (page JPGs, PDFs)
  → server.py
      stdio mode  → Claude Code (user scope) + Claude Desktop on this PC
      --http mode → 127.0.0.1:8788, secret URL path → Tailscale Funnel
                    → https://<device>.<tailnet>.ts.net/<secret>/mcp
                    → claude.ai custom connector (web + Galaxy Tab Claude app)
```

## Moving parts (where to look when debugging)
| Part | Location |
|---|---|
| Server | `server.py` here; 11 tools, all read-only |
| Secret URL token | `http_secret.txt` here (gitignored; rotate = delete + restart task + re-add connector) |
| HTTP server log | `server.log` here (only written in --http mode under pythonw) |
| Auto-start (optional, remote setups only) | e.g. a Scheduled Task running `pythonw server.py --http` at logon (`SamsungNotesMCP` in the commands below) |
| Tunnel | `& "C:\Program Files\Tailscale\tailscale.exe" funnel status` (`--bg 8788`, persists) |
| Claude Code registration | `claude mcp list` → `samsung-notes` (user scope, stdio) |
| Claude Desktop registration | `%APPDATA%\Claude\claude_desktop_config.json` → `mcpServers.samsung-notes` |
| Source DB (never write!) | `Storage.sqlite` under the Samsung Notes package LocalState |

## Debug commands
```powershell
# Is the HTTP server up?
Get-NetTCPConnection -LocalPort 8788 -State Listen
# Restart it
Stop-ScheduledTask -TaskName SamsungNotesMCP; Start-ScheduledTask -TaskName SamsungNotesMCP
# End-to-end public test (expects HTTP 200 + server name)
#   POST {"jsonrpc":"2.0","id":1,"method":"initialize",...} with
#   Accept: application/json, text/event-stream
#   to https://<funnel hostname from `tailscale funnel status`>/<secret from http_secret.txt>/mcp
# Tools can also be tested directly (they're plain sync functions):
.\.venv\Scripts\python.exe -c "import server; print(server.samsung_notes_recent(3))"
```

## Key decisions / hard-won gotchas (do not rediscover these)
- **OneNote/Graph API route is DEAD** for Samsung Notes (Microsoft retired the
  OneNote feed; Samsung notes never reach Graph-visible notebooks). Never suggest it.
- **Read-only is a hard rule**: DB is snapshot-copied to %TEMP% before reads
  (never lock the live DB); wdoc format is undocumented — writing risks corrupting sync.
- **421 from funnel**: MCP SDK DNS-rebinding protection only allows localhost by
  default; server adds the Tailscale DNSName to `allowed_hosts` at startup.
- **Encoding trap**: on non-UTF-8 Windows locales (e.g. Korean cp949) any `subprocess`
  capture needs `encoding="utf-8"`, or it crashes/returns None on non-ASCII output.
- **pythonw trap**: `sys.stdout/stderr` are `None` under the scheduled task;
  server redirects them to `server.log` in --http mode. Don't add bare prints.
- **Handwriting**: pen strokes live in undocumented `.page`/`note.note` binaries.
  A note's `wdoc\<uuid>\` folder is an unzipped `.sdocx`; `_sdocx_render` zips a
  temp copy and runs `render/render.mjs` (node + `@twango/sdocx` WASM, GPL-3.0,
  separate process) → SVG → `pymupdf` raster. sdocx clips to the note's page size
  (often 1080 px) but tablet strokes can use a 1600 px canvas — render.mjs grows the
  SVG viewport to the stroke bboxes; don't remove that. sdocx skips trailing blank pages.
  Page order: `PageDB` by `_id`, else UUIDs parsed from `pageIdInfo.dat` ('$' +
  UTF-16LE). Fallback without node: app cache `Thumbnail\<note-uuid>\<n>\<page-uuid>.jpeg`
  (~286 px; recent app versions may never write it — verified empty on one PC even
  after opening/scrolling). Page JPGs in `wdoc\<uuid>\` / `media\` (`N@` prefix =
  page order) are imported PDF/photo backgrounds WITHOUT strokes.
- **Voice recordings**: `.m4a` in `wdoc\<uuid>\media\` (`N@` prefix = order);
  NoteDB.VoiceName labels them. Listed only — local transcription (faster-whisper)
  was tried and dropped as too slow; also faster-whisper 1.2.1 breaks with av>=17.
- **Locked notes** are listed but content is encrypted; **freshness** depends on
  the Samsung Notes Windows app having synced (open the app to force it).

## Common failure modes
1. Tab/web can't connect → PC off, server task not running, or funnel off (check in that order)
2. New notes missing → Samsung Notes Windows app hasn't synced; open it once
3. 421 on public URL → funnel hostname changed (re-check `tailscale status --json` DNSName)
4. Everything broken after Samsung Notes app update → package folder name or DB
   schema changed; re-verify the glob and table columns (NoteDB, CategoryTreeDB, TextSearchDB)

## Don'ts
- Never write to Storage.sqlite or anything under the Samsung Notes package folder
- Never commit or print `http_secret.txt` contents into docs/chat logs
- Don't break stdio mode when changing HTTP mode (Claude Code/Desktop use stdio daily)
