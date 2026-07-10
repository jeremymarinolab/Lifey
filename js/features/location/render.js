import { escape } from '../../renderers.js';
import { emptyState } from '../../ui/components.js';
import { segmentedControl } from '../../ui/controls.js';
import { placeDurationMilliseconds, placeTiming, totalTimeLabel } from './location.js';

export function renderPlaceRow(place, { index, actions = false, date = '', traccarConnected = false, placeMergeMode = false, placeMergeSelection = [] } = {}) {
  const timing = placeTiming(place);
  const hasCoordinates = traccarConnected && Number.isFinite(place.latitude) && Number.isFinite(place.longitude);
  const selected = placeMergeSelection.includes(index);
  const hasPointDetail = (place.points || []).length > 1;
  const pointButton = hasPointDetail ? `<button class="icon-button place-points" title="See ${place.points.length} captured points" aria-label="See ${place.points.length} captured points" data-action="view-place-points" data-place-index="${index}" data-place-date="${date}">◎</button>` : '';
  const mapButton = hasCoordinates ? `<button class="icon-button place-map" title="Open in Google Maps" aria-label="Open in Google Maps" data-action="open-place-map" data-latitude="${place.latitude}" data-longitude="${place.longitude}">↗</button>` : '';
  const passiveControls = hasPointDetail ? pointButton : mapButton;
  return `<div class="${place.merged ? 'is-merged' : ''}">${placeMergeMode && actions ? `<button class="place-select ${selected ? 'selected' : ''}" title="Select ${escape(place.name)}" aria-label="Select ${escape(place.name)}" data-action="toggle-place-merge" data-place-index="${index}">${selected ? '✓' : ''}</button>` : '<span class="pin">✦</span>'}<p><strong>${escape(place.name)}${place.merged ? '<span class="merged-place" title="Manual merge">★</span>' : ''}</strong><small>${escape(timing.range)} · ${escape(place.source)}${timing.total ? `<br><span class="place-total">${escape(timing.total)}</span>` : ''}</small></p>${actions && hasCoordinates && !placeMergeMode ? `${pointButton}<button class="icon-button place-label" title="Name this place" aria-label="Name this place" data-action="label-place" data-place-index="${index}">✎</button>${mapButton}` : !placeMergeMode ? passiveControls : ''}</div>`;
}

export function renderLocationWeekContent(weekData, { selectedDate = '', traccarConnected = false } = {}) {
  const selectedDay = weekData.days?.find(day => day.date === selectedDate) || weekData.days?.at(-1);
  const selectedTotal = (selectedDay?.places || []).reduce((sum, place) => sum + placeDurationMilliseconds(place), 0);
  return `<div class="week-places"><section class="week-top-places"><p class="eyebrow">TOP PLACES THIS WEEK</p>${weekData.topPlaces?.length ? weekData.topPlaces.map((place, index) => `<div><span>${String(index + 1).padStart(2, '0')}</span><strong>${escape(place.name)}</strong><small>${totalTimeLabel((place.seconds || 0) * 1000)} · ${place.visits} visit(s)</small></div>`).join('') : emptyState('Load this week to see your top places.')}</section><section class="week-days">${weekData.days?.length ? `${segmentedControl(weekData.days.map(day => { const date = new Date(`${day.date}T12:00:00`); return { value: day.date, label: `<span>${date.toLocaleDateString([], { weekday: 'short' })}</span><b>${date.getDate()}</b>` }; }), { className: 'week-day-switch', action: 'set-week-day', dataKey: 'date', selected: selectedDay?.date })}<div class="week-day"><div class="week-day-summary"><p>${new Date(`${selectedDay.date}T12:00:00`).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })}</p><span><small>Total time</small><strong>${selectedDay.places.length ? totalTimeLabel(selectedTotal) : '0 min'}</strong></span></div><div class="place-list">${selectedDay.places.length ? selectedDay.places.map((place, index) => renderPlaceRow(place, { index, date: selectedDay.date, traccarConnected })).join('') : '<small>No location points</small>'}</div></div>` : emptyState('Load this week to see each day’s visits.')}</section></div>`;
}
