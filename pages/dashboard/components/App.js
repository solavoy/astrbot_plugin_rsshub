// 根组件：纯左右布局（左侧选项卡片 + 右侧内容卡片），无顶部条。
// 各页标题/操作均在右侧大卡片头部内。

const { defineComponent } = window.Vue;

import { Sidebar } from './Sidebar.js';
import { NAV_GROUPS } from '../store.js';

export const App = defineComponent({
  name: 'App',
  components: { Sidebar },
  template: `
    <div class="dashboard-shell">
      <Sidebar :store="store" :nav-groups="navGroups" />
      <main class="dashboard-main">
        <div class="dashboard-content">
          <keep-alive>
            <component :is="activeComponent" :store="store" />
          </keep-alive>
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
