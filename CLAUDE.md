# CLAUDE.md — Samsung Notes MCP Server

## Project overview
- One line: read-only MCP server that lets Claude read the user's Samsung Notes
  (text, page images, handwriting thumbnails) from the local Samsung Notes for
  Windows database. Built 2026-06-08 with Claude Code; owners are typically
  non-developers — explain things click-by-click and run commands for them.
- Language/runtime: Python 3.14, single file `server.py` (deps: `mcp[cli]`, `pillow`)
- Docs: `README.md` (technical), `MANUAL.md` (Korean, for the owner — keep it non-technical)

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
| Server | `server.py` here; 8 tools, all read-only |
| Secret URL token | `http_secret.txt` here (gitignored; rotate = delete + restart task + re-add connector) |
| HTTP server log | `server.log` here (only written in --http mode under pythonw) |
| Auto-start | Windows Scheduled Task `SamsungNotesMCP` (runs `pythonw server.py --http` at logon) |
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
python -c "import server; print(server.samsung_notes_recent(3))"
```

## Key decisions / hard-won gotchas (do not rediscover these)
- **OneNote/Graph API route is DEAD** for Samsung Notes (Microsoft retired the
  OneNote feed; Samsung notes never reach Graph-visible notebooks). Never suggest it.
- **Read-only is a hard rule**: DB is snapshot-copied to %TEMP% before reads
  (never lock the live DB); wdoc format is undocumented — writing risks corrupting sync.
- **421 from funnel**: MCP SDK DNS-rebinding protection only allows localhost by
  default; server adds the Tailscale DNSName to `allowed_hosts` at startup.
- **cp949 trap**: this is Korean Windows — any `subprocess` capture needs
  `encoding="utf-8"`, or it crashes/returns None on non-ASCII output.
- **pythonw trap**: `sys.stdout/stderr` are `None` under the scheduled task;
  server redirects them to `server.log` in --http mode. Don't add bare prints.
- **Handwriting**: pen strokes live in undocumented `.page` files; only visible
  via the app-rendered first-page thumbnail (`samsung_notes_get_thumbnail`).
  Page JPGs (`wdoc\<uuid>\` or `media\` subfolder; `N@` prefix = page order)
  are imported PDF/photo backgrounds without strokes.
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
