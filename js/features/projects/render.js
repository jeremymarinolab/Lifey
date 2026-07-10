import { escape } from '../../renderers.js';
import { emptyState } from '../../ui/components.js';
import { button, iconButton } from '../../ui/controls.js';

export function hoursLabel(hours) {
  const value = Number(hours || 0);
  if (!value) return '0h';
  const whole = Math.floor(value), minutes = Math.round((value - whole) * 60);
  return whole && minutes ? `${whole}h ${minutes}m` : whole ? `${whole}h` : `${minutes}m`;
}

function projectTaskList(tasks = []) {
  return tasks.length ? `<ol class="project-detail-tasks">${tasks.map(task => `<li class="${task.done ? 'done' : ''} ${task.milestone ? 'milestone' : ''}">${button(task.done ? '✓' : '', { className: 'check', action: 'toggle-project-task', attrs: { 'data-source': task.source, 'data-line': task.line, 'data-raw': task.raw, 'data-completed': task.done ? 'true' : 'false' } })}<p>${task.milestone ? '<b>◆</b> ' : ''}${escape(task.text || task.raw)}<small>${escape(task.date)} · L${task.line}${task.estimate ? ` · estimated ${hoursLabel(task.estimate)}` : ''}${task.time ? ` · took ${hoursLabel(task.time)}` : ''}</small></p>${iconButton('✎', { action: 'edit-project-task', title: 'Edit project task', attrs: { 'data-source': task.source, 'data-line': task.line, 'data-raw': task.raw, 'data-project-slug': task.projectSlug } })}</li>`).join('')}</ol>` : emptyState('Nothing here yet.', 'muted project-empty');
}

function projectDetail(project, progress = null) {
  const tasks = project.tasks || [];
  const milestones = tasks.filter(task => task.milestone && !task.done);
  const active = tasks.filter(task => !task.milestone && !task.done);
  const completed = tasks.filter(task => task.done);
  const percent = progress ?? (project.taskCount ? Math.round(project.completedCount / project.taskCount * 100) : 0);
  return `<section class="project-detail"><div class="project-progress"><i style="width:${percent}%"></i></div><div class="project-metrics"><span><b>${project.openCount}</b><small>open tasks</small></span><span><b>${project.milestoneCompleted}/${project.milestoneCount}</b><small>milestones</small></span><span><b>${hoursLabel(project.timeTotal)}</b><small>time so far</small></span><span><b>${hoursLabel(project.estimateTotal)}</b><small>estimated</small></span></div><section><h3>Milestones</h3>${projectTaskList(milestones)}</section><section><h3>Active tasks</h3>${projectTaskList(active)}</section><details class="project-completed" ${completed.length ? 'open' : ''}><summary>Completed tasks <span>${completed.length}</span></summary>${projectTaskList(completed)}</details><footer>${button('＋ Add project task', { action: 'project-capture', attrs: { 'data-project-slug': project.slug } })}${project.path ? button('Open note', { className: 'button ghost', action: 'open-project-note', attrs: { 'data-project-slug': project.slug } }) : button('Create note', { className: 'button ghost', action: 'create-project-note', attrs: { 'data-project-slug': project.slug, 'data-project-title': project.title } })}${button('↻ Refresh', { className: 'button ghost', action: 'refresh-projects' })}</footer></section>`;
}

export function renderProjectCard(project, { expandedSlug = '' } = {}) {
  const progress = project.taskCount ? Math.round(project.completedCount / project.taskCount * 100) : 0;
  const expanded = expandedSlug === project.slug;
  return `<article class="project-card ${expanded ? 'expanded' : ''}">
    <button class="project-card-summary" data-action="open-project" data-project-slug="${escape(project.slug)}" aria-expanded="${expanded ? 'true' : 'false'}">
      <strong>${escape(project.title)}</strong><b>${progress}%</b>
    </button>
    ${expanded ? projectDetail(project, progress) : ''}
  </article>`;
}
