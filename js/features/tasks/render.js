import { escape } from '../../renderers.js';
import { button, iconButton } from '../../ui/controls.js';

export function renderTaskCard(task, { showPath = false } = {}) {
  return `<article class="task ${task.done ? 'done' : ''}" data-task-card-id="${escape(task.id)}">
    ${button(task.done ? '✓' : '', { className: 'check', action: 'toggle-task', attrs: { 'data-id': task.id, 'aria-label': 'Toggle task' } })}
    <div class="task-copy"><p>${escape(task.text)}</p><small data-task-meta data-source="${escape(task.source)}" data-line="${task.line}">${showPath ? `${escape(task.source)} · ` : ''}L${task.line}</small></div>
    <div class="task-actions">
      ${iconButton('×', { className: 'task-delete', title: 'Delete task', ariaLabel: 'Delete task', action: 'delete-task', attrs: { 'data-id': task.id } })}
      ${iconButton('✎', { title: 'Edit task', ariaLabel: 'Edit task', action: 'edit-task', attrs: { 'data-id': task.id } })}
      ${iconButton('N', { className: task.notion ? 'active' : '', title: 'Send to Notion', action: 'notion', attrs: { 'data-id': task.id } })}
      ${iconButton(task.calendar ? '−' : '＋', { className: task.calendar ? 'active' : '', title: task.calendar ? 'Remove Calendar event' : 'Add to calendar', ariaLabel: task.calendar ? 'Remove Calendar event' : 'Add to calendar', action: task.calendar ? 'remove-calendar' : 'calendar', attrs: { 'data-id': task.id } })}
    </div>
  </article>`;
}

function normalisePlaceName(name = '') {
  return String(name).toLowerCase().replace(/^place\s*-\s*["“”']?|["“”']$/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

function taskPlaceNames(task) {
  return [...String(task?.text || '').matchAll(/\bat\s+\[\[([^\]]+)\]\]/gi)].map(match => normalisePlaceName(match[1])).filter(Boolean);
}

function latestCurrentPlace(places = []) {
  const now = Date.now();
  return [...places].filter(place => place?.name).map(place => {
    const points = Array.isArray(place.points) ? place.points : [];
    const pointTime = points.map(point => new Date(point.timestamp || point.time || point.lastSeen || 0).getTime()).filter(Number.isFinite).sort((a, b) => b - a)[0];
    const end = pointTime || new Date(place.departure || place.lastSeen || place.arrival || 0).getTime();
    return { place, end: Number.isFinite(end) ? end : 0 };
  }).filter(item => item.end && now - item.end <= 45 * 60 * 1000).sort((a, b) => b.end - a.end)[0]?.place || null;
}

export function tasksForCurrentPlace(tasks, places) {
  const current = latestCurrentPlace(places);
  if (!current) return { currentPlace: null, tasks: [] };
  const currentName = normalisePlaceName(current.name);
  return { currentPlace: current, tasks: tasks.filter(task => taskPlaceNames(task).includes(currentName)) };
}
