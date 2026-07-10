export function parseTasks(markdown, source, taskMappings = {}) {
  const lines = markdown.split('\n');
  const habitStart = lines.findIndex(line => /^(?:#{1,6}\s*)?Habits::\s*$/i.test(line.trim()));
  const habitEnd = habitStart < 0 ? -1 : lines.findIndex((line, index) => index > habitStart && /^#{1,6}\s+/.test(line));
  const inHabitSection = index => habitStart >= 0 && index > habitStart && (habitEnd < 0 || index < habitEnd);
  return lines.flatMap((line, index) => {
    if (inHabitSection(index)) return [];
    const match = line.match(/^\s*-\s+\[([ xX])\]\s+(.+)/);
    if (!match) return [];
    const mapping = taskMappings[`${source}:${index + 1}`] || {};
    return [{
      id: `obs-${source}-${index}`,
      text: match[2].trim(),
      source,
      line: index + 1,
      done: match[1].toLowerCase() === 'x',
      notion: Boolean(mapping.notionPageId),
      notionPageId: mapping.notionPageId || '',
      notionUrl: mapping.notionUrl || '',
      calendar: Boolean(mapping.calendarEventId),
      calendarEventId: mapping.calendarEventId || ''
    }];
  });
}
