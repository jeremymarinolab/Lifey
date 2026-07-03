export function escape(value) {
  return String(value).replace(/[&<>"']/g, match => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;' })[match]);
}

export function badge(label, kind = '') {
  return `<span class="badge ${kind}">${label}</span>`;
}

export function stat(label, value, meta, tone) {
  return `<div class="stat ${tone || ''}"><span>${label}</span><strong>${value}</strong><small>${meta}</small></div>`;
}
