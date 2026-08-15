// 头部组件：标题 + 全局搜索 + 添加按钮 + 刷新 + 主题切换。

const { defineComponent } = window.Vue;

export const Topbar = defineComponent({
  name: 'Topbar',
  template: `
    <header class="topbar">
      <h1 class="topbar-title">{{ store.pageTitle() }}</h1>
      <div class="topbar-actions">
        <input
          v-if="showSearch"
          class="topbar-search"
          type="text"
          :placeholder="searchPlaceholder"
          v-model="searchQuery"
          @input="$emit('search', searchQuery)"
          @keyup.enter="$emit('search', searchQuery)"
        />
        <button
          v-if="showAdd"
          class="btn btn-primary"
          type="button"
          @click="$emit('add')"
        >+ 添加</button>
        <button class="icon-btn" type="button" title="刷新" aria-label="刷新" @click="$emit('refresh')">⟳</button>
        <button class="icon-btn" type="button" :title="store.isDark ? '切换浅色' : '切换深色'" :aria-label="store.isDark ? '切换浅色' : '切换深色'" @click="store.toggleTheme()">
          <span v-if="store.isDark">☀️</span>
          <span v-else>🌙</span>
        </button>
      </div>
    </header>
  `,
  props: {
    store: { type: Object, required: true },
    showSearch: { type: Boolean, default: false },
    showAdd: { type: Boolean, default: false },
    searchPlaceholder: { type: String, default: '搜索…' },
  },
  data() {
    return { searchQuery: '' };
  },
  emits: ['search', 'add', 'refresh'],
});
