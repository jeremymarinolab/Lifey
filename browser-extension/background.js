const api = globalThis.browser ?? globalThis.chrome;
const ENDPOINT = 'http://127.0.0.1:4173/api/activity/youtube';

async function ping() { try { await fetch(`${ENDPOINT}/ping`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch {} }

async function queued() { return (await api.storage.local.get('youtubeQueue')).youtubeQueue || []; }
async function saveQueue(queue) { await api.storage.local.set({ youtubeQueue: queue.slice(-100) }); }
async function send(payload) {
  const response = await fetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  if (!response.ok) throw new Error(`Local helper returned ${response.status}`);
}
async function flush() {
  const queue = await queued(); const remaining = [];
  for (const payload of queue) { try { await send(payload); } catch { remaining.push(payload); } }
  await saveQueue(remaining);
}
api.runtime.onMessage.addListener(async message => {
  if (message?.type !== 'youtube-activity') return;
  try { await flush(); await send(message.payload); }
  catch { const queue = await queued(); queue.push(message.payload); await saveQueue(queue); }
});
ping();
setInterval(ping, 30000);
