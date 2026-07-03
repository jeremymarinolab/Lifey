const PROJECT_ACTIONS = new Set([
  'refresh-projects',
  'open-project',
  'project-capture',
  'open-project-note',
  'create-project-note',
  'toggle-project-task',
  'edit-project-task'
]);

export function handleProjectAction(action, button, ctx) {
  if (!PROJECT_ACTIONS.has(action)) return false;
  if (action === 'refresh-projects') ctx.loadProjects().catch(error => ctx.toast(error.message));
  if (action === 'open-project') {
    const slug = button.dataset.projectSlug;
    ctx.state.projects.expandedSlug = ctx.state.projects.expandedSlug === slug ? '' : slug;
    ctx.persist();
    ctx.render();
  }
  if (action === 'project-capture') {
    const slug = button.dataset.projectSlug;
    document.querySelector('#modal')?.close();
    ctx.quickCaptureModal(null, { projectSlug: slug });
  }
  if (action === 'open-project-note') ctx.openProjectNote(button.dataset.projectSlug).catch(error => ctx.toast(error.message));
  if (action === 'create-project-note') ctx.createProjectNote(button.dataset.projectSlug, button.dataset.projectTitle).then(() => ctx.toast('Project note created from template.')).catch(error => ctx.toast(error.message));
  if (action === 'toggle-project-task') {
    const task = { source: button.dataset.source, line: Number(button.dataset.line), raw: button.dataset.raw };
    ctx.updateProjectTask(task, { completed: button.dataset.completed !== 'true' }).catch(error => ctx.toast(error.message));
  }
  if (action === 'edit-project-task') {
    const task = { source: button.dataset.source, line: Number(button.dataset.line), raw: button.dataset.raw, text: button.dataset.raw, projectTask: true };
    window.editingProjectTask = task;
    document.querySelector('#modal')?.close();
    ctx.quickCaptureModal(task, { projectSlug: button.dataset.projectSlug });
  }
  return true;
}
