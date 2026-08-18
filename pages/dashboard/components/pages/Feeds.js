// Feed 源页：卡片网格 + 批量操作。

const { defineComponent } = window.Vue;

export const Feeds = defineComponent({
  name: 'Feeds',
  template: `
    <section class="table-section">
      <div class="section-header">
        <span class="section-count">共 {{ store.feeds.length }} 个</span>
        <div class="section-header-actions">
          <base-search-input v-model="store.feedsKeyword" placeholder="搜索 Feed…" @search="store.applyFeedSearch" />
          <base-page-actions :store="store" />
        </div>
      </div>

      <div class="subs-toolbar">
        <button
          class="btn"
          :class="store.feedEditMode ? 'btn-primary' : 'btn-secondary'"
          type="button"
          @click="store.toggleFeedEditMode()"
        >{{ store.feedEditMode ? '完成编辑' : '批量操作' }}</button>
        <div v-if="store.feedEditMode && store.selectedFeedIds.length > 0" class="subs-batch">
          <span class="edit-toolbar-count">已选 {{ store.selectedFeedIds.length }} 项</span>
          <button class="btn btn-primary btn-small" type="button" @click="store.refreshSelectedFeeds()">批量刷新</button>
          <button class="btn btn-danger btn-small" type="button" @click="store.deleteSelectedFeeds()">批量删除</button>
        </div>
      </div>

      <div class="grid-cards">
        <base-skeleton v-if="store.feedsLoading" :count="6" />
        <base-empty v-else-if="store.feeds.length === 0" title="暂无 Feed 源" />
        <article
          v-for="f in store.feeds"
          :key="f.id"
          class="sub-card"
          :class="{ selected: store.selectedFeedIds.includes(f.id) }"
          @click="store.feedEditMode ? store.toggleFeedSelection(f.id) : null"
        >
          <div class="sub-card-head">
            <div class="sub-card-main">
              <h3 class="sub-card-title">{{ f.title || '未知' }}</h3>
              <p class="sub-card-url" :title="f.link">{{ f.link || '' }}</p>
            </div>
            <label v-if="store.feedEditMode" class="card-checkbox" @click.stop>
              <input type="checkbox" :checked="store.selectedFeedIds.includes(f.id)" @change="store.toggleFeedSelection(f.id)" />
            </label>
          </div>
          <dl class="sub-card-meta">
            <div><dt>订阅数</dt><dd>{{ f.subscription_count }}</dd></div>
            <div><dt>状态</dt><dd><span class="status-dot" :class="f.state === 1 ? 'active' : 'inactive'"></span> {{ f.state === 1 ? '启用' : '停用' }}</dd></div>
          </dl>
          <div class="sub-card-footer">
            <div class="card-actions">
              <button class="btn btn-text btn-action" type="button" @click.stop="store.handleRefreshFeed(f.id)">刷新</button>
              <button class="btn btn-text btn-action danger" type="button" @click.stop="store.handleDeleteFeed(f)">删除</button>
            </div>
          </div>
        </article>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  mounted() {
    this.store.loadFeeds();
  },
});
