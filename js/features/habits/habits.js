export const DEFAULT_HABIT_SETTINGS = {
  timezone: 'America/Guayaquil',
  periods: [
    { id: 'morning', name: 'Morning', start: '00:00', end: '12:00' },
    { id: 'afternoon', name: 'Afternoon', start: '12:00', end: '18:00' },
    { id: 'evening', name: 'Evening', start: '18:00', end: '23:59' }
  ]
};

export function timeToMinutes(value) {
  const match = String(value || '').match(/^([01]?\d|2[0-3]):([0-5]\d)$/);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

export function minutesInRange(minutes, start, end) {
  if (!Number.isFinite(minutes) || !Number.isFinite(start) || !Number.isFinite(end)) return false;
  return start <= end ? minutes >= start && minutes < end : minutes >= start || minutes < end;
}

export function habitPeriods(settings = DEFAULT_HABIT_SETTINGS) {
  return (settings?.periods || DEFAULT_HABIT_SETTINGS.periods)
    .map((period, index) => ({ ...period, id: period.id || `period-${index + 1}`, startMinutes: timeToMinutes(period.start), endMinutes: timeToMinutes(period.end) }))
    .filter(period => period.name && Number.isFinite(period.startMinutes) && Number.isFinite(period.endMinutes));
}

export function zonedParts(timezone = DEFAULT_HABIT_SETTINGS.timezone, fallbackDate = () => new Date().toLocaleDateString('en-CA')) {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date());
    const get = type => parts.find(part => part.type === type)?.value;
    let hour = Number(get('hour'));
    if (hour === 24) hour = 0;
    return { date: `${get('year')}-${get('month')}-${get('day')}`, minutes: hour * 60 + Number(get('minute')) };
  } catch {
    const now = new Date();
    return { date: fallbackDate(), minutes: now.getHours() * 60 + now.getMinutes() };
  }
}

export function habitPeriod(habit, settings = DEFAULT_HABIT_SETTINGS) {
  const minutes = Number(habit.timeMinutes);
  if (!Number.isFinite(minutes)) return 'anytime';
  return habitPeriods(settings).find(period => minutesInRange(minutes, period.startMinutes, period.endMinutes))?.id || 'anytime';
}

export function habitPeriodLabel(periodId, settings = DEFAULT_HABIT_SETTINGS) {
  return habitPeriods(settings).find(period => period.id === periodId)?.name || (periodId === 'anytime' ? 'Anytime' : periodId);
}

export function habitPeriodMeta(periodId, settings = DEFAULT_HABIT_SETTINGS) {
  const period = habitPeriods(settings).find(item => item.id === periodId);
  return period ? `${period.start} – ${period.end}` : 'No set time';
}

export function isMissedHabit(habit, state = {}, settings = DEFAULT_HABIT_SETTINGS, fallbackDate) {
  if (habit.state !== 'pending') return false;
  const now = zonedParts(settings?.timezone || DEFAULT_HABIT_SETTINGS.timezone, fallbackDate);
  const habitDate = habit.dueDate || state.habits?.date || now.date;
  if (habitDate > now.date) return false;
  if (habitDate < now.date) return true;
  const minutes = Number(habit.timeMinutes);
  if (!Number.isFinite(minutes)) return false;
  const period = habitPeriods(settings).find(item => item.id === habitPeriod(habit, settings));
  if (!period) return false;
  return period.startMinutes <= period.endMinutes ? now.minutes >= period.endMinutes : now.minutes >= period.endMinutes && now.minutes < period.startMinutes;
}

export function habitStreak(habit, state = {}, settings = DEFAULT_HABIT_SETTINGS, fallbackDate) {
  const name = String(habit.habit || '').trim().toLowerCase();
  const byDate = new Map((state.habits?.history || []).filter(entry => String(entry.habit || '').trim().toLowerCase() === name).map(entry => [entry.date, entry.state]));
  if (habit.date) byDate.set(habit.date, habit.state);
  const dates = [...byDate.keys()].filter(Boolean).sort().reverse();
  const today = zonedParts(settings?.timezone || DEFAULT_HABIT_SETTINGS.timezone, fallbackDate).date;
  let started = false, count = 0;
  for (const date of dates) {
    const value = byDate.get(date);
    if (!started && date === today && value !== 'completed') continue;
    started = true;
    if (value !== 'completed') break;
    count += 1;
  }
  return count;
}
