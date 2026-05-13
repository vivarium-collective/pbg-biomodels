# Workspace bootstrap — friction notes (2026-05-13)

Notes captured during the `pbg-biomodels` workspace bootstrap. Aimed at maintainers of `pbg-superpowers`, `pbg-template`, and `vivarium-dashboard`. Each entry includes the symptom, the root cause we found, and a suggested fix.

## 1. `vivarium-dashboard` is not on PyPI — fresh workspaces fail to install

**Symptom.** Right after `python -m pbg_superpowers.scaffold workspace --name <X> --target <Y>`, running the next quick-setup step (`uv pip install -e ".[dev]"`) fails with:

```
× No solution found when resolving dependencies:
  ╰─▶ Because vivarium-dashboard was not found in the package registry and
      <workspace>==0.0.0 depends on vivarium-dashboard, we can conclude that
      <workspace>==0.0.0 cannot be used.
```

**Root cause.** `pbg-template/template/pyproject.toml.j2` lists `vivarium-dashboard` as a regular PyPI dependency, but the package is not (yet) published. It only exists as a local checkout at `../vivarium-dashboard/`.

**Workaround applied here.** Added to the workspace's `pyproject.toml`:

```toml
[tool.uv.sources]
vivarium-dashboard = { path = "../vivarium-dashboard", editable = true }
```

**Suggested fixes.**
- **pbg-template**: during `template-init`, detect a sibling `../vivarium-dashboard/` directory and inject the `[tool.uv.sources]` block automatically (mirroring how `v2ecoli-chromosome-rep1/pyproject.toml` wires pbg-* git-only deps under `external/`). When no sibling exists, emit a clear error during scaffolding so the user knows to either publish, clone, or override.
- **vivarium-dashboard**: publish to PyPI (or a private index) so workspaces can declare it plainly. Until then, README needs a prominent "Install editable from local checkout" section.

## 2. `pbg-server start` does not start the 5/6-tab dashboard

**Symptom.** `pbg-server start` printed a healthy `http://localhost:<port>` URL and `/api/state` returned 200, but the page rendered just the static workspace report (title + "No models yet" + "No decisions logged yet"). No tab rail. No Workspace inputs/Registry/Visualizations panels.

**Root cause.** Two distinct servers exist and the skill catalog conflates them:
- `pbg-superpowers/server/start-server.sh` serves `reports/index.html` via stdlib `http.server`. This is what `/pbg-server start` actually launches.
- `vivarium-dashboard serve --workspace <ws>` (called via the workspace's `scripts/serve.sh`) serves the live 5/6-tab interactive dashboard with tab rail, Registry, etc.

The `pbg-server` skill description claims its server "backs the 5-tab dashboard". It does not — it backs the static report page and is only used by stage skills to mirror prompts to `.pbg/server/content/`. The interactive dashboard is a separate process.

**Suggested fixes.**
- **pbg-superpowers**: rewrite the `pbg-server` skill so `start` either (a) delegates to `vivarium-dashboard serve` when the workspace declares it as a dep, or (b) is renamed (e.g. `pbg-report-server`) and the skill description is updated to make clear it serves `reports/index.html` only. Today's situation — same skill name, different server, same `.pbg/server/` directory — is the worst of both worlds.
- **pbg-template**: NEXT_STEPS.md tells users to run `bash scripts/serve.sh`. The user-facing `/pbg-workspace` skill output also tells them to run `bash scripts/serve.sh`. But the `/pbg-server` skill is listed in the skill catalog as "Manage the local HTTP server that backs the 5-tab dashboard." Pick one entrypoint and route everyone through it.

## 3. `start-server.sh` invokes bare `python3`, not the workspace venv

**Symptom.** First `pbg-server start` attempt crashed during boot:

```
File "/Users/eranagmon/code/pbg-superpowers/server/server.py", line 10, in <module>
    import yaml
ModuleNotFoundError: No module named 'yaml'
```

PID file was written before the process died, so the skill's "stale state" guard tripped and refused future `start` calls until the state files were manually removed.

**Root cause.** `pbg-superpowers/server/start-server.sh` runs `nohup python3 server.py …`, picking up the system Python (no `yaml`) rather than the workspace's `.venv/bin/python3` (has `yaml` via `pyyaml>=6.0`).

**Workaround applied here.** Manually prefixed `PATH="<ws>/.venv/bin:$PATH"` before calling `start-server.sh`.

**Suggested fixes.**
- **pbg-superpowers**: in `start-server.sh`, resolve Python with the same preference logic that `pbg-template/template/scripts/serve.sh` already uses for the dashboard binary — workspace `.venv/bin/python3` first, then `command -v python3`, then a clear error.
- **pbg-superpowers**: if a server crashes during launch, the script should detect the dead PID and remove `server-info` / `server.pid` instead of leaving stale state that blocks the next `start`. Tail of `server.log` would be useful in the error path.

## 4. Scaffold workspace name vs Python package name

**Symptom.** `python -m pbg_superpowers.scaffold workspace --name pbg-biomodels` produced a package directory `pbg_pbg_biomodels/` (doubled prefix), because the scaffolder unconditionally prepends `pbg_` to the snake_cased workspace name. Discovered before commit — re-scaffolded with `--name biomodels` to get `pbg_biomodels/`.

**Suggested fixes.**
- **pbg-superpowers**: in the scaffold CLI, if the supplied `--name` already starts with `pbg-` or `pbg_`, either (a) strip the prefix before adding it back, or (b) refuse with a clear "name should not start with pbg-; the package will be pbg_<name>" message.

## 5. Skill description count mismatch (minor)

The `pbg-server` skill description and several other docs refer to "the 5-tab dashboard". The actual dashboard now renders six rail entries: Workspace inputs, Registry, Composites, Investigations, Visualizations, GitHub Branches. Worth a sweep through `pbg-superpowers/` and `pbg-template/` docs to update the count or rephrase ("the dashboard tabs").

## 6. `pbg_superpowers` not on host Python by default

**Symptom.** Step §7.4 of the `/pbg-workspace` skill calls `python -m pbg_superpowers.scaffold workspace …`. With the default `python` on PATH, the module isn't importable.

**Root cause.** `pbg-superpowers` is installed in a specific venv at `/Users/eranagmon/code/venv/` but is not on the user's default `python`. The skill doesn't tell you which Python to use, and other pbg-* venvs each have their own copy.

**Suggested fix.**
- **pbg-superpowers**: ship a shim/CLI entrypoint (`pbg-scaffold` or `pbg`) registered as a `[project.scripts]` so users invoke it directly instead of `python -m pbg_superpowers.scaffold`. The skill could then reference `pbg-scaffold workspace …`.

---

## Sequence we actually had to run (for the record)

```bash
# 1. Scaffold
/Users/eranagmon/code/venv/bin/python -m pbg_superpowers.scaffold workspace \
    --name biomodels \
    --target /Users/eranagmon/code/pbg-biomodels \
    --template-source /Users/eranagmon/code/pbg-template

cd /Users/eranagmon/code/pbg-biomodels

# 2. git init
git init -b main && git add -A && git commit -m "feat(stage-0): workspace bootstrap"

# 3. venv + install — FAILED at first; needed the [tool.uv.sources] fix
uv venv .venv && source .venv/bin/activate
# (manually added [tool.uv.sources] entry for vivarium-dashboard)
uv pip install -e ".[dev]"
git add -A && git commit -m "chore: pin vivarium-dashboard to local editable source"

# 4. Lint and render
python scripts/lint-workspace.py
python -c "from pbg_superpowers.report import render_workspace_report; from pathlib import Path; render_workspace_report(Path('.'))"
git add -A && git commit -m "docs: render initial workspace report"

# 5. Dashboard — DON'T use /pbg-server here; use scripts/serve.sh
bash scripts/serve.sh
```
