export const CAPTURE_PRIORITIES = [{ value: '', label: '❗️ Priority' }, { value: '⏫', label: '❗️ ⏫ Highest' }, { value: '🔼', label: '❗️ 🔼 High' }, { value: '🔽', label: '❗️ 🔽 Low' }, { value: '⏬', label: '❗️ ⏬ Lowest' }];
export const CAPTURE_RECURRENCES = ['', 'every day', 'every 2 days', 'every 3 days', 'every week', 'every month', 'every year'];

function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function projectSlug(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function parseClock(hour, minute = '0', period = '') {
  let value = Number(hour);
  const suffix = String(period).replaceAll('.', '').toLowerCase();
  if (suffix === 'pm' && value < 12) value += 12;
  if (suffix === 'am' && value === 12) value = 0;
  return `${String(value).padStart(2, '0')}:${String(minute || '0').padStart(2, '0')}`;
}

function naturalDate(text) {
  const todayDate = new Date(); const weekdays = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']; const months = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
  const countedDays = text.match(/\b(?:in\s+(\d+)\s+days?|(\d+)\s+days?\s+from\s+now)\b/i);
  if (countedDays) { const date = new Date(todayDate); date.setDate(date.getDate() + Number(countedDays[1] || countedDays[2])); return { value: isoDate(date), phrase: countedDays[0] }; }
  const relative = text.match(/\b(the\s+day\s+after\s+tomorrow|tomorrow|today)\b/i);
  if (relative) { const date = new Date(todayDate); date.setDate(date.getDate() + (/day\s+after/i.test(relative[0]) ? 2 : /^tomorrow$/i.test(relative[0]) ? 1 : 0)); return { value: isoDate(date), phrase: relative[0] }; }
  const weekday = text.match(/\bnext\s+(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b/i);
  if (weekday) { const target = weekdays.indexOf(weekday[1].toLowerCase()); let delta = (target - todayDate.getDay() + 7) % 7; if (!delta) delta = 7; const date = new Date(todayDate); date.setDate(date.getDate() + delta); return { value: isoDate(date), phrase: weekday[0] }; }
  const monthFirst = text.match(/\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?\b/i);
  const dayFirst = text.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b/i);
  const match = monthFirst || dayFirst;
  if (!match) return null;
  const month = months.indexOf((monthFirst ? match[1] : match[2]).toLowerCase()), day = Number(monthFirst ? match[2] : match[1]); let year = todayDate.getFullYear(); const date = new Date(year, month, day); if (date < new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate())) date.setFullYear(++year); return { value: isoDate(date), phrase: match[0] };
}

export function parseNaturalTask(raw, controls = {}) {
  let text = String(raw || '').trim(), due = controls.due || '', time = controls.time || '', recurrence = '', priority = controls.priority || '';
  let project = controls.project || '', estimate = '', actualTime = '';
  const explicitDate = text.match(/📅\s*(\d{4}-\d{2}-\d{2})/); if (explicitDate) { due = explicitDate[1]; text = text.replace(explicitDate[0], ' '); }
  const explicitProject = text.match(/#project\/([A-Za-z0-9/_-]+)/i); if (explicitProject) { project = explicitProject[1]; text = text.replace(explicitProject[0], ' '); }
  const naturalProject = !project && text.match(/\b(?:for|on|in)\s+(?:the\s+)?project\s+([A-Za-z0-9][A-Za-z0-9 _/-]*?)(?=\s+(?:estimated time|around|it will take|it took|tomorrow|today|next|at|every|priority|!|#)|$)/i);
  if (naturalProject) { project = naturalProject[1]; text = text.replace(naturalProject[0], ' '); }
  const projectSuffix = text.match(/\bproject\s+([A-Za-z0-9][A-Za-z0-9 _/-]*?)$/i);
  if (!project && projectSuffix) { project = projectSuffix[1]; text = text.replace(projectSuffix[0], ' '); }
  const explicitEstimate = text.match(/\[estimate::\s*([0-9]+(?:\.[0-9]+)?)\]/i); if (explicitEstimate) { estimate = explicitEstimate[1]; text = text.replace(explicitEstimate[0], ' '); }
  const explicitActual = text.match(/\[time::\s*([0-9]+(?:\.[0-9]+)?)\]/i); if (explicitActual) { actualTime = explicitActual[1]; text = text.replace(explicitActual[0], ' '); }
  const estimatePhrase = !estimate && text.match(/\b(?:estimated\s+time|around|it\s+will\s+take|will\s+take|takes?)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:hours?|hrs?|h)?\b/i);
  if (estimatePhrase) { estimate = estimatePhrase[1]; text = text.replace(estimatePhrase[0], ' '); }
  const actualPhrase = !actualTime && text.match(/\b(?:it\s+took|took|actual(?:ly)?\s+took)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:hours?|hrs?|h)?\b/i);
  if (actualPhrase) { actualTime = actualPhrase[1]; text = text.replace(actualPhrase[0], ' '); }
  const foundDate = naturalDate(text); if (foundDate) { due = foundDate.value; text = text.replace(foundDate.phrase, ' '); }
  const explicitTime = text.match(/⏰\s*([01]?\d|2[0-3]):([0-5]\d)(?:\s*(?:-|–|to)\s*([01]?\d|2[0-3]):([0-5]\d))?/); if (explicitTime) { time = `${String(explicitTime[1]).padStart(2, '0')}:${explicitTime[2]}${explicitTime[3] ? `–${String(explicitTime[3]).padStart(2, '0')}:${explicitTime[4]}` : ''}`; text = text.replace(explicitTime[0], ' '); }
  const recurring = text.match(/\bevery\s+(?:(\d+)\s+)?(days?|weeks?|months?|years?)\b/i);
  if (recurring) { recurrence = `every ${recurring[1] ? `${recurring[1]} ` : ''}${recurring[2].toLowerCase()}`; text = text.replace(recurring[0], ' '); }
  if (controls.recurring && !recurrence) recurrence = controls.recurring;
  const meridiemTime = text.match(/\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?:\s*(?:-|–|to)\s*(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?)?\b/i);
  const twentyFourTime = !meridiemTime && text.match(/\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)(?:\s*(?:-|–|to)\s*([01]?\d|2[0-3]):([0-5]\d))?\b/i);
  if (meridiemTime) { const detected = `${parseClock(meridiemTime[1], meridiemTime[2], meridiemTime[3])}${meridiemTime[4] ? `–${parseClock(meridiemTime[4], meridiemTime[5], meridiemTime[6] || meridiemTime[3])}` : ''}`; time = detected; text = text.replace(meridiemTime[0], ' '); }
  else if (twentyFourTime) { const detected = `${parseClock(twentyFourTime[1], twentyFourTime[2])}${twentyFourTime[3] ? `–${parseClock(twentyFourTime[3], twentyFourTime[4])}` : ''}`; time = detected; text = text.replace(twentyFourTime[0], ' '); }
  const milestone = /#milestone\b/i.test(text); if (milestone) text = text.replace(/#milestone\b/ig, ' ');
  const priorityEmoji = text.match(/[⏫🔼🔽⏬]/); const foundPriority = text.match(/(?:\bpriority\s*(highest|high|low|lowest)?\b|!(highest|high|low|lowest)?\b)/i); if (priorityEmoji) { priority = priorityEmoji[0]; text = text.replace(priorityEmoji[0], ' '); } else if (foundPriority) { const value = (foundPriority[1] || foundPriority[2] || 'highest').toLowerCase(); priority = ({ highest: '⏫', high: '🔼', low: '🔽', lowest: '⏬' })[value]; text = text.replace(foundPriority[0], ' '); }
  text = text.replace(/\s{2,}/g, ' ').trim().replace(/[,.]$/, '');
  const projectTag = project ? `#project/${projectSlug(project)}` : '';
  const metadata = [projectTag, milestone && '#milestone', estimate && `[estimate:: ${estimate}]`, actualTime && `[time:: ${actualTime}]`, due && `📅 ${due}`, time && `⏰ ${time}`, priority, recurrence && `🔁 ${recurrence}`].filter(Boolean);
  return { text: [text, ...metadata].filter(Boolean).join(' '), due, time, priority, recurrence, project: projectTag, estimate, actualTime, milestone };
}

export function taskCaptureValues(task) {
  let text = String(task?.text || '');
  const due = text.match(/📅\s*(\d{4}-\d{2}-\d{2})/);
  const time = text.match(/⏰\s*([01]?\d|2[0-3]):([0-5]\d)(?:\s*(?:-|–|to)\s*[01]?\d:[0-5]\d)?/);
  const priority = text.match(/[⏫🔼🔽⏬]/);
  const recurring = text.match(/🔁\s*(every\s+(?:(?:\d+)\s+)?(?:days?|weeks?|months?|years?))/i);
  const project = text.match(/#project\/([A-Za-z0-9/_-]+)/i);
  text = text.replace(/#project\/[A-Za-z0-9/_-]+/gi, '').replace(/📅\s*\d{4}-\d{2}-\d{2}/g, '').replace(/⏰\s*[01]?\d:[0-5]\d(?:\s*(?:-|–|to)\s*[01]?\d:[0-5]\d)?/g, '').replace(/[⏫🔼🔽⏬]/g, '').replace(/🔁\s*every\s+(?:(?:\d+)\s+)?(?:days?|weeks?|months?|years?)/gi, '').replace(/\s{2,}/g, ' ').trim();
  return { text, due: due?.[1] || '', time: time ? `${String(time[1]).padStart(2, '0')}:${time[2]}` : '', priority: priority?.[0] || '', recurrence: recurring?.[1]?.toLowerCase() || '', project: project?.[1] || '' };
}

export function captureDayTimeLabel(dateValue, timeValue) {
  if (!dateValue && !timeValue) return '📅 ⏰ Day & time';
  const date = dateValue ? new Date(`${dateValue}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' }) : 'Day';
  return `📅 ${date} · ⏰ ${timeValue || 'Time'}`;
}

export function capturePriorityLabel(value) {
  return CAPTURE_PRIORITIES.find(option => option.value === value)?.label || '❗️ Priority';
}

export function captureRecurringLabel(value) {
  return value ? `🔁 ${value.replace(/^every\s/, 'Every ')}` : '🔁 Recurring';
}
