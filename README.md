# continuity-engine
Human-governed continuity intelligence and production memory for creative production workflows.

## STUDIO//ONE Web Console

STUDIO//ONE now includes a minimal judge-facing FastAPI console for the canonical workflow:

`BRAINSTORM -> REFINE -> FINALIZE STORYBOARD -> GENERATE ASSETS -> QUALITY CONTROL -> POST PRODUCTION -> PUBLISH`

### Local Setup

Create a virtual environment, install dependencies, and configure local environment values from the placeholder template:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with reviewer-owned Google Cloud, Gemini, ClickHouse, and Secret Manager values. Do not commit `.env` or credential files.

Required runtime environment variables:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`
- `GEMINI_MODEL`
- `CLICKHOUSE_HOST`
- `CLICKHOUSE_USER`
- `CLICKHOUSE_DATABASE`
- `CLICKHOUSE_PASSWORD_SECRET`

Optional runtime environment variables:

- `CLICKHOUSE_PORT` defaults to `8443`
- `CLICKHOUSE_SECURE` defaults to `true`
- `CLICKHOUSE_VERIFY` defaults to `true`
- `CLICKHOUSE_MCP_QUERY_TIMEOUT` defaults to `90`
- `MCP_CLICKHOUSE_PYTHON` overrides the Python executable used for the MCP subprocess

### Local Web Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn studio_one.web.app:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

Health endpoints:

- `/health` verifies the FastAPI process and canonical stage count only.
- `/ready` verifies required environment variable presence and installed `mcp-clickhouse` availability. It does not call Gemini, Secret Manager, or ClickHouse.

The web console does not generate media, edit final video, authenticate to external platforms, upload media, schedule posts, or publish content. PUBLISH prepares a creator-ready package for approval and manual posting only.

### Docker Build and Local Container Run

```powershell
docker build -t studio-one-cloud-run .
docker run --rm -p 8080:8080 -e PORT=8080 studio-one-cloud-run
```

Open `http://127.0.0.1:8080/health` for a health-only container check. Full workflow calls require runtime environment variables and Google Cloud identity.

### Google Cloud Run Deployment

The FastAPI production entrypoint is `studio_one.web.app:app`. The container starts Uvicorn on `0.0.0.0` and uses Cloud Run's `$PORT`.

Build and push with Cloud Build:

```powershell
gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT_ID/ARTIFACT_REPOSITORY/studio-one:TAG .
```

Deploy to Cloud Run:

```powershell
gcloud run deploy studio-one `
  --image REGION-docker.pkg.dev/PROJECT_ID/ARTIFACT_REPOSITORY/studio-one:TAG `
  --region REGION `
  --service-account SERVICE_ACCOUNT_EMAIL `
  --allow-unauthenticated `
  --set-env-vars GOOGLE_CLOUD_PROJECT=PROJECT_ID,GOOGLE_CLOUD_LOCATION=us,GEMINI_MODEL=gemini-3.5-flash,GOOGLE_GENAI_USE_VERTEXAI=true,CLICKHOUSE_HOST=CLICKHOUSE_HOST,CLICKHOUSE_USER=CLICKHOUSE_USER,CLICKHOUSE_DATABASE=continuity_engine,CLICKHOUSE_PASSWORD_SECRET=CLICKHOUSE_PASSWORD_SECRET,CLICKHOUSE_PORT=8443,CLICKHOUSE_SECURE=true,CLICKHOUSE_VERIFY=true,CLICKHOUSE_MCP_QUERY_TIMEOUT=90
```

Minimum runtime IAM for `SERVICE_ACCOUNT_EMAIL`:

- Secret Manager access to the configured ClickHouse password secret: `roles/secretmanager.secretAccessor` on that secret.
- Vertex AI/Gemini invocation in the configured project/location. Prefer a custom role limited to prediction/inference permissions where available; otherwise use the narrowest predefined Vertex AI/Agent Platform user role accepted by the project.

Cloud Run should use its service account and Application Default Credentials. Do not deploy with downloaded service-account JSON keys in the image or repository.

### Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
