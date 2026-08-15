// 数据管理页：统计卡 + 导出文件表 + 清理操作。

const { defineComponent } = window.Vue;

export const DataManagement = defineComponent({
  name: 'DataManagement',
  template: `
    <section class="settings-shell narrow-page">
      <base-skeleton v-if="store.dataManagementLoading" :count="4" />
      <div v-else-if="store.dataManagementOverview" class="settings-form">
        <div class="panel-section">
          <div class="section-header section-header-bordered">
            <h2>数据管理</h2>
            <div class="section-header-actions">
              <button class="btn btn-secondary btn-small" type="button" @click="store.loadDataManagement()">刷新</button>
              <button class="btn btn-secondary btn-small" type="button" @click="store.handleClearCache()">清理缓存</button>
              <button class="btn btn-danger btn-small" type="button" @click="store.handleClearExports()">清空导出</button>
            </div>
          </div>
          <div class="data-overview-grid">
            <div class="data-summary-card">
              <div class="data-summary-title">缓存</div>
              <div class="data-summary-value">{{ formatBytes(store.dataManagementOverview.cache.total_size) }}</div>
              <div class="data-summary-meta">{{ store.dataManagementOverview.cache.file_count }} 个文件</div>
            </div>
            <div class="data-summary-card">
              <div class="data-summary-title">导出</div>
              <div class="data-summary-value">{{ formatBytes(store.dataManagementOverview.exports.total_size) }}</div>
              <div class="data-summary-meta">{{ store.dataManagementOverview.exports.file_count }} 个文件</div>
            </div>
            <div class="data-summary-card">
              <div class="data-summary-title">合计</div>
              <div class="data-summary-value">{{ formatBytes(store.dataManagementOverview.totals.total_size) }}</div>
              <div class="data-summary-meta">缓存 + 导出</div>
            </div>
          </div>
        </div>

        <div class="panel-section">
          <div class="section-header section-header-bordered">
            <h2>导出文件</h2>
            <span class="section-count">{{ store.exportFiles.length }} 个</span>
          </div>
          <base-empty v-if="store.exportFiles.length === 0" title="暂无导出文件" />
          <div class="table-card" v-else>
            <table class="sub-table exports-table">
              <thead><tr><th>文件名</th><th>大小</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="file in store.exportFiles" :key="file.name">
                  <td class="cell-mono" :title="file.name">{{ file.name }}</td>
                  <td>{{ formatBytes(file.size) }}</td>
                  <td><button class="btn btn-text btn-action danger" type="button" @click="store.handleDeleteExportFile(file.name)">删除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  mounted() {
    this.store.loadDataManagement();
  },
  methods: {
    formatBytes(value) {
      const bytes = Number(value) || 0;
      if (bytes <= 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
      const size = bytes / 1024 ** exponent;
      return `${size.toFixed(size >= 100 || exponent === 0 ? 0 : size >= 10 ? 1 : 2)} ${units[exponent]}`;
    },
  },
});
