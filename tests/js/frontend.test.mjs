import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createAppUpdateManager, isLifeyShellCache, updateDecision } from '../../js/app-updates.js';
import { calendarEmptyMessage, eventMinutesFromDrag, eventPatchFromMinutes, normalizeCalendarScale, normalizeTimedCalendarEvent, timelineHeight } from '../../js/features/calendar/calendar.js';
import { parseNaturalTask } from '../../js/features/capture/capture.js';
import { habitPeriod, habitStreak, isMissedHabit, timeToMinutes } from '../../js/features/habits/habits.js';
import { durationLabel, placeDurationMilliseconds, totalTimeLabel } from '../../js/features/location/location.js';
import { handleLocationAction } from '../../js/features/location/controller.js';
import { handlePreferenceAction, handlePreferenceChange } from '../../js/features/preferences/controller.js';
import { handleProjectAction } from '../../js/features/projects/controller.js';
import { parseTasks } from '../../js/parsers.js';
import { normalizeLocationResponse, normalizeProjectsResponse, normalizeStoredState, normalizeYoutubeActivityResponse } from '../../js/state.js';

test('parseTasks ignores Habits section and applies task mappings', () => {
  const tasks = parseTasks(
    [
      '# Today',
      '- [ ] Ship feature',
      '## Habits::',
      '- [ ] Drink water',
      '## Later',
      '- [x] Close loop',
    ].join('\n'),
    'Daily/2026-07-04.md',
    {
      'Daily/2026-07-04.md:2': { notionPageId: 'notion-1', notionUrl: 'https://notion.test/page' },
      'Daily/2026-07-04.md:6': { calendarEventId: 'event-1' },
    },
  );

  assert.equal(tasks.length, 2);
  assert.deepEqual(
    tasks.map(task => ({ text: task.text, line: task.line, done: task.done, notion: task.notion, calendar: task.calendar })),
    [
      { text: 'Ship feature', line: 2, done: false, notion: true, calendar: false },
      { text: 'Close loop', line: 6, done: true, notion: false, calendar: true },
    ],
  );
});

test('calendar timeline scale normalizes geometry and height', () => {
  const scale = normalizeCalendarScale({ dayStart: 8 * 60, dayEnd: 18 * 60, pxPerHour: 60, snapMinutes: 15 });
  const event = normalizeTimedCalendarEvent({
    id: 'calendar-1',
    summary: 'Review',
    start: { dateTime: '2026-07-08T09:30:00-05:00' },
    end: { dateTime: '2026-07-08T10:15:00-05:00' },
  }, scale);

  assert.equal(timelineHeight(scale), 600);
  assert.equal(event.startMinutes, 570);
  assert.equal(event.endMinutes, 615);
  assert.equal(event.geometry.top, 90);
  assert.equal(event.geometry.height, 45);
});

test('calendar drag snaps move and resize actions to the configured scale', () => {
  const scale = normalizeCalendarScale({ dayStart: 8 * 60, dayEnd: 18 * 60, pxPerHour: 60, snapMinutes: 15, minDurationMinutes: 30 });
  const original = { startMinutes: 9 * 60, endMinutes: 10 * 60 };

  assert.deepEqual(eventMinutesFromDrag(original, 30, 'move', scale), { startMinutes: 570, endMinutes: 630 });
  assert.deepEqual(eventMinutesFromDrag(original, 30, 'start', scale), { startMinutes: 570, endMinutes: 600 });
  assert.deepEqual(eventMinutesFromDrag(original, -45, 'end', scale), { startMinutes: 540, endMinutes: 570 });
});

test('calendar event patch keeps the source date and configured timezone', () => {
  const patch = eventPatchFromMinutes(
    { start: { dateTime: '2026-07-08T09:00:00-05:00' } },
    13 * 60 + 15,
    14 * 60,
    { timezone: 'America/Guayaquil' },
  );

  assert.equal(patch.start.dateTime, '2026-07-08T13:15:00');
  assert.equal(patch.end.dateTime, '2026-07-08T14:00:00');
  assert.equal(patch.start.timeZone, 'America/Guayaquil');
  assert.equal(patch.end.timeZone, 'America/Guayaquil');
});

test('calendar empty prompt appears only while Google Calendar is disconnected', () => {
  assert.equal(calendarEmptyMessage(false), 'Connect Google Calendar to show today’s events.');
  assert.equal(calendarEmptyMessage(true), '');
});

test('parseNaturalTask extracts project, time, priority, recurrence, and effort metadata', () => {
  const parsed = parseNaturalTask('Write test plan for project Lifey Architecture at 2:30pm every week priority high estimated time 1.5 it took 0.25', {
    due: '2026-07-05',
  });

  assert.equal(parsed.due, '2026-07-05');
  assert.equal(parsed.time, '14:30');
  assert.equal(parsed.priority, '🔼');
  assert.equal(parsed.recurrence, 'every week');
  assert.equal(parsed.project, '#project/lifey-architecture');
  assert.equal(parsed.estimate, '1.5');
  assert.equal(parsed.actualTime, '0.25');
  assert.match(parsed.text, /#project\/lifey-architecture/);
  assert.match(parsed.text, /\[estimate:: 1.5\]/);
  assert.match(parsed.text, /\[time:: 0.25\]/);
});

test('habit pure logic handles time periods, missed state, and streaks', () => {
  const settings = {
    timezone: 'America/Guayaquil',
    periods: [
      { id: 'morning', name: 'Morning', start: '06:00', end: '12:00' },
      { id: 'night', name: 'Night', start: '22:00', end: '02:00' },
    ],
  };
  const state = {
    habits: {
      date: '2026-07-04',
      history: [
        { date: '2026-07-04', habit: 'Walk', state: 'completed' },
        { date: '2026-07-03', habit: 'Walk', state: 'completed' },
        { date: '2026-07-02', habit: 'Walk', state: 'pending' },
      ],
    },
  };

  assert.equal(timeToMinutes('22:30'), 1350);
  assert.equal(habitPeriod({ timeMinutes: 23 * 60 }, settings), 'night');
  assert.equal(isMissedHabit({ state: 'pending', dueDate: '2026-07-03', timeMinutes: 8 * 60 }, state, settings, () => '2026-07-04'), true);
  assert.equal(habitStreak({ habit: 'Walk', date: '2026-07-04', state: 'completed' }, state, settings, () => '2026-07-04'), 2);
});

test('location pure logic formats durations and place timing', () => {
  assert.equal(durationLabel(65), '1 min');
  assert.equal(durationLabel(3660), '1 hour, 1 min');
  assert.equal(totalTimeLabel(90 * 60 * 1000), '1h 30m');
  assert.equal(placeDurationMilliseconds({ totalSeconds: 300 }), 300000);
});

test('normalizeStoredState strips secrets and coerces malformed persisted data', () => {
  const normalized = normalizeStoredState({
    tasks: [{ text: 'Do it', source: 'Daily.md', line: '3' }, null, { text: '' }],
    integrations: {
      google: { clientId: 'client', clientSecret: 'secret' },
      spotify: { clientId: 'spotify', accessToken: 'token', refreshToken: 'refresh' },
    },
    projects: { projects: [{ slug: 'alpha', title: 'Alpha', tasks: [{ raw: 'Task', source: 'P.md', line: 4 }] }] },
    youtube: { videos: [{ title: 'Video', activeSeconds: '120' }, {}] },
    locationSettings: { radiusMeters: '900', merges: 'bad' },
  });

  assert.equal(normalized.tasks.length, 1);
  assert.equal(normalized.tasks[0].line, 3);
  assert.equal(normalized.integrations.google.clientSecret, undefined);
  assert.equal(normalized.integrations.spotify.accessToken, undefined);
  assert.equal(normalized.projects.projects[0].taskCount, 1);
  assert.equal(normalized.youtube.videos[0].activeSeconds, 120);
  assert.equal(normalized.locationSettings.radiusMeters, 500);
  assert.deepEqual(normalized.locationSettings.merges, []);
});

test('API response normalizers reject bad shapes and preserve valid data', () => {
  assert.throws(() => normalizeProjectsResponse(null), /Projects response/);
  assert.throws(() => normalizeLocationResponse([], 'today'), /Location response/);

  const projects = normalizeProjectsResponse({ projects: [{ slug: 'alpha', title: 'Alpha', taskCount: '2' }], taskCount: '2' });
  assert.equal(projects.projects[0].slug, 'alpha');
  assert.equal(projects.taskCount, 2);

  const location = normalizeLocationResponse({ places: [{ name: 'Studio', latitude: '-0.18', longitude: '-78.47' }], positions: '5' });
  assert.equal(location.places[0].latitude, -0.18);
  assert.equal(location.positions, 5);

  const youtube = normalizeYoutubeActivityResponse({ days: [{ date: '2026-07-04', videos: [{ title: 'Clip', activeSeconds: '30' }] }] });
  assert.equal(youtube.days[0].videos[0].activeSeconds, 30);
});

test('app update decisions reload once per worker version and preserve capture drafts', () => {
  assert.equal(updateDecision({ loadedVersion: 'v1', workerVersion: 'v1' }), 'current');
  assert.equal(updateDecision({ loadedVersion: 'v1', workerVersion: 'v2' }), 'reload');
  assert.equal(updateDecision({ loadedVersion: 'v1', workerVersion: 'v2', hasUnsavedCapture: true }), 'prompt');
  assert.equal(updateDecision({ loadedVersion: 'v1', workerVersion: 'v2', reloadTarget: 'v2' }), 'recovery');
  assert.equal(isLifeyShellCache('lifey-shell-v123'), true);
  assert.equal(isLifeyShellCache('other-cache'), false);
});

test('app cache recovery deletes only Lifey shell caches before reloading', async () => {
  const deleted = [];
  let reloads = 0;
  const manager = createAppUpdateManager({
    loadedVersion: 'v1',
    navigatorObject: {},
    cacheStorage: {
      keys: async () => ['lifey-shell-v1', 'lifey-shell-v2', 'other-cache'],
      delete: async key => { deleted.push(key); return true; },
    },
    sessionStore: { removeItem: () => {} },
    reload: () => { reloads += 1; },
  });

  await manager.clearAppCacheAndReload();

  assert.deepEqual(deleted, ['lifey-shell-v1', 'lifey-shell-v2']);
  assert.equal(reloads, 1);
});

test('project controller mutates expanded project state and persists', () => {
  const calls = [];
  const ctx = {
    state: { projects: { expandedSlug: '' } },
    persist: () => calls.push('persist'),
    render: () => calls.push('render'),
    toast: message => calls.push(message),
    loadProjects: async () => calls.push('loadProjects'),
    quickCaptureModal: () => calls.push('quickCaptureModal'),
    openProjectNote: async () => calls.push('openProjectNote'),
    createProjectNote: async () => calls.push('createProjectNote'),
    updateProjectTask: async () => calls.push('updateProjectTask'),
  };

  const handled = handleProjectAction('open-project', { dataset: { projectSlug: 'alpha' } }, ctx);

  assert.equal(handled, true);
  assert.equal(ctx.state.projects.expandedSlug, 'alpha');
  assert.deepEqual(calls, ['persist', 'render']);
});

test('preference controller updates display state without DOM dependencies', () => {
  const calls = [];
  const ctx = {
    state: { contentDisplay: { limit: 6, youtubeSize: 'medium' }, habitSettings: { timezone: 'America/Guayaquil', periods: [] } },
    persist: () => calls.push('persist'),
    render: () => calls.push('render'),
    toast: message => calls.push(message),
    openPreferences: tab => calls.push(`open:${tab || 'default'}`),
    preferencesScrollTop: () => 42,
    rerenderPreferences: (tab, scrollTop) => calls.push(`rerender:${tab}:${scrollTop}`),
    applyAppearance: () => calls.push('applyAppearance'),
    saveDashboardBackgroundImage: () => calls.push('saveImage'),
    exportProfile: async () => calls.push('exportProfile'),
    importProfileFile: () => calls.push('importProfileFile'),
    importProfile: async () => calls.push('importProfile'),
    DEFAULT_HABIT_SETTINGS: { timezone: 'America/Guayaquil', periods: [{ id: 'morning', name: 'Morning', start: '00:00', end: '12:00' }] },
    timeToMinutes,
    saveLocationRadius: async () => calls.push('saveLocationRadius'),
    loadLocationData: async () => calls.push('loadLocationData'),
  };

  assert.equal(handlePreferenceAction('set-suggestion-count', { dataset: { count: '3' } }, ctx), true);
  assert.equal(ctx.state.contentDisplay.limit, 3);
  assert.deepEqual(calls, ['persist', 'rerender:appearance:42']);
});

test('preference controller delegates app update maintenance actions', async () => {
  const calls = [];
  const ctx = {
    checkForAppUpdate: async () => { calls.push('check'); return { status: 'current' }; },
    clearAppCacheAndReload: async () => calls.push('clear'),
    toast: message => calls.push(message),
  };

  assert.equal(handlePreferenceAction('check-app-update', { dataset: {} }, ctx), true);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(handlePreferenceAction('clear-app-cache', { dataset: {} }, ctx), true);
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(calls, ['check', 'Lifey is up to date.', 'clear']);
});

test('preference task path toggle updates in place without rerendering settings', () => {
  const calls = [];
  const ctx = {
    state: { taskDisplay: { showPath: true } },
    persist: () => calls.push('persist'),
    render: () => calls.push('render'),
    rerenderPreferences: () => calls.push('rerenderPreferences'),
    updateTaskPathVisibility: () => calls.push('updateTaskPathVisibility'),
  };
  const event = {
    target: { dataset: { taskDisplay: 'showPath' }, checked: false },
    stopPropagation: () => calls.push('stopPropagation'),
    stopImmediatePropagation: () => calls.push('stopImmediatePropagation'),
  };

  const handled = handlePreferenceChange(event, ctx);

  assert.equal(handled, true);
  assert.equal(ctx.state.taskDisplay.showPath, false);
  assert.deepEqual(calls, ['stopPropagation', 'stopImmediatePropagation', 'persist', 'updateTaskPathVisibility']);
});

test('location controller switches view and requests location reload', async () => {
  const calls = [];
  const ctx = {
    state: { locationView: 'today', locationWeekDay: '', traccar: { places: [] }, places: [] },
    persist: () => calls.push('persist'),
    render: () => calls.push('render'),
    toast: message => calls.push(message),
    modal: () => calls.push('modal'),
    escape: value => String(value),
    showPlacePoints: () => calls.push('showPlacePoints'),
    savePlaceLabel: async () => calls.push('savePlaceLabel'),
    loadLocationData: async view => calls.push(`load:${view}`),
    setPlaceMergeMode: value => calls.push(`mergeMode:${value}`),
    setPlaceMergeSelection: value => calls.push(`mergeSelection:${value.length}`),
    placeMergeSelection: () => [],
    createPlaceMerge: async () => ({}),
    undoPlaceMerge: async () => ({}),
    openPreferences: () => calls.push('openPreferences'),
    todayIso: () => '2026-07-04',
    archiveLocationPeriod: async () => calls.push('archiveLocationPeriod'),
  };

  assert.equal(handleLocationAction('set-location-view', { dataset: { view: 'week' } }, ctx), true);
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.equal(ctx.state.locationView, 'week');
  assert.equal(ctx.state.locationWeekDay, '2026-07-04');
  assert.deepEqual(calls, ['persist', 'render', 'load:week']);
});
