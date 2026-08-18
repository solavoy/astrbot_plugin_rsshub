// 订阅页：卡片网格 + 搜索 + 批量操作 + 新建订阅面板。

const { defineComponent } = window.Vue;

export const Subscriptions = defineComponent({
  name: 'Subscriptions',
  template: `
    <section class="table-section">
      <div class="section-header">
        <span class="section-count">共 {{ store.subs.length }} 个</span>
        <div class="section-header-actions">
          <base-search-input v-model="store.subsKeyword" placeholder="搜索订阅…" @search="store.applySubSearch" />
          <button class="btn btn-primary" type="button" @click="store.openAddPanel()">+ 添加</button>
          <base-page-actions :store="store" />
        </div>
      </div>

      <div class="subs-toolbar">
        <button
          class="btn"
          :class="store.editMode ? 'btn-primary' : 'btn-secondary'"
          type="button"
          @click="store.toggleEditMode()"
        >{{ store.editMode ? '完成编辑' : '批量操作' }}</button>
        <div v-if="store.editMode && store.selectedSubIds.length > 0" class="subs-batch">
          <span class="edit-toolbar-count">已选 {{ store.selectedSubIds.length }} 项</span>
          <button class="btn btn-primary btn-small" type="button" @click="store.batchActivate()">批量启用</button>
          <button class="btn btn-secondary btn-small" type="button" @click="store.batchDeactivate()">批量禁用</button>
          <button class="btn btn-danger btn-small" type="button" @click="store.batchUnsubscribe()">批量取消</button>
        </div>
      </div>

      <div class="grid-cards">
        <base-skeleton v-if="store.subsLoading" :count="6" />
        <base-empty v-else-if="store.subs.length === 0" title="暂无订阅" hint="可通过搜索或添加创建订阅" />
        <article
          v-for="sub in store.subs"
          :key="sub.id"
          class="sub-card"
          :class="{ selected: store.selectedSubIds.includes(sub.id) }"
          @click="store.editMode ? store.toggleSelect(sub.id) : null"
        >
          <div class="sub-card-head">
            <div class="sub-card-main">
              <h3 class="sub-card-title">{{ sub.feed_title || '#' + sub.id }}</h3>
              <p class="sub-card-url" :title="sub.feed_link">{{ sub.feed_link || '' }}</p>
            </div>
            <label v-if="store.editMode" class="card-checkbox" @click.stop>
              <input type="checkbox" :checked="store.selectedSubIds.includes(sub.id)" @change="store.toggleSelect(sub.id)" />
            </label>
          </div>
          <dl class="sub-card-meta">
            <div><dt>状态</dt><dd><span class="status-dot" :class="sub.state === 1 ? 'active' : 'inactive'"></span> {{ sub.state === 1 ? '启用' : '停用' }}</dd></div>
            <div><dt>用户</dt><dd class="cell-mono" :title="sub.user_id">{{ sub.user_id }}</dd></div>
            <div><dt>间隔</dt><dd>{{ sub.interval > 0 ? sub.interval + ' 分钟' : '继承' }}</dd></div>
            <div><dt>目标</dt><dd class="cell-mono" :title="sub.target_session">{{ sub.target_session || '-' }}</dd></div>
          </dl>
          <div class="sub-card-footer">
            <span v-if="sub.list_id" class="badge badge-active">Lists</span>
            <span v-else class="badge badge-neutral">即时推送</span>
            <div class="card-actions">
              <button class="btn btn-text btn-action" type="button" @click.stop="store.openSubEditPanel(sub)">编辑</button>
              <button class="btn btn-text btn-action danger" type="button" @click.stop="removeSub(sub)">删除</button>
            </div>
          </div>
        </article>
      </div>

      <!-- 新建订阅面板 -->
      <div class="panel-backdrop" v-if="store.addPanelVisible" @click.self="store.closeAddPanel()">
        <div class="panel-shell">
          <div class="panel-header">
            <h3>新建订阅</h3>
            <button class="btn btn-text" type="button" @click="store.closeAddPanel()">关闭</button>
          </div>
          <div class="panel-body">
            <div class="form-group">
              <label>RSS 地址</label>
              <div class="input-wrapper">
                <input type="text" v-model="store.addUrl" placeholder="https://rsshub.app/..." @keyup.enter="store.submitAdd()" />
              </div>
            </div>
          </div>
          <div class="panel-footer">
            <button class="btn btn-secondary" type="button" @click="store.closeAddPanel()">取消</button>
            <button
              class="btn btn-primary"
              :class="{ 'is-loading': store.addPanelLoading }"
              :disabled="store.addPanelLoading"
              type="button"
              @click="store.submitAdd()"
            >{{ store.addPanelLoading ? '订阅中…' : '订阅' }}</button>
          </div>
        </div>
      </div>

      <!-- 编辑订阅面板 -->
      <div class="panel-backdrop" v-if="store.subEditPanelVisible" @click.self="store.closeSubEditPanel()">
        <div class="panel-shell">
          <div class="panel-header">
            <h3>编辑订阅</h3>
            <button class="btn btn-text" type="button" @click="store.closeSubEditPanel()">关闭</button>
          </div>
          <div class="panel-body form-layout">
            <div class="setting-row"><span class="setting-label">目标会话</span><input class="select-input" type="text" v-model="store.subEditForm.target_session" placeholder="如：telegram:UserMessage:123" /></div>
            <div class="setting-row"><span class="setting-label">平台</span><input class="select-input" type="text" v-model="store.subEditForm.platform_name" placeholder="如：telegram" /></div>
            <div class="setting-row"><span class="setting-label">更新间隔（分钟）</span><input class="select-input" type="number" v-model.number="store.subEditForm.interval" min="0" placeholder="0=继承" /></div>
            <div class="setting-row"><span class="setting-label">状态</span><select class="select-input" v-model.number="store.subEditForm.state"><option :value="1">启用</option><option :value="0">停用</option></select></div>
          </div>
          <div class="panel-footer">
            <button class="btn btn-secondary" type="button" @click="store.closeSubEditPanel()">取消</button>
            <button
              class="btn btn-primary"
              :class="{ 'is-loading': store.subEditLoading }"
              :disabled="store.subEditLoading"
              type="button"
              @click="store.saveSubEdit()"
            >{{ store.subEditLoading ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </section>
  `,
  props: { store: { type: Object, required: true } },
  mounted() {
    this.store.loadData();
  },
  methods: {
    async removeSub(sub) {
      try {
        const { unsubscribe } = await import('../../js/api.js');
        const ok = await this.store.showConfirm('取消订阅', `确定取消订阅「${sub.feed_title || '#' + sub.id}」？`);
        if (!ok) return;
        await unsubscribe(sub.id, sub.user_id);
        this.store.showToast('已取消订阅', 'success');
        this.store.loadData();
      } catch (err) {
        this.store.showToast(`取消失败: ${err.message}`, 'error');
      }
    },
  },
});
