const LOCATION_ACTIONS = new Set([
  'add-place',
  'save-place',
  'label-place',
  'view-place-points',
  'open-place-map',
  'save-place-label',
  'start-place-merge',
  'cancel-place-merge',
  'toggle-place-merge',
  'confirm-place-merge',
  'save-place-merge',
  'undo-place-merge',
  'set-location-view',
  'set-week-day',
  'archive-location-menu',
  'archive-location',
  'refresh-location'
]);

export function handleLocationAction(action, button, ctx) {
  if (!LOCATION_ACTIONS.has(action)) return false;
  if (action === 'add-place') ctx.modal('Add a place', '<label>Place name<input id="place-name" placeholder="A place you visited" /></label><label>Time window<input id="place-time" placeholder="14:00–15:30" /></label>', 'save-place');
  if (action === 'save-place') {
    const name = document.querySelector('#place-name').value;
    if (name) {
      ctx.state.places.push({ name, time: document.querySelector('#place-time').value || 'Today', source: 'Manual' });
      ctx.persist();
      document.querySelector('#modal').close();
      ctx.render();
      ctx.toast('Place added as manual data.');
    }
  }
  if (action === 'label-place') {
    const place = ctx.state.traccar.places[Number(button.dataset.placeIndex)];
    if (!place) return true;
    window.pendingPlaceLabel = place;
    ctx.modal('Name this place', `<p class="modal-copy">This name stays on your Mac and automatically applies whenever a location point is within <strong>50 metres</strong> of this spot.</p><label>Place name<input id="local-place-label" value="${ctx.escape(place.name)}" placeholder="e.g. Home, Studio, Gym" autofocus></label>`, 'save-place-label');
  }
  if (action === 'view-place-points') {
    const index = Number(button.dataset.placeIndex);
    const day = button.dataset.placeDate;
    const place = day ? ctx.state.traccar.week?.days?.find(item => item.date === day)?.places?.[index] : ctx.state.traccar.places[index];
    if (place) ctx.showPlacePoints(place);
  }
  if (action === 'open-place-map') {
    const latitude = Number(button.dataset.latitude), longitude = Number(button.dataset.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return ctx.toast('Coordinates are unavailable for this place.'), true;
    window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${latitude},${longitude}`)}`, '_blank', 'noopener');
  }
  if (action === 'save-place-label') {
    const place = window.pendingPlaceLabel;
    const name = document.querySelector('#local-place-label')?.value.trim();
    if (!place || !name) return ctx.toast('Enter a name for this place.'), true;
    document.querySelector('#modal').close();
    ctx.savePlaceLabel(name, place.latitude, place.longitude)
      .then(() => { ctx.state.osmPlaces.configured = false; ctx.persist(); ctx.toast(`Saved “${name}” for this location and nearby visits.`); return ctx.loadLocationData(); })
      .catch(error => ctx.toast(error.message));
  }
  if (action === 'start-place-merge') { ctx.setPlaceMergeMode(true); ctx.setPlaceMergeSelection([]); ctx.render(); }
  if (action === 'cancel-place-merge') { ctx.setPlaceMergeMode(false); ctx.setPlaceMergeSelection([]); ctx.render(); }
  if (action === 'toggle-place-merge') {
    const index = Number(button.dataset.placeIndex);
    ctx.setPlaceMergeSelection(ctx.placeMergeSelection().includes(index) ? ctx.placeMergeSelection().filter(item => item !== index) : [...ctx.placeMergeSelection(), index]);
    ctx.render();
  }
  if (action === 'confirm-place-merge') {
    const selected = ctx.placeMergeSelection().map(index => ctx.state.traccar.places[index]).filter(Boolean);
    if (selected.length < 2) return ctx.toast('Select at least two places to merge.'), true;
    const defaultName = [...new Set(selected.map(place => place.name))].join(' – ').slice(0, 120);
    window.pendingPlaceMerge = selected;
    ctx.modal('Merge places', `<p class="modal-copy">This creates one local place, preserves the old place notes as <code>-lifey-archive</code>, and can be undone in Settings → Location.</p><label>Merged place name<input id="merged-place-name" value="${ctx.escape(defaultName)}" autofocus></label>`, 'save-place-merge');
  }
  if (action === 'save-place-merge') {
    const name = document.querySelector('#merged-place-name')?.value.trim();
    const selected = window.pendingPlaceMerge || [];
    if (!name) return ctx.toast('Give the merged place a name.'), true;
    document.querySelector('#modal').close();
    ctx.createPlaceMerge(name, selected).then(async merge => {
      ctx.setPlaceMergeMode(false);
      ctx.setPlaceMergeSelection([]);
      await ctx.loadLocationData();
      ctx.toast(`Merged ${selected.length} locations as “${merge.name}”.`);
    }).catch(error => ctx.toast(error.message));
  }
  if (action === 'undo-place-merge') {
    ctx.undoPlaceMerge(button.dataset.mergeId).then(async result => {
      await ctx.loadLocationData();
      ctx.openPreferences('location');
      ctx.toast(`Undid “${result.name}”.`);
    }).catch(error => ctx.toast(error.message));
  }
  if (action === 'set-location-view') { ctx.state.locationView = button.dataset.view === 'week' ? 'week' : 'today'; if (ctx.state.locationView === 'week') ctx.state.locationWeekDay = ctx.todayIso(); ctx.persist(); ctx.render(); ctx.loadLocationData(ctx.state.locationView).catch(error => ctx.toast(error.message)); }
  if (action === 'set-week-day') { ctx.state.locationWeekDay = button.dataset.date; ctx.persist(); ctx.render(); }
  if (action === 'archive-location-menu') ctx.modal('Archive top places', '<p class="modal-copy">Create an editable location archive directly in Journals and update the top place notes for the selected period.</p><div class="location-archive-actions"><button class="button ghost" data-action="archive-location" data-period="weekly">Archive week</button><button class="button ghost" data-action="archive-location" data-period="monthly">Archive month</button><button class="button" data-action="archive-location" data-period="yearly">Archive year</button></div>', 'close');
  if (action === 'archive-location') { document.querySelector('#modal').close(); ctx.archiveLocationPeriod(button.dataset.period).catch(error => ctx.toast(error.message)); }
  if (action === 'refresh-location') ctx.loadLocationData(ctx.state.locationView).catch(error => ctx.toast(error.message || 'Set up Lifey Location or Traccar first.'));
  return true;
}
