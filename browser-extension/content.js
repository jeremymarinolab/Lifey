let firstSeen = new Date().toISOString();
let previousTick = Date.now();
let bufferedSeconds = 0;

function payload(seconds = 0) {
  return {
    title: document.title.replace(/\s*-\s*YouTube$/i, '').trim() || 'YouTube video',
    url: location.href,
    firstSeen,
    lastSeen: new Date().toISOString(),
    activeSeconds: seconds
  };
}
function active() { return document.visibilityState === 'visible' && document.hasFocus(); }
function report(seconds) { browser.runtime.sendMessage({ type: 'youtube-activity', payload: payload(seconds) }); }

report(0);
setInterval(() => {
  const now = Date.now(); const elapsed = Math.min((now - previousTick) / 1000, 20); previousTick = now;
  if (active()) bufferedSeconds += elapsed;
  if (bufferedSeconds >= 10) { report(Math.round(bufferedSeconds)); bufferedSeconds = 0; }
}, 5000);
addEventListener('beforeunload', () => { if (bufferedSeconds > 0) report(Math.round(bufferedSeconds)); });
addEventListener('yt-navigate-finish', () => { firstSeen = new Date().toISOString(); bufferedSeconds = 0; report(0); });
