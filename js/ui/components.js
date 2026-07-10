import { escape } from '../renderers.js';
import { button } from './controls.js';

export function emptyState(message, className = 'muted') {
  return `<p class="${escape(['empty-state', className].filter(Boolean).join(' '))}" data-ui="empty-state">${escape(message)}</p>`;
}

export function panelCard({ key, className = '', hidden = false, order = '', eyebrow = '', title = '', meta = '', status = '', body = '', footer = '' }) {
  const classes = ['panel', className, hidden ? 'hidden-by-preference' : ''].filter(Boolean).join(' ');
  const header = eyebrow || title || meta || status
    ? `<header><div>${eyebrow ? `<p class="eyebrow">${escape(eyebrow)}</p>` : ''}${title ? `<h2>${title}</h2>` : ''}${meta ? `<small class="youtube-card-meta">${meta}</small>` : ''}</div>${status || ''}</header>`
    : '';
  return `<section class="${escape(classes)}" data-card-key="${escape(key)}" ${order}>${header}${body}${footer ? `<footer>${footer}</footer>` : ''}</section>`;
}

export function preferenceSection({ className = '', eyebrow = '', title = '', copy = '', body = '' }) {
  return `<section class="${escape(['appearance-section', className].filter(Boolean).join(' '))}"><div>${eyebrow ? `<p class="eyebrow">${escape(eyebrow)}</p>` : ''}${title ? `<h3>${escape(title)}</h3>` : ''}${copy ? `<p>${copy}</p>` : ''}</div>${body}</section>`;
}

export function preferenceHead(eyebrow, title, copy = '') {
  return `<div class="preferences-head"><p class="eyebrow">${escape(eyebrow)}</p><h2>${escape(title)}</h2>${copy ? `<p>${copy}</p>` : ''}</div>`;
}

export function integrationRow({ icon, title, detail, action, className = '' }) {
  return button(`<span class="integration-logo">${escape(icon)}</span><span><strong>${escape(title)}</strong><small>${escape(detail)}</small></span><i>›</i>`, {
    className: ['integration-row', className].filter(Boolean).join(' '),
    action
  });
}
