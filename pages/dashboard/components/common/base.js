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
