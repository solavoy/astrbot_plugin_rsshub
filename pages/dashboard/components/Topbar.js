// 头部组件：仅页面标题。刷新/主题/添加/搜索均已下放到各页大卡片头部。

const { defineComponent } = window.Vue;

export const Topbar = defineComponent({
  name: 'Topbar',
  template: `
    <header class="topbar">
      <h1 class="topbar-title">{{ store.pageTitle() }}</h1>
    </header>
  `,
  props: {
    store: { type: Object, required: true },
  },
});
