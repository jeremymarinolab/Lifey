import { badge, escape } from '../../renderers.js';
import { emptyState } from '../../ui/components.js';
import { button, segmentedControl } from '../../ui/controls.js';
import { SPOTIFY_RANGE_OPTIONS, SPOTIFY_VIEW_OPTIONS, YOUTUBE_VIEW_OPTIONS } from '../../ui/config.js';
import { durationLabel } from '../location/location.js';

export function renderSpotifySummary({ spotify, currentTrack }) {
  const periodStats = spotify.stats || { minutes: 0, playCount: 0, songs: [], artists: [] };
  const minutes = Number(periodStats.minutes || 0);
  const artworkUrl = currentTrack?.artwork || '';
  const artwork = `<div class="spotify-art large ${currentTrack?.isPlaying ? 'is-playing' : ''}"><span class="spotify-vinyl"></span>${artworkUrl ? `<img src="${escape(artworkUrl)}" alt="${escape(currentTrack?.title || 'Spotify album artwork')}" loading="lazy">` : '<div class="album">◒</div>'}</div>`;
  const rows = (spotify.view === 'songs' ? periodStats.songs || [] : periodStats.artists || []).map((item, index) => {
    const main = spotify.view === 'songs' ? item.title : item.name;
    const meta = spotify.view === 'songs' ? `${item.artist} · ${item.playbacks} playback${item.playbacks === 1 ? '' : 's'} · ${durationLabel(item.minutes * 60)}` : `${durationLabel(item.minutes * 60)} · ${item.playbacks} playback${item.playbacks === 1 ? '' : 's'}`;
    return `<div class="spotify-stat-row"><span>${String(index + 1).padStart(2, '0')}</span>${item.artwork ? `<img src="${escape(item.artwork)}" alt="" loading="lazy">` : '<i>◒</i>'}<p><strong>${escape(main)}</strong><small>${escape(meta)}</small></p></div>`;
  }).join('');
  const status = spotify.error ? spotify.errorKind === 'expired' ? 'reconnect' : 'needs attention' : spotify.connected ? 'connected' : 'not connected';
  const statusKind = spotify.error ? 'estimated' : spotify.connected ? 'captured' : 'manual';
  const title = minutes ? `${durationLabel(minutes * 60)} ${spotify.range || 'today'}` : spotify.connected ? 'Listening history' : 'Spotify';
  const count = periodStats.playCount || 0;
  const meta = `${count} captured play${count === 1 ? '' : 's'} · estimated listening time`;
  const trackMeta = currentTrack?.artist || (spotify.error || (spotify.connected ? 'Nothing playing right now' : 'Connect Spotify to see current playback'));
  const nowTitle = currentTrack?.title || (spotify.connected ? 'Nothing playing right now' : 'Connect Spotify');
  const viewTabs = segmentedControl(SPOTIFY_VIEW_OPTIONS, { className: 'segmented-control media-switch spotify-switch', action: 'set-spotify-view', dataKey: 'view', selectedWhen: item => spotify.view === item.value || (item.value === 'artists' && spotify.view !== 'songs') });
  const rangeTabs = segmentedControl(SPOTIFY_RANGE_OPTIONS, { className: 'segmented-filter spotify-range', action: 'set-spotify-range', dataKey: 'range', selected: spotify.range });
  const connectPrompt = !spotify.connected ? `<div class="spotify-connect-prompt">${button('Connect Spotify', { action: 'connect-spotify' })}<small>Spotify developer app owners need Premium. Recent plays are saved on this Mac.</small></div>` : '';
  const syncLabel = spotify.lastSync ? `Last synced ${new Date(spotify.lastSync).toLocaleString()}` : 'No completed plays synced yet';
  const coverage = spotify.historyGapUnrecoverable ? 'Spotify could not supply a gap between syncs; totals are incomplete.' : spotify.historyGap ? 'A gap between syncs is being recovered; totals may be incomplete.' : spotify.backfillComplete ? 'Spotify has no older plays available through this API.' : spotify.connected ? 'Earlier plays are still being checked; historical totals may be incomplete.' : 'Reconnect to update saved history.';
  const stale = spotify.connected && spotify.lastSync && Date.now() - new Date(spotify.lastSync).getTime() > 75 * 60_000;
  const historyView = spotify.connected || count ? `${viewTabs}${rangeTabs}<div class="spotify-stat-list">${rows || emptyState('No completed Spotify plays available for this period.', 'muted spotify-empty')}</div>` : '';
  const syncNote = spotify.lastSync ? `<p class="spotify-limited">${stale ? 'Sync overdue · ' : ''}${escape(syncLabel)} · ${escape(coverage)}</p>` : '';
  const body = `<div class="spotify-now-v2">${artwork}<div class="spotify-now-copy"><small>${currentTrack?.isPlaying ? 'Now playing' : currentTrack?.type === 'episode' ? 'Podcast' : 'Spotify'}</small><strong>${escape(nowTitle)}</strong><span>${escape(trackMeta)}</span></div></div>${connectPrompt}${historyView}${syncNote}${spotify.error ? `<p class="spotify-limited" role="status">${escape(spotify.error)}</p>` : ''}`;
  return { minutes, title, meta, status, statusKind, body };
}

export function renderYoutubeWeekContent({ youtubeWeekData, selectedDay, activeVideos, activeSeconds }) {
  return `<div class="week-days youtube-week">${youtubeWeekData.days?.length ? `${segmentedControl(youtubeWeekData.days.map(day => { const date = new Date(`${day.date}T12:00:00`); return { value: day.date, label: `<span>${date.toLocaleDateString([], { weekday: 'short' })}</span><b>${date.getDate()}</b>` }; }), { className: 'week-day-switch', action: 'set-youtube-week-day', dataKey: 'date', selected: selectedDay?.date })}<div class="week-day"><div class="week-day-summary"><p>${new Date(`${selectedDay.date}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })}</p><span><small>Total time</small><strong>${activeVideos.length ? durationLabel(activeSeconds) : '0 min'}</strong></span></div></div>` : emptyState('Load this week to see watched videos by day.')}</div>`;
}

export function renderYoutubeViewTabs(selectedView) {
  return segmentedControl(YOUTUBE_VIEW_OPTIONS, { className: 'segmented-control media-switch', action: 'set-youtube-view', dataKey: 'view', selected: selectedView });
}

export function renderVideoRows(videos, { extensionLastSeen = false } = {}) {
  return (videos.length ? videos.map(video => [video.title, durationLabel(video.activeSeconds), new Date(video.lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), 'Captured']) : [[extensionLastSeen ? 'Tracker connected — reload a YouTube video' : 'Tracker has not reached the local helper', '—', 'Zen / Firefox', 'Setup']]).map(v => `<div><span class="play">▶</span><p>${escape(v[0])}<small>${v[2]} · ${v[1]}</small></p>${badge(v[3], 'captured')}</div>`).join('');
}
