const PREFERENCE_ACTIONS = new Set([
  'settings',
  'preferences-tab',
  'choose-background-image',
  'remove-background-image',
  'export-profile',
  'import-profile',
  'confirm-profile-import',
  'check-app-update',
  'clear-app-cache',
  'toggle-task-path',
  'set-suggestion-count',
  'set-youtube-card-size',
  'add-habit-period',
  'delete-habit-period',
  'reset-habit-periods',
  'save-habit-settings'
]);

export function handlePreferenceAction(action, button, ctx) {
  if (!PREFERENCE_ACTIONS.has(action)) return false;
  if (action === 'settings') ctx.openPreferences();
  if (action === 'preferences-tab') ctx.openPreferences(button.dataset.tab);
  if (action === 'choose-background-image') document.querySelector('#dashboard-background-input')?.click();
  if (action === 'remove-background-image') {
    const scrollTop = ctx.preferencesScrollTop();
    ctx.state.appearance.backgroundImage = '';
    ctx.applyAppearance();
    ctx.persist();
    ctx.rerenderPreferences('appearance', scrollTop);
    ctx.toast('Dashboard background image removed.');
  }
  if (action === 'export-profile') ctx.exportProfile().then(() => ctx.toast('Lifey profile exported without secrets.')).catch(error => ctx.toast(error.message));
  if (action === 'import-profile') ctx.importProfileFile();
  if (action === 'check-app-update') ctx.checkForAppUpdate().then(result => ctx.toast(result.status === 'current' ? 'Lifey is up to date.' : 'Update check finished.')).catch(error => ctx.toast(error.message));
  if (action === 'clear-app-cache') ctx.clearAppCacheAndReload().catch(error => ctx.toast(error.message));
  if (action === 'toggle-task-path') {
    const previous = button.getAttribute?.('aria-checked') === 'true';
    const next = !previous;
    ctx.state.taskDisplay.showPath = next;
    button.setAttribute?.('aria-checked', String(next));
    ctx.updateTaskPathVisibility?.();
    try {
      ctx.persist();
    } catch (error) {
      ctx.reportPreferenceError?.(error);
      ctx.state.taskDisplay.showPath = previous;
      button.setAttribute?.('aria-checked', String(previous));
      ctx.updateTaskPathVisibility?.();
      ctx.showDialogError?.('Lifey could not save this setting. Your Settings window was kept open; clear some browser storage and try again.');
    }
  }
  if (action === 'confirm-profile-import') {
    const bundle = window.pendingProfileImport;
    if (!bundle) return ctx.toast('Choose a Lifey profile file first.'), true;
    document.querySelector('#modal').close();
    ctx.importProfile(bundle).then(() => { ctx.render(); ctx.openPreferences('profile'); ctx.toast('Profile imported. Reconnect private tokens on this Mac.'); }).catch(error => ctx.toast(error.message));
  }
  if (action === 'set-suggestion-count') { const scrollTop = ctx.preferencesScrollTop(); ctx.state.contentDisplay.limit = Number(button.dataset.count); ctx.persist(); ctx.rerenderPreferences('appearance', scrollTop); }
  if (action === 'set-youtube-card-size') { const scrollTop = ctx.preferencesScrollTop(); ctx.state.contentDisplay.youtubeSize = ['small', 'medium', 'large'].includes(button.dataset.size) ? button.dataset.size : 'medium'; ctx.persist(); ctx.rerenderPreferences('appearance', scrollTop); }
  if (action === 'add-habit-period') { const scrollTop = ctx.preferencesScrollTop(); ctx.state.habitSettings.periods = [...ctx.state.habitSettings.periods, { id: `period-${Date.now()}`, name: 'New period', start: '18:00', end: '23:59' }]; ctx.persist(); ctx.rerenderPreferences('habits', scrollTop); }
  if (action === 'delete-habit-period') { const scrollTop = ctx.preferencesScrollTop(); ctx.state.habitSettings.periods = ctx.state.habitSettings.periods.filter((_, index) => index !== Number(button.dataset.index)); ctx.persist(); ctx.rerenderPreferences('habits', scrollTop); }
  if (action === 'reset-habit-periods') { const scrollTop = ctx.preferencesScrollTop(); ctx.state.habitSettings = { timezone: ctx.state.habitSettings.timezone || ctx.DEFAULT_HABIT_SETTINGS.timezone, periods: ctx.DEFAULT_HABIT_SETTINGS.periods.map(period => ({ ...period })) }; ctx.persist(); ctx.rerenderPreferences('habits', scrollTop); ctx.toast('Habit periods reset.'); }
  if (action === 'save-habit-settings') {
    const timezone = document.querySelector('#habit-timezone')?.value.trim() || ctx.DEFAULT_HABIT_SETTINGS.timezone;
    try { new Intl.DateTimeFormat('en-US', { timeZone: timezone }).format(new Date()); } catch { return ctx.toast('Use a valid timezone like America/Guayaquil.'), true; }
    const rows = [...document.querySelectorAll('[data-habit-period-index]')];
    const periods = rows.map((row, index) => {
      const field = name => row.querySelector(`[data-habit-period-field="${name}"]`)?.value.trim();
      return { id: ctx.state.habitSettings.periods[index]?.id || `period-${index + 1}`, name: field('name'), start: field('start'), end: field('end') };
    });
    if (!periods.length) return ctx.toast('Keep at least one habit period.'), true;
    if (periods.some(period => !period.name || ctx.timeToMinutes(period.start) === null || ctx.timeToMinutes(period.end) === null)) return ctx.toast('Each habit period needs a name, start time, and end time.'), true;
    ctx.state.habitSettings = { timezone, periods };
    ctx.persist();
    ctx.rerenderPreferences('habits', ctx.preferencesScrollTop());
    ctx.toast('Habit time settings saved.');
  }
  return true;
}

export function handlePreferenceChange(event, ctx) {
  const color = event.target.dataset.appearance;
  if (color) { ctx.state.appearance[color] = event.target.value; ctx.applyAppearance(); ctx.persist(); const preview = event.target.parentElement.querySelector('span'); if (preview) preview.style.background = event.target.value; return true; }
  if (event.target.id === 'background-tint-intensity') { ctx.state.appearance.backgroundTintIntensity = Number(event.target.value); ctx.applyAppearance(); ctx.persist(); return true; }
  if (event.target.id === 'appearance-corner-radius') { ctx.state.appearance.cornerRadius = Math.max(8, Math.min(36, Number(event.target.value))); ctx.applyAppearance(); ctx.persist(); return true; }
  if (event.target.id === 'dashboard-background-input') { ctx.saveDashboardBackgroundImage(event.target.files?.[0]); return true; }
  if (['location-radius', 'location-radius-number'].includes(event.target.id)) {
    const scrollTop = ctx.preferencesScrollTop();
    const radius = Number(event.target.value);
    if (!Number.isFinite(radius) || radius < 20 || radius > 500) return ctx.toast('Choose a distance from 20 to 500 metres.'), true;
    ctx.saveLocationRadius(radius).then(() => ctx.loadLocationData(ctx.state.locationView)).then(() => {
      ctx.openPreferences('location', { scrollTop });
      ctx.toast(`Place grouping updated to ${radius} metres.`);
    }).catch(error => ctx.toast(error.message));
    return true;
  }
  const visibility = event.target.dataset.visibility;
  if (visibility) { const scrollTop = ctx.preferencesScrollTop(); ctx.state.visibility[visibility] = event.target.checked; ctx.persist(); ctx.rerenderPreferences('appearance', scrollTop); return true; }
  const heroMetric = event.target.dataset.heroMetricVisible;
  if (heroMetric) { const scrollTop = ctx.preferencesScrollTop(); ctx.state.heroMetricVisibility[heroMetric] = event.target.checked; ctx.persist(); ctx.rerenderPreferences('appearance', scrollTop); return true; }
  return false;
}

export function handlePreferenceInput(event, ctx) {
  if (event.target.id === 'location-radius') {
    const number = document.querySelector('#location-radius-number');
    const output = document.querySelector('.location-radius output');
    if (number) number.value = event.target.value;
    if (output) output.textContent = `${event.target.value} m`;
    return true;
  }
  if (event.target.id === 'background-tint-intensity') {
    const output = event.target.closest('label')?.querySelector('output');
    if (output) output.textContent = `${event.target.value}%`;
    ctx.state.appearance.backgroundTintIntensity = Number(event.target.value);
    ctx.applyAppearance();
    return true;
  }
  if (event.target.id === 'appearance-corner-radius') {
    const value = Math.max(8, Math.min(36, Number(event.target.value)));
    const output = event.target.closest('label')?.querySelector('output');
    if (output) output.textContent = `${value}px`;
    ctx.state.appearance.cornerRadius = value;
    ctx.applyAppearance();
    return true;
  }
  return false;
}
