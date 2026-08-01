# Deploying to Azure

The live deployment runs on **Azure App Service (Linux, Python 3.12)**, deployed
from source rather than as a container.

## Why not containers

The repo has a working `Dockerfile`, and Container Apps would be the better fit
architecturally. Two subscription limits on **Azure for Students** rule it out:

| Blocker | Detail |
|---|---|
| `TasksOperationsNotAllowed` | `az acr build` (remote image build) is refused on student subscriptions. Without a local Docker daemon there is no way to produce the image. |
| `MaxNumberOfGlobalEnvironmentsInSubExceeded` | The subscription permits **one** Container Apps environment *globally*, and it is already in use by another project. |

App Service needs neither a registry nor a container environment: Oryx installs
`requirements.txt` on the deployment host and runs the app directly. The
`Dockerfile` remains correct and is what a non-student subscription should use.

## Why B1 and not the free tier

**Always On**, which F1 does not offer. The worker runs as an in-process
background task, so when App Service unloads an idle app it takes any running
pipeline with it — a twelve-minute job would die partway with no failure
recorded. B1 keeps the process resident. This is the same reason the free tier is
wrong here even though the traffic would fit.

## Provisioning

```bash
RG=eduforge-rg; PLAN=eduforge-plan; APP=eduforge-ai; LOC=centralindia

az group create -n $RG -l $LOC
az appservice plan create -g $RG -n $PLAN --is-linux --sku B1 -l $LOC
az webapp create -g $RG -p $PLAN -n $APP --runtime "PYTHON:3.12"
```

## Configuration

```bash
az webapp config appsettings set -g $RG -n $APP --settings \
  LLM_PROFILE=production \
  Open_Router_API_KEY="<your key>" \
  ALLOW_ANTHROPIC=false \
  PYTHONPATH=/home/site/wwwroot/backend \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  ENABLE_ORYX_BUILD=true

az webapp config set -g $RG -n $APP --always-on true \
  --startup-file "python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --app-dir backend"
```

Every name above exists in `backend/core/config.py`. The key is set as an app
setting, never committed — `.env` is in both `.gitignore` and `.dockerignore`.

`PYTHONPATH` matters: the backend is imported as top-level packages (`api`,
`core`, `contracts`, …) from inside `backend/`, exactly as the `Makefile` does
locally with `export PYTHONPATH := backend`.

## Deploying

`config/` must ship alongside `backend/`: `core/config.py` resolves
`models.yaml` from `REPO_ROOT`, which is two levels above `backend/core/`. On the
app that is `/home/site/wwwroot`, so the layout has to match the repo's.

```bash
cd frontend && npm run build && cd ..     # the API serves dist/ itself

zip -r deploy.zip backend config requirements.txt frontend/dist \
  -x "*/__pycache__/*" "*.pyc" "*/node_modules/*"

az webapp deploy -g $RG -n $APP --src-path deploy.zip --type zip
```

## Verifying

```bash
curl https://eduforge-ai.azurewebsites.net/healthz     # {"status":"ok"}
curl https://eduforge-ai.azurewebsites.net/readyz      # profile + schema version
```

`/readyz` reports the resolved `llm_profile`, which is the quickest way to catch
a key that did not take: the app boots either way, and a wrong profile only
surfaces when the first job calls a model.

Logs:

```bash
az webapp log tail -g $RG -n $APP
```

## Cost

B1 is roughly $13/month, drawn from the Azure for Students credit. To stop
charges without deleting anything:

```bash
az webapp stop -g $RG -n $APP        # or: az group delete -n $RG --yes
```

An Azure Container Registry (`eduforgeacr*`, Basic) was created before the ACR
Tasks limit surfaced. It holds no images and is not used by this deployment —
delete it:

```bash
az acr delete -g $RG -n <registry-name> --yes
```

## Known limitations in the deployed build

- **Storage is in-memory.** A restart loses uploaded documents, jobs, and
  rendered artifacts. Package downloads work within the life of one process.
- **One instance only.** Scaling out would put jobs in one process's memory and
  SSE readers in another's; the Postgres store is the prerequisite for that.
- **Free-tier model quota.** OpenRouter allows 50 requests/day, roughly one and
  a half full pipeline runs. A `429` in the progress stream is the quota, not a
  defect — `X-RateLimit-Reset` in the error names the reset time.
