const CAPTURE_ACTIONS = new Set([
  'quick-add',
  'save-quick-task',
  'open-capture-calendar',
  'open-capture-options',
  'select-capture-option',
  'open-capture-places',
  'select-capture-place',
  'capture-calendar-prev',
  'capture-calendar-next',
  'capture-calendar-select',
  'capture-clock-mode',
  'capture-clock-period',
  'capture-clock-select'
]);

export function handleCaptureAction(action, button, ctx) {
  if (!CAPTURE_ACTIONS.has(action)) return false;
  if (action === 'quick-add') {
    ctx.quickCaptureModal();
    ctx.loadPlaceLabels().then(() => ctx.renderCapturePlaceDropdown(false)).catch(() => {});
  }
  if (action === 'save-quick-task') ctx.saveQuickCapture().catch(error => ctx.toast(error.message));
  if (action === 'open-capture-calendar') {
    const holder = document.querySelector('#capture-calendar');
    if (holder?.innerHTML) { ctx.closeCaptureSubmenus(); return true; }
    ctx.closeCaptureSubmenus();
    ctx.setCaptureMenuOpen('calendar');
    document.querySelector('#capture-task')?.blur();
    window.captureCalendarMonth = document.querySelector('#capture-date')?.value ? new Date(`${document.querySelector('#capture-date').value}T12:00:00`) : new Date();
    const currentTime = document.querySelector('#capture-time')?.value;
    window.captureClockMode = 'hour';
    window.captureTimePeriod = currentTime && Number(currentTime.split(':')[0]) >= 12 ? 'pm' : 'am';
    ctx.renderCaptureCalendar();
    requestAnimationFrame(() => document.querySelector('#capture-calendar')?.scrollIntoView({ block: 'nearest' }));
  }
  if (action === 'open-capture-options') ctx.renderCaptureOptionDropdown(button.dataset.menu);
  if (action === 'select-capture-option') ctx.selectCaptureOption(button.dataset.menu, button.dataset.value || '');
  if (action === 'open-capture-places') {
    const holder = document.querySelector('#capture-place-dropdown');
    if (holder?.innerHTML && document.querySelector('[data-action="open-capture-places"]')?.classList.contains('is-open')) {
      ctx.closeCaptureSubmenus();
      ctx.refocusCaptureInput();
      return true;
    }
    ctx.closeCaptureSubmenus();
    ctx.setCaptureMenuOpen('place');
    ctx.ensureCapturePlaceContext();
    ctx.renderCapturePlaceDropdown(true, 'Loading saved places…');
    ctx.loadPlaceLabels().then(() => {
      ctx.renderCapturePlaceDropdown(true, 'No saved places yet.');
      ctx.setCaptureMenuOpen('place');
    }).catch(error => {
      ctx.renderCapturePlaceDropdown(true, 'Could not refresh saved places.');
      ctx.toast(error.message);
    });
    ctx.refocusCaptureInput();
  }
  if (action === 'select-capture-place') ctx.selectCapturePlace(button.dataset.placeName);
  if (action === 'capture-calendar-prev') { window.captureCalendarMonth = new Date(window.captureCalendarMonth.getFullYear(), window.captureCalendarMonth.getMonth() - 1, 1); ctx.renderCaptureCalendar(); }
  if (action === 'capture-calendar-next') { window.captureCalendarMonth = new Date(window.captureCalendarMonth.getFullYear(), window.captureCalendarMonth.getMonth() + 1, 1); ctx.renderCaptureCalendar(); }
  if (action === 'capture-calendar-select') { const input = document.querySelector('#capture-date'); if (input) input.value = button.dataset.date; ctx.refreshQuickCapturePreview(); ctx.renderCaptureCalendar(); }
  if (action === 'capture-clock-mode') { window.captureClockMode = button.dataset.mode; ctx.renderCaptureCalendar(); }
  if (action === 'capture-clock-period') {
    window.captureTimePeriod = button.dataset.period;
    const input = document.querySelector('#capture-time');
    if (input?.value) {
      let [hour, minute] = input.value.split(':').map(Number);
      hour = hour % 12 + (button.dataset.period === 'pm' ? 12 : 0);
      input.value = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
      ctx.refreshQuickCapturePreview();
    }
    ctx.renderCaptureCalendar();
  }
  if (action === 'capture-clock-select') {
    const input = document.querySelector('#capture-time');
    const current = input?.value || '09:00';
    let [hour, minute] = current.split(':').map(Number);
    if (window.captureClockMode === 'hour') {
      hour = Number(button.dataset.value) % 12 + (window.captureTimePeriod === 'pm' ? 12 : 0);
      window.captureClockMode = 'minute';
    } else {
      minute = Number(button.dataset.value);
      window.captureClockMode = 'hour';
    }
    if (input) input.value = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    ctx.refreshQuickCapturePreview();
    ctx.renderCaptureCalendar();
  }
  return true;
}

export function handleCaptureInput(event, ctx) {
  if (event.target.id !== 'capture-task') return false;
  ctx.refreshQuickCapturePreview();
  ctx.renderCapturePlaceDropdown(false);
  return true;
}

export function handleCaptureKeydown(event, ctx) {
  if (event.target?.id !== 'capture-task') return false;
  const holder = document.querySelector('#capture-place-dropdown');
  const open = Boolean(holder?.querySelector('[data-place-name]'));
  if (event.key === 'ArrowDown' && open) { event.preventDefault(); ctx.moveCapturePlaceSelection(1); return true; }
  if (event.key === 'ArrowUp' && open) { event.preventDefault(); ctx.moveCapturePlaceSelection(-1); return true; }
  if (event.key === 'Enter' && open && ctx.selectedCapturePlaceName()) { event.preventDefault(); ctx.selectCapturePlace(ctx.selectedCapturePlaceName()); return true; }
  if (event.key === 'Escape' && holder?.innerHTML) { ctx.closeCaptureSubmenus(); event.preventDefault(); return true; }
  return false;
}
