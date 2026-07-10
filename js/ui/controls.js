import { escape } from '../renderers.js';

function attributes(attrs = {}) {
  return Object.entries(attrs)
    .filter(([, value]) => value !== false && value !== null && value !== undefined)
    .map(([key, value]) => value === true ? ` ${key}` : ` ${key}="${escape(value)}"`)
    .join('');
}

export function button(content, { className = 'button', action = '', attrs = {} } = {}) {
  return `<button${attributes({ class: className, 'data-action': action || null, ...attrs })}>${content}</button>`;
}

export function iconButton(content, { className = '', action = '', title = '', ariaLabel = '', attrs = {} } = {}) {
  return button(content, {
    className: ['icon-button', className].filter(Boolean).join(' '),
    action,
    attrs: { title: title || null, 'aria-label': ariaLabel || title || null, ...attrs }
  });
}

export function segmentedControl(options, { className = 'segmented-control', action, dataKey, selected, ariaLabel = '', selectedWhen } = {}) {
  const items = options.map(option => Array.isArray(option) ? { value: option[0], label: option[1] } : (typeof option === 'object' ? option : { value: option, label: String(option) }));
  const controls = items.map(item => {
    const isSelected = selectedWhen ? selectedWhen(item) : item.value === selected;
    return button(item.label, {
      className: isSelected ? 'selected' : '',
      action,
      attrs: { role: 'tab', 'aria-selected': isSelected ? 'true' : 'false', [`data-${dataKey}`]: item.value }
    });
  }).join('');
  return `<div class="${escape(className)}" role="tablist"${ariaLabel ? ` aria-label="${escape(ariaLabel)}"` : ''}>${controls}</div>`;
}
