export function actionTarget(event) {
  return event.target.closest('[data-action]');
}

export function actionPayload(button) {
  return { action: button.dataset.action, id: button.dataset.id };
}
