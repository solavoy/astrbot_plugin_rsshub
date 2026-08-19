// 用户页：卡片网格 + 批量删除。

const { defineComponent } = window.Vue;

export const Users = defineComponent({
  name: 'Users',
  template: `
    <section class="table-section">
      <div class="section-header">
        <div class="section-header-titles">
          <h2 class="section-title">{{ store.pageTitle() }}</h2>
          <span class="section-count">共 {{ store.users.length }} 个</span>
        </div>
        <div class="section-header-actions">
          <base-search-input v-model="store.usersKeyword" placeholder="搜索用户…" @search="store.applyUserSearch" />
          <base-page-actions :store="store" />
        </div>
      </div>

      <div class="subs-toolbar">
        <button
          class="btn"
          :class="store.userEditMode ? 'btn-primary' : 'btn-secondary'"
          type="button"
          @click="store.toggleUserEditMode()"
        >{{ store.userEditMode ? '完成编辑' : '批量操作' }}</button>
        <div v-if="store.userEditMode && store.selectedUserIds.length > 0" class="subs-batch">
          <span class="edit-toolbar-count">已选 {{ store.selectedUserIds.length }} 项</span>
          <button class="btn btn-danger btn-small" type="button" @click="store.deleteSelectedUsers()">批量删除</button>
        </div>
      </div>

      <div class="grid-cards">
        <base-skeleton v-if="store.usersLoading" :count="6" />
        <base-empty v-else-if="store.users.length === 0" title="暂无用户数据" />
        <article
          v-for="u in store.users"
          :key="u.user_id"
          class="sub-card"
          :class="{ selected: store.selectedUserIds.includes(u.user_id) }"
          @click="store.userEditMode ? store.toggleUserSelection(u.user_id) : null"
        >
          <div class="sub-card-head">
            <div class="sub-card-main">
              <h3 class="sub-card-title cell-mono" :title="u.user_id">{{ u.user_id }}</h3>
            </div>
            <label v-if="store.userEditMode" class="card-checkbox" @click.stop>
              <input type="checkbox" :checked="store.selectedUserIds.includes(u.user_id)" @change="store.toggleUserSelection(u.user_id)" />
            </label>
          </div>
          <dl class="sub-card-meta">
            <div><dt>状态</dt><dd><span class="badge" :class="u.state >= 0 ? 'badge-active' : 'badge-failed'">{{ userStateText(u) }}</span></dd></div>
            <div><dt>订阅数</dt><dd>{{ u.subscription_count || u.total || 0 }}</dd></div>
          </dl>
          <div class="sub-card-footer">
            <div class="card-actions">
              <button class="btn btn-text btn-action danger" type="button" @click.stop="store.handleDeleteUser(u)">删除</button>
            </div>
          </div>
        </article>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  mounted() {
    this.store.loadUsers();
  },
  methods: {
    userStateText(u) {
      return Number(u.state) < 0 ? '已封禁' : '用户';
    },
  },
});
