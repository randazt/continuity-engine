# continuity-engine
Human-governed continuity intelligence and production memory for creative production workflows.

## STUDIO//ONE Web Console

STUDIO//ONE now includes a minimal judge-facing FastAPI console for the canonical workflow:

`BRAINSTORM -> REFINE -> FINALIZE STORYBOARD -> GENERATE ASSETS -> QUALITY CONTROL -> POST PRODUCTION -> PUBLISH`

Run locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn studio_one.web.app:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

Live workflow calls require the reviewer's own Google/Gemini, ClickHouse, and official `mcp-clickhouse` configuration. Use `.env.example` as the placeholder template; do not commit `.env` or credential files.

The web console does not generate media, edit final video, authenticate to external platforms, upload media, schedule posts, or publish content. PUBLISH prepares a creator-ready package for approval and manual posting only.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
