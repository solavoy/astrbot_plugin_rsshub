// 左侧分组导航组件。

const { defineComponent } = window.Vue;

export const Sidebar = defineComponent({
  name: 'Sidebar',
  template: `
    <aside class="sidebar" aria-label="RSSHub 管理导航">
      <div class="sidebar-title">RSSHub</div>
      <nav class="sidebar-nav">
        <div class="nav-group" v-for="group in navGroups" :key="group.label || 'root'">
          <div v-if="group.label" class="nav-group-label">{{ group.label }}</div>
          <div class="nav-group-items">
            <button
              v-for="item in group.items"
              :key="item.key"
              class="nav-item"
              :class="{ active: store.activeTab === item.key }"
              @click="store.openTab(item.key)"
              type="button"
            >{{ item.label }}</button>
          </div>
        </div>
      </nav>
    </aside>
  `,
  props: {
    store: { type: Object, required: true },
    navGroups: { type: Array, required: true },
  },
});
