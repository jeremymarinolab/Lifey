# Today Command Center — MVP

A dependency-light, local-first prototype for a personal daily dashboard. Run `npm start` and open `http://localhost:4173`.

## Architecture

- **UI shell:** static, responsive browser app with local state persisted in `localStorage`.
- **Local data boundary:** task records include Obsidian source/line metadata; actions retain local mapping flags for idempotent Notion and Calendar sends. This becomes a small local SQLite/JSON repository in the desktop wrapper.
- **Adapters:** Obsidian filesystem read/write; Notion API; Google OAuth + Calendar; Spotify OAuth; Gmail search/RSS; browser-extension capture. Each adapter is optional and labels its data quality.
- **Platform limits:** YouTube and Instagram are browser-capture/import based; Maps is manual/import/custom-logger based. Nothing assumes private data or unreliable timeline APIs.
- **Archive contract:** generated Markdown replaces only content between `<!-- DASHBOARD:START -->` and `<!-- DASHBOARD:END -->`, after a timestamped backup.

## MVP implementation notes

The app demonstrates the local-first interaction model, task mapping behavior, editable event defaults, account import, manual places, daily archive preview, and local-only retrieval answer. Production connections should keep OAuth/API credentials in the OS keychain and move app state from `localStorage` to a local repository before enabling real account data.
