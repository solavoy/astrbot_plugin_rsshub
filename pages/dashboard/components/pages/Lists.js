// Lists 页：卡片网格 + 详情区 + 编辑/新建面板。

const { defineComponent } = window.Vue;

export const Lists = defineComponent({
  name: 'Lists',
  template: `
    <section class="table-section">
      <div class="section-header">
        <div class="section-header-titles">
          <h2 class="section-title">{{ store.pageTitle() }}</h2>
          <span class="section-count">共 {{ store.lists.length }} 个</span>
        </div>
        <div class="section-header-actions">
          <button class="btn btn-primary" type="button" @click="store.openListCreatePanel()">+ 添加</button>
          <base-page-actions :store="store" />
        </div>
      </div>

      <div class="grid-cards">
        <base-skeleton v-if="store.listsLoading" :count="4" />
        <base-empty v-else-if="store.lists.length === 0" title="暂无 List" hint="点击右上角新建" />
        <article
          v-for="list in store.lists"
          :key="list.id"
          class="sub-card"
          :class="{ selected: store.activeList && store.activeList.id === list.id }"
          @click="store.openListDetail(list)"
        >
          <div class="sub-card-head">
            <div class="sub-card-main">
              <h3 class="sub-card-title">{{ list.name }}</h3>
              <p class="sub-card-url cell-mono" :title="list.target_session">{{ list.target_session }}</p>
            </div>
          </div>
          <dl class="sub-card-meta">
            <div><dt>用户</dt><dd class="cell-mono" :title="list.user_id">{{ list.user_id }}</dd></div>
            <div><dt>平台</dt><dd>{{ list.platform_name || '-' }}</dd></div>
            <div><dt>批次</dt><dd>{{ list.batch_size }} / {{ list.max_wait_minutes }}分</dd></div>
            <div><dt>状态</dt><dd><span class="badge" :class="list.state === 1 ? 'badge-active' : 'badge-neutral'">{{ list.state === 1 ? '启用' : '停用' }}</span></dd></div>
          </dl>
          <div class="sub-card-footer">
            <div class="card-actions">
              <button class="btn btn-text btn-action" type="button" @click.stop="store.toggleListState(list)">{{ list.state === 1 ? '停用' : '启用' }}</button>
              <button class="btn btn-text btn-action" type="button" @click.stop="store.openListEditPanel(list)">编辑</button>
              <button class="btn btn-text btn-action danger" type="button" @click.stop="store.handleDeleteList(list)">删除</button>
            </div>
          </div>
        </article>
      </div>

      <!-- 详情区 -->
      <section v-if="store.activeList" class="panel-section list-detail-section">
        <h4>「{{ store.activeList.name }}」详情</h4>
        <div class="list-detail-meta">
          <span>订阅 {{ store.activeList.subscription_count }} · 排队 {{ store.activeList.queued_count }} · 最近批次 {{ store.activeList.last_batch_state || '无' }}</span>
        </div>
        <div class="detail-actions">
          <button class="btn btn-primary btn-small" type="button" @click="store.flushActiveList()">立即推送队列</button>
          <button class="btn btn-secondary btn-small" type="button" @click="store.clearActiveListQueue()">清空队列</button>
        </div>

        <div class="list-batches-block">
          <h5>最近批次</h5>
          <base-empty v-if="store.listBatches.length === 0" title="暂无批次" />
          <table class="sub-table" v-else>
            <thead><tr><th>批次 ID</th><th>条数</th><th>状态</th><th>成功分片</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="batch in store.listBatches" :key="batch.id">
                <td>{{ batch.id }}</td>
                <td>{{ batch.item_count }}</td>
                <td><span class="badge" :class="batchStateClass(batch)">{{ batch.state }}</span></td>
                <td>{{ batch.success_parts }}/{{ batch.part_count }}</td>
                <td><button v-if="batch.state === 'failed'" class="btn btn-text btn-action" type="button" @click="store.retryListBatch(batch)">重试</button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="list-eligible-block">
          <h5>可加入订阅（按域名分组，共 {{ eligibleTotal }} 条）</h5>
          <base-empty v-if="Object.keys(store.listEligibleGroups).length === 0" title="没有可加入的订阅" />
          <div v-for="(subs, domain) in store.listEligibleGroups" :key="domain" class="list-domain-group">
            <div class="list-domain-header"><strong>{{ domain }}</strong> <span class="muted">({{ subs.length }})</span></div>
            <ul class="list-domain-subs">
              <li v-for="sub in subs" :key="sub.id" class="list-eligible-item">
                <span class="list-eligible-title">{{ sub.feed_title || sub.feed_link }}</span>
                <span v-if="sub.in_list" class="badge badge-active">已在 List</span>
                <button v-else class="btn btn-text btn-action" type="button" @click="store.moveEligibleSubscriptions(domain, [sub.id])">加入</button>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- 编辑/新建面板 -->
      <div class="panel-backdrop" v-if="store.listEditPanelVisible" @click.self="store.closeListEditPanel()">
        <div class="panel-shell panel-shell-lg">
          <div class="panel-header">
            <h3>{{ store.listEditForm.id ? '编辑 List' : '新建 List' }}</h3>
            <button class="btn btn-text" type="button" @click="store.closeListEditPanel()">关闭</button>
          </div>
          <div class="panel-body form-layout">
            <div class="setting-row"><span class="setting-label">名称</span><input type="text" v-model="store.listEditForm.name" placeholder="如：技术新闻" /></div>
            <div class="setting-row"><span class="setting-label">用户 ID</span><input type="text" v-model="store.listEditForm.user_id" /></div>
            <div class="setting-row"><span class="setting-label">目标会话</span><input type="text" v-model="store.listEditForm.target_session" placeholder="如：telegram:Group:123" /></div>
            <div class="setting-row"><span class="setting-label">平台</span><input type="text" v-model="store.listEditForm.platform_name" placeholder="如：telegram" /></div>
            <div class="setting-row"><span class="setting-label">批次条数</span><div class="input-wrapper" style="max-width:120px;"><input type="number" v-model.number="store.listEditForm.batch_size" min="1" /></div></div>
            <div class="setting-row"><span class="setting-label">最长等待（分钟）</span><div class="input-wrapper" style="max-width:120px;"><input type="number" v-model.number="store.listEditForm.max_wait_minutes" min="1" /></div></div>
            <div class="setting-row"><span class="setting-label">内容模式</span><select class="select-input" v-model="store.listEditForm.content_mode"><option value="title_link">标题 + 链接</option><option value="full">全文</option></select></div>
            <div class="setting-row" v-if="store.listEditForm.content_mode === 'full'"><span class="setting-label">全文发送方式</span><select class="select-input" v-model="store.listEditForm.full_delivery_mode"><option value="split">逐条发送</option><option value="aggregate">合并推送</option></select></div>
          </div>
          <div class="panel-footer">
            <button class="btn btn-secondary" type="button" @click="store.closeListEditPanel()">取消</button>
            <button class="btn btn-primary" type="button" @click="store.handleSaveList()">保存</button>
          </div>
        </div>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  mounted() {
    this.store.loadLists();
  },
  computed: {
    eligibleTotal() {
      return Object.values(this.store.listEligibleGroups).reduce((sum, subs) => sum + (subs ? subs.length : 0), 0);
    },
  },
  methods: {
    batchStateClass(batch) {
      if (batch.state === 'success') return 'badge-active';
      if (batch.state === 'failed') return 'badge-failed';
      return 'badge-pending';
    },
  },
});
