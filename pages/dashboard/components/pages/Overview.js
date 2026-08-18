// 概览页：统计卡 + 图表卡（Chart.js）。

const { defineComponent, nextTick } = window.Vue;

import { buildPushSuccessDataset, createPushSuccessLineChartOptions, formatBucketLabel } from '../../store/modules/charts.js';

// Feed 健康分档中文标签与警示色；后端只返回 status 枚举。
const FEED_HEALTH_LABELS = { healthy: '正常', warning: '预警', stale: '陈旧', disabled: '停用' };
const FEED_HEALTH_COLORS = { healthy: '#16a34a', warning: '#f59e0b', stale: '#ef4444', disabled: '#94a3b8' };
// 订阅占比环形图循环调色板（后端 items 不携带颜色字段）。
const SHARE_PALETTE = ['#2563eb', '#f59e0b', '#16a34a', '#ef4444', '#8b5cf6', '#0ea5e9', '#f97316', '#14b8a6', '#64748b'];

export const Overview = defineComponent({
  name: 'Overview',
  template: `
    <section class="overview-page">
      <div class="section-header">
        <div class="section-header-actions">
          <div class="segmented-control" role="group" aria-label="图表时间范围">
            <button
              v-for="r in ranges"
              :key="r.key"
              class="segmented-button"
              :class="{ active: store.overviewRange === r.key }"
              type="button"
              @click="store.setOverviewRange(r.key)"
            >{{ r.label }}</button>
          </div>
          <button
            class="btn btn-icon"
            type="button"
            :class="{ 'is-loading': store.overviewChartsLoading }"
            :disabled="store.overviewChartsLoading"
            @click="store.loadOverview()"
            title="刷新" aria-label="刷新"
          >⟳</button>
        </div>
      </div>

      <div class="overview-stats-grid">
        <div class="stat-card"><div class="stat-card-icon stat-icon-blue">◎</div><div class="stat-card-value">{{ store.stats.total_subscriptions }}</div><div class="stat-card-label">总订阅</div></div>
        <div class="stat-card"><div class="stat-card-icon stat-icon-green">●</div><div class="stat-card-value">{{ store.stats.active_subscriptions }}</div><div class="stat-card-label">启用中</div></div>
        <div class="stat-card"><div class="stat-card-icon stat-icon-violet">✦</div><div class="stat-card-value">{{ store.stats.total_feeds }}</div><div class="stat-card-label">Feed 源</div></div>
        <div class="stat-card"><div class="stat-card-icon stat-icon-amber">◉</div><div class="stat-card-value">{{ store.stats.unique_users }}</div><div class="stat-card-label">用户数</div></div>
      </div>

      <div class="overview-chart-grid">
        <section class="overview-chart-panel overview-chart-panel-wide">
          <div class="overview-chart-head"><h3>推送成功率</h3><span class="overview-chart-meta">success / (success + failed)</span></div>
          <div class="overview-chart-canvas"><canvas id="overview-push-success-chart"></canvas></div>
        </section>
        <section class="overview-chart-panel">
          <div class="overview-chart-head"><h3>Feed 新鲜度</h3><span class="overview-chart-meta">按订阅间隔分档</span></div>
          <div class="overview-chart-canvas overview-chart-canvas-small"><canvas id="overview-feed-health-chart"></canvas></div>
        </section>
        <section class="overview-chart-panel">
          <div class="overview-chart-head"><h3>Feed 订阅占比</h3><span class="overview-chart-meta">Top 8 + 其他</span></div>
          <div class="overview-chart-canvas overview-doughnut-canvas"><canvas id="overview-feed-share-chart"></canvas></div>
        </section>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  data() {
    return { ranges: [
      { key: '24h', label: '24小时' },
      { key: '7d', label: '1周' },
      { key: '30d', label: '1个月' },
    ] };
  },
  mounted() {
    this.store.loadOverview();
    this.$watch(() => this.store.overviewCharts, () => nextTick(() => this.renderCharts()));
    this.$watch(() => this.store.overviewChartsLoading, () => {
      if (!this.store.overviewChartsLoading) nextTick(() => this.renderCharts());
    });
  },
  beforeUnmount() {
    this.destroyCharts();
  },
  methods: {
    renderCharts() {
      const charts = this.store.overviewCharts;
      if (!charts || typeof window.Chart === 'undefined') return;
      this.destroyCharts();
      this._charts = [];

      if (charts.push_success && charts.push_success.points) {
        const el = document.getElementById('overview-push-success-chart');
        if (el) {
          const points = charts.push_success.points;
          this._charts.push(new window.Chart(el, {
            type: 'line',
            data: {
              labels: points.map((p) => formatBucketLabel(p.bucket, charts.bucket_unit)),
              datasets: [buildPushSuccessDataset(points)],
            },
            options: createPushSuccessLineChartOptions(points),
          }));
        }
      }

      if (charts.feed_health && charts.feed_health.buckets) {
        const el = document.getElementById('overview-feed-health-chart');
        if (el) {
          const buckets = charts.feed_health.buckets;
          this._charts.push(new window.Chart(el, {
            type: 'bar',
            data: {
              labels: buckets.map((b) => FEED_HEALTH_LABELS[b.status] || b.status),
              datasets: [{
                label: 'Feed 数',
                data: buckets.map((b) => b.count),
                backgroundColor: buckets.map((b) => FEED_HEALTH_COLORS[b.status] || '#3b82f6'),
                borderRadius: 4,
              }],
            },
            options: { responsive: true, maintainAspectRatio: false },
          }));
        }
      }

      if (charts.feed_share && charts.feed_share.items) {
        const el = document.getElementById('overview-feed-share-chart');
        if (el) {
          const items = charts.feed_share.items;
          this._charts.push(new window.Chart(el, {
            type: 'doughnut',
            data: {
              labels: items.map((i) => i.title || i.name || '其他'),
              datasets: [{
                data: items.map((i) => i.count),
                backgroundColor: items.map((i, idx) => i.color || SHARE_PALETTE[idx % SHARE_PALETTE.length]),
                borderWidth: 2,
              }],
            },
            options: { responsive: true, maintainAspectRatio: false, cutout: '55%' },
          }));
        }
      }
    },
    destroyCharts() {
      if (this._charts) {
        this._charts.forEach((c) => c.destroy());
        this._charts = [];
      }
    },
  },
});
