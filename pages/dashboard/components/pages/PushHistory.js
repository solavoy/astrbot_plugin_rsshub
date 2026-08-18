// 推送历史页：卡片化表格 + 状态筛选 + 重试/删除。

const { defineComponent } = window.Vue;

export const PushHistory = defineComponent({
  name: 'PushHistory',
  template: `
    <section class="table-section">
      <div class="section-header">
        <span class="section-count">共 {{ store.pushHistoryTotal }} 条</span>
        <div class="section-header-actions">
          <base-search-input v-model="store.pushHistoryKeyword" placeholder="搜索推送历史…" @search="store.applyHistorySearch" />
          <base-page-actions :store="store" />
        </div>
      </div>

      <div class="subs-toolbar">
        <select class="select-input" v-model="store.pushHistoryStatus" @change="store.setHistoryStatus(store.pushHistoryStatus)">
          <option value="">全部状态</option>
          <option value="success">成功</option>
          <option value="failed">失败</option>
          <option value="pending">待推送</option>
          <option value="retrying">重试中</option>
          <option value="skipped">已跳过</option>
          <option value="stopped">已停止</option>
        </select>
        <div v-if="store.pushHistoryTotal > store.pushHistoryPageSize" class="pagination-actions">
          <button class="btn btn-secondary btn-small" :disabled="store.pushHistoryPage <= 1" @click="store.historyPrevPage()">上一页</button>
          <span class="page-indicator">{{ store.pushHistoryPage }} / {{ totalPages }}</span>
          <button class="btn btn-secondary btn-small" :disabled="store.pushHistoryPage * store.pushHistoryPageSize >= store.pushHistoryTotal" @click="store.historyNextPage()">下一页</button>
        </div>
      </div>

      <div class="table-card">
        <div class="table-scroll-area">
          <base-empty v-if="store.pushHistoryLoading" title="加载中…" />
          <base-empty v-else-if="store.pushHistory.length === 0" title="暂无推送历史" />
          <table class="sub-table history-table" v-else>
            <thead>
              <tr>
                <th>状态</th>
                <th>用户</th>
                <th>条目</th>
                <th>目标会话</th>
                <th>错误</th>
                <th>重试</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in store.pushHistory" :key="h.id">
                <td><span class="badge" :class="statusClass(h.status)">{{ statusText(h.status) }}</span></td>
                <td class="cell-mono" :title="h.user_id">{{ h.user_id }}</td>
                <td><div class="feed-title">{{ h.entry_title || '无标题' }}</div><div class="feed-url" :title="h.entry_link">{{ h.feed_title || '' }}</div></td>
                <td class="cell-mono" :title="h.target_session">{{ h.target_session || '-' }}</td>
                <td class="cell-wrap" :title="h.fail_reason || ''">{{ h.fail_reason || '-' }}</td>
                <td>{{ h.retry_count }}/{{ h.max_retries }}</td>
                <td>
                  <div class="action-cell">
                    <button class="btn btn-text btn-action" type="button" @click="store.retryPushHistoryItem(h.id)">重试</button>
                    <button class="btn btn-text btn-action danger" type="button" @click="store.deletePushHistoryItem(h.id)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  mounted() {
    this.store.loadPushHistory();
  },
  computed: {
    totalPages() {
      return Math.max(1, Math.ceil(this.store.pushHistoryTotal / this.store.pushHistoryPageSize));
    },
  },
  methods: {
    statusClass(status) {
      const map = {
        success: 'badge-active',
        failed: 'badge-failed',
        pending: 'badge-pending',
        retrying: 'badge-pending',
        skipped: 'badge-neutral',
        stopped: 'badge-neutral',
      };
      return map[status] || 'badge-neutral';
    },
    statusText(status) {
      const map = {
        success: '成功',
        failed: '失败',
        pending: '待推送',
        retrying: '重试中',
        skipped: '已跳过',
        stopped: '已停止',
      };
      return map[status] || status;
    },
  },
});
