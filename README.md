# 삼성 노트 × Claude (Samsung Notes MCP)

Claude(클로드)가 **내 삼성 노트를 직접 읽을 수 있게** 해주는 도구입니다.

- 갤럭시 탭/폰에서 쓴 노트도 보입니다 (삼성 클라우드 → 내 PC의 삼성 노트 앱으로 자동 동기화되기 때문)
- **전부 내 컴퓨터 안에서만 동작**합니다 — 노트가 외부 서버로 전송되지 않습니다
- **읽기 전용**입니다 — Claude가 노트를 수정하거나 지우는 것은 불가능합니다

이런 게 가능해집니다:

> "수학 폴더에서 이차방정식 노트 찾아서 첫 페이지 보여줘" → Claude가 **내 손글씨 풀이를 보고** 채점해 줌

---

## 준비물

| 필요한 것 | 설명 |
|---|---|
| Windows PC | Windows 10/11 |
| 삼성 노트 앱 (PC용) | Microsoft Store에서 "Samsung Notes" 설치 → 삼성 계정 로그인 → 동기화 확인 |
| Claude Desktop 또는 Claude Code | [claude.ai/download](https://claude.ai/download) |
| Python 3.10 이상 | 없으면 설치 프로그램이 자동으로 설치해 줍니다 |

> ⚠️ 갤럭시(삼성 노트) 사용자 전용입니다. PC의 삼성 노트 앱에서 내 노트가 보여야 합니다.

## 설치 (3분, 클릭만 하면 됨)

1. 이 페이지 위쪽 초록색 **`<> Code`** 버튼 → **Download ZIP** 클릭
2. 내려받은 ZIP을 **압축 풀기** (예: 문서 폴더에)
3. 압축 푼 폴더에서 **`설치하기.bat`** 더블클릭
   - "Windows의 PC 보호" 경고가 뜨면: **추가 정보** → **실행** 클릭
4. 창에 **"설치 완료"** 가 나오면 끝. Claude Desktop을 껐다 켜세요.

## 사용법 — 그냥 말하면 됩니다

| 하고 싶은 것 | Claude에게 하는 말 |
|---|---|
| 폴더 보기 | "내 삼성 노트 폴더 보여줘" |
| 노트 목록 | "수학 폴더에 뭐 있어?" |
| 검색 | "삼성 노트에서 한국사 검색해줘" |
| 노트 읽기 | "○○ 노트 내용 읽어줘" |
| 손글씨 보기 (첫 페이지) | "○○ 노트 첫 페이지 보여줘" |
| 손글씨 보기 (모든 페이지) | "○○ 노트 3페이지 보여줘" / "페이지 목록 보여줘" |
| 채점 받기 | "이 노트 5페이지 보고 내 풀이 채점해줘" |
| 요약 | "○○ 노트 요약해줘" |

## 문제 해결

| 증상 | 해결 |
|---|---|
| Claude가 "도구가 없다"고 함 | Claude Desktop 재시작 / Claude Code는 새 세션 시작 |
| 새로 쓴 노트가 안 보임 | PC의 삼성 노트 앱을 한 번 열어 동기화시키기 |
| "삼성 노트 앱이 없습니다" 오류 | Microsoft Store에서 Samsung Notes 설치 후 삼성 계정 로그인 |
| 설치 중 Python 설치됨 → 멈춤 | `설치하기.bat`를 한 번 더 실행 |
| 그 외 | Claude Code에게 "이 폴더의 MCP 서버가 안 돼, 고쳐줘"라고 하면 됩니다 (CLAUDE.md에 디버깅 정보가 들어 있음) |

## 보안 · 개인정보

- 노트 데이터는 **내 컴퓨터 밖으로 나가지 않습니다.** 이 프로그램에는 서버나 계정이 없습니다.
  (Claude와의 대화에서 Claude가 읽은 내용은 일반 대화와 동일하게 처리됩니다)
- 읽기 전용: 원본 노트 데이터베이스는 절대 수정하지 않습니다 (읽기 전 임시 복사본 사용).
- 잠금(비밀번호) 설정된 노트의 내용은 암호화되어 있어 읽을 수 없습니다.

## 한계

- **손글씨**는 텍스트로 변환되지 않습니다. 대신 손글씨가 그려진 화면을 Claude가 이미지로 직접 봅니다.
  (PDF 위에 필기한 노트는 PDF의 텍스트는 추출됩니다)
- **첫 페이지 이후의 손글씨 페이지**도 볼 수 있습니다. 단, 삼성 노트 앱은 **PC에서 한 번 열어 그 페이지까지 넘겨 본** 페이지만 이미지로 저장합니다. 아직 안 본 페이지는 "페이지 목록 보여줘"에서 *아직 준비 안 됨*으로 표시되며, PC 앱에서 그 노트를 열어 끝까지 넘기면 볼 수 있게 됩니다. (저장되는 이미지 해상도는 가로 약 286px로 다소 낮습니다)
- PC 삼성 노트 앱이 마지막으로 동기화한 시점까지의 노트가 보입니다.

---

## 고급: 태블릿이나 claude.ai 웹에서 쓰기 (선택)

기본 설치는 **내 PC의 Claude에서만** 동작합니다. 갤럭시 탭의 Claude 앱이나 claude.ai 웹에서도 쓰려면, **본인 PC를 본인의 Tailscale 계정으로** 인터넷에 공개해야 합니다 (유료 Claude 요금제 필요):

```powershell
# 1. Tailscale 설치 + 본인 계정 로그인 (https://tailscale.com)
# 2. 서버를 HTTP 모드로 실행 (비밀 주소가 자동 생성됨)
python server.py --http
# 3. 터널 켜기
tailscale funnel --bg 8788
# 4. 만들어진 주소를 Claude에 등록 (아래 참고)
```

**주소 등록하는 곳** (PC가 아니라 **claude.ai 사이트**에 등록합니다):

1. 크롬에서 [claude.ai](https://claude.ai) 접속 → 왼쪽 아래 내 이름 → **Settings(설정)**
2. **Connectors(커넥터)** → **Add custom connector(커스텀 커넥터 추가)**
3. URL 칸에 붙여넣기: `https://<내 funnel 주소>/<http_secret.txt 안의 비밀값>/mcp`
4. **Add** 클릭 → 끝. claude.ai 웹과 폰/태블릿 Claude 앱에 자동으로 나타납니다.

⚠️ 이렇게 하면 비밀 URL을 아는 사람은 누구나 내 노트를 읽을 수 있습니다. URL을 절대 공유하지 마세요. 잘 모르겠으면 기본(로컬) 설치만 쓰는 것을 권합니다.

---

## Technical notes (English)

- Single-file MCP server (`server.py`, Python, FastMCP) over the Samsung Notes
  for Windows local database: `%LOCALAPPDATA%\Packages\SAMSUNGELECTRONICSCoLtd.SamsungNotes_*\LocalState`
  (`Storage.sqlite` for metadata/text, `wdoc\<uuid>\` for page images/PDFs).
- 10 read-only tools: list folders/notes/recent, read note (typed + PDF + textbox text),
  keyword search, list page images, get page image (imported PDF/photo backgrounds,
  downscaled), get rendered first-page thumbnail (includes pen strokes), plus
  `list_pages` / `get_page` to view **any** page rendered with handwriting.
- Handwritten pages beyond the first come from the app's own per-page render cache
  (`Thumbnail\<note-uuid>\<n>\<page-uuid>.jpeg`), ordered via `PageDB`. Samsung only
  writes a page's render after it is opened/scrolled in the Windows app, so
  `get_page` reports which pages are not yet rendered instead of guessing.
- The live DB is snapshot-copied to `%TEMP%` before every read — the Samsung
  Notes app never sees a lock, and nothing is ever written to its data.
- Optional `--http` mode serves streamable HTTP on `127.0.0.1:8788` with a
  secret URL path (`http_secret.txt`, generated on first run, gitignored) for
  use behind a tunnel as a claude.ai custom connector.
- The OneNote/Microsoft Graph route does **not** work for Samsung Notes
  (Microsoft retired the OneNote feed) — that's why this reads the local DB.
- See `CLAUDE.md` for debugging context (designed for Claude Code).
