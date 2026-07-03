import { actionPayload, actionTarget } from './js/actions.js';
import { localRequest } from './js/api.js';
import { CAPTURE_PRIORITIES, CAPTURE_RECURRENCES, captureDayTimeLabel, capturePriorityLabel, captureRecurringLabel, parseNaturalTask, taskCaptureValues } from './js/features/capture/capture.js';
import { handleCaptureAction, handleCaptureInput, handleCaptureKeydown } from './js/features/capture/controller.js';
import { DEFAULT_HABIT_SETTINGS, habitPeriod as habitPeriodForSettings, habitPeriodLabel as habitPeriodLabelForSettings, habitPeriodMeta as habitPeriodMetaForSettings, habitPeriods as habitPeriodsForSettings, habitStreak as habitStreakForState, isMissedHabit as isMissedHabitForState, timeToMinutes, zonedParts as zonedPartsForSettings } from './js/features/habits/habits.js';
import { handleLocationAction } from './js/features/location/controller.js';
import { clockTime, durationLabel, placeDurationMilliseconds, placeTiming, totalTimeLabel } from './js/features/location/location.js';
import { handlePreferenceAction, handlePreferenceChange, handlePreferenceInput } from './js/features/preferences/controller.js';
import { handleProjectAction } from './js/features/projects/controller.js';
import { spotifyArtwork, spotifyStats, spotifyTrackFromItem } from './js/integrations/spotify.js';
import { parseTasks } from './js/parsers.js';
import { badge, escape, stat } from './js/renderers.js';
import { loadStoredState, saveStoredState } from './js/state.js';

function todayIso() { return new Date().toLocaleDateString('en-CA'); }
function todayJournalDate() { return new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(new Date()); }
function todayJournalDatePadded() { return new Intl.DateTimeFormat('en-US', { month: 'long', day: '2-digit', year: 'numeric' }).format(new Date()); }
function dailyNoteNameSet() { return new Set([`${todayJournalDate()}.md`, `${todayJournalDatePadded()}.md`, `${todayIso()}.md`]); }
function currentWeekStartIso() { const date = new Date(); date.setHours(12, 0, 0, 0); date.setDate(date.getDate() - ((date.getDay() + 6) % 7)); return date.toLocaleDateString('en-CA'); }
let vaultHandle;
let selectedDailyNote;
const ARCHIVE_MARKER = '---';
const LEGACY_ARCHIVE_START = '<!-- DASHBOARD:START -->', LEGACY_ARCHIVE_END = '<!-- DASHBOARD:END -->';
const HERO_METRIC_KEYS = ['tasks', 'projects', 'habits', 'calendar', 'youtube', 'spotify', 'places', 'suggestions'];
const CARD_KEYS = ['tasks', 'calendar', 'youtube', 'projects', 'suggestions', 'places', 'habits', 'spotify'];
const DEFAULT_LOCATION_ARCHIVE_TEMPLATES = {
  weekly: '---\n## Lifey · {{period}}\n\n### Top places\n{{topPlaces}}\n\n### Days\n{{dailyPlaces}}\n---',
  monthly: '---\n## Lifey · {{period}}\n\n### Top places\n{{topPlaces}}\n---',
  yearly: '---\n## Lifey · {{period}}\n\n### Top places\n{{topPlaces}}\n---'
};
const DEFAULT_ARCHIVE_TITLES = { daily: 'Lifey · MMMM DD, YYYY', weekly: 'Lifey · {{period}}', monthly: 'Lifey · {{period}}', yearly: 'Lifey · {{period}}' };
const DEFAULT_ARCHIVE_TEMPLATE = `---
## Lifey · {{date}}

### Tasks
- {{notionTasks}} task(s) sent to Notion
- {{calendarTasks}} task(s) added to Google Calendar

### Activity
- YouTube: {{youtubeTime}} (estimated; browser capture)
- Spotify: {{spotifyTime}} (estimated; API activity)

### Places
{{places}}

### Useful finding
- No useful findings recorded.
---`;
const state = loadStoredState() || {
  tasks: [],
  accounts: [],
  places: [],
  question: '',
  integrations: { notion: {}, google: {}, spotify: {}, gmail: {} },
};
state.tasks ||= [];
state.accounts ||= [];
state.integrations ||= { notion: {}, google: {}, spotify: {}, gmail: {} };
if (state.integrations.google?.clientSecret) delete state.integrations.google.clientSecret;
state.spotify ||= {};
state.spotify = {
  connected: Boolean(state.spotify.accessToken || state.spotify.connected),
  accessToken: state.spotify.accessToken || '',
  refreshToken: state.spotify.refreshToken || '',
  profile: state.spotify.profile || null,
  current: state.spotify.current || null,
  history: Array.isArray(state.spotify.history) ? state.spotify.history : [],
  view: ['artists', 'songs'].includes(state.spotify.view) ? state.spotify.view : 'artists',
  range: ['today', 'week', 'month'].includes(state.spotify.range) ? state.spotify.range : 'today',
  minutes: Number(state.spotify.minutes || 0),
  errors: [],
  lastSync: state.spotify.lastSync || ''
};
state.google ||= { connected: false, events: [] };
if (!state.google.tokenExpiresAt || state.google.tokenExpiresAt <= Date.now()) {
  state.google = { ...state.google, accessToken: '', connected: false, sessionExpired: Boolean(state.google.accessToken || state.google.sessionExpired) };
}
if ((state.google.events || []).length && state.google.eventsDate !== todayIso()) state.google.events = [];
state.gmail ||= { connected: false, messages: [] };
state.localVaultPath ||= '';
state.notion ||= { configured: false };
state.projects ||= { projects: [], taskCount: 0, projectsPath: '', templatePath: '' };
state.habits ||= { view: 'today', range: 'month', today: [], expected: [], history: [], dailyTotals: [], habits: [], active: [], archived: [], selectedHabit: '', expandedArchive: '' };
state.habitSettings = { ...DEFAULT_HABIT_SETTINGS, ...(state.habitSettings || {}), periods: (state.habitSettings?.periods?.length ? state.habitSettings.periods : DEFAULT_HABIT_SETTINGS.periods).map((period, index) => ({ id: period.id || `period-${index + 1}`, name: period.name || `Period ${index + 1}`, start: period.start || '00:00', end: period.end || '23:59' })) };
state.youtube ||= { totalActiveSeconds: 0, videos: [] };
if ((state.youtube.videos || []).length && state.youtube.date !== todayIso()) state.youtube = { ...state.youtube, date: todayIso(), videos: [], totalActiveSeconds: 0 };
state.youtubeView ||= 'today';
state.youtubeWeekDay = state.youtube.week?.days?.some(day => day.date === state.youtubeWeekDay) ? state.youtubeWeekDay : todayIso();
state.traccar ||= { connected: false, places: [] };
state.places ||= [];
state.placeLabels ||= [];
if ((state.traccar.places || []).length && state.traccar.placesDate !== todayIso()) state.traccar = { ...state.traccar, places: [] };
if (state.traccar.week?.start && state.traccar.week.start !== currentWeekStartIso()) state.traccar = { ...state.traccar, week: { days: [], topPlaces: [], start: currentWeekStartIso() } };
state.mobileLocation ||= { configured: false, samples: 0, latest: '' };
state.locationSettings ||= { radiusMeters: 50, merges: [] };
state.googlePlaces ||= { configured: false };
state.osmPlaces ||= { configured: false };
state.archiveTemplate ||= DEFAULT_ARCHIVE_TEMPLATE;
function normaliseAppearance(appearance = {}) {
  const next = { background: '#2F383E', glass: '#6f9084', accent: '#ff6e55', backgroundImage: '', backgroundTint: '#15221f', backgroundTintIntensity: 72, cornerRadius: 24, ...appearance };
  next.backgroundTintIntensity = Math.max(0, Math.min(95, Number(next.backgroundTintIntensity ?? 72)));
  next.cornerRadius = Math.max(8, Math.min(36, Number(next.cornerRadius ?? 24)));
  return next;
}
state.appearance = normaliseAppearance(state.appearance);
state.visibility = { tasks: true, projects: true, habits: true, calendar: true, youtube: true, spotify: true, suggestions: true, instagram: true, places: true, ...(state.visibility || {}) };
state.taskDisplay = { showPath: true, ...(state.taskDisplay || {}) };
state.contentDisplay = { limit: 6, youtubeSize: 'medium', youtubeSort: 'duration', ...(state.contentDisplay || {}) };
if (!['small', 'medium', 'large'].includes(state.contentDisplay.youtubeSize)) state.contentDisplay.youtubeSize = 'medium';
if (!['duration', 'time'].includes(state.contentDisplay.youtubeSort)) state.contentDisplay.youtubeSort = 'duration';
function normaliseHeroMetricOrder(order = state.heroMetricOrder) { return [...new Set([...(Array.isArray(order) ? order : []), ...HERO_METRIC_KEYS])].filter(key => HERO_METRIC_KEYS.includes(key)); }
function normaliseCardOrder(order = state.cardOrder) { return [...new Set([...(Array.isArray(order) ? order : []), ...CARD_KEYS])].filter(key => CARD_KEYS.includes(key)); }
state.heroMetricOrder = normaliseHeroMetricOrder();
state.cardOrder = normaliseCardOrder();
state.heroMetricVisibility = HERO_METRIC_KEYS.reduce((visibility, key) => ({ ...visibility, [key]: state.heroMetricVisibility?.[key] !== false }), {});
state.locationView ||= 'today';
state.locationWeekDay = state.traccar.week?.days?.some(day => day.date === state.locationWeekDay) ? state.locationWeekDay : todayIso();
let placeMergeMode = false;
let placeMergeSelection = [];
state.locationArchiveTemplates = { ...DEFAULT_LOCATION_ARCHIVE_TEMPLATES, ...(state.locationArchiveTemplates || {}) };
state.archiveTitles = { ...DEFAULT_ARCHIVE_TITLES, ...(state.archiveTitles || {}) };
if (state.archiveTitles.daily === 'Lifey · mmm dd, yyyy') state.archiveTitles.daily = DEFAULT_ARCHIVE_TITLES.daily;
state.taskMappings ||= {};
for (const task of state.tasks) {
  if (task.notionPageId || task.calendarEventId) state.taskMappings[`${task.source}:${task.line}`] ||= { notionPageId: task.notionPageId || '', notionUrl: task.notionUrl || '', calendarEventId: task.calendarEventId || '' };
}
state.taskDate ||= todayIso();
if (state.taskDate !== todayIso()) { state.tasks = state.tasks.filter(task => !task.done); state.taskDate = todayIso(); persist(); }

function hexToRgb(hex = '#15221f') {
  const value = String(hex).replace('#', '').trim();
  const full = value.length === 3 ? value.split('').map(char => char + char).join('') : value;
  const number = Number.parseInt(full, 16);
  if (!Number.isFinite(number)) return '21, 34, 31';
  return `${(number >> 16) & 255}, ${(number >> 8) & 255}, ${number & 255}`;
}
function applyAppearance() {
  document.documentElement.style.setProperty('--bg', state.appearance.background);
  document.documentElement.style.setProperty('--glass-tint', state.appearance.glass);
  document.documentElement.style.setProperty('--accent', state.appearance.accent);
  document.documentElement.style.setProperty('--ui-radius', `${state.appearance.cornerRadius}px`);
  document.documentElement.style.setProperty('--card-radius', `${state.appearance.cornerRadius}px`);
  document.documentElement.style.setProperty('--button-radius', `${Math.max(8, Math.round(state.appearance.cornerRadius * .68))}px`);
  document.documentElement.style.setProperty('--dashboard-image', state.appearance.backgroundImage ? `url("${state.appearance.backgroundImage}")` : 'none');
  document.documentElement.style.setProperty('--dashboard-tint-rgb', hexToRgb(state.appearance.backgroundTint || '#15221f'));
  const tintOpacity = Number(state.appearance.backgroundTintIntensity ?? 72) / 100;
  document.documentElement.style.setProperty('--dashboard-tint-opacity', String(tintOpacity.toFixed(2)));
  document.documentElement.style.setProperty('--dashboard-tint-soft-opacity', String(Math.max(0, tintOpacity * 0.82).toFixed(2)));
  document.body.classList.toggle('has-dashboard-image', Boolean(state.appearance.backgroundImage));
}
applyAppearance();

const EMPTY_CALENDAR_EVENTS = [];
const EMPTY_INSPIRATION_FIXTURES = [
  { source: 'YouTube · The Futur', time: '36 min', title: 'How great designers make a case for their work', why: 'Matches your prototype-review focus today.' },
  { source: 'Medium Digest', time: '7 min', title: 'The quiet craft of product strategy', why: 'Fresh newsletter link; unread and relevant to your design work.' },
  { source: 'YouTube · NN/g', time: '14 min', title: 'Making dashboards people actually use', why: 'You watched adjacent UI research this morning.' },
  { source: 'Manual source · Dense Discovery', time: '5 min', title: 'A small tool for collecting better ideas', why: 'High-quality source, saved for later.' },
  { source: 'Gmail · Lenny’s Newsletter', time: '12 min', title: 'Leading a focused product review', why: 'Useful before your 15:00 review.' },
  { source: 'Manual source · Readwise', time: '8 min', title: 'A small note worth revisiting', why: 'A saved highlight that fits today’s focus.' },
];

let profileSyncTimer;
function profilePreferences() { return { appearance: state.appearance, visibility: state.visibility, taskDisplay: state.taskDisplay, contentDisplay: state.contentDisplay, heroMetricOrder: state.heroMetricOrder, heroMetricVisibility: state.heroMetricVisibility, cardOrder: state.cardOrder, integrations: state.integrations, habitSettings: state.habitSettings }; }
function persist() { saveStoredState(state); clearTimeout(profileSyncTimer); profileSyncTimer = setTimeout(() => localRequest('/api/profile/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preferences: profilePreferences() }) }).catch(() => {}), 350); }
function saveDashboardBackgroundImage(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) return toast('Choose an image file.');
  if (file.size > 2 * 1024 * 1024) return toast('Choose an image under 2 MB so settings stay fast.');
  const reader = new FileReader();
  reader.onload = () => {
    const previous = state.appearance.backgroundImage || '';
    state.appearance.backgroundImage = String(reader.result || '');
    try {
      applyAppearance();
      persist();
      rerenderPreferences('appearance', preferencesScrollTop());
      toast('Dashboard background image saved.');
    } catch {
      state.appearance.backgroundImage = previous;
      applyAppearance();
      toast('That image is too large for local settings. Try a smaller/compressed image.');
    }
  };
  reader.onerror = () => toast('Could not read that image.');
  reader.readAsDataURL(file);
}
function taskMappingKey(task) { return `${task.source}:${task.line}`; }
function rememberTaskMapping(task) { const existing = state.taskMappings[taskMappingKey(task)] || {}; state.taskMappings[taskMappingKey(task)] = { ...existing, ...(task.notionPageId ? { notionPageId: task.notionPageId, notionUrl: task.notionUrl || '' } : {}), ...(task.calendarEventId ? { calendarEventId: task.calendarEventId } : {}) }; }
function scheduleGoogleExpiry() { clearTimeout(window.googleTokenExpiryTimer); const expiresAt = Number(state.google.tokenExpiresAt || 0); if (!state.google.accessToken || !expiresAt) return; const delay = Math.max(0, expiresAt - Date.now()); window.googleTokenExpiryTimer = setTimeout(() => { state.google = { ...state.google, accessToken: '', connected: false, sessionExpired: true }; persist(); render(); }, delay); }
function clearCompletedForNewDay() { state.tasks = state.tasks.filter(task => !task.done); state.taskDate = new Date().toLocaleDateString('en-CA'); persist(); render(); }
const nextMidnight = new Date(); nextMidnight.setHours(24, 0, 1, 0); setTimeout(clearCompletedForNewDay, nextMidnight - Date.now());
async function loadLocalVault(quiet = false) { const note = await localRequest('/api/obsidian/daily'); state.localVaultPath = note.path.replace(/\/[^/]+$/, ''); const tasks = parseTasks(note.markdown, note.path, state.taskMappings); state.tasks = tasks; persist(); render(); if (!quiet) toast(`Refreshed ${tasks.length} task(s) from your Daily folder.`); }
async function configureLocalVault(path) { const data = await localRequest('/api/obsidian/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dailyNotesPath: path }) }); state.localVaultPath = data.dailyNotesPath; persist(); await loadLocalVault(); }
async function writeLocalArchive() { const result = await localRequest('/api/obsidian/archive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ archive: archiveMarkdown() }) }); toast(`Archive written locally; backup created: ${result.backup.split('/').pop()}`); }
async function saveArchiveTemplate(template) { state.archiveTemplate = template; persist(); if (!state.localVaultPath) return { localOnly: true }; try { await localRequest('/api/archive-template', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ template }) }); return { localOnly: false }; } catch (error) { return { localOnly: true, error }; } }
async function configureNotion(token, parentId, titleProperty) { const result = await localRequest('/api/notion/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, parentId, titleProperty }) }); state.notion = { configured: true, dataSourceId: result.dataSourceId }; state.integrations.notion = { database: parentId, property: titleProperty }; persist(); }
async function diagnoseNotion(token, parentId) { return localRequest('/api/notion/diagnose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, parentId }) }); }
async function listNotionSources(token) { return localRequest('/api/notion/data-sources', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }); }
async function loadLocationData(view = state.locationView) { try { const data = await localRequest(`/api/location/${view === 'week' ? 'week' : 'today'}`); if (view === 'week' && data.start && data.start !== currentWeekStartIso()) throw new Error(`Location helper returned ${data.start}, not this week.`); if (view === 'week' && !data.days?.some(day => day.date === state.locationWeekDay)) state.locationWeekDay = data.days?.some(day => day.date === todayIso()) ? todayIso() : (data.days?.[0]?.date || todayIso()); state.traccar = { ...state.traccar, connected: true, source: data.source || 'Lifey Location', places: view === 'today' ? (data.places || []) : state.traccar.places, placesDate: view === 'today' ? todayIso() : state.traccar.placesDate, week: view === 'week' ? data : state.traccar.week }; persist(); render(); toast(data.osmError ? `Loaded ${data.positions} points; OpenStreetMap lookup failed: ${data.osmError}` : `Loaded ${data.positions} ${data.source || 'location'} points.`); return data; } catch (error) { state.traccar = { ...state.traccar, connected: false, ...(view === 'today' ? { places: [], placesDate: todayIso() } : { week: { days: [], topPlaces: [], start: currentWeekStartIso() } }) }; persist(); render(); throw error; } }
async function configureTraccar(server, token, deviceId) { await localRequest('/api/traccar/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ server, token, deviceId }) }); state.traccar.connected = true; persist(); await loadLocationData(); }
async function setupMobileLocation() { const result = await localRequest('/api/location/mobile/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); state.mobileLocation.configured = true; persist(); return result.token; }
async function archiveLocationPeriod(period) { const result = await localRequest('/api/obsidian/location-archive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ period }) }); toast(`${period[0].toUpperCase() + period.slice(1)} location archive written · ${result.placeNotes.length} place note(s) updated.`); }
async function saveLocationArchiveTemplates(templates) { state.locationArchiveTemplates = { ...DEFAULT_LOCATION_ARCHIVE_TEMPLATES, ...templates }; persist(); const result = await localRequest('/api/location-archive-templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ templates: state.locationArchiveTemplates }) }); state.locationArchiveTemplates = result.templates; persist(); }
async function saveArchiveTitles(titles) { state.archiveTitles = { ...DEFAULT_ARCHIVE_TITLES, ...titles }; persist(); const result = await localRequest('/api/archive-titles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ titles: state.archiveTitles }) }); state.archiveTitles = result.titles; persist(); }
async function saveProfilePreferencesNow() { return localRequest('/api/profile/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preferences: profilePreferences() }) }); }
function applyProfile(profile = {}) {
  const preferences = profile.preferences || {};
  for (const key of ['appearance', 'visibility', 'taskDisplay', 'contentDisplay', 'heroMetricOrder', 'heroMetricVisibility', 'cardOrder', 'integrations', 'habitSettings']) if (preferences[key]) state[key] = preferences[key];
  state.appearance = normaliseAppearance(state.appearance);
  state.heroMetricOrder = normaliseHeroMetricOrder();
  state.cardOrder = normaliseCardOrder();
  state.heroMetricVisibility = HERO_METRIC_KEYS.reduce((visibility, key) => ({ ...visibility, [key]: state.heroMetricVisibility?.[key] !== false }), {});
  if (profile.archiveTemplate) state.archiveTemplate = profile.archiveTemplate;
  if (profile.locationArchiveTemplates) state.locationArchiveTemplates = { ...DEFAULT_LOCATION_ARCHIVE_TEMPLATES, ...profile.locationArchiveTemplates };
  if (profile.archiveTitles) state.archiveTitles = { ...DEFAULT_ARCHIVE_TITLES, ...profile.archiveTitles };
  if (profile.obsidian?.dailyNotesPath) state.localVaultPath = profile.obsidian.dailyNotesPath;
  if (profile.location) state.locationSettings = { radiusMeters: profile.location.radiusMeters || state.locationSettings.radiusMeters || 50, merges: profile.location.placeMerges || state.locationSettings.merges || [] };
  applyAppearance();
  persist();
}
async function exportProfile() {
  await saveProfilePreferencesNow();
  const bundle = await localRequest('/api/profile/export');
  const filename = `lifey-profile-${todayIso()}.json`;
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }));
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function importProfileFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'application/json,.json';
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const bundle = JSON.parse(await file.text());
      window.pendingProfileImport = bundle;
      const profile = bundle.profile || {};
      const labels = profile.location?.localPlaceLabels?.length || 0;
      const integrations = Object.keys(profile.preferences?.integrations || {}).length;
      modal('Import Lifey profile', `<p class="modal-copy">This will replace this Mac’s non-secret Lifey settings with <strong>${escape(file.name)}</strong>. Secrets and OAuth sessions are not imported.</p><div class="profile-summary"><span>${integrations} integration setting(s)</span><span>${labels} place label(s)</span><span>${Object.keys(profile.archiveTitles || {}).length} archive title(s)</span></div><p class="modal-copy">After import, reconnect any services that need private tokens on this Mac.</p>`, 'confirm-profile-import');
    } catch {
      toast('That is not a valid Lifey profile JSON file.');
    }
  });
  input.click();
}
async function importProfile(bundle) {
  const result = await localRequest('/api/profile/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) });
  applyProfile(result.profile || {});
  await checkLocalHelper();
  return result;
}
async function configureGooglePlaces(key) { await localRequest('/api/google-places/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) }); state.googlePlaces.configured = true; persist(); }
async function enableOsmPlaces() { await localRequest('/api/osm-places/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); state.osmPlaces.configured = true; persist(); }
async function savePlaceLabel(name, latitude, longitude) { return localRequest('/api/place-labels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, latitude, longitude }) }); }
async function loadPlaceLabels() { const data = await localRequest('/api/place-labels'); state.placeLabels = data.labels || []; persist(); return state.placeLabels; }
async function loadLocationSettings() { const data = await localRequest('/api/location/settings'); state.locationSettings = { radiusMeters: data.radiusMeters || 50, merges: data.merges || [] }; persist(); return data; }
async function saveLocationRadius(radius) { const data = await localRequest('/api/location/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ radiusMeters: radius }) }); state.locationSettings = { radiusMeters: data.radiusMeters, merges: data.merges || [] }; persist(); return data; }
async function createPlaceMerge(name, places) { const data = await localRequest('/api/place-merges', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, places }) }); await loadLocationSettings(); return data.merge; }
async function undoPlaceMerge(id) { const data = await localRequest('/api/place-merges/undo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) }); await loadLocationSettings(); return data; }
async function sendTaskToNotion(task) { if (task.notionPageId) return toast('This task is already mapped to a Notion page.'); const page = await localRequest('/api/notion/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: task.text, source: task.source, line: task.line }) }); task.notion = true; task.notionPageId = page.id; task.notionUrl = page.url; rememberTaskMapping(task); persist(); render(); toast('Notion task created and mapped locally.'); }
async function updateLocalTask(task, completed) { await localRequest('/api/obsidian/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ line: task.line, text: task.text, completed }) }); }
async function addLocalTask(text, options = {}) { return localRequest('/api/obsidian/task/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, ...options }) }); }
async function editLocalTask(task, text) { return localRequest('/api/obsidian/task/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ line: task.line, previousText: task.text, text }) }); }
async function deleteLocalTask(task) { return localRequest('/api/obsidian/task/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ line: task.line, text: task.text }) }); }
async function loadProjects(quiet = false) { const expandedSlug = state.projects?.expandedSlug || ''; const data = await localRequest('/api/projects'); state.projects = { ...data, expandedSlug }; persist(); render(); if (!quiet) toast(`Loaded ${data.projects?.length || 0} project(s).`); return data; }
async function createProjectNote(slug, title = '') { const data = await localRequest('/api/projects/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug, title }) }); await loadProjects(true); return data; }
async function openProjectNote(slug) { return localRequest('/api/projects/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug }) }); }
async function updateProjectTask(task, changes) { const data = await localRequest('/api/projects/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: task.source, line: task.line, previousText: task.raw, ...changes }) }); await loadProjects(true); return data; }
async function loadHabitsToday(quiet = false) { const data = await localRequest('/api/habits/today'); state.habits = { ...state.habits, today: data.habits || [], expected: data.expected || [], active: (state.habits.active?.length ? state.habits.active : data.expected || []), archived: data.archived || state.habits.archived || [], date: data.date, path: data.path, configPath: data.configPath }; persist(); render(); if (!quiet) toast('Habits refreshed from today’s note.'); return data; }
async function loadHabitHistory(range = state.habits.range || 'month', quiet = false) { const data = await localRequest(`/api/habits/history?range=${encodeURIComponent(range)}`); const selected = state.habits.selectedHabit && data.habits?.includes(state.habits.selectedHabit) ? state.habits.selectedHabit : (data.habits?.[0] || ''); state.habits = { ...state.habits, range: data.range || range, history: data.entries || [], dailyTotals: data.dailyTotals || [], habits: data.habits || [], active: data.active || [], archived: data.archived || [], selectedHabit: selected }; persist(); render(); if (!quiet) toast('Habit history refreshed.'); return data; }
async function syncHabitsToday() { const data = await localRequest('/api/habits/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); state.habits = { ...state.habits, today: data.habits || [], expected: data.expected || [], archived: data.archived || [], date: data.date, path: data.path }; persist(); await loadHabitHistory(state.habits.range || 'month', true); toast('Today’s habits synced from Active Habits.'); }
async function setHabitState(habit, nextState) { const data = await localRequest('/api/habits/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ line: habit.line, habit: habit.habit, state: nextState }) }); state.habits = { ...state.habits, today: data.habits || [], expected: data.expected || [], archived: data.archived || [], date: data.date, path: data.path }; persist(); await loadHabitHistory(state.habits.range || 'month', true); }
async function checkLocalHelper() { const status = await localRequest('/api/obsidian/status'); if (status.archiveTemplate) state.archiveTemplate = status.archiveTemplate; try { const [location, locationSettings, titles, profile] = await Promise.all([localRequest('/api/location-archive-templates'), loadLocationSettings(), localRequest('/api/archive-titles'), localRequest('/api/profile/preferences')]); state.locationArchiveTemplates = { ...DEFAULT_LOCATION_ARCHIVE_TEMPLATES, ...(location.templates || {}) }; state.locationSettings = { radiusMeters: locationSettings.radiusMeters || 50, merges: locationSettings.merges || [] }; state.archiveTitles = { ...DEFAULT_ARCHIVE_TITLES, ...(titles.titles || {}) }; const remote = profile.preferences || {}; for (const key of ['appearance', 'visibility', 'taskDisplay', 'contentDisplay', 'heroMetricOrder', 'heroMetricVisibility', 'cardOrder', 'integrations', 'habitSettings']) if (remote[key]) state[key] = remote[key]; state.appearance = normaliseAppearance(state.appearance); state.heroMetricOrder = normaliseHeroMetricOrder(); state.cardOrder = normaliseCardOrder(); state.heroMetricVisibility = HERO_METRIC_KEYS.reduce((visibility, key) => ({ ...visibility, [key]: state.heroMetricVisibility?.[key] !== false }), {}); applyAppearance(); persist(); } catch {} if (status.configured) { state.localVaultPath = status.dailyNotesPath; persist(); await loadLocalVault(true); } }
async function loadYoutube(quiet = false, view = state.youtubeView) { try { const data = await localRequest(`/api/activity/youtube/${view === 'week' ? 'week' : 'today'}`); if (view === 'week') { if (data.start && data.start !== currentWeekStartIso()) throw new Error(`YouTube helper returned ${data.start}, not this week.`); if (!data.days?.some(day => day.date === state.youtubeWeekDay)) state.youtubeWeekDay = data.days?.some(day => day.date === todayIso()) ? todayIso() : (data.days?.[0]?.date || todayIso()); state.youtube = { ...state.youtube, week: data, extensionLastSeen: data.extensionLastSeen || state.youtube.extensionLastSeen }; } else { state.youtube = { ...state.youtube, ...data }; } persist(); render(); if (!quiet) toast('YouTube activity refreshed.'); return data; } catch (error) { if (view === 'today') state.youtube = { ...state.youtube, date: todayIso(), videos: [], totalActiveSeconds: 0 }; else state.youtube = { ...state.youtube, week: { days: [], videos: [], totalActiveSeconds: 0, start: currentWeekStartIso() } }; persist(); render(); throw error; } }
async function checkYoutubeTracker() { const data = await localRequest('/api/activity/youtube/today'); state.youtube = data; persist(); render(); toast(data.extensionLastSeen ? 'Tracker reached the local helper. Reload a YouTube watch page next.' : 'No tracker heartbeat yet. Open the extension’s Inspect view in Zen to check its error log.'); }
function isoDate(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; }
function refocusCaptureInput() { const input = document.querySelector('#capture-task'); if (!input) return; input.focus({ preventScroll: true }); input.setSelectionRange(input.value.length, input.value.length); }
function renderCaptureCalendar() { const holder = document.querySelector('#capture-calendar'); if (!holder) return; const month = window.captureCalendarMonth || new Date(); const year = month.getFullYear(), monthIndex = month.getMonth(); const firstDay = new Date(year, monthIndex, 1).getDay(), days = new Date(year, monthIndex + 1, 0).getDate(); const selected = document.querySelector('#capture-date')?.value; const cells = [...Array(firstDay).fill('<span></span>'), ...Array.from({ length: days }, (_, index) => { const date = isoDate(new Date(year, monthIndex, index + 1)); return `<button type="button" class="${date === selected ? 'selected' : ''}" data-action="capture-calendar-select" data-date="${date}">${index + 1}</button>`; })].join(''); const time = document.querySelector('#capture-time')?.value || ''; let [hour = 9, minute = 0] = time ? time.split(':').map(Number) : []; const period = window.captureTimePeriod || (hour >= 12 ? 'pm' : 'am'); const displayHour = hour % 12 || 12, mode = window.captureClockMode || 'hour'; const values = mode === 'hour' ? Array.from({ length: 12 }, (_, i) => i + 1) : Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0')); const clockButtons = values.map((value, index) => { const angle = (index * 30 - 90) * Math.PI / 180, left = 50 + 39 * Math.cos(angle), top = 50 + 39 * Math.sin(angle); const selectedValue = mode === 'hour' ? Number(value) === displayHour : Number(value) === minute; return `<button type="button" class="${selectedValue ? 'selected' : ''}" style="--x:${left}%;--y:${top}%" data-action="capture-clock-select" data-value="${value}">${value}</button>`; }).join(''); holder.innerHTML = `<div class="capture-datetime"><div class="capture-calendar"><header><button type="button" data-action="capture-calendar-prev">‹</button><strong>${month.toLocaleDateString([], { month: 'long', year: 'numeric' })}</strong><button type="button" data-action="capture-calendar-next">›</button></header><div class="calendar-weekdays"><span>S</span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span></div><div class="calendar-days">${cells}</div></div><div class="capture-clock"><div class="clock-readout"><button type="button" class="${mode === 'hour' ? 'selected' : ''}" data-action="capture-clock-mode" data-mode="hour">${String(displayHour).padStart(2, '0')}</button><span>:</span><button type="button" class="${mode === 'minute' ? 'selected' : ''}" data-action="capture-clock-mode" data-mode="minute">${String(minute).padStart(2, '0')}</button></div><div class="clock-period"><button type="button" class="${period === 'am' ? 'selected' : ''}" data-action="capture-clock-period" data-period="am">AM</button><button type="button" class="${period === 'pm' ? 'selected' : ''}" data-action="capture-clock-period" data-period="pm">PM</button></div><p>Select ${mode === 'hour' ? 'hour' : 'minutes'}</p><div class="analog-clock">${clockButtons}<i></i></div></div></div>`; }
function capturePlaceNames() { const names = [...(state.placeLabels || []).map(label => label.name), ...(state.places || []).filter(place => place.source === 'Manual').map(place => place.name)].map(name => String(name || '').trim()).filter(Boolean); return [...new Set(names)].sort((a, b) => a.localeCompare(b)); }
function capturePlaceContext() { const input = document.querySelector('#capture-task'); if (!input) return null; const cursor = input.selectionStart ?? input.value.length; const before = input.value.slice(0, cursor); const lower = before.toLowerCase(); const indexes = [lower.lastIndexOf(' at '), lower.startsWith('at ') ? 0 : -1].filter(index => index >= 0); const start = indexes.length ? Math.max(...indexes) : -1; if (start < 0) return null; const queryStart = start === 0 && lower.startsWith('at ') ? 3 : start + 4; const query = before.slice(queryStart); if (/\[\[[^\]]*$/.test(query) || query.includes(']]') || /[#📅⏰🔁]/.test(query)) return null; return { input, cursor, start: queryStart, end: cursor, query: query.trimStart() }; }
function setCaptureMenuOpen(menu = '') { document.querySelectorAll('.capture-controls .capture-pill').forEach(button => button.classList.toggle('is-open', button.dataset.menu === menu)); }
function closeCaptureSubmenus() { document.querySelector('#capture-option-dropdown')?.replaceChildren(); document.querySelector('#capture-place-dropdown')?.replaceChildren(); document.querySelector('#capture-calendar')?.replaceChildren(); const optionHolder = document.querySelector('#capture-option-dropdown'); if (optionHolder) optionHolder.dataset.menu = ''; setCaptureMenuOpen(''); }
function renderCapturePlaceDropdown(force = false, emptyText = 'Loading saved places…') { const holder = document.querySelector('#capture-place-dropdown'); if (!holder) return; const context = capturePlaceContext(); const names = capturePlaceNames(); if (!force && (!context || !names.length)) { holder.innerHTML = ''; holder.dataset.index = '0'; if (!context) setCaptureMenuOpen(''); return; } if (!names.length) { holder.innerHTML = force ? `<div class="capture-place-empty">${escape(emptyText)}</div>` : ''; holder.dataset.index = '0'; if (!force) setCaptureMenuOpen(''); return; } const query = context?.query || ''; const filtered = names.filter(name => name.toLowerCase().includes(query.toLowerCase())).slice(0, 8); if (!filtered.length) { holder.innerHTML = query ? '<div class="capture-place-empty">No saved places match.</div>' : `<div class="capture-place-empty">${escape(emptyText)}</div>`; holder.dataset.index = '0'; return; } const current = Math.min(Number(holder.dataset.index || 0), filtered.length - 1); holder.dataset.index = String(current); holder.innerHTML = `<div class="capture-place-menu" role="listbox">${filtered.map((name, index) => `<button type="button" class="${index === current ? 'selected' : ''}" data-action="select-capture-place" data-place-name="${escape(name)}" role="option" aria-selected="${index === current}"><span>at</span><strong>[[${escape(name)}]]</strong></button>`).join('')}</div>`; }
function captureOptionChoices(type) { if (type === 'priority') return CAPTURE_PRIORITIES.map(option => ({ value: option.value, label: option.label, prefix: 'priority' })); const current = document.querySelector('#capture-recurring')?.value || ''; const recurrences = CAPTURE_RECURRENCES.includes(current) ? CAPTURE_RECURRENCES : [...CAPTURE_RECURRENCES, current]; return recurrences.map(value => ({ value, label: captureRecurringLabel(value), prefix: 'repeat' })); }
function renderCaptureOptionDropdown(type) { const holder = document.querySelector('#capture-option-dropdown'); if (!holder) return; if (holder.dataset.menu === type && holder.innerHTML) { closeCaptureSubmenus(); refocusCaptureInput(); return; } closeCaptureSubmenus(); holder.dataset.menu = type; setCaptureMenuOpen(type); const current = document.querySelector(type === 'priority' ? '#capture-priority' : '#capture-recurring')?.value || ''; holder.innerHTML = `<div class="capture-option-menu" role="listbox">${captureOptionChoices(type).map(option => `<button type="button" class="${option.value === current ? 'selected' : ''}" data-action="select-capture-option" data-menu="${type}" data-value="${escape(option.value)}" role="option" aria-selected="${option.value === current}"><span>${escape(option.prefix)}</span><strong>${escape(option.label)}</strong></button>`).join('')}</div>`; }
function selectCaptureOption(type, value = '') { const input = document.querySelector(type === 'priority' ? '#capture-priority' : '#capture-recurring'); if (!input) return; input.value = value; closeCaptureSubmenus(); refreshQuickCapturePreview(); refocusCaptureInput(); }
function selectCapturePlace(name = '') { const context = capturePlaceContext(); if (!context) return false; const clean = String(name || '').trim(); if (!clean) return false; const value = context.input.value; const prefix = value.slice(0, context.start); const suffix = value.slice(context.end); const insertion = `[[${clean.replaceAll(']]', '').trim()}]]`; context.input.value = `${prefix}${insertion}${suffix}`.replace(/\s{2,}/g, ' '); const cursor = `${prefix}${insertion}`.length; context.input.focus({ preventScroll: true }); context.input.setSelectionRange(cursor, cursor); closeCaptureSubmenus(); refreshQuickCapturePreview(); return true; }
function moveCapturePlaceSelection(delta) { const holder = document.querySelector('#capture-place-dropdown'); const items = holder ? [...holder.querySelectorAll('[data-place-name]')] : []; if (!holder || !items.length) return false; const next = (Number(holder.dataset.index || 0) + delta + items.length) % items.length; holder.dataset.index = String(next); renderCapturePlaceDropdown(true); return true; }
function ensureCapturePlaceContext() { const input = document.querySelector('#capture-task'); if (!input || capturePlaceContext()) return; const spacer = input.value.trim() ? ' at ' : 'at '; input.value = `${input.value.replace(/\s*$/, '')}${spacer}`; const cursor = input.value.length; input.focus({ preventScroll: true }); input.setSelectionRange(cursor, cursor); refreshQuickCapturePreview(); }
function selectedCapturePlaceName() { const holder = document.querySelector('#capture-place-dropdown'); return holder?.querySelector('.selected[data-place-name]')?.dataset.placeName || ''; }
function quickCaptureControls() { return { due: document.querySelector('#capture-date')?.value, time: document.querySelector('#capture-time')?.value, priority: document.querySelector('#capture-priority')?.value, recurring: document.querySelector('#capture-recurring')?.value, project: window.captureProjectSlug || '' }; }
function refreshQuickCapturePreview() { const input = document.querySelector('#capture-task'); if (!input) return; const parsed = parseNaturalTask(input.value, quickCaptureControls()); const preview = document.querySelector('#capture-preview'); const dateLabel = document.querySelector('#capture-date-label'), priority = document.querySelector('#capture-priority'), recurring = document.querySelector('#capture-recurring'); if (dateLabel) dateLabel.textContent = captureDayTimeLabel(document.querySelector('#capture-date')?.value || parsed.due, document.querySelector('#capture-time')?.value || parsed.time); const priorityLabel = document.querySelector('#capture-priority-label'), recurringLabel = document.querySelector('#capture-recurring-label'); if (priorityLabel) priorityLabel.textContent = capturePriorityLabel(priority?.value || ''); if (recurringLabel) recurringLabel.textContent = captureRecurringLabel(recurring?.value || ''); if (preview) preview.textContent = parsed.text ? `- [ ] ${parsed.text}` : 'Start typing to preview the task Markdown.'; }
function toast(message) { const el = document.querySelector('#toast'); el.textContent = message; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 2600); }
function cardOrderStyle(key) { const fallback = CARD_KEYS.indexOf(key); const index = state.cardOrder.indexOf(key); return `style="order:${index >= 0 ? index : fallback}"`; }
function activeDialog() { return [...document.querySelectorAll('dialog[open]')].at(-1) || document.querySelector('#modal'); }
function closeActiveDialog() { activeDialog()?.close(); updateMobileCaptureOffset(); }
function updateMobileCaptureOffset() {
  const isMobile = window.matchMedia?.('(max-width: 620px)').matches;
  const hasCapture = Boolean(document.querySelector('dialog[open] .capture-raycast'));
  const viewport = window.visualViewport;
  const offset = isMobile && hasCapture && viewport ? Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop)) : 0;
  document.documentElement.style.setProperty('--lifey-keyboard-offset', `${offset}px`);
}
function preferencesMain() { return document.querySelector('#modal .preferences main'); }
function currentPreferencesTab() { return document.querySelector('#modal .preferences-tab.selected')?.dataset.tab || 'integrations'; }
function preferencesScrollTop() { return preferencesMain()?.scrollTop || 0; }
function rerenderPreferences(tab, scrollTop = preferencesScrollTop()) { render(); openPreferences(tab, { scrollTop }); }
function dashboardColumnCount() { return window.matchMedia('(max-width: 620px)').matches ? 1 : window.matchMedia('(max-width: 900px)').matches ? 2 : 3; }
function arrangeDashboardCards() {
  const grid = document.querySelector('.grid');
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll('[data-card-key]'));
  if (!cards.length) return;
  const byKey = new Map(cards.map(card => [card.dataset.cardKey, card]));
  const orderedKeys = [...new Set([...normaliseCardOrder(), ...CARD_KEYS])];
  const orderedCards = orderedKeys.map(key => byKey.get(key)).filter(Boolean);
  const columnCount = Math.min(dashboardColumnCount(), Math.max(1, orderedCards.length));
  const columns = Array.from({ length: columnCount }, () => {
    const column = document.createElement('div');
    column.className = 'card-column';
    return column;
  });
  orderedCards.forEach((card, index) => columns[index % columnCount].append(card));
  grid.replaceChildren(...columns);
}
function renderDashboardShell() {
  const app = document.querySelector('#app');
  if (!app) return;
  if (!app.querySelector('.shell') || !app.querySelector('#dashboard-stats') || !app.querySelector('#dashboard-grid')) {
    app.innerHTML = `
  <div class="shell">
    <nav><a class="brand" href="#top" aria-label="Lifey home"><span class="brand-mark">L.</span><span class="brand-name">Lifey</span></a><div class="nav-actions"><button class="button ghost archive-action" data-action="archive"><span class="action-arrow">↗</span>Update daily archive</button><button class="button quick-action" data-action="quick-add">＋ <span>Quick capture</span></button><button class="settings" data-action="settings" title="Settings (⌘ .)" aria-label="Settings, shortcut Command period">⚙<kbd>⌘ .</kbd></button></div></nav>
    <section class="hero" id="top"><h1 class="date-title"></h1></section>
    <div id="dashboard-stats"></div>
    <div class="grid" id="dashboard-grid"></div>
  </div>`;
  }
  const dateTitle = app.querySelector('.date-title');
  if (dateTitle) dateTitle.textContent = todayJournalDatePadded();
}
async function saveGoogleHelperConfig(clientSecret = '') {
  const google = state.integrations.google || {};
  const gmail = state.integrations.gmail || {};
  if (!google.clientId) throw new Error('Add a Google Desktop OAuth Client ID first.');
  const result = await localRequest('/api/google/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clientId: google.clientId, clientSecret, calendar: google.calendar || 'primary', gmailQuery: gmail.query || '' }) });
  state.google = { ...state.google, connected: Boolean(result.status?.connected), sessionExpired: false, accountEmail: result.status?.email || state.google.accountEmail || '', hasClientSecret: Boolean(result.status?.hasClientSecret) };
  persist();
  return result.status || {};
}
async function loadGoogleStatus() {
  const status = await localRequest('/api/google/status');
  if (status.clientId) state.integrations.google = { ...(state.integrations.google || {}), clientId: status.clientId, calendar: status.calendar || 'primary' };
  if (status.gmailQuery) state.integrations.gmail = { ...(state.integrations.gmail || {}), query: status.gmailQuery };
  state.google = { ...state.google, connected: Boolean(status.connected), sessionExpired: false, accountEmail: status.email || '', hasClientSecret: Boolean(status.hasClientSecret) };
  state.gmail = { ...state.gmail, connected: Boolean(status.connected) };
  persist();
  return status;
}
async function loadGoogleCalendar() {
  try {
    const result = await localRequest('/api/google/calendar/today');
    state.google = { ...state.google, connected: true, sessionExpired: false, events: result.items || [], eventsDate: todayIso() };
    persist();
    render();
    return result;
  } catch (error) {
    state.google = { ...state.google, connected: false, sessionExpired: true, events: [], eventsDate: todayIso() };
    state.gmail = { ...state.gmail, connected: false };
    persist();
    render();
    throw error;
  }
}
async function connectGoogleCalendar() {
  if (state.google.connected) return loadGoogleCalendar();
  if (!state.integrations.google?.clientId) { integrationForm('google'); return; }
  if (!state.google.hasClientSecret) { integrationForm('google'); toast('Add and save the Google Desktop OAuth Client Secret first.'); return; }
  await saveGoogleHelperConfig();
  window.location.assign('/api/google/auth/start');
}
async function createGoogleCalendarEvent(task, time, date = todayIso()) {
  const start = `${date}T${time}:00`;
  const endDate = new Date(`${start}-05:00`);
  endDate.setMinutes(endDate.getMinutes() + 30);
  const event = await localRequest('/api/google/calendar/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ summary: task.text, description: `Source: ${task.source} line ${task.line}\nCreated by Lifey.`, start: { dateTime: start, timeZone: 'America/Guayaquil' }, end: { dateTime: endDate.toISOString(), timeZone: 'America/Guayaquil' } }) });
  task.calendar = true;
  task.calendarEventId = event.id;
  rememberTaskMapping(task);
  persist();
  await loadGoogleCalendar();
  toast('Google Calendar event created and mapped locally.');
}
function forgetCalendarMapping(eventId) { for (const [key, mapping] of Object.entries(state.taskMappings)) { if (mapping.calendarEventId !== eventId) continue; delete mapping.calendarEventId; if (Object.keys(mapping).length) state.taskMappings[key] = mapping; else delete state.taskMappings[key]; } for (const task of state.tasks) { if (task.calendarEventId === eventId) { task.calendar = false; delete task.calendarEventId; } } }
async function deleteGoogleCalendarEventById(eventId) { if (!eventId) throw new Error('That Calendar event no longer has an ID.'); await localRequest('/api/google/calendar/event/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ eventId }) }); forgetCalendarMapping(eventId); persist(); await loadGoogleCalendar(); }
async function removeGoogleCalendarEvent(task) { if (!task?.calendarEventId) throw new Error('This task has no Lifey-created Calendar event to remove.'); await deleteGoogleCalendarEventById(task.calendarEventId); toast('Calendar event removed; the task is still in Obsidian.'); }
async function updateGoogleCalendarEvent(task, text) {
  if (!task?.calendarEventId) return;
  const intent = taskCalendarIntent({ ...task, text });
  const event = { summary: text, description: `Source: ${task.source} line ${task.line}\nUpdated by Lifey.` };
  if (intent.time && !intent.overdue) {
    const start = `${intent.date}T${intent.time}:00`;
    const endDate = new Date(`${start}-05:00`);
    endDate.setMinutes(endDate.getMinutes() + 30);
    event.start = { dateTime: start, timeZone: 'America/Guayaquil' };
    event.end = { dateTime: endDate.toISOString(), timeZone: 'America/Guayaquil' };
  }
  await localRequest('/api/google/calendar/event/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ eventId: task.calendarEventId, event }) });
  await loadGoogleCalendar();
}
function taskCalendarIntent(task) { const text = String(task?.text || ''); const due = text.match(/📅\s*(\d{4}-\d{2}-\d{2})/); const time = text.match(/⏰\s*([01]?\d|2[0-3]):([0-5]\d)/); const dueDate = due?.[1] || ''; const overdue = Boolean(dueDate && dueDate < todayIso()); return { date: dueDate && !overdue ? dueDate : todayIso(), time: time ? `${String(time[1]).padStart(2, '0')}:${time[2]}` : '', overdue }; }
function askCalendarTime(task, intent = taskCalendarIntent(task)) { const dateLabel = new Date(`${intent.date}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' }); const reason = intent.overdue ? 'This task is overdue, so its old time is not assumed to be your current intention.' : 'No task time was found.'; modal('Add to Google Calendar', `<p class="modal-copy">${reason} Create a 30-minute event for <strong>${escape(task.text)}</strong>.</p><label>Starts ${escape(dateLabel)} at<input type="time" value="14:00" /></label>`, 'confirm-calendar'); window.pendingTask = task.id; window.pendingCalendarDate = intent.date; }
function scheduleTaskFromMetadata(task) { const intent = taskCalendarIntent(task); if (intent.time && !intent.overdue) return createGoogleCalendarEvent(task, intent.time, intent.date); askCalendarTime(task, intent); }
async function loadGmail() {
  const result = await localRequest('/api/google/gmail/suggestions');
  state.gmail = { ...state.gmail, connected: true, messages: result.messages || [] };
  state.google = { ...state.google, connected: true, sessionExpired: false };
  persist();
  render();
}
async function connectGmail() {
  if (!state.integrations.google?.clientId) { toast('Add the Google Desktop OAuth Client ID in Google Calendar setup first.'); return; }
  const status = await saveGoogleHelperConfig();
  if (status.connected) return loadGmail();
  window.location.assign('/api/google/auth/start');
}
function base64url(bytes) { return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
async function spotifyChallenge(verifier) { return base64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))); }
function spotifyHeaders() { return { Authorization: `Bearer ${state.spotify.accessToken || ''}` }; }
async function spotifyApi(path) {
  const res = await fetch(`https://api.spotify.com/v1${path}`, { headers: spotifyHeaders(), cache: 'no-store' });
  if (res.status === 401) {
    state.spotify.connected = false;
    state.spotify.errors = ['Spotify session expired. Reconnect Spotify.'];
    persist();
    render();
    throw new Error('Spotify session expired. Reconnect Spotify.');
  }
  if (!res.ok) {
    let detail = '';
    try { const body = await res.json(); detail = body?.error?.message || body?.error_description || ''; } catch {}
    const error = new Error(`Spotify request failed (${res.status})${detail ? `: ${detail}` : ''}`);
    error.status = res.status;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}
async function spotifyMaybe(label, path) { try { return { label, data: await spotifyApi(path) }; } catch (error) { return { label, error: error.message, status: error.status || 0 }; } }
async function spotifyDebugFetch(label, path) {
  if (!state.spotify.accessToken) return { label, status: 'missing token', summary: 'No Spotify access token is saved in this browser.' };
  try {
    const response = await fetch(`https://api.spotify.com/v1${path}`, { headers: spotifyHeaders(), cache: 'no-store' });
    const text = response.status === 204 ? '' : await response.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    const item = body?.item || body?.items?.[0]?.track || null;
    const errorSummary = typeof body?.error === 'string'
      ? `${body.error}${body.error_description ? `: ${body.error_description}` : ''}`
      : body?.error?.message || body?.error_description || body?.message || '';
    return {
      label,
      status: response.status,
      ok: response.ok,
      summary: item ? `${item.name || 'Untitled'} — ${(item.artists || []).map(artist => artist.name).join(', ') || 'unknown artist'}` : errorSummary || (response.status === 204 ? '204 No Content' : body ? 'Response received, but no track item found.' : 'Empty response'),
      body
    };
  } catch (error) {
    return { label, status: 'network error', ok: false, summary: error.message };
  }
}
async function diagnoseSpotify() {
  const checks = await Promise.all([
    spotifyDebugFetch('Profile', '/me'),
    spotifyDebugFetch('Currently playing', '/me/player/currently-playing?additional_types=track,episode'),
    spotifyDebugFetch('Player state', '/me/player?additional_types=track,episode'),
    spotifyDebugFetch('Recently played', '/me/player/recently-played?limit=5')
  ]);
  const rows = checks.map(check => `<div class="spotify-diagnostic-row"><strong>${escape(check.label)}</strong><span>${escape(String(check.status))}</span><small>${escape(check.summary || 'No summary')}</small></div>`).join('');
  const current = checks.find(check => check.label === 'Currently playing')?.body?.item || checks.find(check => check.label === 'Player state')?.body?.item || null;
  if (current) {
    state.spotify.current = spotifyCurrentFromPlayback({ item: current, is_playing: true, progress_ms: 0 });
    state.spotify.nowStatus = 'Recovered from Spotify diagnostic.';
    state.spotify.connected = true;
    persist();
    render();
  }
  const allForbidden = checks.every(check => Number(check.status) === 403);
  modal('Spotify diagnostic', `<p class="modal-copy">${allForbidden ? 'Spotify is refusing this access token for every endpoint, including profile. This usually means the Spotify account is not allowed in the app dashboard/development mode, or the token was issued before the required scopes were granted.' : 'This is the raw status Lifey gets from Spotify. If current playback says <strong>403</strong>, use Reconnect. If it says <strong>204</strong>, Spotify is saying there is no active playback visible to the API.'}</p><div class="spotify-diagnostic">${rows}</div>`, 'close');
}
function spotifyTrimHistory() {
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - 4);
  state.spotify.history = (state.spotify.history || []).filter(play => new Date(play.playedAt || 0) >= cutoff).slice(-1000);
}
function spotifyRemember(play) {
  if (!play?.trackId && !play?.title) return;
  state.spotify.history ||= [];
  const exists = state.spotify.history.some(item => item.playId === play.playId);
  if (!exists) state.spotify.history.push(play);
  spotifyTrimHistory();
}
function spotifyCurrentFromPlayback(playback) {
  const item = playback?.item;
  if (!item) return null;
  const current = spotifyTrackFromItem(item, new Date().toISOString(), 'currently-playing');
  return { ...current, isPlaying: Boolean(playback.is_playing), progressMs: Number(playback.progress_ms || 0), capturedAt: new Date().toISOString() };
}
function startSpotifyPolling() {
  clearInterval(window.spotifyPollingTimer);
  if (!state.spotify.accessToken) return;
  window.spotifyPollingTimer = setInterval(() => {
    if (!state.spotify.accessToken) return;
    loadSpotify({ quiet: true }).catch(() => {});
  }, 30_000);
}
async function loadSpotify(options = {}) {
  if (!state.spotify.accessToken) { state.spotify.connected = false; state.spotify.errors = ['Connect Spotify first.']; persist(); render(); throw new Error('Connect Spotify first.'); }
  const [profile, recent, currentlyPlaying, playerState] = await Promise.all([
    spotifyMaybe('profile', '/me'),
    spotifyMaybe('recently played', '/me/player/recently-played?limit=50'),
    spotifyMaybe('currently playing', '/me/player/currently-playing?additional_types=track,episode'),
    spotifyMaybe('player state', '/me/player?additional_types=track,episode')
  ]);
  if (profile.data) state.spotify.profile = { id: profile.data.id, name: profile.data.display_name || profile.data.id };
  for (const item of recent.data?.items || []) spotifyRemember(spotifyTrackFromItem(item, item.played_at, 'recently-played'));
  const currentSource = currentlyPlaying.data?.item ? currentlyPlaying.data : playerState.data?.item ? playerState.data : null;
  const current = spotifyCurrentFromPlayback(currentSource);
  if (current) {
    state.spotify.current = current;
    state.spotify.nowStatus = current.isPlaying ? 'Now playing from Spotify' : 'Spotify is open, but playback is paused';
    if (current.isPlaying) {
      const alreadyCaptured = (state.spotify.history || []).some(play => play.trackId === current.trackId && Date.now() - new Date(play.playedAt || 0).getTime() < 90_000);
      if (!alreadyCaptured) spotifyRemember({ ...current, playedAt: current.capturedAt, playId: `${current.trackId || current.title}:live:${Math.floor(Date.now() / 90000)}` });
    }
  } else {
    state.spotify.current = null;
    const currentErrors = [currentlyPlaying, playerState].filter(result => result.error).map(result => result.error).join(' · ');
    state.spotify.nowStatus = currentErrors
      ? (currentErrors.includes('403') ? 'Reconnect Spotify so Lifey can read playback state.' : currentErrors)
      : 'No active Spotify playback was found. Start Spotify on any device, then refresh.';
  }
  const endpointNotes = [profile, recent, currentlyPlaying, playerState].filter(result => result.error && !String(result.error).includes('session expired')).map(result => `${result.label}: ${result.error}`);
  const stats = spotifyStats(state.spotify, state.spotify.range);
  state.spotify.connected = Boolean(state.spotify.accessToken);
  state.spotify.minutes = stats.minutes;
  state.spotify.errors = [];
  state.spotify.endpointNotes = endpointNotes;
  state.spotify.lastSync = new Date().toISOString();
  persist();
  render();
  if (!options.quiet) toast('Spotify refreshed.');
}
async function connectSpotify(forceAuthorize = false) {
  const clientId = state.integrations.spotify?.clientId;
  if (!clientId) { integrationForm('spotify'); return; }
  if (state.spotify.accessToken && !forceAuthorize) {
    try { await loadSpotify(); return; }
    catch (error) { if (!String(error.message || '').toLowerCase().includes('expired')) throw error; }
  }
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(64)));
  const oauthState = base64url(crypto.getRandomValues(new Uint8Array(16)));
  sessionStorage.setItem('spotify-pkce-verifier', verifier); sessionStorage.setItem('spotify-oauth-state', oauthState);
  const query = new URLSearchParams({ client_id: clientId, response_type: 'code', redirect_uri: window.location.origin, code_challenge_method: 'S256', code_challenge: await spotifyChallenge(verifier), state: oauthState, scope: 'user-read-currently-playing user-read-playback-state user-read-recently-played', show_dialog: 'true' });
  window.location.assign(`https://accounts.spotify.com/authorize?${query}`);
}
async function reconnectSpotify() {
  state.spotify = { ...state.spotify, accessToken: '', refreshToken: '', connected: false, errors: [] };
  persist();
  await connectSpotify(true);
}
async function finishSpotifyAuth() {
  const params = new URLSearchParams(window.location.search); const code = params.get('code');
  if (!code || !params.get('state')) return;
  if (params.get('state') !== sessionStorage.getItem('spotify-oauth-state')) throw new Error('Spotify authorization state did not match.');
  const body = new URLSearchParams({ client_id: state.integrations.spotify?.clientId || '', grant_type: 'authorization_code', code, redirect_uri: window.location.origin, code_verifier: sessionStorage.getItem('spotify-pkce-verifier') || '' });
  const response = await fetch('https://accounts.spotify.com/api/token', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body });
  if (!response.ok) throw new Error('Spotify did not return an access token.');
  const token = await response.json(); state.spotify = { ...state.spotify, accessToken: token.access_token, refreshToken: token.refresh_token || state.spotify.refreshToken || '', connected: true, errors: [] }; persist(); sessionStorage.removeItem('spotify-pkce-verifier'); sessionStorage.removeItem('spotify-oauth-state'); history.replaceState({}, '', window.location.pathname); await loadSpotify({ quiet: true }); startSpotifyPolling(); toast('Spotify connected.');
}

function taskCard(task) {
  return `<article class="task ${task.done ? 'done' : ''}">
    <button class="check" data-action="toggle-task" data-id="${task.id}" aria-label="Toggle task">${task.done ? '✓' : ''}</button>
    <div class="task-copy"><p>${escape(task.text)}</p><small>${state.taskDisplay.showPath ? `${escape(task.source)} · ` : ''}L${task.line}</small></div>
    <div class="task-actions">
      <button class="icon-button task-delete" title="Delete task" aria-label="Delete task" data-action="delete-task" data-id="${task.id}">×</button>
      <button class="icon-button" title="Edit task" aria-label="Edit task" data-action="edit-task" data-id="${task.id}">✎</button>
      <button class="icon-button ${task.notion ? 'active' : ''}" title="Send to Notion" data-action="notion" data-id="${task.id}">N</button>
      <button class="icon-button ${task.calendar ? 'active' : ''}" title="${task.calendar ? 'Remove Calendar event' : 'Add to calendar'}" aria-label="${task.calendar ? 'Remove Calendar event' : 'Add to calendar'}" data-action="${task.calendar ? 'remove-calendar' : 'calendar'}" data-id="${task.id}">${task.calendar ? '−' : '＋'}</button>
    </div>
  </article>`;
}
function normalisePlaceName(name = '') { return String(name).toLowerCase().replace(/^place\s*-\s*["“”']?|["“”']$/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim(); }
function taskPlaceNames(task) { return [...String(task?.text || '').matchAll(/\bat\s+\[\[([^\]]+)\]\]/gi)].map(match => normalisePlaceName(match[1])).filter(Boolean); }
function latestCurrentPlace(places = []) { const now = Date.now(); return [...places].filter(place => place?.name).map(place => { const points = Array.isArray(place.points) ? place.points : []; const pointTime = points.map(point => new Date(point.timestamp || point.time || point.lastSeen || 0).getTime()).filter(Number.isFinite).sort((a, b) => b - a)[0]; const end = pointTime || new Date(place.departure || place.lastSeen || place.arrival || 0).getTime(); return { place, end: Number.isFinite(end) ? end : 0 }; }).filter(item => item.end && now - item.end <= 45 * 60 * 1000).sort((a, b) => b.end - a.end)[0]?.place || null; }
function tasksForCurrentPlace(tasks, places) { const current = latestCurrentPlace(places); if (!current) return { currentPlace: null, tasks: [] }; const currentName = normalisePlaceName(current.name); const matches = tasks.filter(task => taskPlaceNames(task).includes(currentName)); return { currentPlace: current, tasks: matches }; }
function projectSlug(value) { return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''); }
function hoursLabel(hours) {
  const value = Number(hours || 0);
  if (!value) return '0h';
  const whole = Math.floor(value), minutes = Math.round((value - whole) * 60);
  return whole && minutes ? `${whole}h ${minutes}m` : whole ? `${whole}h` : `${minutes}m`;
}
function projectCard(project) {
  const progress = project.taskCount ? Math.round(project.completedCount / project.taskCount * 100) : 0;
  const expanded = state.projects?.expandedSlug === project.slug;
  return `<article class="project-card ${expanded ? 'expanded' : ''}">
    <button class="project-card-summary" data-action="open-project" data-project-slug="${escape(project.slug)}" aria-expanded="${expanded ? 'true' : 'false'}">
      <strong>${escape(project.title)}</strong><b>${progress}%</b>
    </button>
    ${expanded ? projectDetail(project, progress) : ''}
  </article>`;
}
function projectTaskList(tasks = []) {
  return tasks.length ? `<ol class="project-detail-tasks">${tasks.map(task => `<li class="${task.done ? 'done' : ''} ${task.milestone ? 'milestone' : ''}"><button class="check" data-action="toggle-project-task" data-source="${escape(task.source)}" data-line="${task.line}" data-raw="${escape(task.raw)}" data-completed="${task.done ? 'true' : 'false'}">${task.done ? '✓' : ''}</button><p>${task.milestone ? '<b>◆</b> ' : ''}${escape(task.text || task.raw)}<small>${escape(task.date)} · L${task.line}${task.estimate ? ` · estimated ${hoursLabel(task.estimate)}` : ''}${task.time ? ` · took ${hoursLabel(task.time)}` : ''}</small></p><button class="icon-button" data-action="edit-project-task" data-source="${escape(task.source)}" data-line="${task.line}" data-raw="${escape(task.raw)}" data-project-slug="${escape(task.projectSlug)}" title="Edit project task">✎</button></li>`).join('')}</ol>` : '<p class="muted project-empty">Nothing here yet.</p>';
}
function projectDetail(project, progress = null) {
  const tasks = project.tasks || [];
  const milestones = tasks.filter(task => task.milestone && !task.done);
  const active = tasks.filter(task => !task.milestone && !task.done);
  const completed = tasks.filter(task => task.done);
  const percent = progress ?? (project.taskCount ? Math.round(project.completedCount / project.taskCount * 100) : 0);
  return `<section class="project-detail"><div class="project-progress"><i style="width:${percent}%"></i></div><div class="project-metrics"><span><b>${project.openCount}</b><small>open tasks</small></span><span><b>${project.milestoneCompleted}/${project.milestoneCount}</b><small>milestones</small></span><span><b>${hoursLabel(project.timeTotal)}</b><small>time so far</small></span><span><b>${hoursLabel(project.estimateTotal)}</b><small>estimated</small></span></div><section><h3>Milestones</h3>${projectTaskList(milestones)}</section><section><h3>Active tasks</h3>${projectTaskList(active)}</section><details class="project-completed" ${completed.length ? 'open' : ''}><summary>Completed tasks <span>${completed.length}</span></summary>${projectTaskList(completed)}</details><footer><button class="button" data-action="project-capture" data-project-slug="${escape(project.slug)}">＋ Add project task</button>${project.path ? `<button class="button ghost" data-action="open-project-note" data-project-slug="${escape(project.slug)}">Open note</button>` : `<button class="button ghost" data-action="create-project-note" data-project-slug="${escape(project.slug)}" data-project-title="${escape(project.title)}">Create note</button>`}<button class="button ghost" data-action="refresh-projects">↻ Refresh</button></footer></section>`;
}
function habitStateMark(stateValue) { return stateValue === 'completed' ? '✓' : stateValue === 'skipped' ? '−' : ''; }
function habitStateClass(stateValue) { return stateValue === 'completed' ? 'done' : stateValue === 'skipped' ? 'skipped' : ''; }
function habitPeriods() { return habitPeriodsForSettings(state.habitSettings); }
function zonedParts(timezone = state.habitSettings?.timezone || DEFAULT_HABIT_SETTINGS.timezone) { return zonedPartsForSettings(timezone, todayIso); }
function habitPeriod(habit) { return habitPeriodForSettings(habit, state.habitSettings); }
function habitPeriodLabel(periodId) { return habitPeriodLabelForSettings(periodId, state.habitSettings); }
function habitPeriodMeta(periodId) { return habitPeriodMetaForSettings(periodId, state.habitSettings); }
function isMissedHabit(habit) { return isMissedHabitForState(habit, state, state.habitSettings, todayIso); }
function habitStreak(habit) { return habitStreakForState(habit, state, state.habitSettings, todayIso); }
function habitRow(habit) {
  const missed = isMissedHabit(habit);
  const streak = habitStreak(habit);
  const justCompleted = window.justCompletedHabit === habit.habit && habit.state === 'completed';
  return `<article class="habit-row ${habitStateClass(habit.state)}">
    <button class="check" data-action="toggle-habit" data-line="${habit.line}" data-habit="${escape(habit.habit)}" data-state="${habit.state}" aria-label="Toggle habit">${habitStateMark(habit.state)}</button>
    <div><p>${escape(habit.habit)}</p><small>${escape(habit.progress || '')}</small></div>
    <div class="habit-signals">${streak ? `<span class="habit-streak ${justCompleted ? 'flare' : ''}" title="${streak} completed in a row">🔥 ${streak}</span>` : ''}${missed ? '<span class="habit-missed">missed</span>' : ''}</div>
    <button class="icon-button" title="${habit.state === 'skipped' ? 'Restore habit' : 'Skip today'}" data-action="skip-habit" data-line="${habit.line}" data-habit="${escape(habit.habit)}" data-state="${habit.state}">${habit.state === 'skipped' ? '↺' : '−'}</button>
  </article>`;
}
function habitDailySections(habits = []) {
  const periods = [...habitPeriods().map(period => period.id), 'anytime'];
  const groups = periods.map(period => [period, habits.filter(habit => habitPeriod(habit) === period)]).filter(([, items]) => items.length);
  return `<div class="habit-list grouped">${groups.map(([period, items]) => `<section class="habit-period"><header><span>${escape(habitPeriodLabel(period))}</span><small>${escape(habitPeriodMeta(period))}</small></header>${items.map(habitRow).join('')}</section>`).join('')}</div>`;
}
function monthDays() { const now = new Date(), days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate(); return Array.from({ length: days }, (_, index) => new Date(now.getFullYear(), now.getMonth(), index + 1)); }
function allTimeDates(entries = []) { const dates = [...new Set(entries.map(entry => entry.date))].sort(); return dates.map(date => new Date(`${date}T12:00:00`)); }
function habitCalendar(habitName, entries = [], range = 'month') {
  const dates = range === 'all' ? allTimeDates(entries) : monthDays();
  const byDate = Object.fromEntries(entries.filter(entry => entry.habit === habitName).map(entry => [entry.date, entry]));
  const completed = Object.values(byDate).filter(entry => entry.state === 'completed').length, scheduled = Object.keys(byDate).length;
  return `<div class="habit-calendar"><div class="habit-calendar-summary"><strong>${escape(habitName || 'Choose a habit')}</strong><small>${completed}/${scheduled} completed${scheduled ? ` · ${Math.round(completed / scheduled * 100)}%` : ''}</small></div><div class="habit-month-grid">${dates.map(date => { const iso = isoDate(date), entry = byDate[iso], stateName = entry?.state || 'empty'; return `<span class="${stateName}" title="${escape(`${iso}${entry ? ` · ${entry.state}` : ''}`)}"><b>${date.getDate()}</b></span>`; }).join('')}</div></div>`;
}
function habitGraph(totals = [], range = 'month') {
  const dates = range === 'all' ? allTimeDates(totals) : monthDays();
  const byDate = Object.fromEntries(totals.map(day => [day.date, day]));
  const max = Math.max(1, ...totals.map(day => day.scheduled || 0));
  return `<div class="habit-graph ${range === 'all' ? 'all-time' : 'month-view'}">${dates.map(date => { const iso = isoDate(date), day = byDate[iso] || { completed: 0, scheduled: 0 }; const height = Math.max(3, Math.round((day.completed || 0) / max * 54)); return `<div title="${escape(`${iso}: ${day.completed || 0}/${day.scheduled || 0}`)}"><i style="height:${height}px"></i><small>${date.getDate()}</small></div>`; }).join('')}</div>`;
}
function archivedHabitPanel(habit, entries = [], range = 'month') {
  const open = state.habits.expandedArchive === habit.habit;
  const habitEntries = entries.filter(entry => entry.habit === habit.habit);
  const totals = [...new Set(habitEntries.map(entry => entry.date))].map(date => ({ date, completed: habitEntries.some(entry => entry.date === date && entry.state === 'completed') ? 1 : 0, scheduled: habitEntries.some(entry => entry.date === date) ? 1 : 0 }));
  return `<div class="archived-habit"><button data-action="toggle-archived-habit" data-habit="${escape(habit.habit)}"><span>${escape(habit.habit)}</span><small>${escape(habit.status || 'archived')}</small><b>${open ? '⌃' : '⌄'}</b></button>${open ? `<div class="archived-habit-detail">${habitCalendar(habit.habit, entries, range)}${habitGraph(totals, range)}</div>` : ''}</div>`;
}
function render() {
  const openTasks = state.tasks.filter(t => !t.done).length;
  const activeTasks = state.tasks.filter(t => !t.done);
  const completedTasks = state.tasks.filter(t => t.done);
  const projectData = state.projects || { projects: [], taskCount: 0 };
  const visibleProjects = (projectData.projects || []).slice(0, 4);
  const spotify = state.spotify;
  const youtube = state.youtube;
  const placeData = state.traccar.connected ? state.traccar.places : state.places;
  const locationTaskData = tasksForCurrentPlace(activeTasks, placeData || []);
  const locationTaskIds = new Set(locationTaskData.tasks.map(task => task.id));
  const normalActiveTasks = activeTasks.filter(task => !locationTaskIds.has(task.id));
  const locationTaskSection = locationTaskData.tasks.length ? `<section class="location-tasks"><div class="location-tasks-head"><span>⌖</span><p><strong>Tasks in your location</strong><small>${escape(locationTaskData.currentPlace?.name || 'Current place')}</small></p></div>${locationTaskData.tasks.map(taskCard).join('')}</section>` : '';
  const calendarEvents = state.google.connected ? state.google.events.map(event => {
    const allDay = Boolean(event.start?.date && !event.start?.dateTime);
    return allDay
      ? { id: event.id, title: event.summary || '(Untitled event)', type: 'all-day', allDay: true }
      : { id: event.id, time: new Date(event.start?.dateTime || `${event.start?.date}T00:00:00`).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), end: new Date(event.end?.dateTime || `${event.end?.date}T00:00:00`).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), title: event.summary || '(Untitled event)', type: 'meeting', allDay: false };
  }) : EMPTY_CALENDAR_EVENTS;
  const allDayEvents = calendarEvents.filter(event => event.allDay);
  const timedCalendarEvents = calendarEvents.filter(event => !event.allDay);
  const gmailSuggestions = state.gmail.connected ? state.gmail.messages.map(message => ({ source: `Gmail · ${message.from.split('<')[0].trim()}`, time: 'new', title: message.subject, why: message.snippet || 'Fresh message captured from your configured Gmail search.', url: `https://mail.google.com/mail/u/0/#all/${message.id}` })) : null;
  const availableSuggestions = gmailSuggestions || EMPTY_INSPIRATION_FIXTURES;
  const contentSuggestions = state.locationView === 'week' ? availableSuggestions : availableSuggestions.slice(0, state.contentDisplay.limit);
  const spotifyPeriodStats = spotifyStats(spotify, spotify.range || 'today');
  const spotifyMinutes = Number(spotifyPeriodStats.minutes || 0);
  const currentTrack = spotify.current || null;
  const spotifyArtworkUrl = currentTrack?.artwork || '';
  const spotifyArtwork = `<div class="spotify-art large ${currentTrack?.isPlaying ? 'is-playing' : ''}"><span class="spotify-vinyl"></span>${spotifyArtworkUrl ? `<img src="${escape(spotifyArtworkUrl)}" alt="${escape(currentTrack?.title || 'Spotify album artwork')}" loading="lazy">` : '<div class="album">◒</div>'}</div>`;
  const spotifyRows = (spotify.view === 'songs' ? spotifyPeriodStats.songs : spotifyPeriodStats.artists).map((item, index) => {
    const main = spotify.view === 'songs' ? item.title : item.name;
    const meta = spotify.view === 'songs' ? `${item.artist} · ${item.playbacks} playback${item.playbacks === 1 ? '' : 's'} · ${durationLabel(item.minutes * 60)}` : `${durationLabel(item.minutes * 60)} · ${item.playbacks} playback${item.playbacks === 1 ? '' : 's'}`;
    return `<div class="spotify-stat-row"><span>${String(index + 1).padStart(2, '0')}</span>${item.artwork ? `<img src="${escape(item.artwork)}" alt="" loading="lazy">` : '<i>◒</i>'}<p><strong>${escape(main)}</strong><small>${escape(meta)}</small></p></div>`;
  }).join('');
  const spotifyStatus = spotify.connected ? (spotify.endpointNotes?.length ? 'partial' : 'connected') : 'not connected';
  const spotifyStatusKind = spotify.connected ? (spotify.endpointNotes?.length ? 'estimated' : 'captured') : 'manual';
  const spotifyTitle = spotify.connected ? (spotifyMinutes ? `${durationLabel(spotifyMinutes * 60)} ${spotify.range || 'today'}` : 'Listening history') : 'Spotify';
  const spotifyMeta = spotify.connected ? `${spotifyPeriodStats.plays.length} captured play${spotifyPeriodStats.plays.length === 1 ? '' : 's'} · local history` : 'Connect Spotify to start local listening history';
  const spotifyTrackMeta = currentTrack?.artist || (spotify.connected ? (spotify.nowStatus || 'Play something in Spotify to wake this card up') : 'Current song, top artists, and top songs');
  const spotifyNowTitle = currentTrack?.title || (spotify.connected ? 'Nothing playing right now' : 'Connect Spotify');
  const spotifyViewTabs = `<div class="places-switch media-switch spotify-switch" role="tablist"><button class="${spotify.view !== 'songs' ? 'selected' : ''}" data-action="set-spotify-view" data-view="artists">Top artists</button><button class="${spotify.view === 'songs' ? 'selected' : ''}" data-action="set-spotify-view" data-view="songs">Top songs</button></div>`;
  const spotifyRangeTabs = `<div class="youtube-filter spotify-range" role="tablist"><button class="${spotify.range === 'today' ? 'selected' : ''}" data-action="set-spotify-range" data-range="today">Today</button><button class="${spotify.range === 'week' ? 'selected' : ''}" data-action="set-spotify-range" data-range="week">This week</button><button class="${spotify.range === 'month' ? 'selected' : ''}" data-action="set-spotify-range" data-range="month">This month</button></div>`;
  const spotifyConnectPrompt = !spotify.connected ? `<div class="spotify-connect-prompt"><button class="button" data-action="connect-spotify">Connect Spotify</button><small>Premium is not required. Lifey stores listening history locally from now on.</small></div>` : '';
  const youtubeWeekData = youtube.week || { days: [], videos: [], totalActiveSeconds: 0 };
  const selectedYoutubeDay = youtubeWeekData.days?.find(day => day.date === state.youtubeWeekDay) || youtubeWeekData.days?.find(day => day.date === todayIso()) || youtubeWeekData.days?.at(-1);
  const youtubeActiveVideos = [...(state.youtubeView === 'week' ? (selectedYoutubeDay?.videos || []) : (youtube.videos || []))].sort((a, b) => state.contentDisplay.youtubeSort === 'time' ? String(b.lastSeen || '').localeCompare(String(a.lastSeen || '')) || Number(b.activeSeconds || 0) - Number(a.activeSeconds || 0) : Number(b.activeSeconds || 0) - Number(a.activeSeconds || 0) || String(b.lastSeen || '').localeCompare(String(a.lastSeen || '')));
  const youtubeActiveSeconds = state.youtubeView === 'week' ? Number(selectedYoutubeDay?.totalActiveSeconds || 0) : Number(youtube.totalActiveSeconds || 0);
  const youtubeWeekTotal = Number(youtubeWeekData.totalActiveSeconds || 0);
  const youtubeEntryCount = youtubeActiveVideos.length;
  const youtubeStatusBadge = youtube.extensionLastSeen ? 'connected' : 'extension offline';
  const videoRows = (youtubeActiveVideos.length ? youtubeActiveVideos.map(video => [video.title, durationLabel(video.activeSeconds), new Date(video.lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), 'Captured']) : [[youtube.extensionLastSeen ? 'Tracker connected — reload a YouTube video' : 'Tracker has not reached the local helper', '—', 'Zen / Firefox', 'Setup']]).map(v => `<div><span class="play">▶</span><p>${escape(v[0])}<small>${v[2]} · ${v[1]}</small></p>${badge(v[3], 'captured')}</div>`).join('');
  const youtubeWeekContent = `<div class="week-days youtube-week">${youtubeWeekData.days?.length ? `<div class="week-day-switch" role="tablist">${youtubeWeekData.days.map(day => { const date = new Date(`${day.date}T12:00:00`); return `<button class="${selectedYoutubeDay?.date === day.date ? 'selected' : ''}" data-action="set-youtube-week-day" data-date="${day.date}"><span>${date.toLocaleDateString([], { weekday: 'short' })}</span><b>${date.getDate()}</b></button>`; }).join('')}</div><div class="week-day"><div class="week-day-summary"><p>${new Date(`${selectedYoutubeDay.date}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })}</p><span><small>Total time</small><strong>${youtubeActiveVideos.length ? durationLabel(youtubeActiveSeconds) : '0 min'}</strong></span></div></div>` : '<p class="muted">Load this week to see watched videos by day.</p>'}</div>`;
  const activeProjectCount = (projectData.projects || []).filter(project => project.openCount > 0).length;
  const projectProgress = projectData.taskCount ? Math.round((projectData.projects || []).reduce((sum, project) => sum + (project.completedCount || 0), 0) / projectData.taskCount * 100) : 0;
  const habitScheduled = (state.habits.today || []).filter(habit => habit.state !== 'skipped').length;
  const habitCompleted = (state.habits.today || []).filter(habit => habit.state === 'completed').length;
  const placeTotal = (placeData || []).reduce((sum, place) => sum + placeDurationMilliseconds(place), 0);
  const heroMetric = {
    tasks: () => stat('Tasks', `${openTasks} left`, 'exact · Obsidian', 'yellow'),
    projects: () => stat('Projects', `${activeProjectCount} active`, projectData.taskCount ? `${projectProgress}% complete` : 'no tagged tasks yet', 'yellow'),
    habits: () => stat('Habits', `${habitCompleted}/${habitScheduled}`, 'today · Obsidian', 'yellow'),
    calendar: () => stat('Calendar', `${calendarEvents.length} events`, state.google.connected ? 'exact · Google Calendar' : 'not connected', 'blue'),
    youtube: () => stat('YouTube', youtube.videos.length ? durationLabel(youtube.totalActiveSeconds) : '—', youtube.videos.length ? 'active tab time' : 'extension not connected', 'lime'),
    spotify: () => stat('Spotify', spotify.connected ? (spotifyMinutes ? durationLabel(spotifyMinutes * 60) : 'connected') : '—', spotify.connected ? 'read-only API' : 'not connected', 'violet'),
    places: () => stat('Places', `${(placeData || []).length} visited`, state.traccar.connected ? `estimated · ${totalTimeLabel(placeTotal)}` : 'location not connected', 'blue'),
    suggestions: () => stat('Inspiration', `${contentSuggestions.length} items`, state.gmail.connected ? 'Gmail · fresh' : 'starter fixtures', 'blue')
  };
  const heroStats = state.heroMetricOrder.filter(key => state.heroMetricVisibility?.[key] !== false && heroMetric[key]).map(key => heroMetric[key]());
  const placeRow = (p, index, actions = false, date = '') => { const timing = placeTiming(p); const hasCoordinates = state.traccar.connected && Number.isFinite(p.latitude) && Number.isFinite(p.longitude); const selected = placeMergeSelection.includes(index); const hasPointDetail = (p.points || []).length > 1; const pointButton = hasPointDetail ? `<button class="icon-button place-points" title="See ${p.points.length} captured points" aria-label="See ${p.points.length} captured points" data-action="view-place-points" data-place-index="${index}" data-place-date="${date}">◎</button>` : ''; const mapButton = hasCoordinates ? `<button class="icon-button place-map" title="Open in Google Maps" aria-label="Open in Google Maps" data-action="open-place-map" data-latitude="${p.latitude}" data-longitude="${p.longitude}">↗</button>` : ''; const passiveControls = hasPointDetail ? pointButton : mapButton; return `<div class="${p.merged ? 'is-merged' : ''}">${placeMergeMode && actions ? `<button class="place-select ${selected ? 'selected' : ''}" title="Select ${escape(p.name)}" aria-label="Select ${escape(p.name)}" data-action="toggle-place-merge" data-place-index="${index}">${selected ? '✓' : ''}</button>` : '<span class="pin">✦</span>'}<p><strong>${escape(p.name)}${p.merged ? '<span class="merged-place" title="Manual merge">★</span>' : ''}</strong><small>${escape(timing.range)} · ${escape(p.source)}${timing.total ? `<br><span class="place-total">${escape(timing.total)}</span>` : ''}</small></p>${actions && hasCoordinates && !placeMergeMode ? `${pointButton}<button class="icon-button place-label" title="Name this place" aria-label="Name this place" data-action="label-place" data-place-index="${index}">✎</button>${mapButton}` : !placeMergeMode ? passiveControls : ''}</div>`; };
  const weekData = state.traccar.week || { days: [], topPlaces: [] };
  const selectedWeekDay = weekData.days?.find(day => day.date === state.locationWeekDay) || weekData.days?.at(-1);
  const selectedWeekDayTotal = (selectedWeekDay?.places || []).reduce((sum, place) => sum + placeDurationMilliseconds(place), 0);
  const weekContent = `<div class="week-places"><section class="week-top-places"><p class="eyebrow">TOP PLACES THIS WEEK</p>${weekData.topPlaces?.length ? weekData.topPlaces.map((place, index) => `<div><span>${String(index + 1).padStart(2, '0')}</span><strong>${escape(place.name)}</strong><small>${totalTimeLabel((place.seconds || 0) * 1000)} · ${place.visits} visit(s)</small></div>`).join('') : '<p class="muted">Load this week to see your top places.</p>'}</section><section class="week-days">${weekData.days?.length ? `<div class="week-day-switch" role="tablist">${weekData.days.map(day => { const date = new Date(`${day.date}T12:00:00`); return `<button class="${selectedWeekDay?.date === day.date ? 'selected' : ''}" data-action="set-week-day" data-date="${day.date}"><span>${date.toLocaleDateString([], { weekday: 'short' })}</span><b>${date.getDate()}</b></button>`; }).join('')}</div><div class="week-day"><div class="week-day-summary"><p>${new Date(`${selectedWeekDay.date}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })}</p><span><small>Total time</small><strong>${selectedWeekDay.places.length ? totalTimeLabel(selectedWeekDayTotal) : '0 min'}</strong></span></div><div class="place-list">${selectedWeekDay.places.length ? selectedWeekDay.places.map((place, index) => placeRow(place, index, false, selectedWeekDay.date)).join('') : '<small>No location points</small>'}</div></div>` : '<p class="muted">Load this week to see each day’s visits.</p>'}</section></div>`;
  const habitData = state.habits || {};
  const habitTabs = ['today', 'calendar', 'graph', 'archived'].map(tab => `<button class="${habitData.view === tab ? 'selected' : ''}" data-action="set-habits-view" data-view="${tab}">${tab === 'today' ? 'Today' : tab[0].toUpperCase() + tab.slice(1)}</button>`).join('');
  const habitRange = `<div class="habit-range"><button class="${habitData.range !== 'all' ? 'selected' : ''}" data-action="set-habits-range" data-range="month">Month</button><button class="${habitData.range === 'all' ? 'selected' : ''}" data-action="set-habits-range" data-range="all">All time</button></div>`;
  const selectedHabit = habitData.selectedHabit || habitData.habits?.[0] || habitData.active?.[0]?.habit || '';
  const habitSelector = `<div class="habit-selector">${(habitData.habits || []).map(habit => `<button class="${selectedHabit === habit ? 'selected' : ''}" data-action="select-habit" data-habit="${escape(habit)}">${escape(habit)}</button>`).join('') || '<small>No habit history yet.</small>'}</div>`;
  const habitsToday = habitData.today || [];
  const habitTodayContent = habitsToday.length ? habitDailySections(habitsToday) : `<p class="muted">No habits are in today’s note yet. Sync from Active Habits to create today’s snapshot.</p>`;
  const habitCalendarContent = `${habitRange}${habitSelector}${selectedHabit ? habitCalendar(selectedHabit, habitData.history || [], habitData.range || 'month') : '<p class="muted">No habit history found yet.</p>'}`;
  const habitGraphContent = `${habitRange}${habitGraph(habitData.dailyTotals || [], habitData.range || 'month')}`;
  const habitArchivedContent = `${habitRange}<div class="archived-habits">${(habitData.archived || []).length ? habitData.archived.map(habit => archivedHabitPanel(habit, habitData.history || [], habitData.range || 'month')).join('') : '<p class="muted">No archived habits in Active Habits.md yet.</p>'}</div>`;
  const habitContent = habitData.view === 'calendar' ? habitCalendarContent : habitData.view === 'graph' ? habitGraphContent : habitData.view === 'archived' ? habitArchivedContent : habitTodayContent;
  renderDashboardShell();
  const statsRoot = document.querySelector('#dashboard-stats');
  if (statsRoot) statsRoot.innerHTML = heroStats.length ? `<section class="stats">${heroStats.join('')}</section>` : '';
  const gridRoot = document.querySelector('#dashboard-grid');
  if (gridRoot) gridRoot.innerHTML = `
      <section class="panel tasks-panel ${state.visibility.tasks === false ? 'hidden-by-preference' : ''}" data-card-key="tasks" ${cardOrderStyle('tasks')}><header><div><p class="eyebrow">OBSIDIAN</p><h2>Today’s tasks</h2></div>${badge('vault synced', 'exact')}</header>${locationTaskSection}<div class="task-list">${normalActiveTasks.map(taskCard).join('')}</div>${completedTasks.length ? `<details class="completed-tasks"><summary><span>Completed</span><span class="completed-count">${completedTasks.length}</span><span class="completed-chevron">⌄</span></summary><div class="completed-list">${completedTasks.map(taskCard).join('')}</div></details>` : ''}<footer><button class="text-button" data-action="refresh-vault">↻ Refresh daily note</button></footer></section>
      <section class="panel projects-panel ${state.visibility.projects === false ? 'hidden-by-preference' : ''}" data-card-key="projects" ${cardOrderStyle('projects')}><header><div><p class="eyebrow">PROJECTS</p><h2>Active projects</h2></div>${badge(`${projectData.projects?.length || 0} found`, 'exact')}</header><div class="project-list">${visibleProjects.length ? visibleProjects.map(projectCard).join('') : '<p class="muted">No project-tagged tasks found yet. Add #project/project-name to tasks in your daily notes.</p>'}</div><footer><button class="text-button" data-action="refresh-projects">↻ Refresh projects</button><span>${projectData.taskCount || 0} tagged task(s)</span></footer></section>
      <section class="panel habits-panel ${state.visibility.habits === false ? 'hidden-by-preference' : ''}" data-card-key="habits" ${cardOrderStyle('habits')}><header><div><p class="eyebrow">HABITS</p><h2>Daily practice</h2></div>${badge(`${habitsToday.filter(h => h.state === 'completed').length}/${habitsToday.length || 0}`, 'exact')}</header><div class="places-switch habits-tabs" role="tablist">${habitTabs}</div><div class="habit-content">${habitContent}</div><footer><button class="text-button" data-action="refresh-habits">↻ Refresh habits</button><button class="text-button" data-action="sync-habits">＋ Sync from Active Habits</button></footer></section>
      <section class="panel calendar ${state.visibility.calendar === false ? 'hidden-by-preference' : ''}" data-card-key="calendar" ${cardOrderStyle('calendar')}><header><div><p class="eyebrow">GOOGLE CALENDAR</p><h2>Day in motion</h2></div>${badge(state.google.connected ? 'connected' : state.google.sessionExpired ? 'reconnect' : 'not connected', state.google.connected ? 'exact' : 'estimated')}</header>${allDayEvents.length ? `<div class="all-day-events">${allDayEvents.map(e => `<div class="all-day-event"><span>All day</span><strong>${escape(e.title)}</strong>${e.id ? `<button class="icon-button event-delete" title="Delete Calendar event" aria-label="Delete ${escape(e.title)}" data-action="delete-calendar-event" data-event-id="${escape(e.id)}">×</button>` : ''}</div>`).join('')}</div>` : ''}<div class="timeline">${timedCalendarEvents.length ? timedCalendarEvents.map((e,i) => `<div class="event ${e.type}" style="--offset:${i * 1.26}"><time>${e.time}</time><div><strong>${escape(e.title)}</strong><small>${e.time} — ${e.end}</small>${e.id ? `<button class="icon-button event-delete" title="Delete Calendar event" aria-label="Delete ${escape(e.title)}" data-action="delete-calendar-event" data-event-id="${escape(e.id)}">×</button>` : ''}</div></div>`).join('') : '<p class="muted">Connect Google Calendar to show today’s events.</p>'}</div><footer><button class="text-button" data-action="connect-google">${state.google.connected ? '↻ Refresh calendar' : state.google.sessionExpired ? 'Reconnect Google Calendar' : 'Connect Google Calendar'}</button><button class="text-button" data-action="open-google-calendar"><span class="action-arrow">↗</span>Open today</button><button class="text-button" data-action="create-event">＋ Create event</button></footer></section>
      <section class="panel compact youtube-panel youtube-size-${escape(state.contentDisplay.youtubeSize)} ${state.visibility.youtube === false ? 'hidden-by-preference' : ''}" data-card-key="youtube" ${cardOrderStyle('youtube')}><header><div><p class="eyebrow">YOUTUBE</p><h2>${state.youtubeView === 'week' ? `${durationLabel(youtubeWeekTotal)} this week` : youtubeActiveVideos.length ? `${durationLabel(youtubeActiveSeconds)} today` : 'No activity yet'}</h2><small class="youtube-card-meta">${youtubeEntryCount} captured entr${youtubeEntryCount === 1 ? 'y' : 'ies'} · active tab time</small></div>${badge(youtubeStatusBadge, youtube.extensionLastSeen ? 'captured' : 'manual')}</header><div class="places-switch media-switch" role="tablist"><button class="${state.youtubeView === 'today' ? 'selected' : ''}" data-action="set-youtube-view" data-view="today">Today</button><button class="${state.youtubeView === 'week' ? 'selected' : ''}" data-action="set-youtube-view" data-view="week">This week</button></div><div class="youtube-filter" role="tablist" aria-label="Sort YouTube videos"><button class="${state.contentDisplay.youtubeSort === 'duration' ? 'selected' : ''}" data-action="set-youtube-sort" data-sort="duration">By duration</button><button class="${state.contentDisplay.youtubeSort === 'time' ? 'selected' : ''}" data-action="set-youtube-sort" data-sort="time">By time</button></div>${state.youtubeView === 'week' ? youtubeWeekContent : ''}<div class="video-list youtube-scroll">${videoRows}</div><footer><button class="text-button" data-action="youtube-setup">${youtubeActiveVideos.length || state.youtubeView === 'week' ? '↻ Refresh activity' : 'Check tracker'}</button></footer></section>
      <section class="panel compact spotify spotify-v2 ${state.visibility.spotify === false ? 'hidden-by-preference' : ''}" data-card-key="spotify" ${cardOrderStyle('spotify')}><header><div><p class="eyebrow">SPOTIFY</p><h2>${spotifyTitle}</h2><small class="youtube-card-meta">${spotifyMeta}</small></div>${badge(spotifyStatus, spotifyStatusKind)}</header><div class="spotify-now-v2">${spotifyArtwork}<div class="spotify-now-copy"><small>${currentTrack?.isPlaying ? 'Now playing' : 'Spotify'}</small><strong>${escape(spotifyNowTitle)}</strong><span>${escape(spotifyTrackMeta)}</span></div><button class="icon-button" data-action="connect-spotify">${spotify.connected ? '↻' : '↗'}</button></div>${spotifyConnectPrompt}${spotify.connected ? `${spotifyViewTabs}${spotifyRangeTabs}<div class="spotify-stat-list">${spotifyRows || `<p class="muted spotify-empty">No captured Spotify plays for this period yet. Keep Lifey open while listening, or refresh after Spotify has recent plays.</p>`}</div>` : ''}${spotify.endpointNotes?.length ? `<p class="spotify-limited">${escape(spotify.nowStatus || 'Some Spotify endpoints are unavailable, but local history still works when playback can be read.')}</p>` : ''}<footer><button class="text-button" data-action="connect-spotify">${spotify.connected ? '↻ Refresh Spotify' : 'Connect Spotify'}</button>${spotify.connected ? '<button class="text-button" data-action="reconnect-spotify">↗ Reconnect</button>' : ''}<button class="text-button" data-action="diagnose-spotify">Diagnose</button></footer></section>
      <section class="panel suggestions ${state.visibility.suggestions === false ? 'hidden-by-preference' : ''}" data-card-key="suggestions" ${cardOrderStyle('suggestions')}><header><div><p class="eyebrow">A LITTLE INSPIRATION</p><h2>Inspiration for today</h2></div></header><div class="suggestion-list">${contentSuggestions.map((s,i) => `<article><span class="number">${String(i + 1).padStart(2, '0')}</span><div><small>${escape(s.source)} · ${s.time}</small><h3>${escape(s.title)}</h3><p>${escape(s.why)}</p></div><button class="save" title="${s.url ? 'Open in Gmail' : 'Source link unavailable'}" data-action="open-suggestion" data-url="${escape(s.url || '')}">↗</button></article>`).join('')}</div><footer><button class="text-button" data-action="connect-gmail">${state.gmail.connected ? '↻ Refresh Gmail' : 'Connect Gmail'}</button></footer></section>
      <section class="panel places ${state.visibility.places === false ? 'hidden-by-preference' : ''}" data-card-key="places" ${cardOrderStyle('places')}><header><div><p class="eyebrow">PLACES</p><h2>Where the day went</h2></div>${badge(state.traccar.connected ? (state.traccar.source || 'locations') : 'manual + import', state.traccar.connected ? 'exact' : 'manual')}</header><div class="places-switch" role="tablist"><button class="${state.locationView === 'today' ? 'selected' : ''}" data-action="set-location-view" data-view="today">Today</button><button class="${state.locationView === 'week' ? 'selected' : ''}" data-action="set-location-view" data-view="week">This week</button></div>${state.locationView === 'week' ? weekContent : `<div class="place-list">${placeData.map((place, index) => placeRow(place, index, true)).join('')}</div>`}<footer><button class="text-button" data-action="refresh-location">${state.traccar.connected ? '↻ Refresh locations' : 'Load locations'}</button>${state.locationView === 'today' && state.traccar.connected ? (placeMergeMode ? `<button class="text-button" data-action="confirm-place-merge">Merge ${placeMergeSelection.length || ''}</button><button class="text-button" data-action="cancel-place-merge">Cancel</button>` : '<button class="text-button" data-action="start-place-merge">Merge places</button>') : ''}<button class="text-button" data-action="archive-location-menu">Archive…</button><span>Durations approximate</span></footer></section>
    `;
  arrangeDashboardCards();
}
function modal(title, content, action = 'close', options = {}) { const el = options.layer === 'sub' ? (document.querySelector('#submodal') || document.body.appendChild(Object.assign(document.createElement('dialog'), { id: 'submodal' }))) : document.querySelector('#modal'); const confirmLabel = action === 'save-quick-task' ? 'Add task' : 'Confirm'; el.classList.toggle('submodal', options.layer === 'sub'); el.innerHTML = `<button class="close" data-action="close">×</button><p class="eyebrow">QUICK ACTION</p><h2>${title}</h2>${content}<div class="modal-actions"><button class="button ghost" data-action="close">Cancel</button><button class="button" data-action="${action}">${confirmLabel}</button></div>`; if (!el.open) el.showModal(); }
function showPlacePoints(place) { const el = document.querySelector('#modal'); const points = place.points || []; el.innerHTML = `<button class="close" data-action="close">×</button><p class="eyebrow">MERGED PLACE</p><h2>${escape(place.name)}</h2><p class="modal-copy">${points.length} captured point${points.length === 1 ? '' : 's'} behind this ★ location. Times and position are estimated from ${escape(state.traccar.source || 'location samples')}.</p><div class="place-point-list">${points.length ? points.map((point, index) => `<div><span>${String(index + 1).padStart(2, '0')}</span><p><strong>${escape(clockTime(point.timestamp))}</strong><small>${Number(point.latitude).toFixed(5)}, ${Number(point.longitude).toFixed(5)}</small></p><button class="icon-button" title="Open in Google Maps" aria-label="Open point ${index + 1} in Google Maps" data-action="open-place-map" data-latitude="${point.latitude}" data-longitude="${point.longitude}">↗</button></div>`).join('') : '<p class="muted">These points were captured before Lifey began retaining point detail. Refresh after new tracking data arrives to see them here.</p>'}</div><div class="modal-actions"><button class="button" data-action="close">Close</button></div>`; if (!el.open) el.showModal(); }
function quickCaptureModal(editTask = null, options = {}) { const el = document.querySelector('#modal'); const values = taskCaptureValues(editTask); window.captureProjectSlug = options.projectSlug || values.project || ''; window.editingTask = editTask; el.innerHTML = `<form class="capture-raycast" id="quick-capture-form">${window.captureProjectSlug ? `<div class="capture-context">#project/${escape(window.captureProjectSlug)}</div>` : ''}<div class="capture-command"><input id="capture-task" autocomplete="off" value="${escape(values.text)}" placeholder="Add a task…" aria-label="Task"><button class="capture-add" type="submit">${editTask ? 'Save task ↵' : 'Add task ↵'}</button></div><div class="capture-controls"><button class="capture-pill capture-daytime" type="button" data-action="open-capture-calendar" data-menu="calendar"><span id="capture-date-label">📅 ⏰ Day & time</span><span class="capture-arrow">⌄</span></button><input id="capture-date" type="hidden" value="${escape(values.due)}"><input id="capture-time" type="hidden" value="${escape(values.time)}"><input id="capture-priority" type="hidden" value="${escape(values.priority)}"><input id="capture-recurring" type="hidden" value="${escape(values.recurrence)}"><button class="capture-pill capture-menu-trigger" type="button" data-action="open-capture-options" data-menu="priority"><span id="capture-priority-label">❗️ Priority</span><span class="capture-arrow">⌄</span></button><button class="capture-pill capture-menu-trigger" type="button" data-action="open-capture-options" data-menu="recurring"><span id="capture-recurring-label">🔁 Recurring</span><span class="capture-arrow">⌄</span></button><button class="capture-pill capture-place" type="button" data-action="open-capture-places" data-menu="place"><span>📍 Place</span><span class="capture-arrow">⌄</span></button></div><div id="capture-option-dropdown"></div><div id="capture-place-dropdown"></div><div id="capture-calendar"></div><p class="capture-preview" id="capture-preview">Start typing to preview the task Markdown.</p><div class="capture-help"><span>Use “project personal dashboard”, “estimated time 1.5”, “around 2”, “it will take 3”, or “it took 1.25”.</span><kbd>Esc to close</kbd></div></form>`; if (!el.open) el.showModal(); const focusCapture = () => { const input = document.querySelector('#capture-task'); if (!input) return; input.focus({ preventScroll: true }); if (editTask) input.setSelectionRange(input.value.length, input.value.length); refreshQuickCapturePreview(); }; updateMobileCaptureOffset(); focusCapture(); requestAnimationFrame(() => { updateMobileCaptureOffset(); focusCapture(); }); setTimeout(() => { updateMobileCaptureOffset(); focusCapture(); document.querySelector('#capture-task')?.scrollIntoView({ block: 'nearest' }); }, 160); }
async function saveQuickCapture() { const parsed = parseNaturalTask(document.querySelector('#capture-task')?.value, quickCaptureControls()); if (!parsed.text) return toast('Write a task first.'); const editingProjectTask = window.editingProjectTask; const editingTask = window.editingTask && !editingProjectTask ? window.editingTask : null; const isProjectTask = Boolean(parsed.project); const result = editingProjectTask ? await updateProjectTask(editingProjectTask, { text: parsed.text }) : editingTask ? await editLocalTask(editingTask, parsed.text) : await addLocalTask(parsed.text, { preferDueDateNote: isProjectTask }); document.querySelector('#modal').close(); window.editingTask = null; window.editingProjectTask = null; window.captureProjectSlug = ''; let calendarSynced = true; if (editingTask?.calendarEventId) { try { await updateGoogleCalendarEvent(editingTask, parsed.text); } catch (error) { calendarSynced = false; toast(`Task updated in Obsidian, but its Calendar event was not synced: ${error.message}`); } } await loadLocalVault(true); await loadProjects(true).catch(() => {}); const addedLabel = result.noteDate && result.noteDate !== todayIso() ? `Added to ${result.noteDate} note` : 'Added to today’s note'; if (calendarSynced) toast(editingProjectTask ? `Updated project task · L${result.line}` : editingTask ? `Updated task${editingTask.calendarEventId ? ' and Calendar event' : ''} · L${result.line}` : `${addedLabel} · L${result.line}`); }
function preferenceToggle(label, key, checked, sub = '') { return `<section class="preference-section"><label class="preference-toggle"><span>${label}</span><input type="checkbox" data-visibility="${key}" ${checked ? 'checked' : ''}><i></i></label>${sub}</section>`; }
function openPreferences(tab = 'integrations', options = {}) {
  const el = document.querySelector('#modal');
  const tabs = [['integrations', '⌁', 'Integrations'], ['appearance', '◐', 'Appearance'], ['habits', '🔥', 'Habits'], ['archives', '▤', 'Archives'], ['location', '⌖', 'Location'], ['profile', '◇', 'Profile']];
  const activeTabLabel = tabs.find(([id]) => id === tab)?.[2] || 'Settings';
  const menu = tabs.map(([id, icon, label]) => `<button class="preferences-tab ${id === tab ? 'selected' : ''}" data-action="preferences-tab" data-tab="${id}"><b>${icon}</b><span>${label}</span></button>`).join('');
  const integration = (icon, title, detail, action) => `<button class="integration-row" data-action="${action}"><span class="integration-logo">${icon}</span><span><strong>${title}</strong><small>${detail}</small></span><i>›</i></button>`;
  const colors = [['background', 'Background'], ['glass', 'Card tint'], ['accent', 'Accent']];
  const heroMetricLabels = { tasks: 'Tasks', projects: 'Projects', habits: 'Habits', calendar: 'Calendar', youtube: 'YouTube', spotify: 'Spotify', places: 'Places', suggestions: 'Inspiration' };
  const heroMetricOrder = `<section class="appearance-section hero-metric-order"><div><p class="eyebrow">HERO METRICS</p><h3>Metric order</h3><p>Drag a metric into the place you want it to appear.</p></div><div class="hero-metric-list" role="list">${state.heroMetricOrder.map((key, index) => `<div class="hero-metric-item ${state.heroMetricVisibility?.[key] === false ? 'disabled' : ''}" draggable="true" role="listitem" data-hero-metric="${key}"><span class="hero-metric-number">${index + 1}</span><strong>${heroMetricLabels[key]}</strong><label class="hero-metric-toggle"><input type="checkbox" data-hero-metric-visible="${key}" ${state.heroMetricVisibility?.[key] === false ? '' : 'checked'}><i></i></label><span class="hero-metric-handle" aria-hidden="true">⠿</span></div>`).join('')}</div></section>`;
  const cardLabels = { tasks: 'Today’s tasks', calendar: 'Day in motion', youtube: 'YouTube', projects: 'Projects', suggestions: 'Inspiration', places: 'Where the day went', habits: 'Habits', spotify: 'Spotify' };
  const cardOrder = `<section class="appearance-section card-order-section"><div><p class="eyebrow">CARD SYSTEM</p><h3>Card order</h3><p>Drag cards into the order Lifey should place them in the three-column dashboard grid.</p></div><div class="card-order-list" role="list">${state.cardOrder.map((key, index) => `<div class="card-order-item" draggable="true" role="listitem" data-card-order="${key}"><span class="hero-metric-number">${index + 1}</span><strong>${cardLabels[key]}</strong><span class="hero-metric-handle" aria-hidden="true">⠿</span></div>`).join('')}</div></section>`;
  const cornerRadiusSettings = `<section class="appearance-section radius-settings"><div><p class="eyebrow">SHAPE</p><h3>Corner roundness</h3><p>Controls the radius used by cards, buttons, inputs, and preference controls.</p></div><label class="appearance-range">Round corners <output>${state.appearance.cornerRadius}px</output><input id="appearance-corner-radius" type="range" min="8" max="36" step="1" value="${state.appearance.cornerRadius}"></label></section>`;
  const backgroundImageSettings = `<section class="appearance-section background-image-settings"><div><p class="eyebrow">BACKGROUND IMAGE</p><h3>Dashboard background</h3><p>Add an image behind the whole dashboard. It is stored locally in this browser.</p></div><div class="background-image-control ${state.appearance.backgroundImage ? 'has-image' : ''}"><div class="background-image-preview">${state.appearance.backgroundImage ? `<img src="${escape(state.appearance.backgroundImage)}" alt="Dashboard background preview">` : '<span>No image</span>'}</div><div class="background-image-actions"><button class="button ghost" data-action="choose-background-image">Choose image</button>${state.appearance.backgroundImage ? '<button class="text-button" data-action="remove-background-image">Remove image</button>' : ''}<input id="dashboard-background-input" type="file" accept="image/*" hidden></div></div><div class="background-tint-controls"><label>Tint color<input type="color" data-appearance="backgroundTint" value="${escape(state.appearance.backgroundTint || '#15221f')}"></label><label>Tint intensity <output>${Number(state.appearance.backgroundTintIntensity ?? 72)}%</output><input id="background-tint-intensity" type="range" min="0" max="95" step="1" value="${Number(state.appearance.backgroundTintIntensity ?? 72)}"></label></div></section>`;
  const suggestionControl = `<div class="preference-sub suggestion-count"><span>Items to show</span><div><button class="${state.contentDisplay.limit === 2 ? 'selected' : ''}" data-action="set-suggestion-count" data-count="2">2</button><button class="${state.contentDisplay.limit === 4 ? 'selected' : ''}" data-action="set-suggestion-count" data-count="4">4</button><button class="${state.contentDisplay.limit === 6 ? 'selected' : ''}" data-action="set-suggestion-count" data-count="6">6</button></div></div>`;
  const youtubeSizeControl = `<div class="preference-sub suggestion-count"><span>Card size</span><div><button class="${state.contentDisplay.youtubeSize === 'small' ? 'selected' : ''}" data-action="set-youtube-card-size" data-size="small">Small</button><button class="${state.contentDisplay.youtubeSize === 'medium' ? 'selected' : ''}" data-action="set-youtube-card-size" data-size="medium">Medium</button><button class="${state.contentDisplay.youtubeSize === 'large' ? 'selected' : ''}" data-action="set-youtube-card-size" data-size="large">Large</button></div></div>`;
  const visibilitySettings = `<section class="appearance-section visibility-settings"><div><p class="eyebrow">VISIBILITY</p><h3>Show or hide cards</h3><p>Hide cards without disconnecting integrations or erasing their data.</p></div>${preferenceToggle('Today’s tasks', 'tasks', state.visibility.tasks, `<div class="preference-sub"><label class="preference-toggle small"><span>Show note path</span><input type="checkbox" data-task-display="showPath" ${state.taskDisplay.showPath ? 'checked' : ''}><i></i></label></div>`)}${preferenceToggle('Projects', 'projects', state.visibility.projects)}${preferenceToggle('Habits', 'habits', state.visibility.habits)}${preferenceToggle('Day in motion', 'calendar', state.visibility.calendar)}${preferenceToggle('YouTube', 'youtube', state.visibility.youtube, youtubeSizeControl)}${preferenceToggle('Spotify', 'spotify', state.visibility.spotify)}${preferenceToggle('Suggested content', 'suggestions', state.visibility.suggestions, suggestionControl)}${preferenceToggle('Where the day went', 'places', state.visibility.places)}</section>`;
  const timezoneOptions = ['America/Guayaquil', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/Madrid', 'UTC'];
  const habitRows = (state.habitSettings.periods || []).map((period, index) => `<div class="habit-period-setting" data-habit-period-index="${index}"><label>Name<input data-habit-period-field="name" value="${escape(period.name)}"></label><label>Starts<input type="time" data-habit-period-field="start" value="${escape(period.start)}"></label><label>Ends<input type="time" data-habit-period-field="end" value="${escape(period.end)}"></label><button class="icon-button" data-action="delete-habit-period" data-index="${index}" title="Delete period">×</button></div>`).join('');
  const habitsSettings = `<div class="preferences-head"><p class="eyebrow">HABITS</p><h2>Time periods</h2><p>These periods control the daily habit headers and when pending habits become missed. Times are evaluated in the timezone below.</p></div><section class="habit-settings"><label class="habit-timezone">Timezone<input id="habit-timezone" list="habit-timezones" value="${escape(state.habitSettings.timezone)}"><datalist id="habit-timezones">${timezoneOptions.map(zone => `<option value="${zone}"></option>`).join('')}</datalist><small>Use IANA names like <code>America/Guayaquil</code>. Current habit time there: ${String(Math.floor(zonedParts().minutes / 60)).padStart(2, '0')}:${String(zonedParts().minutes % 60).padStart(2, '0')}.</small></label><div class="habit-period-settings">${habitRows}</div><div class="habit-settings-actions"><button class="text-button" data-action="add-habit-period">＋ Add period</button><button class="text-button" data-action="reset-habit-periods">Reset defaults</button><button class="button" data-action="save-habit-settings">Save habit settings</button></div></section>`;
  const locationSettings = `<div class="preferences-head"><p class="eyebrow">LOCATION</p><h2>Place grouping</h2><p>Raw phone and Traccar points stay intact. This distance only changes how Lifey groups them into places.</p></div><section class="location-radius"><div><b>Different-place distance</b><small>Points closer than this are shown as the same visit.</small></div><output>${state.locationSettings.radiusMeters} m</output><input id="location-radius" type="range" min="20" max="500" step="10" value="${state.locationSettings.radiusMeters}"><label>Exact distance<input id="location-radius-number" type="number" min="20" max="500" step="10" value="${state.locationSettings.radiusMeters}"> metres</label></section><section class="merge-settings"><div><b>Manual merges</b><small>Always win over the distance above. Undoing a merge restores its archived place notes when possible.</small></div>${state.locationSettings.merges.length ? `<div class="merge-list">${state.locationSettings.merges.map(merge => `<div><span><strong>${escape(merge.name)}</strong><small>${merge.anchors?.length || 0} saved location(s)</small></span><button class="text-button" data-action="undo-place-merge" data-merge-id="${escape(merge.id)}">Undo</button></div>`).join('')}</div>` : '<p class="muted location-empty">No manual merges yet.</p>'}</section>`;
  const archiveSettings = `<div class="preferences-head"><p class="eyebrow">ARCHIVES</p><h2>Archive defaults</h2><p>Edit the plain Markdown Lifey writes into Journals. Each template must begin and end with <code>---</code>.</p></div><section class="archive-settings"><button class="integration-row archive-now" data-action="archive"><span class="integration-logo">↗</span><span><strong>Update daily archive</strong><small>Preview and write today’s Lifey section into Obsidian.</small></span><i>›</i></button><label>Daily archive title<input id="archive-title-daily" value="${escape(state.archiveTitles.daily)}"><small>Moment format: <code>DD-MM-YYYY</code> → 23-02-2026; <code>MMMM DD, YYYY</code> → June 03, 2026.</small></label><label>Daily archive<textarea id="archive-default-daily">${escape(normaliseArchiveTemplate(state.archiveTemplate))}</textarea><small>Use {{date}}, {{notionTasks}}, {{calendarTasks}}, {{youtubeTime}}, {{spotifyTime}}, and {{places}}.</small></label><label>Weekly location archive title<input id="archive-title-weekly" value="${escape(state.archiveTitles.weekly)}"><small>Use {{period}} for the selected week.</small></label><label>Weekly location archive<textarea id="archive-default-weekly">${escape(state.locationArchiveTemplates.weekly)}</textarea><small>Use {{period}}, {{topPlaces}}, and {{dailyPlaces}}.</small></label><label>Monthly location archive title<input id="archive-title-monthly" value="${escape(state.archiveTitles.monthly)}"><small>Use {{period}} for the selected month.</small></label><label>Monthly location archive<textarea id="archive-default-monthly">${escape(state.locationArchiveTemplates.monthly)}</textarea><small>Summary only: top places and their total times.</small></label><label>Yearly location archive title<input id="archive-title-yearly" value="${escape(state.archiveTitles.yearly)}"><small>Use {{period}} for the selected year.</small></label><label>Yearly location archive<textarea id="archive-default-yearly">${escape(state.locationArchiveTemplates.yearly)}</textarea><small>Summary only: Lifey includes the top 20 places and their total times.</small></label><button class="button archive-save" data-action="save-archive-settings">Save archive defaults</button></section>`;
  const profileSettings = `<div class="preferences-head"><p class="eyebrow">PROFILE</p><h2>Backup and transfer</h2><p>Export a safe Lifey profile for another Mac or browser. Private tokens, OAuth sessions, raw activity, and raw location samples are excluded.</p></div><section class="profile-backup"><button class="integration-row" data-action="export-profile"><span class="integration-logo">↓</span><span><strong>Export profile</strong><small>Download appearance, layout, archive, integration IDs, and place settings.</small></span><i>›</i></button><button class="integration-row" data-action="import-profile"><span class="integration-logo">↑</span><span><strong>Import profile</strong><small>Apply a Lifey profile JSON on this Mac.</small></span><i>›</i></button><div class="profile-exclusions"><p class="eyebrow">NOT INCLUDED</p><span>Notion token</span><span>Google Places key</span><span>Traccar token</span><span>Lifey Location token</span><span>OAuth access tokens</span><span>Raw activity/location history</span></div></section>`;
  const content = tab === 'integrations' ? `<div class="preferences-head"><p class="eyebrow">CONNECTIONS</p><h2>Integrations</h2><p>Configure each service independently. Sensitive tokens remain on your Mac.</p></div><div class="integration-list">${integration('◈', 'Obsidian', state.localVaultPath ? 'Daily notes connected' : 'Choose your daily-notes folder', 'setup-local-vault')}${integration('N', 'Notion', state.notion?.configured ? 'Connected' : 'Create tasks from Obsidian', 'setup-notion')}${integration('31', 'Google Calendar', state.integrations.google?.clientId ? 'Configured' : 'Today’s schedule and task events', 'setup-google')}${integration('⌖', 'Lifey Location', state.mobileLocation.configured ? `${state.mobileLocation.samples || 0} point(s) stored` : 'Pair the iPhone companion app', 'setup-mobile-location')}${integration('⌖', 'Google Places', state.googlePlaces.configured ? 'Configured' : 'Fallback labels for untagged locations', 'setup-google-places')}${integration('◒', 'Spotify', state.integrations.spotify?.clientId ? 'Configured' : 'Recent listening and playback', 'setup-spotify')}${integration('✉', 'Gmail', state.integrations.gmail?.query ? 'Configured' : 'Reading suggestions', 'setup-gmail')}${integration('⌖', 'Traccar', state.traccar.connected && state.traccar.source === 'Traccar' ? 'Connected' : 'Optional fallback location source', 'setup-traccar')}</div>` : tab === 'appearance' ? `<div class="preferences-head"><p class="eyebrow">LOOK & FEEL</p><h2>Appearance</h2><p>Changes are saved locally and applied immediately.</p></div><div class="appearance-swatches">${colors.map(([key, label]) => `<label class="color-preference"><input type="color" data-appearance="${key}" value="${escape(state.appearance[key])}"><span style="background:${escape(state.appearance[key])}"></span><b>${label}</b></label>`).join('')}</div>${cornerRadiusSettings}${backgroundImageSettings}${heroMetricOrder}${cardOrder}${visibilitySettings}` : tab === 'habits' ? habitsSettings : tab === 'archives' ? archiveSettings : tab === 'location' ? locationSettings : tab === 'profile' ? profileSettings : '';
  el.innerHTML = `<button class="close" data-action="close" aria-label="Close settings">×</button><div class="preferences"><div class="preferences-mobile-nav"><button class="preferences-back" data-action="close" aria-label="Back to Lifey">‹</button><strong>${escape(activeTabLabel)}</strong><span>L.</span></div><aside><div class="preferences-brand"><span class="brand-mark">L.</span><b>Lifey</b></div>${menu}</aside><main>${content}</main></div>`;
  if (!el.open) el.showModal();
  if (Number.isFinite(options.scrollTop)) requestAnimationFrame(() => { const main = preferencesMain(); if (main) main.scrollTop = options.scrollTop; });
}
async function findTodayFile(directory, path = '') {
  for await (const [name, handle] of directory.entries()) {
    if (handle.kind === 'file' && dailyNoteNameSet().has(name)) return { handle, parent: directory, path: path + name };
    if (handle.kind === 'directory' && !name.startsWith('.')) { const found = await findTodayFile(handle, path + name + '/'); if (found) return found; }
  }
}
async function getDirectoryCaseInsensitive(root, segment) { for await (const [name, handle] of root.entries()) if (handle.kind === 'directory' && name.toLowerCase() === segment.toLowerCase()) return { handle, name }; }
async function findJournalDailyFile(root) {
  for (const segments of [['journals'], ['journals', 'Daily'], ['Lab', 'journals'], ['Lab', 'journals', 'Daily']]) {
    let current = root, displayPath = '';
    for (const segment of segments) { const found = await getDirectoryCaseInsensitive(current, segment); if (!found) { current = null; break; } current = found.handle; displayPath += `${found.name}/`; }
    if (current) { const match = await findTodayFile(current, displayPath); if (match) return match; }
  }
  return findTodayFile(root);
}
async function connectVault() {
  if (state.localVaultPath) { try { await loadLocalVault(); return; } catch { state.localVaultPath = ''; persist(); } }
  if (!window.showDirectoryPicker) { selectDailyNote(); return; }
  vaultHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
  const current = await findJournalDailyFile(vaultHandle);
  if (!current) { toast(`No ${todayJournalDate()}.md was found. Select the note directly instead.`); selectDailyNote(); return; }
  const markdown = await (await current.handle.getFile()).text();
  const tasks = parseTasks(markdown, current.path, state.taskMappings);
  if (tasks.length) { state.tasks = tasks; persist(); render(); }
  toast(`Read ${tasks.length} task(s) from ${current.path}.`);
}
function selectDailyNote() {
  const input = document.createElement('input'); input.type = 'file'; input.accept = '.md,text/markdown';
  input.addEventListener('change', async () => { const file = input.files?.[0]; if (!file) return; const markdown = await file.text(); selectedDailyNote = { name: file.name, markdown }; const tasks = parseTasks(markdown, file.name, state.taskMappings); if (tasks.length) { state.tasks = tasks; persist(); render(); } toast(`Read ${tasks.length} task(s) from ${file.name}.`); }); input.click();
}
function downloadText(filename, text) { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([text], { type: 'text/markdown' })); link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 1000); }
function normaliseArchiveTemplate(template) { return String(template || DEFAULT_ARCHIVE_TEMPLATE).replaceAll(LEGACY_ARCHIVE_START, ARCHIVE_MARKER).replaceAll(LEGACY_ARCHIVE_END, ARCHIVE_MARKER).replace(/^\s*- Instagram:.*(?:\r?\n)?/gmi, ''); }
function momentOrdinal(value) { const mod = value % 100; return `${value}${mod >= 10 && mod <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[value % 10] || 'th')}`; }
function momentFormat(date, pattern = 'YYYY-MM-DDTHH:mm:ssZ') { const literals = []; const held = String(pattern).replace(/\[([^\]]*)\]/g, (_, text) => `\u0000${literals.push(text) - 1}\u0000`); const day = date.getDate(), month = date.getMonth() + 1, year = date.getFullYear(), weekday = date.getDay(), dayYear = Math.floor((Date.UTC(year, month - 1, day) - Date.UTC(year, 0, 0)) / 86400000); const iso = new Date(Date.UTC(year, month - 1, day)); iso.setUTCDate(iso.getUTCDate() + 4 - (iso.getUTCDay() || 7)); const isoYear = iso.getUTCFullYear(), isoWeek = Math.ceil((((iso - Date.UTC(isoYear, 0, 1)) / 86400000) + 1) / 7); const localWeek = Math.floor((dayYear + new Date(year, 0, 1).getDay() - 1) / 7) + 1; const offset = -date.getTimezoneOffset(), sign = offset >= 0 ? '+' : '-', absOffset = Math.abs(offset), hour = date.getHours(), milliseconds = String(date.getMilliseconds()).padStart(3, '0'); const monthsLong = date.toLocaleDateString('en-US', { month: 'long' }), monthsShort = date.toLocaleDateString('en-US', { month: 'short' }), weekdayLong = date.toLocaleDateString('en-US', { weekday: 'long' }), weekdayShort = date.toLocaleDateString('en-US', { weekday: 'short' }); const values = { YYYYYY: `${year >= 0 ? '+' : '-'}${String(Math.abs(year)).padStart(6, '0')}`, YYYY: String(year).padStart(4, '0'), YY: String(year % 100).padStart(2, '0'), Y: String(year), MMMM: monthsLong, MMM: monthsShort, MM: String(month).padStart(2, '0'), Mo: momentOrdinal(month), M: String(month), DDDD: String(dayYear).padStart(3, '0'), DDDo: momentOrdinal(dayYear), DDD: String(dayYear), DD: String(day).padStart(2, '0'), Do: momentOrdinal(day), D: String(day), dddd: weekdayLong, ddd: weekdayShort, dd: weekdayShort.slice(0, 2), do: momentOrdinal(weekday), d: String(weekday), e: String(weekday), E: String(weekday || 7), Q: String(Math.ceil(month / 3)), Qo: momentOrdinal(Math.ceil(month / 3)), ww: String(localWeek).padStart(2, '0'), wo: momentOrdinal(localWeek), w: String(localWeek), WW: String(isoWeek).padStart(2, '0'), Wo: momentOrdinal(isoWeek), W: String(isoWeek), gggg: String(year), gg: String(year % 100).padStart(2, '0'), GGGG: String(isoYear), GG: String(isoYear % 100).padStart(2, '0'), HH: String(hour).padStart(2, '0'), H: String(hour), hh: String(hour % 12 || 12).padStart(2, '0'), h: String(hour % 12 || 12), kk: String(hour || 24).padStart(2, '0'), k: String(hour || 24), mm: String(date.getMinutes()).padStart(2, '0'), m: String(date.getMinutes()), ss: String(date.getSeconds()).padStart(2, '0'), s: String(date.getSeconds()), A: hour < 12 ? 'AM' : 'PM', a: hour < 12 ? 'am' : 'pm', Z: `${sign}${String(Math.floor(absOffset / 60)).padStart(2, '0')}:${String(absOffset % 60).padStart(2, '0')}`, ZZ: `${sign}${String(Math.floor(absOffset / 60)).padStart(2, '0')}${String(absOffset % 60).padStart(2, '0')}`, z: Intl.DateTimeFormat('en-US', { timeZoneName: 'short' }).formatToParts(date).find(part => part.type === 'timeZoneName')?.value || '', zz: Intl.DateTimeFormat('en-US', { timeZoneName: 'short' }).formatToParts(date).find(part => part.type === 'timeZoneName')?.value || '', X: String(Math.floor(date.getTime() / 1000)), x: String(date.getTime()), N: 'AD', NN: 'AD', NNN: 'AD', NNNN: 'Anno Domini', NNNNN: 'AD', y: String(year) }; const tokens = /YYYYYY|YYYY|YY|Y|MMMM|MMM|MM|Mo|M|DDDD|DDDo|DDD|DD|Do|D|dddd|ddd|dd|do|d|Qo|Q|ww|wo|w|WW|Wo|W|gggg|gg|GGGG|GG|HH|H|hh|h|kk|k|mm|m|ss|s|A|a|zz|z|ZZ|Z|X|x|NNNNN|NNNN|NNN|NN|N|y|e|E|S{1,9}/g; return held.replace(tokens, token => token.startsWith('S') ? `${milliseconds}${'0'.repeat(token.length)}`.slice(0, token.length) : values[token]).replace(/\u0000(\d+)\u0000/g, (_, index) => literals[Number(index)]); }
function resolvedArchiveTitle(kind) { const pattern = String(state.archiveTitles?.[kind] || DEFAULT_ARCHIVE_TITLES[kind]).replaceAll('{{date}}', 'MMMM DD, YYYY'); return momentFormat(new Date(), pattern).replaceAll('{{period}}', kind); }
function applyArchiveTitle(template, kind) { return String(template).replace(/^##\s+.*$/m, `## ${resolvedArchiveTitle(kind)}`); }
function hasArchiveMarkers(template) { const lines = String(template || '').trim().split(/\r?\n/); return lines.length >= 2 && lines[0].trim() === ARCHIVE_MARKER && lines.at(-1).trim() === ARCHIVE_MARKER; }
function replaceArchiveBlock(previous, generated) { const legacy = new RegExp(`${LEGACY_ARCHIVE_START.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]*?${LEGACY_ARCHIVE_END.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`); const modern = /^---\s*\r?\n(?=## Lifey\b)[\s\S]*?^---\s*$/m; return legacy.test(previous) ? previous.replace(legacy, generated) : modern.test(previous) ? previous.replace(modern, generated) : `${previous.trimEnd()}\n\n${generated}\n`; }
function downloadArchiveFallback() { const previous = selectedDailyNote.markdown, generated = archiveMarkdown(); const updated = replaceArchiveBlock(previous, generated); const stem = selectedDailyNote.name.replace(/\.md$/i, ''); downloadText(`${stem}.dashboard-backup.md`, previous); downloadText(`${stem}.dashboard-updated.md`, updated); toast('Downloaded a backup and updated note. Replace the daily note in Obsidian when ready.'); }
async function writeArchive() {
  if (state.localVaultPath) return writeLocalArchive();
  if (!vaultHandle && selectedDailyNote) return downloadArchiveFallback();
  if (!vaultHandle) { await connectVault(); if (!vaultHandle) return; }
  const current = await findJournalDailyFile(vaultHandle);
  if (!current) { toast(`No ${todayJournalDate()}.md was found. Select the note directly instead.`); selectDailyNote(); return; }
  const file = await current.handle.getFile(); const previous = await file.text(); const generated = archiveMarkdown();
  const updated = replaceArchiveBlock(previous, generated);
  const backupHandle = await current.parent.getFileHandle(`${todayIso()}.dashboard-backup-${Date.now()}.md`, { create: true });
  const backupWrite = await backupHandle.createWritable(); await backupWrite.write(previous); await backupWrite.close();
  const writable = await current.handle.createWritable(); await writable.write(updated); await writable.close();
  toast('Daily archive written; the existing note was preserved outside Lifey markers.');
}
async function toggleTask(task) {
  const completed = !task.done;
  if (state.localVaultPath) await updateLocalTask(task, completed);
  else if (vaultHandle) {
    const current = await findJournalDailyFile(vaultHandle);
    if (!current) throw new Error('Daily note not found. Refresh the vault first.');
    const file = await current.handle.getFile(); const lines = (await file.text()).split('\n'); const index = task.line - 1;
    const match = lines[index]?.match(/^(\s*-\s+\[)[ xX](\]\s+)(.*)$/);
    if (!match || match[3].trim() !== task.text.trim()) throw new Error('Task changed in Obsidian. Refresh the daily note first.');
    lines[index] = `${match[1]}${completed ? 'x' : ' '}${match[2]}${match[3]}`; const writable = await current.handle.createWritable(); await writable.write(lines.join('\n')); await writable.close();
  } else throw new Error('Connect the persistent vault helper before completing tasks.');
  task.done = completed; persist(); render(); toast(completed ? 'Task completed in Obsidian.' : 'Task reopened in Obsidian.');
}
function placeWikiLink(name) { const safe = String(name || 'Unknown place').replaceAll('"', "'").replaceAll(']]', '').trim(); return `[[Place - "${safe}"]]`; }
function archiveMarkdown() { const places = state.traccar.connected ? state.traccar.places : state.places; const values = { date: todayJournalDatePadded(), notionTasks: state.tasks.filter(t => t.notion).length, calendarTasks: state.tasks.filter(t => t.calendar).length, youtubeTime: durationLabel(state.youtube.totalActiveSeconds || 0), spotifyTime: durationLabel((spotifyStats(state.spotify, 'today').minutes || 0) * 60), places: places.length ? places.map(p => `- ${placeWikiLink(p.name)} · ${p.time || placeTiming(p).range} (${p.source})`).join('\n') : '- No places recorded' }; return applyArchiveTitle(normaliseArchiveTemplate(state.archiveTemplate), 'daily').replace(/\{\{(\w+)\}\}/g, (match, key) => values[key] ?? match); }
function integrationForm(name) {
  const value = state.integrations[name] || {};
  const forms = {
    notion: `<p class="modal-copy">Create a Notion internal integration and share your task database with it. The token is saved only by the local helper, never browser storage. You may paste either a Database ID or Data Source ID.</p><label>Integration token<input id="integration-token" type="password" placeholder="ntn_…"></label><label>Database or Data Source ID<input id="integration-database" value="${escape(value.database || '')}" placeholder="Notion ID"></label><label>Title property<input id="integration-property" value="${escape(value.property || 'Name')}" placeholder="Name"></label><button class="connection" data-action="diagnose-notion">Test Notion connection <span>Read-only</span></button><button class="connection" data-action="list-notion-sources">Find accessible databases <span>Read-only</span></button>`,
    google: `<p class="modal-copy">Google Calendar and Gmail now connect through the Mac helper. Create a <strong>Desktop app</strong> OAuth client in Google Cloud, then paste its Client ID and Client Secret here. Lifey stores the refresh token in macOS Keychain.</p><p class="modal-copy">${state.google.hasClientSecret ? 'Client Secret is saved in Keychain. Leave the field blank unless you want to replace it.' : '<strong>Client Secret is not saved yet.</strong> Paste it before connecting.'}</p><label>Google Desktop OAuth client ID<input id="integration-client-id" value="${escape(value.clientId || '')}" placeholder="…apps.googleusercontent.com"></label><label>Google Desktop OAuth client secret<input id="integration-client-secret" type="password" placeholder="GOCSPX-…"></label><label>Calendar ID<input id="integration-calendar" value="${escape(value.calendar || 'primary')}" placeholder="primary"></label>`,
    spotify: `<p class="modal-copy">Create a Spotify app and add <strong>http://127.0.0.1:4173</strong> as its redirect URI. Premium is not required. Lifey reads current playback, player state, and recent plays, then builds local listening history for Today, This week, and This month. If the current song does not appear, use Reconnect once to grant the playback-state scope.</p><label>Spotify client ID<input id="integration-client-id" value="${escape(value.clientId || '')}" placeholder="Spotify client ID"></label>`,
    gmail: `<p class="modal-copy">Gmail uses the Google OAuth client configured under Calendar. Save a search query for newsletters, Medium links, and reading recommendations.</p><label>Gmail search query<input id="integration-query" value="${escape(value.query || 'from:(medium.com OR substack.com) newer_than:14d')}" placeholder="Gmail search query"></label>`
  };
  modal(`${name === 'google' ? 'Google Calendar' : name[0].toUpperCase()+name.slice(1)} setup`, forms[name], `save-${name}`, { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' });
}
async function saveIntegration(name) {
  const val = id => document.querySelector(id)?.value.trim() || '';
  const googleSecret = name === 'google' ? val('#integration-client-secret') : '';
  const saved = name === 'notion' ? { token: val('#integration-token'), database: val('#integration-database'), property: val('#integration-property') } : name === 'google' ? { clientId: val('#integration-client-id'), calendar: val('#integration-calendar') } : name === 'spotify' ? { clientId: val('#integration-client-id') } : { query: val('#integration-query') };
  state.integrations[name] = saved;
  persist();
  if (['google', 'gmail'].includes(name) && state.integrations.google?.clientId) await saveGoogleHelperConfig(googleSecret);
  const shouldRestoreSettings = Boolean(document.querySelector('#modal .preferences'));
  const tab = currentPreferencesTab();
  const scrollTop = preferencesScrollTop();
  closeActiveDialog();
  if (shouldRestoreSettings) rerenderPreferences(tab, scrollTop);
  toast(saved.token || saved.clientId || saved.query ? `${name === 'google' ? 'Google' : name[0].toUpperCase()+name.slice(1)} settings saved locally.` : 'Nothing saved yet.');
}
const captureController = {
  quickCaptureModal, loadPlaceLabels, renderCapturePlaceDropdown, saveQuickCapture, closeCaptureSubmenus,
  setCaptureMenuOpen, renderCaptureCalendar, renderCaptureOptionDropdown, selectCaptureOption,
  refocusCaptureInput, ensureCapturePlaceContext, selectCapturePlace, refreshQuickCapturePreview,
  toast, moveCapturePlaceSelection, selectedCapturePlaceName
};
const locationController = {
  state, persist, render, toast, modal, escape, showPlacePoints, savePlaceLabel, loadLocationData,
  setPlaceMergeMode: value => { placeMergeMode = value; },
  setPlaceMergeSelection: value => { placeMergeSelection = value; },
  placeMergeSelection: () => placeMergeSelection,
  createPlaceMerge, undoPlaceMerge, openPreferences, todayIso, archiveLocationPeriod
};
const projectController = {
  state, persist, render, toast, loadProjects, quickCaptureModal, openProjectNote, createProjectNote, updateProjectTask
};
const preferenceController = {
  state, persist, render, toast, openPreferences, preferencesScrollTop, rerenderPreferences, applyAppearance,
  saveDashboardBackgroundImage, exportProfile, importProfileFile, importProfile, DEFAULT_HABIT_SETTINGS,
  timeToMinutes, saveLocationRadius, loadLocationData
};
document.addEventListener('click', e => { const b = actionTarget(e); if (!b) return; const { action, id } = actionPayload(b); const task = state.tasks.find(t => t.id === id);
  if (handleCaptureAction(action, b, captureController)) return;
  if (handleLocationAction(action, b, locationController)) return;
  if (handleProjectAction(action, b, projectController)) return;
  if (handlePreferenceAction(action, b, preferenceController)) return;
  if(action === 'toggle-task') toggleTask(task).catch(error => toast(error.message));
  if(action === 'delete-task') { const hadExternalRecord = Boolean(task?.calendarEventId || task?.notionPageId); deleteLocalTask(task).then(async () => { delete state.taskMappings[taskMappingKey(task)]; persist(); await loadLocalVault(true); toast(hadExternalRecord ? 'Task deleted from Obsidian; its external record was kept.' : 'Task deleted from Obsidian.'); }).catch(error => toast(error.message)); }
  if(action === 'notion') sendTaskToNotion(task).catch(error => toast(error.message));
  if(action === 'edit-task') quickCaptureModal(task);
  if(action === 'calendar') { if (task?.calendarEventId) return toast('This task is already mapped to a Calendar event.'); scheduleTaskFromMetadata(task).catch(error => toast(error.message)); }
  if(action === 'remove-calendar') removeGoogleCalendarEvent(task).catch(error => toast(error.message));
  if(action === 'delete-calendar-event') deleteGoogleCalendarEventById(b.dataset.eventId).then(() => toast('Calendar event deleted.')).catch(error => toast(error.message));
  if(action === 'confirm-calendar') { const t = state.tasks.find(t => t.id === window.pendingTask); const time = document.querySelector('#modal input[type="time"]')?.value || '14:00'; const date = window.pendingCalendarDate || todayIso(); document.querySelector('#modal').close(); createGoogleCalendarEvent(t, time, date).catch(error => toast(error.message)); }
  if(action === 'create-event') { const t = state.tasks.find(t => !t.calendar && !t.done); if (t) scheduleTaskFromMetadata(t).catch(error => toast(error.message)); }
  if(action === 'open-google-calendar') window.open(`https://calendar.google.com/calendar/u/0/r/day/${todayIso().replaceAll('-', '/')}`, '_blank', 'noopener');
  if(action === 'open-suggestion') { if (b.dataset.url) window.open(b.dataset.url, '_blank', 'noopener'); else toast('This suggestion does not have a direct source link yet.'); }
  if(action === 'archive') { modal('Archive preview', `<pre>${escape(archiveMarkdown())}</pre><p class="modal-copy">Chromium writes only between Lifey markers and creates a backup. Firefox/Zen downloads an updated note plus a backup for you to replace in Obsidian.</p>`, 'write-archive'); }
  if(action === 'write-archive') { document.querySelector('#modal').close(); writeArchive().catch(() => toast('Could not write the archive. Check vault permission.')); }
  if(action === 'import') modal('Import monitored accounts', '<p class="modal-copy">Paste handles, one per line. CSV and JSON imports belong in the local integration adapter.</p><textarea id="accounts-input" placeholder="@goodrestaurant\n@anotheraccount"></textarea>', 'save-accounts');
  if(action === 'save-accounts') { const list = document.querySelector('#accounts-input').value.match(/@?[a-zA-Z0-9._]+/g) || []; state.accounts.push(...list.map(h=>({handle:h.startsWith('@')?h:'@'+h,type:'Imported',freshness:'Unknown'}))); persist(); document.querySelector('#modal').close(); render(); toast(`${list.length} account(s) added locally.`); }
  if(action === 'save-archive-settings') { const scrollTop = preferencesScrollTop(); const daily = normaliseArchiveTemplate(document.querySelector('#archive-default-daily')?.value.trim()); const templates = { weekly: document.querySelector('#archive-default-weekly')?.value.trim(), monthly: document.querySelector('#archive-default-monthly')?.value.trim(), yearly: document.querySelector('#archive-default-yearly')?.value.trim() }; const titles = { daily: document.querySelector('#archive-title-daily')?.value.trim(), weekly: document.querySelector('#archive-title-weekly')?.value.trim(), monthly: document.querySelector('#archive-title-monthly')?.value.trim(), yearly: document.querySelector('#archive-title-yearly')?.value.trim() }; if (!hasArchiveMarkers(daily) || Object.values(templates).some(template => !hasArchiveMarkers(template))) return toast('Keep --- as the first and last line of every archive default.'); if (Object.values(titles).some(title => !title)) return toast('Give every archive a title.'); Promise.all([saveArchiveTemplate(daily), saveLocationArchiveTemplates(templates), saveArchiveTitles(titles)]).then(([dailyResult]) => { openPreferences('archives', { scrollTop }); toast(dailyResult.localOnly ? 'Archive defaults saved in this browser. Restart Lifey once to sync them locally.' : 'Archive defaults saved.'); }).catch(error => toast(error.message)); }
  if(action === 'edit-archive-template') modal('Archive default', `<p class="modal-copy">Edit the Markdown Lifey writes every day. Keep one <code>---</code> on the first line and another on the last line. You can use <code>{{date}}</code>, <code>{{notionTasks}}</code>, <code>{{calendarTasks}}</code>, <code>{{youtubeTime}}</code>, <code>{{spotifyTime}}</code>, and <code>{{places}}</code>.</p><textarea id="archive-template">${escape(normaliseArchiveTemplate(state.archiveTemplate))}</textarea><button class="text-button" data-action="reset-archive-template">Reset to Lifey’s default</button><button class="text-button" data-action="edit-location-archive-templates">Edit weekly, monthly, and yearly defaults</button>`, 'save-archive-template');
  if(action === 'edit-location-archive-templates') modal('Location archive defaults', `<p class="modal-copy">These editable templates create reports directly inside Journals. Keep <code>---</code> as the first and final line. Use <code>{{period}}</code>, <code>{{topPlaces}}</code>, and, for weekly archives, <code>{{dailyPlaces}}</code>.</p><label>Weekly<textarea id="location-template-weekly">${escape(state.locationArchiveTemplates.weekly)}</textarea></label><label>Monthly<textarea id="location-template-monthly">${escape(state.locationArchiveTemplates.monthly)}</textarea></label><label>Yearly<textarea id="location-template-yearly">${escape(state.locationArchiveTemplates.yearly)}</textarea></label>`, 'save-location-archive-templates');
  if(action === 'save-location-archive-templates') { const templates = { weekly: document.querySelector('#location-template-weekly')?.value.trim(), monthly: document.querySelector('#location-template-monthly')?.value.trim(), yearly: document.querySelector('#location-template-yearly')?.value.trim() }; if (Object.values(templates).some(template => !hasArchiveMarkers(template))) return toast('Keep --- as the first and last line of every location archive default.'); document.querySelector('#modal').close(); saveLocationArchiveTemplates(templates).then(() => toast('Location archive defaults saved.')).catch(error => toast(error.message)); }
  if(action === 'reset-archive-template') { document.querySelector('#modal').close(); saveArchiveTemplate(DEFAULT_ARCHIVE_TEMPLATE).then(result => { toast(result.localOnly ? 'Archive default reset in this browser. Restart Lifey to sync it locally.' : 'Archive default reset.'); }); }
  if(action === 'save-archive-template') { const template = normaliseArchiveTemplate(document.querySelector('#archive-template')?.value.trim()); if (!hasArchiveMarkers(template)) return toast('Keep --- as the first and last line of the archive default.'); document.querySelector('#modal').close(); saveArchiveTemplate(template).then(result => toast(result.localOnly ? 'Saved here. Restart Lifey once to sync the default locally.' : 'Archive default saved for future days.')); }
  if(action === 'connect-vault') { document.querySelector('#modal').close(); connectVault().catch(() => toast('Vault access was cancelled or unavailable.')); }
  if(action === 'open-vault') connectVault().catch(() => toast('Vault access was cancelled or unavailable.'));
  if(action === 'refresh-vault') connectVault().catch(() => toast('Vault access was cancelled or unavailable.'));
  if(action === 'setup-notion') integrationForm('notion');
  if(action === 'setup-google') integrationForm('google');
  if(action === 'setup-spotify') integrationForm('spotify');
  if(action === 'setup-gmail') integrationForm('gmail');
  if(action === 'setup-local-vault') modal('Persistent Zen vault', `<p class="modal-copy">Enter your Journals folder. Lifey supports daily notes directly in this folder or in its <strong>Daily</strong> subfolder.</p><label>Journals folder<input id="local-vault-path" value="${escape(state.localVaultPath)}" placeholder="/Users/you/Library/Mobile Documents/com~apple~CloudDocs/Lab/journals"></label>`, 'save-local-vault', { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' });
  if(action === 'setup-mobile-location') setupMobileLocation().then(token => modal('Lifey Location', `<p class="modal-copy">Enter this collector token in the iPhone companion app with your Mac’s Tailscale URL. Phone samples are stored locally on this Mac and used before Traccar.</p><label>Collector token<input readonly value="${escape(token)}" onclick="this.select()"></label>`, 'close', { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' })).catch(error => toast(error.message));
  if(action === 'setup-traccar') modal('Traccar location', '<p class="modal-copy">Enter your self-hosted or hosted Traccar server details. The token stays in the local helper.</p><label>Server URL<input id="traccar-server" placeholder="https://traccar.example.com"></label><label>Account token<input id="traccar-token" type="password"></label><label>iPhone device ID<input id="traccar-device" placeholder="e.g. 12"></label>', 'save-traccar', { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' });
  if(action === 'setup-google-places') modal('Google place names', '<p class="modal-copy">Nearby Google Places lookups use one representative coordinate per new place and are cached locally. The API key stays in the local helper.</p><label>Google Maps API key<input id="google-places-key" type="password" placeholder="AIza…"></label>', 'save-google-places', { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' });
  if(action === 'enable-osm-places') { closeActiveDialog(); enableOsmPlaces().then(() => toast('OpenStreetMap place naming enabled. Refresh locations.')).catch(error => toast(error.message)); }
  if(action === 'save-notion') { const token = document.querySelector('#integration-token')?.value.trim(); const parentId = document.querySelector('#integration-database')?.value.trim(); const property = document.querySelector('#integration-property')?.value.trim() || 'Name'; if (!token || !parentId) return toast('Enter the Notion token and database/data source ID.'); closeActiveDialog(); configureNotion(token, parentId, property).then(() => toast('Notion configured locally.')).catch(error => toast(error.message)); }
  if(action === 'diagnose-notion') { const token = document.querySelector('#integration-token')?.value.trim(); const parentId = document.querySelector('#integration-database')?.value.trim(); const property = document.querySelector('#integration-property')?.value.trim() || 'Name'; diagnoseNotion(token, parentId).then(result => { const status = result.resourceAccessible ? 'Ready' : 'Needs access'; if (result.resourceAccessible) window.notionDiagnostic = { token, parentId, property }; modal(`Notion diagnostic · ${status}`, `<p class="modal-copy">${escape(result.message)}</p>`, result.resourceAccessible ? 'save-tested-notion' : 'close', { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' }); }).catch(error => toast(error.message)); }
  if(action === 'save-tested-notion') { const setup = window.notionDiagnostic; if (!setup) return toast('Reopen Notion setup and test the connection again.'); closeActiveDialog(); configureNotion(setup.token, setup.parentId, setup.property).then(() => toast('Notion configured locally.')).catch(error => toast(error.message)); }
  if(action === 'list-notion-sources') { const token = document.querySelector('#integration-token')?.value.trim(); listNotionSources(token).then(result => { const sources = result.dataSources || []; const content = sources.length ? `<p class="modal-copy">Copy the ID of your task database’s data source into the setup field.</p><pre>${escape(sources.map(source => `${source.title}\nData source ID: ${source.id}\nDatabase ID: ${source.databaseId}`).join('\n\n'))}</pre>` : '<p class="modal-copy">No accessible data sources were found. With a PAT, confirm this is the same workspace and that the database is a regular Notion database—not merely a linked view.</p>'; modal('Accessible Notion databases', content, 'close', { layer: document.querySelector('#modal .preferences') ? 'sub' : 'main' }); }).catch(error => toast(error.message)); }
  if(action === 'save-google') saveIntegration('google').catch(error => toast(error.message));
  if(action === 'save-spotify') saveIntegration('spotify').catch(error => toast(error.message));
  if(action === 'save-gmail') saveIntegration('gmail').catch(error => toast(error.message));
  if(action === 'save-local-vault') { const path = document.querySelector('#local-vault-path')?.value.trim(); if (!path) return toast('Enter the Daily notes folder path first.'); closeActiveDialog(); configureLocalVault(path).catch(error => toast(error.message)); }
  if(action === 'save-traccar') { const server = document.querySelector('#traccar-server')?.value.trim(), token = document.querySelector('#traccar-token')?.value.trim(), deviceId = document.querySelector('#traccar-device')?.value.trim(); closeActiveDialog(); configureTraccar(server, token, deviceId).catch(error => toast(error.message)); }
  if(action === 'save-google-places') { const key = document.querySelector('#google-places-key')?.value.trim(); closeActiveDialog(); configureGooglePlaces(key).then(() => { toast('Google place naming configured. Refresh locations.'); }).catch(error => toast(error.message)); }
  if(action === 'connect-spotify') connectSpotify().catch(error => toast(error.message));
  if(action === 'reconnect-spotify') reconnectSpotify().catch(error => toast(error.message));
  if(action === 'diagnose-spotify') diagnoseSpotify().catch(error => toast(error.message));
  if(action === 'set-spotify-view') { state.spotify.view = b.dataset.view === 'songs' ? 'songs' : 'artists'; persist(); render(); }
  if(action === 'set-spotify-range') { state.spotify.range = ['today', 'week', 'month'].includes(b.dataset.range) ? b.dataset.range : 'today'; state.spotify.minutes = spotifyStats(state.spotify, state.spotify.range).minutes; persist(); render(); }
  if(action === 'connect-google') connectGoogleCalendar().catch(error => toast(error.message));
  if(action === 'connect-gmail') connectGmail().catch(error => toast(error.message));
  if(action === 'toggle-habit') { const habit = { line: Number(b.dataset.line), habit: b.dataset.habit, state: b.dataset.state }; const nextState = habit.state === 'completed' ? 'pending' : 'completed'; if (nextState === 'completed') { window.justCompletedHabit = habit.habit; setTimeout(() => { if (window.justCompletedHabit === habit.habit) { window.justCompletedHabit = ''; render(); } }, 1300); } setHabitState(habit, nextState).catch(error => toast(error.message)); }
  if(action === 'skip-habit') { const habit = { line: Number(b.dataset.line), habit: b.dataset.habit, state: b.dataset.state }; setHabitState(habit, habit.state === 'skipped' ? 'pending' : 'skipped').catch(error => toast(error.message)); }
  if(action === 'set-habits-view') { state.habits.view = b.dataset.view || 'today'; persist(); render(); if (['calendar', 'graph', 'archived'].includes(state.habits.view)) loadHabitHistory(state.habits.range || 'month', true).catch(error => toast(error.message)); }
  if(action === 'set-habits-range') { state.habits.range = b.dataset.range === 'all' ? 'all' : 'month'; persist(); render(); loadHabitHistory(state.habits.range, true).catch(error => toast(error.message)); }
  if(action === 'select-habit') { state.habits.selectedHabit = b.dataset.habit; persist(); render(); }
  if(action === 'toggle-archived-habit') { state.habits.expandedArchive = state.habits.expandedArchive === b.dataset.habit ? '' : b.dataset.habit; persist(); render(); }
  if(action === 'refresh-habits') Promise.all([loadHabitsToday(true), loadHabitHistory(state.habits.range || 'month', true)]).then(() => toast('Habits refreshed.')).catch(error => toast(error.message));
  if(action === 'sync-habits') syncHabitsToday().catch(error => toast(error.message));
  if(action === 'set-youtube-view') { state.youtubeView = b.dataset.view === 'week' ? 'week' : 'today'; if (state.youtubeView === 'week') state.youtubeWeekDay = todayIso(); persist(); render(); loadYoutube(false, state.youtubeView).catch(error => toast(error.message)); }
  if(action === 'set-youtube-week-day') { state.youtubeWeekDay = b.dataset.date; persist(); render(); }
  if(action === 'set-youtube-sort') { state.contentDisplay.youtubeSort = b.dataset.sort === 'time' ? 'time' : 'duration'; persist(); render(); }
  if(action === 'youtube-setup') { if (state.youtubeView === 'week' || state.youtube.videos.length) loadYoutube(false, state.youtubeView).catch(error => toast(error.message)); else checkYoutubeTracker().catch(error => toast(error.message)); }
  if(['capture','capture-post','refresh'].includes(action)) toast('This capture workflow is the next local connection to build.');
  if(action === 'close') { b.closest('dialog')?.close(); updateMobileCaptureOffset(); }
});
document.addEventListener('submit', e => { if (e.target.id !== 'quick-capture-form') return; e.preventDefault(); saveQuickCapture().catch(error => toast(error.message)); });
document.addEventListener('click', e => { if (e.target.closest('.capture-help kbd')) document.querySelector('#modal')?.close(); });
window.visualViewport?.addEventListener('resize', updateMobileCaptureOffset);
window.visualViewport?.addEventListener('scroll', updateMobileCaptureOffset);
window.addEventListener('resize', updateMobileCaptureOffset);
let draggedHeroMetric = null;
function clearHeroMetricDragState() { document.querySelectorAll('.hero-metric-item').forEach(item => item.classList.remove('dragging', 'drag-over')); }
document.addEventListener('dragstart', e => { const item = e.target.closest('[data-hero-metric]'); if (!item) return; draggedHeroMetric = item.dataset.heroMetric; item.classList.add('dragging'); e.dataTransfer?.setData('text/plain', draggedHeroMetric); if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'; });
document.addEventListener('dragover', e => { const item = e.target.closest('[data-hero-metric]'); if (!draggedHeroMetric || !item || item.dataset.heroMetric === draggedHeroMetric) return; e.preventDefault(); clearHeroMetricDragState(); document.querySelector(`[data-hero-metric="${draggedHeroMetric}"]`)?.classList.add('dragging'); item.classList.add('drag-over'); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; });
document.addEventListener('dragleave', e => { e.target.closest('[data-hero-metric]')?.classList.remove('drag-over'); });
document.addEventListener('dragend', () => { draggedHeroMetric = null; clearHeroMetricDragState(); });
document.addEventListener('drop', e => { const target = e.target.closest('[data-hero-metric]'); if (!draggedHeroMetric || !target) return; e.preventDefault(); const scrollTop = preferencesScrollTop(); const sourceIndex = state.heroMetricOrder.indexOf(draggedHeroMetric), targetIndex = state.heroMetricOrder.indexOf(target.dataset.heroMetric); if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return; state.heroMetricOrder.splice(sourceIndex, 1); state.heroMetricOrder.splice(targetIndex, 0, draggedHeroMetric); persist(); draggedHeroMetric = null; rerenderPreferences('appearance', scrollTop); });
let draggedCard = null;
function clearCardDragState() { document.querySelectorAll('.card-order-item').forEach(item => item.classList.remove('dragging', 'drag-over')); }
document.addEventListener('dragstart', e => { const item = e.target.closest('[data-card-order]'); if (!item) return; draggedCard = item.dataset.cardOrder; item.classList.add('dragging'); e.dataTransfer?.setData('text/plain', draggedCard); if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'; });
document.addEventListener('dragover', e => { const item = e.target.closest('[data-card-order]'); if (!draggedCard || !item || item.dataset.cardOrder === draggedCard) return; e.preventDefault(); clearCardDragState(); document.querySelector(`[data-card-order="${draggedCard}"]`)?.classList.add('dragging'); item.classList.add('drag-over'); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; });
document.addEventListener('dragleave', e => { e.target.closest('[data-card-order]')?.classList.remove('drag-over'); });
document.addEventListener('dragend', () => { draggedCard = null; clearCardDragState(); });
document.addEventListener('drop', e => { const target = e.target.closest('[data-card-order]'); if (!draggedCard || !target) return; e.preventDefault(); const scrollTop = preferencesScrollTop(); const sourceIndex = state.cardOrder.indexOf(draggedCard), targetIndex = state.cardOrder.indexOf(target.dataset.cardOrder); if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return; state.cardOrder.splice(sourceIndex, 1); state.cardOrder.splice(targetIndex, 0, draggedCard); persist(); draggedCard = null; rerenderPreferences('appearance', scrollTop); });
document.addEventListener('change', e => {
  if (handlePreferenceChange(e, preferenceController)) return;
  if (['capture-date', 'capture-priority', 'capture-recurring'].includes(e.target.id)) refreshQuickCapturePreview();
});
document.addEventListener('input', e => {
  if (handleCaptureInput(e, captureController)) return;
  if (handlePreferenceInput(e, preferenceController)) return;
});
document.addEventListener('keydown', e => {
  if (handleCaptureKeydown(e, captureController)) return;
  if ((e.metaKey || e.ctrlKey) && e.key === '.') { e.preventDefault(); document.querySelector('[data-action="settings"]').click(); }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); document.querySelector('[data-action="quick-add"]').click(); }
});
window.addEventListener('resize', () => { clearTimeout(window.cardLayoutResizeTimer); window.cardLayoutResizeTimer = setTimeout(arrangeDashboardCards, 120); });
render();
scheduleGoogleExpiry();
finishSpotifyAuth().catch(error => { history.replaceState({}, '', window.location.pathname); toast(error.message); });
checkLocalHelper().then(async () => { const [notion, googlePlaces, osmPlaces, mobileLocation, googleStatus, placeLabels] = await Promise.all([localRequest('/api/notion/status'), localRequest('/api/google-places/status'), localRequest('/api/osm-places/status'), localRequest('/api/location/mobile/status'), loadGoogleStatus(), loadPlaceLabels().catch(() => [])]); state.notion.configured = Boolean(notion.configured); state.googlePlaces.configured = Boolean(googlePlaces.configured); state.osmPlaces.configured = Boolean(osmPlaces.configured); state.mobileLocation = { configured: Boolean(mobileLocation.configured), samples: mobileLocation.samples || 0, latest: mobileLocation.latest || '' }; state.placeLabels = placeLabels || state.placeLabels || []; persist(); render(); loadProjects(true).catch(() => {}); loadHabitsToday(true).catch(() => {}); loadHabitHistory(state.habits.range || 'month', true).catch(() => {}); if (googleStatus.connected) loadGoogleCalendar().catch(() => {}); if (mobileLocation.samples) loadLocationData(state.locationView).catch(() => {}); }).catch(() => {});
loadYoutube(true).catch(() => {});
if (state.spotify.accessToken) {
  loadSpotify({ quiet: true }).catch(() => {});
  startSpotifyPolling();
}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('./service-worker.js').then(registration => registration.update()).catch(() => {});
