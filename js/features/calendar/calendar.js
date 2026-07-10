const DEFAULT_TIMEZONE = 'America/Guayaquil';

export const DEFAULT_CALENDAR_SCALE = {
  dayStart: 5 * 60,
  dayEnd: 23 * 60,
  pxPerHour: 42,
  snapMinutes: 15,
  minDurationMinutes: 30,
  timezone: DEFAULT_TIMEZONE,
};

export function normalizeCalendarScale(scale = {}) {
  const next = { ...DEFAULT_CALENDAR_SCALE, ...(scale || {}) };
  next.dayStart = clampNumber(next.dayStart, 0, 23 * 60, DEFAULT_CALENDAR_SCALE.dayStart);
  next.dayEnd = clampNumber(next.dayEnd, next.dayStart + 60, 24 * 60, DEFAULT_CALENDAR_SCALE.dayEnd);
  next.pxPerHour = clampNumber(next.pxPerHour, 28, 96, DEFAULT_CALENDAR_SCALE.pxPerHour);
  next.snapMinutes = clampNumber(next.snapMinutes, 5, 60, DEFAULT_CALENDAR_SCALE.snapMinutes);
  next.minDurationMinutes = clampNumber(next.minDurationMinutes, 15, 240, DEFAULT_CALENDAR_SCALE.minDurationMinutes);
  next.timezone = typeof next.timezone === 'string' && next.timezone ? next.timezone : DEFAULT_TIMEZONE;
  return next;
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

export function minutesFromDate(date) {
  return date.getHours() * 60 + date.getMinutes();
}

export function snapMinutes(minutes, snap = DEFAULT_CALENDAR_SCALE.snapMinutes) {
  const step = Math.max(1, Number(snap) || DEFAULT_CALENDAR_SCALE.snapMinutes);
  return Math.round(minutes / step) * step;
}

export function timeLabelFromMinutes(minutes) {
  const safe = Math.max(0, Math.min(24 * 60 - 1, Math.round(minutes)));
  const hour = Math.floor(safe / 60);
  const minute = safe % 60;
  const period = hour >= 12 ? 'PM' : 'AM';
  const displayHour = hour % 12 || 12;
  return `${String(displayHour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${period}`;
}

function isoDateFromEvent(event) {
  const raw = event?.start?.dateTime || event?.start?.date || '';
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10);
  return new Date().toLocaleDateString('en-CA');
}

function localDateTime(dateIso, minutes) {
  const safe = Math.max(0, Math.min(24 * 60 - 1, Math.round(minutes)));
  const hour = Math.floor(safe / 60);
  const minute = safe % 60;
  return `${dateIso}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00`;
}

export function eventPatchFromMinutes(event, startMinutes, endMinutes, scale = DEFAULT_CALENDAR_SCALE) {
  const timezone = normalizeCalendarScale(scale).timezone;
  const date = isoDateFromEvent(event);
  return {
    start: { dateTime: localDateTime(date, startMinutes), timeZone: timezone },
    end: { dateTime: localDateTime(date, endMinutes), timeZone: timezone },
  };
}

export function normalizeTimedCalendarEvent(event, scale = DEFAULT_CALENDAR_SCALE) {
  if (!event || typeof event !== 'object') return null;
  if (event.start?.date && !event.start?.dateTime) return null;
  const startDate = new Date(event.start?.dateTime || `${event.start?.date}T00:00:00`);
  const endDate = new Date(event.end?.dateTime || `${event.end?.date}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null;
  const startMinutes = minutesFromDate(startDate);
  const endMinutes = Math.max(startMinutes + 1, minutesFromDate(endDate));
  const normalizedScale = normalizeCalendarScale(scale);
  return {
    id: event.id || '',
    title: event.summary || '(Untitled event)',
    type: 'meeting',
    allDay: false,
    original: event,
    startIso: event.start?.dateTime || '',
    endIso: event.end?.dateTime || '',
    startMinutes,
    endMinutes,
    durationMinutes: endMinutes - startMinutes,
    time: timeLabelFromMinutes(startMinutes),
    end: timeLabelFromMinutes(endMinutes),
    geometry: eventGeometry(startMinutes, endMinutes, normalizedScale),
  };
}

export function eventGeometry(startMinutes, endMinutes, scale = DEFAULT_CALENDAR_SCALE) {
  const normalizedScale = normalizeCalendarScale(scale);
  const pxPerMinute = normalizedScale.pxPerHour / 60;
  const visibleStart = Math.max(normalizedScale.dayStart, Math.min(startMinutes, normalizedScale.dayEnd));
  const visibleEnd = Math.max(visibleStart + normalizedScale.minDurationMinutes, Math.min(endMinutes, normalizedScale.dayEnd));
  return {
    top: Math.max(0, (visibleStart - normalizedScale.dayStart) * pxPerMinute),
    height: Math.max(normalizedScale.minDurationMinutes * pxPerMinute, (visibleEnd - visibleStart) * pxPerMinute),
    outOfRange: startMinutes < normalizedScale.dayStart || endMinutes > normalizedScale.dayEnd,
  };
}

export function timelineHeight(scale = DEFAULT_CALENDAR_SCALE) {
  const normalizedScale = normalizeCalendarScale(scale);
  return (normalizedScale.dayEnd - normalizedScale.dayStart) * (normalizedScale.pxPerHour / 60);
}

export function calendarEmptyMessage(connected) {
  return connected ? '' : 'Connect Google Calendar to show today’s events.';
}

export function timelineTicks(scale = DEFAULT_CALENDAR_SCALE) {
  const normalizedScale = normalizeCalendarScale(scale);
  const ticks = [];
  for (let minute = normalizedScale.dayStart; minute <= normalizedScale.dayEnd; minute += 60) {
    ticks.push({
      minute,
      label: timeLabelFromMinutes(minute).replace(':00', ''),
      top: (minute - normalizedScale.dayStart) * (normalizedScale.pxPerHour / 60),
    });
  }
  return ticks;
}

export function eventMinutesFromDrag(original, deltaPixels, mode, scale = DEFAULT_CALENDAR_SCALE) {
  const normalizedScale = normalizeCalendarScale(scale);
  const deltaMinutes = snapMinutes(deltaPixels / (normalizedScale.pxPerHour / 60), normalizedScale.snapMinutes);
  let start = original.startMinutes;
  let end = original.endMinutes;
  if (mode === 'move') {
    const duration = end - start;
    start = snapMinutes(start + deltaMinutes, normalizedScale.snapMinutes);
    start = Math.max(normalizedScale.dayStart, Math.min(normalizedScale.dayEnd - duration, start));
    end = start + duration;
  } else if (mode === 'start') {
    start = snapMinutes(start + deltaMinutes, normalizedScale.snapMinutes);
    start = Math.max(normalizedScale.dayStart, Math.min(end - normalizedScale.minDurationMinutes, start));
  } else if (mode === 'end') {
    end = snapMinutes(end + deltaMinutes, normalizedScale.snapMinutes);
    end = Math.min(normalizedScale.dayEnd, Math.max(start + normalizedScale.minDurationMinutes, end));
  }
  return { startMinutes: start, endMinutes: end };
}
