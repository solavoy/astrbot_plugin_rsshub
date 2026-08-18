// 通用组件注册。Vue 3 全局构建，用 template 字符串定义。

const { defineComponent, h } = window.Vue;

export function registerCommonComponents(app) {
  app.component('base-card', defineComponent({
    name: 'BaseCard',
    template: `
      <div class="card" :class="{ 'card-hover': hover }">
        <slot></slot>
      </div>
    `,
    props: { hover: { type: Boolean, default: false } },
  }));

  app.component('base-badge', defineComponent({
    name: 'BaseBadge',
    template: `<span class="badge" :class="badgeClass"><slot></slot></span>`,
    props: { kind: { type: String, default: 'neutral' } },
    computed: {
      badgeClass() {
        return `badge-${this.kind}`;
      },
    },
  }));

  app.component('base-empty', defineComponent({
    name: 'BaseEmpty',
    template: `
      <div class="empty-state">
        <p class="empty-state-title">{{ title }}</p>
        <p v-if="hint" class="empty-state-hint">{{ hint }}</p>
      </div>
    `,
    props: {
      title: { type: String, default: '暂无数据' },
      hint: { type: String, default: '' },
    },
  }));

  app.component('base-search-input', defineComponent({
    name: 'BaseSearchInput',
    template: `
      <div class="page-search">
        <input
          class="page-search-input"
          type="text"
          :placeholder="placeholder"
          :value="modelValue"
          @input="onInput($event.target.value)"
          @keyup.enter="immediate()"
        />
      </div>
    `,
    props: {
      modelValue: { type: String, default: '' },
      placeholder: { type: String, default: '搜索…' },
    },
    emits: ['update:modelValue', 'search'],
    data() {
      return { _timer: null };
    },
    methods: {
      onInput(value) {
        this.$emit('update:modelValue', value);
        clearTimeout(this._timer);
        this._timer = setTimeout(() => this.$emit('search', value.trim()), 300);
      },
      immediate() {
        clearTimeout(this._timer);
        this.$emit('search', (this.modelValue || '').trim());
      },
    },
  }));

  app.component('base-skeleton', defineComponent({
    name: 'BaseSkeleton',
    template: `
      <div class="skeleton-card" v-for="n in count" :key="n">
        <div class="skeleton-line" style="width:60%;height:14px;margin-bottom:12px;"></div>
        <div class="skeleton-line" style="width:100%;height:10px;margin-bottom:8px;"></div>
        <div class="skeleton-line" style="width:80%;height:10px;"></div>
      </div>
    `,
    props: { count: { type: Number, default: 6 } },
  }));

  app.component('base-page-actions', defineComponent({
    name: 'BasePageActions',
    // 页级操作（刷新 + 主题切换），置于各页大卡片头部。
    template: `
      <button class="icon-btn" type="button" title="刷新" aria-label="刷新" @click="store.headerRefresh()">⟳</button>
      <button class="icon-btn" type="button" :title="store.isDark ? '切换浅色' : '切换深色'" :aria-label="store.isDark ? '切换浅色' : '切换深色'" @click="store.toggleTheme()">
        <span v-if="store.isDark">☀️</span>
        <span v-else>🌙</span>
      </button>
    `,
    props: { store: { type: Object, required: true } },
  }));

  app.component('base-toast', defineComponent({
    name: 'BaseToast',
    template: `
      <div class="toast" :class="[store.toast.type, { show: store.toast.show }]" v-if="store.toast.show">
        {{ store.toast.message }}
      </div>
    `,
    props: { store: { type: Object, required: true } },
  }));

  app.component('base-confirm', defineComponent({
    name: 'BaseConfirm',
    template: `
      <div class="confirm-dialog" :class="{ visible: store.confirm.show }" v-if="store.confirm.show" style="display:flex;">
        <div class="confirm-dialog-overlay" @click="store.resolveConfirm(false)"></div>
        <div class="confirm-dialog-content">
          <h4>{{ store.confirm.title }}</h4>
          <p>{{ store.confirm.message }}</p>
          <div class="confirm-dialog-actions">
            <button type="button" class="btn btn-secondary" @click="store.resolveConfirm(false)">取消</button>
            <button type="button" class="btn" :class="store.confirm.okClass" @click="store.resolveConfirm(true)">{{ store.confirm.okText }}</button>
          </div>
        </div>
      </div>
    `,
    props: { store: { type: Object, required: true } },
  }));
}
