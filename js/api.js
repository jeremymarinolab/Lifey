export async function localRequest(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  const data = await response.json().catch(() => {
    throw new Error('Local helper returned invalid JSON.');
  });
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Local helper returned an invalid response.');
  if (!response.ok) throw new Error(typeof data.error === 'string' && data.error ? data.error : 'Local helper request failed.');
  return data;
}
