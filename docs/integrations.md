# Integrations: local models, project trackers, CI

Every integration is an adapter, and they all coexist. Pick per run with flags. Nothing else changes.

| layer | options | switch |
|---|---|---|
| Coding harness | Claude Code (default) · pi · **DeepSeek Harness (dsh) on local models** | `--harness dsh` |
| Project tracker | GitHub Issues (default) · **Plane** · Jira Cloud | `--pm plane` / `--pm jira` |
| CI | GitHub Actions (default) · **CircleCI** · anything that reports PR checks | automatic |

---

## 1. Local models with DeepSeek Harness (dsh)

deleg8 reuses the `~/local-ai` setup as-is: the panel picks the model and runs llama-server on `:8080`, and it keeps
`~/.local/share/augmentor/dsh-home/settings.yaml` pointing at that model. The `dsh` preset in `deleg8.yaml` runs
the same dsh install headless with that DSH home, so **Dex uses whatever model is running in the panel.**

What deleg8 does on each call:
- runs `dsh --patch <overlay> --profile headless "<task>"` in the task's workspace
- the overlay mounts deleg8's research tools (wiki, DBs, tickets) as an MCP server inside dsh, plus Dex's persona
- planning, review and reports use `DSH_PERMISSION_MODE=read-only`; coding uses `workspace-write`
  (set `permission_mode: danger-full-access` in the preset if the sandbox blocks the agent's test runs; deleg8
  re-runs all checks itself before any PR either way)
- headless sessions are stored in the same DSH home, so you can follow them in the DSH web UI (`:3080`)
- local runs cost $0; the journal still records time per step

### Steps
1. **Pick a capable model in the panel** (http://127.0.0.1:8090) and **raise its context to 65536 or more**. Agentic coding
   needs room for repo files and tool output. 16k (the current setting) will truncate. A 27B–35B coder/instruct
   model with tool calling (`--jinja`) is the practical minimum for reliable results.
2. **Save & start**, then check everything:
   ```bash
   uv run deleg8 --harness dsh doctor
   ```
   You should see `dsh model: <your model>` and `model server is up`. A context warning means step 1 isn't done.
3. **Smoke-test one ticket** (no GitHub writes beyond that ticket):
   ```bash
   uv run deleg8 --harness dsh run --ticket <issue-number>
   ```
4. **Run the employee** on local models:
   ```bash
   uv run deleg8 --harness dsh work --interval 60
   ```
5. Debug: every dsh call's prompt, model, sandbox mode, output and stderr tail is saved in `.deleg8/logs/`.
   The DSH web UI shows the full trajectory.

Mix and match is supported: edit the `harnesses.dsh` preset so that only `coding_agent` uses dsh, and keep
`brain` (planning/review) on Claude, or the other way round.

---

## 2. Project tracker: Plane (free, open source)

[Plane](https://plane.so) is an open-source (AGPL-3.0) Jira alternative with work items, sub-items, states,
labels, cycles, modules and a REST API.

- **Self-hosted Community Edition:** free with no user limit; needs 2 CPU / 4 GB RAM (8 GB recommended)
- **Plane Cloud:** has a free tier (third-party sources say up to 12 users; check plane.so/pricing)

deleg8 maps ticket types to labels (`type:epic|story|task|bug`, because native Epics are a paid Plane feature),
statuses to Plane states (Todo / In Progress / In Review / Blocked / Done), and hierarchy to native sub-work-items.

### Self-host (Docker)
```bash
mkdir ~/plane-selfhost && cd ~/plane-selfhost
curl -fsSL -o setup.sh https://github.com/makeplane/plane/releases/latest/download/setup.sh
chmod +x setup.sh && ./setup.sh          # choose 1 (Install), then 8 (Exit)
# edit plane-app/plane.env: LISTEN_HTTP_PORT=8088, WEB_URL=http://localhost:8088,
#                           CORS_ALLOWED_ORIGINS=http://localhost:8088   (8080 is taken by llama-server)
./setup.sh                               # choose 2 (Start)
```
Open http://localhost:8088, create the admin account, create a workspace (for example `deleg8`) and a project with
identifier `DEL`, then create an API token (Profile settings → Personal access tokens).

### Connect deleg8
```bash
export PLANE_BASE_URL=http://localhost:8088   # or https://api.plane.so for Plane Cloud
export PLANE_API_KEY=plane_api_...
export PLANE_WORKSPACE=deleg8
uv run deleg8 --pm plane doctor
uv run deleg8 --pm plane bootstrap --skip-infra   # creates the deleg8 labels + In Review/Blocked states
uv run deleg8 --pm plane seed                     # the demo backlog, now in Plane
uv run deleg8 --pm plane run                      # combine with --harness dsh for a fully local stack
```
Code, PRs and CI still go through GitHub; only the tickets move to Plane. Plane's API allows 60 requests/min per
key, and deleg8 waits and retries on 429.

### Jira (still supported)
Jira Cloud's **Free plan is free for up to 10 users** (proprietary, 2 GB storage, limited automation).
Set the `pm.jira` values (or `JIRA_*` env vars) in `deleg8.yaml` and use `--pm jira`.

---

## 3. CI: GitHub Actions and CircleCI

- **GitHub Actions (default, already running):** free on public repos; private repos on GitHub Free get
  2,000 Linux minutes/month.
- **CircleCI (added):** Free plan of 30,000 credits/month (about 3,000 medium-Linux minutes).

deleg8 waits on whatever checks appear on the PR, so CircleCI works as soon as it reports. When a CircleCI check
fails, deleg8 fetches the failing step's log through CircleCI's API and gives it to the coding agent to fix, the same
as with Actions logs.

### Enable CircleCI for deleg8-website
1. The pipeline is in `.circleci/config.yml` (lint, format, tests, static export, Docker build). It is the same set of checks as Actions.
2. Sign in at circleci.com with GitHub and **Set up project** for `attrivivekai/deleg8-website` (use the existing config).
3. Create a personal API token (User settings → Personal API Tokens) and `export CIRCLE_TOKEN=...` where deleg8
   runs, so it can read failure logs.
4. Optional: to make CircleCI **required** for merging, add `ci/circleci: test` and `ci/circleci: docker` to the
   `protect-main` ruleset's required status checks (Settings → Rules). To use *only* CircleCI, also remove
   `test`/`docker` from the ruleset and delete `.github/workflows/ci.yml`. Keep `deploy.yml`, because GitHub Pages deploys
   from Actions.
