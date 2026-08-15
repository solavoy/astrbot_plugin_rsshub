// RSSHub 管理面板入口。
// 零构建：Vue 3 全局构建 + Chart UMD + 原生 CSS + AstrBot bridge。

import { bridgeReady, setDarkTheme, isDarkTheme, onThemeChange } from './js/bridge.js';
import { store } from './store.js';
import { registerCommonComponents } from './components/common/base.js';
import { App } from './components/App.js';

// 各页组件
import { Overview } from './components/pages/Overview.js';
import { Subscriptions } from './components/pages/Subscriptions.js';
import { Feeds } from './components/pages/Feeds.js';
import { Users } from './components/pages/Users.js';
import { Lists } from './components/pages/Lists.js';
import { PushHistory } from './components/pages/PushHistory.js';
import { Settings } from './components/pages/Settings.js';
import { DataManagement } from './components/pages/DataManagement.js';

const { createApp, watch } = window.Vue;

// 主题初始化
setDarkTheme(isDarkTheme());
onThemeChange((dark) => {
  store.isDark = dark;
  setDarkTheme(dark);
});
// 顶栏切换（store.toggleTheme 翻转 isDark）同步到 DOM data-theme
watch(() => store.isDark, (dark) => setDarkTheme(dark));

async function init() {
  try {
    await bridgeReady();
  } catch (err) {
    // 无 bridge 时仍渲染 UI，数据操作会提示错误
    console.warn('bridge not ready:', err.message);
  }

  const pages = {
    overview: Overview,
    subs: Subscriptions,
    feeds: Feeds,
    users: Users,
    lists: Lists,
    'push-history': PushHistory,
    settings: Settings,
    'data-management': DataManagement,
  };

  const headerConfig = {
    overview: { search: false, add: false },
    subs: { search: true, add: true, searchPlaceholder: '搜索订阅…' },
    feeds: { search: true, add: false, searchPlaceholder: '搜索 Feed…' },
    users: { search: true, add: false, searchPlaceholder: '搜索用户…' },
    lists: { search: false, add: true },
    'push-history': { search: true, add: false, searchPlaceholder: '搜索推送历史…' },
    settings: { search: false, add: false },
    'data-management': { search: false, add: false },
  };

  const app = createApp(App, { store, pages, headerConfig });
  registerCommonComponents(app);
  app.mount('#app');
}

init();
