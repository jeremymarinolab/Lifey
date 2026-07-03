export function spotifyArtwork(item = {}) {
  return item.album?.images?.[0]?.url || item.images?.[0]?.url || '';
}

export function spotifyTrackFromItem(item = {}, playedAt = new Date().toISOString(), source = 'recently-played') {
  const track = item.track || item;
  const artists = (track.artists || []).map(artist => ({ id: artist.id || artist.name, name: artist.name || 'Unknown artist' }));
  return {
    playId: `${track.id || track.name || 'track'}:${playedAt}`,
    trackId: track.id || track.uri || track.name || '',
    title: track.name || 'Untitled track',
    artists,
    artist: artists.map(artist => artist.name).join(', ') || 'Unknown artist',
    album: track.album?.name || '',
    artwork: spotifyArtwork(track),
    durationMs: Number(track.duration_ms || 0),
    playedAt,
    lastSeen: playedAt,
    source
  };
}

export function spotifyRangeStart(range = 'today') {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  if (range === 'week') date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  if (range === 'month') date.setDate(1);
  return date;
}

export function spotifyHistoryForRange(spotify = {}, range = spotify.range || 'today') {
  const start = spotifyRangeStart(range).getTime();
  return (spotify.history || []).filter(play => new Date(play.playedAt || 0).getTime() >= start);
}

export function spotifyStats(spotify = {}, range = spotify.range || 'today') {
  const plays = spotifyHistoryForRange(spotify, range);
  const songs = new Map(), artists = new Map();
  for (const play of plays) {
    const minutes = Math.max(1, Math.round(Number(play.durationMs || 0) / 60000));
    const songKey = play.trackId || `${play.title}:${play.artist}`;
    const song = songs.get(songKey) || { title: play.title, artist: play.artist, artwork: play.artwork, playbacks: 0, minutes: 0 };
    song.playbacks += 1; song.minutes += minutes; if (!song.artwork && play.artwork) song.artwork = play.artwork; songs.set(songKey, song);
    for (const artist of play.artists || [{ id: play.artist, name: play.artist }]) {
      const artistKey = artist.id || artist.name;
      const row = artists.get(artistKey) || { name: artist.name, playbacks: 0, minutes: 0, artwork: play.artwork };
      row.playbacks += 1; row.minutes += minutes; if (!row.artwork && play.artwork) row.artwork = play.artwork; artists.set(artistKey, row);
    }
  }
  return {
    plays,
    songs: [...songs.values()].sort((a, b) => b.playbacks - a.playbacks || b.minutes - a.minutes).slice(0, 10),
    artists: [...artists.values()].sort((a, b) => b.minutes - a.minutes || b.playbacks - a.playbacks).slice(0, 10),
    minutes: plays.reduce((sum, play) => sum + Math.max(1, Math.round(Number(play.durationMs || 0) / 60000)), 0)
  };
}
