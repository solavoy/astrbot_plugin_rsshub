// 左侧分组导航组件。

const { defineComponent } = window.Vue;

export const Sidebar = defineComponent({
  name: 'Sidebar',
  template: `
    <aside class="sidebar" aria-label="RSSHub 管理导航">
      <div class="sidebar-title">RSSHub</div>
      <nav class="sidebar-nav">
        <div class="nav-group" v-for="group in navGroups" :key="group.label || 'root'">
          <button
            v-if="group.label"
            class="nav-group-label"
            :class="{ 'is-collapsed': store.isGroupCollapsed(group.label) }"
            :aria-expanded="!store.isGroupCollapsed(group.label)"
            @click="store.toggleGroup(group.label)"
            type="button"
          >
            <span>{{ group.label }}</span>
            <span class="nav-group-chevron" aria-hidden="true">▾</span>
          </button>
          <div class="nav-group-items" v-show="!store.isGroupCollapsed(group.label)">
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
