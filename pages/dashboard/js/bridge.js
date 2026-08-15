// AstrBot Plugin Pages bridge 工具封装。

export function getBridge() {
  return typeof window !== 'undefined' ? window.AstrBotPluginPage || null : null;
}

export function requireBridge() {
  const bridge = getBridge();
  if (!bridge) {
    throw new Error('AstrBotPluginPage bridge not available');
  }
  return bridge;
}

export async function bridgeReady() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const bridge = getBridge();
    if (bridge) {
      return await bridge.ready();
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('AstrBotPluginPage bridge not available');
}

export function isDarkTheme() {
  const bridge = getBridge();
  if (bridge && typeof bridge.getContext === 'function') {
    const ctx = bridge.getContext();
    return !!(ctx && ctx.isDark);
  }
  return (
    typeof document !== 'undefined' &&
    document.documentElement.getAttribute('data-theme') === 'dark'
  );
}

export function setDarkTheme(dark) {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    document.body.classList.toggle('dark-mode', dark);
  }
}

export function onThemeChange(listener) {
  const bridge = getBridge();
  if (bridge && typeof bridge.onContext === 'function') {
    bridge.onContext((ctx) => {
      if (ctx && typeof ctx.isDark === 'boolean') {
        listener(!!ctx.isDark);
      }
    });
  }
}
