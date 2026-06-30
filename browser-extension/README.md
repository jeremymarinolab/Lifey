# Lifey — YouTube tracker

This Zen/Firefox-first extension records only YouTube watch-page title, URL,
first/last seen, and visible/focused tab seconds. It posts to the local helper
at `http://127.0.0.1:4173`; no YouTube or Google account access is requested.

## Install temporarily in Zen

1. Start the dashboard with `npm start`.
2. Open `about:debugging#/runtime/this-firefox`.
3. Choose **Load Temporary Add-on**.
4. Select this folder's `manifest.json`.

The extension stays installed until Zen restarts.

## Install permanently in Zen

Zen/Firefox release builds require Mozilla to sign extensions before they can
stay installed across restarts. This does **not** require listing the tracker
publicly:

1. Run `./browser-extension/package.sh` from the Lifey project folder.
2. Go to the [AMO Developer Hub](https://addons.mozilla.org/developers/) and
   submit the generated `.xpi` as an **unlisted** / self-distributed add-on.
3. Download Mozilla's signed `.xpi` after validation.
4. In Zen, open `about:addons`, use the gear menu, choose **Install Add-on From
   File**, and select the signed `.xpi`.

After that one-time install, it survives Zen restarts. Keep the signed XPI in
a safe place; updates can be signed and installed the same way.
