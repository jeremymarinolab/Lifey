const runtime = globalThis.browser?.runtime ?? globalThis.chrome?.runtime;

let firstSeen = new Date().toISOString();
let previousTick = Date.now();
let bufferedSeconds = 0;
let currentVideoId = '';

function videoInfo() {
  const url = new URL(location.href);
  let videoId = '';
  let kind = 'watch';
  if (url.pathname === '/watch') videoId = url.searchParams.get('v') || '';
  else if (url.pathname.startsWith('/shorts/')) {
    videoId = url.pathname.split('/').filter(Boolean)[1] || '';
    kind = 'shorts';
  }
  if (!videoId) return null;
  return {
    videoId,
    kind,
    url: kind === 'shorts' ? `https://www.youtube.com/shorts/${videoId}` : `https://www.youtube.com/watch?v=${videoId}`
  };
}

function cleanTitle() {
  return document.title.replace(/\s*-\s*YouTube$/i, '').trim() || 'YouTube video';
}

function payload(seconds = 0) {
  const info = videoInfo();
  if (!info) return null;
  return {
    title: cleanTitle(),
    url: info.url,
    videoId: info.videoId,
    kind: info.kind,
    firstSeen,
    lastSeen: new Date().toISOString(),
    activeSeconds: Math.max(0, Math.round(seconds))
  };
}

function active() {
  const video = document.querySelector('video');
  return Boolean(
    video &&
    !video.paused &&
    !video.ended &&
    video.readyState >= 2 &&
    document.visibilityState === 'visible' &&
    document.hasFocus()
  );
}

function report(seconds = 0) {
  const body = payload(seconds);
  if (body && runtime) runtime.sendMessage({ type: 'youtube-activity', payload: body });
}

function flush() {
  if (bufferedSeconds > 0) {
    report(bufferedSeconds);
    bufferedSeconds = 0;
  }
}

function resetForCurrentVideo() {
  const info = videoInfo();
  const nextVideoId = info?.videoId || '';
  if (nextVideoId === currentVideoId) return;
  flush();
  currentVideoId = nextVideoId;
  firstSeen = new Date().toISOString();
  previousTick = Date.now();
  bufferedSeconds = 0;
  if (currentVideoId) report(0);
}

resetForCurrentVideo();

setInterval(() => {
  resetForCurrentVideo();
  const now = Date.now();
  const elapsed = Math.min((now - previousTick) / 1000, 15);
  previousTick = now;
  if (active()) bufferedSeconds += elapsed;
  if (bufferedSeconds >= 5) flush();
}, 3000);

addEventListener('beforeunload', flush);
addEventListener('pagehide', flush);
addEventListener('yt-navigate-start', flush);
addEventListener('yt-navigate-finish', resetForCurrentVideo);
