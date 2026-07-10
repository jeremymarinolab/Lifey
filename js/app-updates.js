export const LAST_LOADED_VERSION_KEY = 'lifey:last-loaded-asset-version';
export const RELOAD_TARGET_KEY = 'lifey:update-reload-target';
export const SHELL_CACHE_PREFIX = 'lifey-shell-v';

export function isLifeyShellCache(name) {
  return typeof name === 'string' && name.startsWith(SHELL_CACHE_PREFIX);
}

export function updateDecision({ loadedVersion, workerVersion, reloadTarget = '', hasUnsavedCapture = false }) {
  if (!workerVersion || workerVersion === loadedVersion) return 'current';
  if (reloadTarget === workerVersion) return 'recovery';
  return hasUnsavedCapture ? 'prompt' : 'reload';
}

export function loadedAssetVersion(documentObject = globalThis.document) {
  return documentObject?.querySelector?.('meta[name="lifey-asset-version"]')?.content?.trim() || 'unknown';
}

function storageGet(storage, key) {
  try { return storage?.getItem?.(key) || ''; } catch { return ''; }
}

function storageSet(storage, key, value) {
  try { storage?.setItem?.(key, value); } catch {}
}

function storageRemove(storage, key) {
  try { storage?.removeItem?.(key); } catch {}
}

export function createAppUpdateManager(options = {}) {
  const windowObject = options.windowObject || globalThis.window;
  const documentObject = options.documentObject || globalThis.document;
  const navigatorObject = options.navigatorObject || globalThis.navigator;
  const localStore = options.localStore || globalThis.localStorage;
  const sessionStore = options.sessionStore || globalThis.sessionStorage;
  const cacheStorage = options.cacheStorage || globalThis.caches;
  const setTimer = options.setTimer || globalThis.setTimeout;
  const clearTimer = options.clearTimer || globalThis.clearTimeout;
  const reload = options.reload || (() => windowObject?.location?.reload?.());
  const autoReloadDelay = Number(options.autoReloadDelay ?? 1000);
  const loadedVersion = options.loadedVersion || loadedAssetVersion(documentObject);
  const listeners = new Set();
  let registration = null;
  let reloadTimer = null;
  let workerVersion = '';
  let status = navigatorObject?.serviceWorker ? 'checking' : 'unsupported';

  function snapshot() {
    return {
      loadedVersion,
      workerVersion,
      previousVersion: storageGet(localStore, LAST_LOADED_VERSION_KEY),
      status,
    };
  }

  function notify() {
    const current = snapshot();
    for (const listener of listeners) listener(current);
    return current;
  }

  function hasUnsavedCapture() {
    const input = documentObject?.querySelector?.('#capture-task');
    return Boolean(input && String(input.value || '').trim());
  }

  function removeBanner() {
    documentObject?.querySelector?.('#app-update-banner')?.remove?.();
  }

  function reloadToVersion(targetVersion) {
    if (!targetVersion) return;
    if (reloadTimer) clearTimer?.(reloadTimer);
    storageSet(sessionStore, RELOAD_TARGET_KEY, targetVersion);
    reload();
  }

  function renderBanner(kind, targetVersion) {
    if (!documentObject?.body) return;
    removeBanner();
    const banner = documentObject.createElement('aside');
    banner.id = 'app-update-banner';
    banner.className = `app-update-banner ${kind}`;
    banner.setAttribute('role', kind === 'recovery' ? 'alert' : 'status');
    banner.setAttribute('aria-live', 'polite');
    const copy = kind === 'recovery'
      ? '<strong>Lifey could not finish updating.</strong><span>Clear the saved app shell and reload from this Mac.</span>'
      : '<strong>A new Lifey version is ready.</strong><span>Lifey will reload once to use it.</span>';
    banner.innerHTML = `<div>${copy}</div><button type="button" data-update-action="${kind === 'recovery' ? 'clear' : 'reload'}">${kind === 'recovery' ? 'Clear cache and reload' : 'Reload now'}</button>`;
    banner.querySelector('[data-update-action="reload"]')?.addEventListener('click', () => reloadToVersion(targetVersion));
    banner.querySelector('[data-update-action="clear"]')?.addEventListener('click', () => clearAppCacheAndReload());
    documentObject.body.appendChild(banner);
  }

  function acceptWorkerVersion(targetVersion) {
    if (!targetVersion) return snapshot();
    workerVersion = targetVersion;
    const reloadTarget = storageGet(sessionStore, RELOAD_TARGET_KEY);
    const decision = updateDecision({ loadedVersion, workerVersion, reloadTarget, hasUnsavedCapture: hasUnsavedCapture() });
    if (decision === 'current') {
      status = 'current';
      storageSet(localStore, LAST_LOADED_VERSION_KEY, loadedVersion);
      if (reloadTarget === loadedVersion) storageRemove(sessionStore, RELOAD_TARGET_KEY);
      removeBanner();
    } else if (decision === 'recovery') {
      status = 'recovery';
      renderBanner('recovery', targetVersion);
    } else {
      status = 'update-ready';
      renderBanner('ready', targetVersion);
      if (decision === 'reload') {
        if (reloadTimer) clearTimer?.(reloadTimer);
        reloadTimer = setTimer?.(() => reloadToVersion(targetVersion), autoReloadDelay);
      }
    }
    return notify();
  }

  function requestWorkerVersion() {
    const worker = navigatorObject?.serviceWorker?.controller || registration?.active || registration?.waiting || registration?.installing;
    worker?.postMessage?.({ type: 'LIFEY_GET_VERSION' });
  }

  function handleWorkerMessage(event) {
    if (!['LIFEY_VERSION', 'LIFEY_ACTIVATED'].includes(event?.data?.type)) return;
    acceptWorkerVersion(String(event.data.version || ''));
  }

  async function checkForUpdates() {
    if (!navigatorObject?.serviceWorker) {
      status = 'unsupported';
      return notify();
    }
    status = 'checking';
    notify();
    registration ||= await navigatorObject.serviceWorker.getRegistration?.();
    await registration?.update?.();
    requestWorkerVersion();
    await new Promise(resolve => (setTimer || globalThis.setTimeout)(resolve, 180));
    return snapshot();
  }

  async function clearAppCacheAndReload() {
    if (reloadTimer) clearTimer?.(reloadTimer);
    const keys = await cacheStorage?.keys?.() || [];
    await Promise.all(keys.filter(isLifeyShellCache).map(key => cacheStorage.delete(key)));
    storageRemove(sessionStore, RELOAD_TARGET_KEY);
    try { await registration?.update?.(); } catch {}
    reload();
  }

  async function init() {
    storageSet(localStore, LAST_LOADED_VERSION_KEY, loadedVersion);
    const existingTarget = storageGet(sessionStore, RELOAD_TARGET_KEY);
    if (existingTarget === loadedVersion) storageRemove(sessionStore, RELOAD_TARGET_KEY);
    if (!navigatorObject?.serviceWorker) {
      status = 'unsupported';
      return notify();
    }
    navigatorObject.serviceWorker.addEventListener?.('message', handleWorkerMessage);
    navigatorObject.serviceWorker.addEventListener?.('controllerchange', requestWorkerVersion);
    try {
      registration = await navigatorObject.serviceWorker.register('./service-worker.js', { updateViaCache: 'none' });
      registration.addEventListener?.('updatefound', () => {
        status = 'checking';
        notify();
      });
      await registration.update?.();
      requestWorkerVersion();
    } catch {
      status = 'unsupported';
      notify();
    }
    return snapshot();
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return {
    init,
    status: snapshot,
    subscribe,
    checkForUpdates,
    clearAppCacheAndReload,
    acceptWorkerVersion,
    reloadToVersion,
  };
}

export const appUpdates = createAppUpdateManager();
