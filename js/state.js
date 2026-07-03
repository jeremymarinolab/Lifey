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

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

export function normalizeStoredState(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const state = { ...value };
  state.tasks = arrayValue(state.tasks);
  state.accounts = arrayValue(state.accounts);
  state.places = arrayValue(state.places);
  state.placeLabels = arrayValue(state.placeLabels);
  state.integrations = objectValue(state.integrations, { notion: {}, google: {}, spotify: {}, gmail: {} });
  state.integrations.notion = objectValue(state.integrations.notion);
  state.integrations.google = objectValue(state.integrations.google);
  state.integrations.spotify = objectValue(state.integrations.spotify);
  state.integrations.gmail = objectValue(state.integrations.gmail);
  state.taskMappings = objectValue(state.taskMappings);
  state.spotify = objectValue(state.spotify);
  state.google = objectValue(state.google, { connected: false, events: [] });
  state.google.events = arrayValue(state.google.events);
  state.gmail = objectValue(state.gmail, { connected: false, messages: [] });
  state.gmail.messages = arrayValue(state.gmail.messages);
  state.projects = objectValue(state.projects, { projects: [], taskCount: 0 });
  state.projects.projects = arrayValue(state.projects.projects);
  state.habits = objectValue(state.habits, {});
  state.habits.today = arrayValue(state.habits.today);
  state.habits.expected = arrayValue(state.habits.expected);
  state.habits.history = arrayValue(state.habits.history);
  state.habits.dailyTotals = arrayValue(state.habits.dailyTotals);
  state.habits.habits = arrayValue(state.habits.habits);
  state.habits.active = arrayValue(state.habits.active);
  state.habits.archived = arrayValue(state.habits.archived);
  state.youtube = objectValue(state.youtube, { totalActiveSeconds: 0, videos: [] });
  state.youtube.videos = arrayValue(state.youtube.videos);
  state.traccar = objectValue(state.traccar, { connected: false, places: [] });
  state.traccar.places = arrayValue(state.traccar.places);
  state.mobileLocation = objectValue(state.mobileLocation, { configured: false, samples: 0, latest: '' });
  state.locationSettings = objectValue(state.locationSettings, { radiusMeters: 50, merges: [] });
  state.locationSettings.merges = arrayValue(state.locationSettings.merges);
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
