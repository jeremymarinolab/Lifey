export function durationLabel(seconds) {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return '<1 min';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60), remainder = minutes % 60;
  return `${hours} hour${hours === 1 ? '' : 's'}${remainder ? `, ${remainder} min` : ''}`;
}

export function clockTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function totalTimeLabel(milliseconds) {
  const minutes = Math.max(0, Math.round(milliseconds / 60000));
  if (minutes < 1) return '<1 min';
  const hours = Math.floor(minutes / 60), remainder = minutes % 60;
  return hours ? `${hours}h${remainder ? ` ${remainder}m` : ''}` : `${remainder} min`;
}

export function placeDurationMilliseconds(place) {
  if (Number.isFinite(Number(place.totalSeconds))) return Math.max(0, Number(place.totalSeconds) * 1000);
  const arrival = new Date(place.arrival), departure = new Date(place.departure);
  return Number.isNaN(arrival.getTime()) || Number.isNaN(departure.getTime()) ? 0 : Math.max(0, departure.getTime() - arrival.getTime());
}

export function placeTiming(place) {
  if (place.time) return { range: place.time, total: '' };
  const arrival = new Date(place.arrival), departure = new Date(place.departure);
  if (Number.isNaN(arrival.getTime()) || Number.isNaN(departure.getTime())) return { range: 'Time unavailable', total: '' };
  const visits = Number(place.visits || 1);
  const estimatedMilliseconds = Number.isFinite(Number(place.totalSeconds)) ? Number(place.totalSeconds) * 1000 : departure.getTime() - arrival.getTime();
  return {
    range: `${visits > 1 ? `${visits} visits · ` : ''}${clockTime(place.arrival)} → ${clockTime(place.departure)}`,
    total: `Estimated time there today: ${totalTimeLabel(estimatedMilliseconds)}`
  };
}
