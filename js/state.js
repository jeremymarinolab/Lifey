export const STATE_STORAGE_KEY = 'lifey-state';
const LEGACY_STATE_STORAGE_KEY = 'command-center-state';

function parseStoredJson(raw) {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function objectValue(value, fallback = {}) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : fallback;
}

export function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

export function objectPayload(value, label = 'Payload') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} has an invalid shape.`);
  return value;
}

function stringValue(value, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function numberValue(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function booleanValue(value, fallback = false) {
  return typeof value === 'boolean' ? value : fallback;
}

function stringArray(value) {
  return arrayValue(value).map(item => String(item || '')).filter(Boolean);
}

function normalizeTask(task, index = 0) {
  if (!task || typeof task !== 'object' || Array.isArray(task)) return null;
  const text = stringValue(task.text || task.raw).trim();
  const source = stringValue(task.source, 'Unknown.md');
  const line = Math.max(1, numberValue(task.line, index + 1));
  if (!text) return null;
  return {
    ...task,
    id: stringValue(task.id, `${source}:${line}:${text}`),
    text,
    source,
    line,
    raw: stringValue(task.raw, task.raw === undefined ? text : ''),
    done: booleanValue(task.done),
    notion: booleanValue(task.notion),
    calendar: booleanValue(task.calendar),
  };
}

function normalizePlace(place) {
  if (!place || typeof place !== 'object' || Array.isArray(place)) return null;
  const name = stringValue(place.name || place.label).trim();
  if (!name) return null;
  return {
    ...place,
    name,
    source: stringValue(place.source, 'Manual'),
    latitude: place.latitude === undefined ? place.latitude : numberValue(place.latitude, 0),
    longitude: place.longitude === undefined ? place.longitude : numberValue(place.longitude, 0),
    totalSeconds: place.totalSeconds === undefined ? place.totalSeconds : numberValue(place.totalSeconds, 0),
    points: arrayValue(place.points).filter(point => point && typeof point === 'object' && !Array.isArray(point)),
  };
}

function normalizeHabitEntry(habit, index = 0) {
  if (!habit || typeof habit !== 'object' || Array.isArray(habit)) return null;
  const name = stringValue(habit.habit || habit.name).trim();
  if (!name) return null;
  const state = ['completed', 'pending', 'skipped', 'archived'].includes(habit.state) ? habit.state : 'pending';
  return { ...habit, habit: name, line: Math.max(1, numberValue(habit.line, index + 1)), state };
}

function normalizeProject(project) {
  if (!project || typeof project !== 'object' || Array.isArray(project)) return null;
  const slug = stringValue(project.slug).trim();
  const title = stringValue(project.title || slug).trim();
  if (!slug && !title) return null;
  const tasks = arrayValue(project.tasks).map(normalizeTask).filter(Boolean);
  return {
    ...project,
    slug: slug || title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''),
    title: title || slug,
    tasks,
    taskCount: Math.max(0, numberValue(project.taskCount, tasks.length)),
    completedCount: Math.max(0, numberValue(project.completedCount, tasks.filter(task => task.done).length)),
    openCount: Math.max(0, numberValue(project.openCount, tasks.filter(task => !task.done).length)),
  };
}

function normalizeYoutubeVideo(video) {
  if (!video || typeof video !== 'object' || Array.isArray(video)) return null;
  const title = stringValue(video.title || video.url || video.videoId).trim();
  if (!title) return null;
  return { ...video, title, activeSeconds: Math.max(0, numberValue(video.activeSeconds)), lastSeen: stringValue(video.lastSeen || video.capturedAt) };
}

function normalizeYoutubeDay(day) {
  if (!day || typeof day !== 'object' || Array.isArray(day)) return null;
  const date = stringValue(day.date).trim();
  if (!date) return null;
  return { ...day, date, videos: arrayValue(day.videos).map(normalizeYoutubeVideo).filter(Boolean), totalActiveSeconds: Math.max(0, numberValue(day.totalActiveSeconds)) };
}

function normalizeLocationDay(day) {
  if (!day || typeof day !== 'object' || Array.isArray(day)) return null;
  const date = stringValue(day.date).trim();
  if (!date) return null;
  return { ...day, date, places: arrayValue(day.places).map(normalizePlace).filter(Boolean) };
}

export function normalizeStoredState(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const state = { ...value };
  state.tasks = arrayValue(state.tasks).map(normalizeTask).filter(Boolean);
  state.accounts = arrayValue(state.accounts).filter(item => item && typeof item === 'object' && !Array.isArray(item));
  state.places = arrayValue(state.places).map(normalizePlace).filter(Boolean);
  state.placeLabels = arrayValue(state.placeLabels).map(normalizePlace).filter(Boolean);
  state.integrations = objectValue(state.integrations, { notion: {}, google: {}, spotify: {}, gmail: {} });
  state.integrations.notion = objectValue(state.integrations.notion);
  state.integrations.google = objectValue(state.integrations.google);
  if (state.integrations.google.clientSecret) delete state.integrations.google.clientSecret;
  state.integrations.spotify = objectValue(state.integrations.spotify);
  for (const key of ['accessToken', 'refreshToken', 'clientSecret']) delete state.integrations.spotify[key];
  state.integrations.gmail = objectValue(state.integrations.gmail);
  state.taskMappings = objectValue(state.taskMappings);
  state.spotify = objectValue(state.spotify);
  state.google = objectValue(state.google, { connected: false, events: [] });
  state.google.events = arrayValue(state.google.events);
  state.gmail = objectValue(state.gmail, { connected: false, messages: [] });
  state.gmail.messages = arrayValue(state.gmail.messages);
  state.projects = normalizeProjectsResponse(objectValue(state.projects, { projects: [], taskCount: 0 }));
  state.habits = objectValue(state.habits, {});
  state.habits.today = arrayValue(state.habits.today).map(normalizeHabitEntry).filter(Boolean);
  state.habits.expected = arrayValue(state.habits.expected).map(normalizeHabitEntry).filter(Boolean);
  state.habits.history = arrayValue(state.habits.history);
  state.habits.dailyTotals = arrayValue(state.habits.dailyTotals);
  state.habits.habits = stringArray(state.habits.habits);
  state.habits.active = arrayValue(state.habits.active).map(normalizeHabitEntry).filter(Boolean);
  state.habits.archived = arrayValue(state.habits.archived).map(normalizeHabitEntry).filter(Boolean);
  state.youtube = normalizeYoutubeActivityResponse(objectValue(state.youtube, { totalActiveSeconds: 0, videos: [] }));
  state.traccar = objectValue(state.traccar, { connected: false, places: [] });
  state.traccar.places = arrayValue(state.traccar.places).map(normalizePlace).filter(Boolean);
  if (state.traccar.week) state.traccar.week = normalizeLocationResponse(state.traccar.week, 'week');
  state.mobileLocation = objectValue(state.mobileLocation, { configured: false, samples: 0, latest: '' });
  state.locationSettings = normalizeLocationSettingsResponse(objectValue(state.locationSettings, { radiusMeters: 50, merges: [] }));
  state.visibility = objectValue(state.visibility);
  state.taskDisplay = objectValue(state.taskDisplay);
  state.contentDisplay = objectValue(state.contentDisplay);
  state.heroMetricVisibility = objectValue(state.heroMetricVisibility);
  state.appearance = objectValue(state.appearance);
  state.habitSettings = objectValue(state.habitSettings);
  return state;
}

export function loadStoredState() {
  return normalizeStoredState(parseStoredJson(localStorage.getItem(STATE_STORAGE_KEY)) || parseStoredJson(localStorage.getItem(LEGACY_STATE_STORAGE_KEY)));
}

export function saveStoredState(state) {
  localStorage.setItem(STATE_STORAGE_KEY, JSON.stringify(state));
}

export function normalizeDailyNoteResponse(data) {
  const note = objectPayload(data, 'Daily note response');
  if (typeof note.markdown !== 'string' || typeof note.path !== 'string') throw new Error('Daily note response is missing markdown or path.');
  return note;
}

export function normalizeProjectsResponse(data) {
  const payload = objectPayload(data, 'Projects response');
  const projects = arrayValue(payload.projects).map(normalizeProject).filter(Boolean);
  return {
    ...payload,
    projects,
    taskCount: Math.max(0, numberValue(payload.taskCount, projects.reduce((sum, project) => sum + project.taskCount, 0))),
    projectsPath: stringValue(payload.projectsPath),
    templatePath: stringValue(payload.templatePath),
  };
}

export function normalizeLocationResponse(data, view = 'today') {
  const payload = objectPayload(data, 'Location response');
  if (view === 'week') {
    const days = arrayValue(payload.days).map(normalizeLocationDay).filter(Boolean);
    return { ...payload, days, topPlaces: arrayValue(payload.topPlaces).map(normalizePlace).filter(Boolean), positions: Math.max(0, numberValue(payload.positions)), start: stringValue(payload.start) };
  }
  return { ...payload, places: arrayValue(payload.places).map(normalizePlace).filter(Boolean), positions: Math.max(0, numberValue(payload.positions)), source: stringValue(payload.source, 'Lifey Location') };
}

export function normalizePlaceLabelsResponse(data) {
  const payload = objectPayload(data, 'Place labels response');
  return { ...payload, labels: arrayValue(payload.labels).map(normalizePlace).filter(Boolean) };
}

export function normalizeLocationSettingsResponse(data) {
  const payload = objectPayload(data, 'Location settings response');
  return { ...payload, radiusMeters: Math.max(20, Math.min(500, numberValue(payload.radiusMeters, 50))), merges: arrayValue(payload.merges).filter(item => item && typeof item === 'object' && !Array.isArray(item)) };
}

export function normalizeHabitsTodayResponse(data) {
  const payload = objectPayload(data, 'Habits response');
  return { ...payload, habits: arrayValue(payload.habits).map(normalizeHabitEntry).filter(Boolean), expected: arrayValue(payload.expected).map(normalizeHabitEntry).filter(Boolean), archived: arrayValue(payload.archived).map(normalizeHabitEntry).filter(Boolean), date: stringValue(payload.date), path: stringValue(payload.path), configPath: stringValue(payload.configPath) };
}

export function normalizeHabitHistoryResponse(data) {
  const payload = objectPayload(data, 'Habit history response');
  return { ...payload, range: ['month', 'all'].includes(payload.range) ? payload.range : 'month', entries: arrayValue(payload.entries), dailyTotals: arrayValue(payload.dailyTotals), habits: stringArray(payload.habits), active: arrayValue(payload.active).map(normalizeHabitEntry).filter(Boolean), archived: arrayValue(payload.archived).map(normalizeHabitEntry).filter(Boolean) };
}

export function normalizeYoutubeActivityResponse(data) {
  const payload = objectPayload(data, 'YouTube response');
  const videos = arrayValue(payload.videos).map(normalizeYoutubeVideo).filter(Boolean);
  const days = arrayValue(payload.days).map(normalizeYoutubeDay).filter(Boolean);
  const week = payload.week && typeof payload.week === 'object' ? { ...payload.week, days: arrayValue(payload.week.days).map(normalizeYoutubeDay).filter(Boolean), videos: arrayValue(payload.week.videos).map(normalizeYoutubeVideo).filter(Boolean), totalActiveSeconds: Math.max(0, numberValue(payload.week.totalActiveSeconds)) } : payload.week;
  return { ...payload, videos, days, week, totalActiveSeconds: Math.max(0, numberValue(payload.totalActiveSeconds)), extensionLastSeen: stringValue(payload.extensionLastSeen), date: stringValue(payload.date) };
}

export function normalizeGoogleCalendarResponse(data) {
  const payload = objectPayload(data, 'Google Calendar response');
  return { ...payload, items: arrayValue(payload.items).filter(item => item && typeof item === 'object' && !Array.isArray(item)) };
}

export function normalizeGmailSuggestionsResponse(data) {
  const payload = objectPayload(data, 'Gmail response');
  return { ...payload, messages: arrayValue(payload.messages).filter(item => item && typeof item === 'object' && !Array.isArray(item)) };
}

export function normalizeProfileResponse(data) {
  const payload = objectPayload(data, 'Profile response');
  return { ...payload, preferences: objectValue(payload.preferences), location: objectValue(payload.location), obsidian: objectValue(payload.obsidian) };
}
