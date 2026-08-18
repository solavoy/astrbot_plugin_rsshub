// 根组件：布局骨架（侧边栏 + 头部 + 内容区）。

const { defineComponent } = window.Vue;

import { Sidebar } from './Sidebar.js';
import { Topbar } from './Topbar.js';
import { NAV_GROUPS } from '../store.js';

export const App = defineComponent({
  name: 'App',
  components: { Sidebar, Topbar },
  template: `
    <div class="dashboard-shell">
      <Sidebar :store="store" :nav-groups="navGroups" />
      <main class="dashboard-main">
        <Topbar :store="store" />
        <div class="dashboard-content">
          <div v-if="store.loading" class="dashboard-loading">
            <base-skeleton :count="6" />
          </div>
          <component v-else :is="activeComponent" :store="store" />
        </div>
      </main>
      <base-toast :store="store" />
      <base-confirm :store="store" />
    </div>
  `,
  props: {
    store: { type: Object, required: true },
    pages: { type: Object, required: true },
  },
  data() {
    return { navGroups: NAV_GROUPS };
  },
  computed: {
    activeComponent() {
      const key = this.store.activeTab;
      return this.pages[key] || this.pages.overview;
    },
  },
});
