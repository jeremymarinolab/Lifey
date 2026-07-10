# agents.md

This file is for coding agents working on Lifey without prior chat context. Keep it short, operational, and project-specific. Use `README.md` for human onboarding, architecture overview, command details, and setup instructions.

## Canonical checkout

Use this project root for all new Lifey work:

```text
/Users/life/Documents/Codex/2026-07-03/review-this-entire-app-as-a/work/Lifey
```

The older checkout below is historical and should not receive new implementation work unless the user explicitly asks for comparison or recovery:

```text
/Users/life/Documents/Codex/2026-06-19/refine-and-build-the-mvp-for
```

Stable branch and remote:

```text
main
origin https://github.com/jeremymarinolab/Lifey.git
```

Do not assume a clean tree. Always start with:

```sh
git status --short --branch
```

## Agent operating rules

- Preserve user work. Never reset, discard, overwrite, or mass-format unrelated changes without explicit approval.
- Prefer small, focused edits that fit the revised modular structure.
- Do not grow `app.js` by default. Put new isolated logic in `js/` modules or backend service modules when practical.
- Use `apply_patch` for file edits.
- Keep local-first behavior as the default. External integrations are optional enrichments, not hard dependencies.
- Show disconnected, stale, estimated, manual, imported, captured, and inferred states honestly in the UI.
- Do not invent or fake integration data.
- Do not add cloud infrastructure, login systems, databases, or background services unless the user explicitly scopes that project.

## Product boundaries to preserve

Lifey is a local-first daily command center backed by Obsidian and a small Mac helper.

Non-negotiable platform constraints:

- YouTube: no official watch-history API. Use local browser extension/activity capture only.
- Instagram: do not scrape private feeds, stories, private data, or assume full following-feed access. The Instagram business-directory/AI project is paused.
- Google Maps Timeline: do not assume a reliable Timeline API.
- Spotify: API access may be limited or blocked for non-Premium accounts. Do not show demo/fake listening data.
- Google Calendar/Gmail: use official OAuth and show expired/disconnected auth accurately.
- Obsidian: local Markdown/filesystem is the source of truth.

## Architecture edit map

Use `README.md` for the full architecture map. Practical routing:

- Frontend state normalization: `js/state.js`
- Local API wrapper/response shape: `js/api.js`
- Pure parsing logic: `js/parsers.js`
- Feature rendering/controllers: `js/features/*`
- Reusable UI helpers: `js/ui/*`
- Spotify frontend integration: `js/integrations/spotify.js`
- Backend route table/validation: `routes.py`
- HTTP server/static serving: `local_server.py`
- Obsidian filesystem behavior: `obsidian_repo.py`
- Domain services: `task_service.py`, `project_service.py`, `habit_service.py`, `places_service.py`, `activity_service.py`, `archive_service.py`, `profile_service.py`
- Provider clients: `google_client.py`, `notion_client.py`
- Secrets/profile persistence: `config_store.py`

Styling:

- Shared foundations: `styles.css`, `dashboard-layout.css`, `settings-panels.css`, `mobile.css`
- Feature card styles: `*-card.css`
- Capture UI: `capture.css`, `capture-calendar.css`

Avoid recreating the old giant patch style. Put styles near the feature or in the shared layout file only when the rule is truly shared.

## Obsidian contracts

- Daily note title format: `MMMM DD, YYYY`.
- Daily notes and vault/Journals paths must come from configuration and `obsidian_repo.py`, not old hardcoded paths.
- Normal tasks are Markdown checkboxes and should be written under `## Tasks::`.
- Habit checkboxes live under `Habits::`; normal task actions must not touch them.
- Task source path and line number matter for edits, deletion, Notion mapping, and Calendar mapping.
- When creating a dated task, prefer the daily note for that due date if available; otherwise use today.
- If editing a task that is linked to a calendar event, update the event when relevant.
- Archive writes must update only the Lifey archive block and create backups before modifying notes.
- Project tasks are created from Daily Notes and assigned with `#project/project-name`; project notes live in `Projects/`.

## Secrets and privacy

Never commit or persist secrets in source files, JSON config, exported profiles, Obsidian notes, or `localStorage`.

Secrets belong in macOS Keychain through `config_store.py`. If adding a secret field, update the secret handling/export stripping there.

Secret-like values include:

- Notion tokens
- Google refresh tokens/client secrets/Places keys
- Traccar tokens
- Lifey Location collector token
- Spotify access/refresh tokens
- GitHub/OpenAI/API keys

Before commits or pushes, run a targeted scan:

```sh
rg -n "ghp_|github_pat_|sk-|client_secret|refresh_token|access_token|Authorization: Bearer|AIza[0-9A-Za-z_-]+" . --glob '!node_modules' --glob '!.git'
```

The scan can report code references to token field names; inspect results before deciding they are real secrets.

## UX rules learned from prior iterations

- The user is a UI/UX designer; alignment, rhythm, spacing, and visual consistency matter.
- Lifey should feel like a polished dark-mode command center, not an admin dashboard.
- Cards should share the same liquid-glass surface, border, shadow, and edge treatment.
- The top bar should remain a floating liquid-glass pill aligned to the card grid.
- Appearance settings include background image, tint color/intensity, corner radius, hero metric order/visibility, card order, and card visibility.
- Do not stack brittle mobile fixes. If a UI interaction becomes fragile, simplify the model.
- Mobile quick capture should not mimic a draggable native iOS sheet. No fake grab handle.
- Mobile quick capture should lock/hide the dashboard behind it; do not allow background page scroll.
- In mobile capture, only date/calendar selection should scroll when needed.

## Location and mobile app direction

- Primary location source is the `LifeyLocation` iOS companion app.
- The app queues samples on-device and uploads to the Mac helper when reachable.
- Traccar is optional fallback only; do not make Lifey depend on it.
- Raw location points should remain intact.
- Place grouping must be reversible because it is computed from raw points.
- Manual place merges override radius grouping and should be undoable.
- Home coordinates and raw location history must remain local.

## Browser extension direction

- `browser-extension/` captures focused YouTube watch-page activity and posts to the local helper.
- Keep data collection minimal and explicit.
- Extension ID: `lifey-youtube@local`.

## Validation expectations

Use the smallest validation that matches the change.

For normal code changes:

```sh
npm run lint
npm run format:check
```

For larger or cross-cutting changes:

```sh
npm run check
```

For quick syntax-only checks:

```sh
node --check app.js
python3 -m py_compile local_server.py
```

After adding, removing, renaming, or changing app-shell assets:

```sh
npm run assets:version
```

Do not manually edit generated service-worker shell entries or `?v=` query strings.

## Git workflow

- Keep the canonical checkout on `main`; do not implement features directly on it.
- Start each meaningful task from updated `origin/main` in a sibling worktree, using a `codex/feature-name`, `codex/bug-name`, or `codex/refactor-name` branch.
- Keep one task per branch and keep commits focused. Push the branch and merge it through a pull request before removing its worktree.
- Use `../worktrees/<task-name>` from the canonical checkout as the standard worktree location.
- Do not commit generated local data such as `.activity-log.json`, `test-results/`, `node_modules/`, `.npm-cache/`, `.playwright-browsers/`, logs, or local dashboards.
- GitHub auth is through GitHub CLI. If push auth fails:

```sh
gh auth status
gh auth setup-git
```

Then push normally.

## Current caution

Always inspect `git status --short --branch` before editing. Preserve unexpected local work and ask before broad refactors, rebases, branch changes involving uncommitted files, or destructive cleanup.
