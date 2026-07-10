import { badge, escape } from '../../renderers.js';
import { emptyState } from '../../ui/components.js';
import { button, iconButton, segmentedControl } from '../../ui/controls.js';
import { SPOTIFY_RANGE_OPTIONS, SPOTIFY_VIEW_OPTIONS, YOUTUBE_VIEW_OPTIONS } from '../../ui/config.js';
import { durationLabel } from '../location/location.js';

export function renderSpotifySummary({ spotify, spotifyStats, currentTrack }) {
  const periodStats = spotifyStats(spotify, spotify.range || 'today');
  const minutes = Number(periodStats.minutes || 0);
  const artworkUrl = currentTrack?.artwork || '';
  const artwork = `<div class="spotify-art large ${currentTrack?.isPlaying ? 'is-playing' : ''}"><span class="spotify-vinyl"></span>${artworkUrl ? `<img src="${escape(artworkUrl)}" alt="${escape(currentTrack?.title || 'Spotify album artwork')}" loading="lazy">` : '<div class="album">◒</div>'}</div>`;
  const rows = (spotify.view === 'songs' ? periodStats.songs : periodStats.artists).map((item, index) => {
    const main = spotify.view === 'songs' ? item.title : item.name;
    const meta = spotify.view === 'songs' ? `${item.artist} · ${item.playbacks} playback${item.playbacks === 1 ? '' : 's'} · ${durationLabel(item.minutes * 60)}` : `${durationLabel(item.minutes * 60)} · ${item.playbacks} playback${item.playbacks === 1 ? '' : 's'}`;
    return `<div class="spotify-stat-row"><span>${String(index + 1).padStart(2, '0')}</span>${item.artwork ? `<img src="${escape(item.artwork)}" alt="" loading="lazy">` : '<i>◒</i>'}<p><strong>${escape(main)}</strong><small>${escape(meta)}</small></p></div>`;
  }).join('');
  const status = spotify.connected ? (spotify.endpointNotes?.length ? 'partial' : 'connected') : 'not connected';
  const statusKind = spotify.connected ? (spotify.endpointNotes?.length ? 'estimated' : 'captured') : 'manual';
  const title = spotify.connected ? (minutes ? `${durationLabel(minutes * 60)} ${spotify.range || 'today'}` : 'Listening history') : 'Spotify';
  const meta = spotify.connected ? `${periodStats.plays.length} captured play${periodStats.plays.length === 1 ? '' : 's'} · local history` : 'Connect Spotify to start local listening history';
  const trackMeta = currentTrack?.artist || (spotify.connected ? (spotify.nowStatus || 'Play something in Spotify to wake this card up') : 'Current song, top artists, and top songs');
  const nowTitle = currentTrack?.title || (spotify.connected ? 'Nothing playing right now' : 'Connect Spotify');
  const viewTabs = segmentedControl(SPOTIFY_VIEW_OPTIONS, { className: 'segmented-control media-switch spotify-switch', action: 'set-spotify-view', dataKey: 'view', selectedWhen: item => spotify.view === item.value || (item.value === 'artists' && spotify.view !== 'songs') });
  const rangeTabs = segmentedControl(SPOTIFY_RANGE_OPTIONS, { className: 'segmented-filter spotify-range', action: 'set-spotify-range', dataKey: 'range', selected: spotify.range });
  const connectPrompt = !spotify.connected ? `<div class="spotify-connect-prompt">${button('Connect Spotify', { action: 'connect-spotify' })}<small>Premium is not required. Lifey stores listening history locally from now on.</small></div>` : '';
  const body = `<div class="spotify-now-v2">${artwork}<div class="spotify-now-copy"><small>${currentTrack?.isPlaying ? 'Now playing' : 'Spotify'}</small><strong>${escape(nowTitle)}</strong><span>${escape(trackMeta)}</span></div>${iconButton(spotify.connected ? '↻' : '↗', { action: 'connect-spotify', title: spotify.connected ? 'Refresh Spotify' : 'Connect Spotify' })}</div>${connectPrompt}${spotify.connected ? `${viewTabs}${rangeTabs}<div class="spotify-stat-list">${rows || emptyState('No captured Spotify plays for this period yet. Keep Lifey open while listening, or refresh after Spotify has recent plays.', 'muted spotify-empty')}</div>` : ''}${spotify.endpointNotes?.length ? `<p class="spotify-limited">${escape(spotify.nowStatus || 'Some Spotify endpoints are unavailable, but local history still works when playback can be read.')}</p>` : ''}`;
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
