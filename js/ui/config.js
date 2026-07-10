export const HERO_METRIC_KEYS = ['tasks', 'projects', 'habits', 'calendar', 'youtube', 'spotify', 'places', 'suggestions'];

export const CARD_KEYS = ['tasks', 'calendar', 'youtube', 'projects', 'suggestions', 'places', 'habits', 'spotify'];

export const HERO_METRIC_LABELS = {
  tasks: 'Tasks',
  projects: 'Projects',
  habits: 'Habits',
  calendar: 'Calendar',
  youtube: 'YouTube',
  spotify: 'Spotify',
  places: 'Places',
  suggestions: 'Inspiration'
};

export const CARD_LABELS = {
  tasks: 'Today’s tasks',
  calendar: 'Day in motion',
  youtube: 'YouTube',
  projects: 'Projects',
  suggestions: 'Inspiration',
  places: 'Where the day went',
  habits: 'Habits',
  spotify: 'Spotify'
};

export const PREFERENCE_TABS = [
  { id: 'integrations', icon: '⌁', label: 'Integrations' },
  { id: 'appearance', icon: '◐', label: 'Appearance' },
  { id: 'habits', icon: '🔥', label: 'Habits' },
  { id: 'archives', icon: '▤', label: 'Archives' },
  { id: 'location', icon: '⌖', label: 'Location' },
  { id: 'profile', icon: '◇', label: 'Profile' }
];

export const APPEARANCE_COLORS = [
  ['background', 'Background'],
  ['glass', 'Card tint'],
  ['accent', 'Accent']
];

export const SUGGESTION_COUNT_OPTIONS = [2, 4, 6];

export const YOUTUBE_SIZE_OPTIONS = [
  ['small', 'Small'],
  ['medium', 'Medium'],
  ['large', 'Large']
];

export const YOUTUBE_VIEW_OPTIONS = [
  ['today', 'Today'],
  ['week', 'This week']
];

export const YOUTUBE_SORT_OPTIONS = [
  ['duration', 'By duration'],
  ['time', 'By time']
];

export const SPOTIFY_VIEW_OPTIONS = [
  ['artists', 'Top artists'],
  ['songs', 'Top songs']
];

export const SPOTIFY_RANGE_OPTIONS = [
  ['today', 'Today'],
  ['week', 'This week'],
  ['month', 'This month']
];

export const HABIT_VIEW_OPTIONS = [
  ['today', 'Today'],
  ['calendar', 'Calendar'],
  ['graph', 'Graph'],
  ['archived', 'Archived']
];

export const HABIT_RANGE_OPTIONS = [
  ['month', 'Month'],
  ['all', 'All time']
];

export const LOCATION_VIEW_OPTIONS = [
  ['today', 'Today'],
  ['week', 'This week']
];

export const HABIT_TIMEZONE_OPTIONS = [
  'America/Guayaquil',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Europe/Madrid',
  'UTC'
];

export const INTEGRATION_ROWS = [
  {
    icon: '◈',
    title: 'Obsidian',
    action: 'setup-local-vault',
    detail: state => state.localVaultPath ? 'Daily notes connected' : 'Choose your daily-notes folder'
  },
  {
    icon: 'N',
    title: 'Notion',
    action: 'setup-notion',
    detail: state => state.notion?.configured ? 'Connected' : 'Create tasks from Obsidian'
  },
  {
    icon: '31',
    title: 'Google Calendar',
    action: 'setup-google',
    detail: state => state.integrations.google?.clientId ? 'Configured' : 'Today’s schedule and task events'
  },
  {
    icon: '⌖',
    title: 'Lifey Location',
    action: 'setup-mobile-location',
    detail: state => state.mobileLocation.configured ? `${state.mobileLocation.samples || 0} point(s) stored` : 'Pair the iPhone companion app'
  },
  {
    icon: '⌖',
    title: 'Google Places',
    action: 'setup-google-places',
    detail: state => state.googlePlaces.configured ? 'Configured' : 'Fallback labels for untagged locations'
  },
  {
    icon: '◒',
    title: 'Spotify',
    action: 'setup-spotify',
    detail: state => state.integrations.spotify?.clientId ? 'Configured' : 'Recent listening and playback'
  },
  {
    icon: '✉',
    title: 'Gmail',
    action: 'setup-gmail',
    detail: state => state.integrations.gmail?.query ? 'Configured' : 'Reading suggestions'
  },
  {
    icon: '⌖',
    title: 'Traccar',
    action: 'setup-traccar',
    detail: state => state.traccar.connected && state.traccar.source === 'Traccar' ? 'Connected' : 'Optional fallback location source'
  }
];
