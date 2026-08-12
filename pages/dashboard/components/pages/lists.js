export const listsPageTemplate = String.raw`
      <section class="table-section" v-if="activeTab === 'lists'">
        <div class="section-header">
          <h2>Lists 聚合推送</h2>
          <div class="section-actions">
            <button class="btn btn-primary btn-small" type="button" @click="openListCreatePanel()">新建 List</button>
          </div>
        </div>
        <div class="table-scroll-area">
          <div v-if="listsLoading" class="empty-state"><p>加载中...</p></div>
          <div v-else-if="lists.length === 0" class="empty-state"><p>暂无 List，点击右上角新建</p></div>
          <table class="sub-table lists-table" v-else>
            <thead><tr><th class="col-title">名称</th><th class="col-user">用户</th><th class="col-session">目标会话</th><th class="col-platform">平台</th><th class="col-interval">批次/等待</th><th class="col-status">状态</th><th class="col-actions">操作</th></tr></thead>
            <tbody>
              <tr v-for="list in lists" :key="list.id" :class="{ selected: activeList && activeList.id === list.id }" @click="openListDetail(list)">
                <td class="col-title" data-label="名称">{{ list.name }}</td>
                <td class="col-user cell-mono" data-label="用户">{{ list.user_id }}</td>
                <td class="col-session cell-mono" data-label="会话" :title="list.target_session">{{ list.target_session }}</td>
                <td class="col-platform" data-label="平台">{{ list.platform_name || '-' }}</td>
                <td class="col-interval" data-label="批次">{{ list.batch_size }} / {{ list.max_wait_minutes }}分</td>
                <td class="col-status" data-label="状态"><span class="status-badge" :class="list.state === 1 ? 'active' : 'inactive'">{{ list.state === 1 ? '启用' : '停用' }}</span></td>
                <td class="col-actions" data-label="操作">
                  <div class="action-cell">
                    <button class="btn btn-text btn-action" :class="{ 'is-loading': isPending('list:update:' + list.id) }" :disabled="isPending('list:update:' + list.id)" @click.stop="toggleListState(list)">{{ list.state === 1 ? '停用' : '启用' }}</button>
                    <button class="btn btn-text btn-action" @click.stop="openListEditPanel(list)">编辑</button>
                    <button class="btn btn-text btn-action danger" :class="{ 'is-loading': isPending('list:delete:' + list.id) }" :disabled="isPending('list:delete:' + list.id)" @click.stop="handleDeleteList(list)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel-section list-detail-section" v-if="activeTab === 'lists' && activeList">
        <h4>「{{ activeList.name }}」详情</h4>
        <div class="list-detail-meta">
          <span>订阅 {{ activeList.subscription_count }} · 排队 {{ activeList.queued_count }} · 最近批次 {{ activeList.last_batch_state || '无' }}</span>
        </div>
        <div class="detail-actions">
          <button class="btn btn-primary btn-small" :class="{ 'is-loading': isPending('list:flush') }" :disabled="isPending('list:flush')" @click="flushActiveList()">立即推送队列</button>
          <button class="btn btn-secondary btn-small" @click="clearActiveListQueue()">清空队列</button>
        </div>

        <div class="list-batches-block">
          <h5>最近批次</h5>
          <div v-if="listBatches.length === 0" class="empty-state"><p>暂无批次</p></div>
          <table class="sub-table" v-else>
            <thead><tr><th>批次 ID</th><th>条数</th><th>状态</th><th>总结</th><th>成功分片</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="batch in listBatches" :key="batch.id">
                <td>{{ batch.id }}</td>
                <td>{{ batch.item_count }}</td>
                <td><span class="status-badge" :class="batch.state === 'success' ? 'active' : batch.state === 'failed' ? 'inactive' : 'pending'">{{ batch.state }}</span></td>
                <td>{{ batch.summary_status }}</td>
                <td>{{ batch.success_parts }}/{{ batch.part_count }}</td>
                <td><button class="btn btn-text btn-action" v-if="batch.state === 'failed'" @click="retryListBatch(batch)">重试</button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="list-eligible-block">
          <h5>可加入订阅（按域名分组，共 {{ listEligibleTotal }} 条）</h5>
          <div v-if="Object.keys(listEligibleGroups).length === 0" class="empty-state"><p>没有可加入的订阅</p></div>
          <div v-for="(subs, domain) in listEligibleGroups" :key="domain" class="list-domain-group">
            <div class="list-domain-header">
              <strong>{{ domain }}</strong> <span class="muted">({{ subs.length }})</span>
            </div>
            <ul class="list-domain-subs">
              <li v-for="sub in subs" :key="sub.id" class="list-eligible-item">
                <span class="list-eligible-title">{{ sub.feed_title || sub.feed_link }}</span>
                <span v-if="sub.in_list" class="status-badge active">已在 List</span>
                <button v-else class="btn btn-text btn-action" :class="{ 'is-loading': isPending('list:move:' + sub.id) }" :disabled="isPending('list:move:' + sub.id)" @click="moveEligibleSubscriptions(domain, [sub.id])">加入</button>
              </li>
            </ul>
          </div>
        </div>
      </section>
`;

export const listEditPanelTemplate = String.raw`
      <div class="panel-backdrop" v-if="listEditPanelVisible" @click.self="closeListEditPanel()">
        <div class="panel-shell panel-shell-lg">
          <div class="panel-header">
            <h3>{{ listEditForm.id ? '编辑 List' : '新建 List' }}</h3>
            <button class="btn btn-text" @click="closeListEditPanel()" type="button">关闭</button>
          </div>
          <div class="panel-body form-layout">
            <div class="setting-row"><span class="setting-label">名称</span><input type="text" v-model="listEditForm.name" placeholder="如：技术新闻" /></div>
            <div class="setting-row"><span class="setting-label">用户 ID</span><input type="text" v-model="listEditForm.user_id" /></div>
            <div class="setting-row"><span class="setting-label">目标会话</span><input type="text" v-model="listEditForm.target_session" placeholder="如：telegram:Group:123" /></div>
            <div class="setting-row"><span class="setting-label">平台</span><input type="text" v-model="listEditForm.platform_name" placeholder="如：telegram" /></div>
            <div class="setting-row"><span class="setting-label">批次条数</span><div class="input-wrapper" style="max-width:120px;"><input type="number" v-model.number="listEditForm.batch_size" min="1" /></div></div>
            <div class="setting-row"><span class="setting-label">最长等待（分钟）</span><div class="input-wrapper" style="max-width:120px;"><input type="number" v-model.number="listEditForm.max_wait_minutes" min="1" /></div></div>
            <div class="setting-row"><span class="setting-label">内容模式</span><select class="select-input" v-model="listEditForm.content_mode"><option value="title_link">标题 + 链接</option><option value="full">全文</option></select></div>
            <div class="setting-row" v-if="listEditForm.content_mode === 'full'"><span class="setting-label">全文发送方式</span><select class="select-input" v-model="listEditForm.full_delivery_mode"><option value="split">逐条发送</option><option value="aggregate">合并推送</option></select></div>
            <div class="setting-row"><span class="setting-label">AI 总结</span><label class="toggle-switch"><input type="checkbox" v-model="listEditForm.ai_summary_enabled" /><span class="toggle-slider"></span></label></div>
            <div class="setting-row" v-if="listEditForm.ai_summary_enabled"><span class="setting-label">总结提示词</span><textarea class="textarea-input" v-model="listEditForm.ai_summary_prompt" rows="2" placeholder="留空使用默认提示"></textarea></div>
            <div class="setting-row"><span class="setting-label">关注词</span><input type="text" v-model="listEditForm.include_keywords" placeholder="逗号分隔，任一层命中即可" /></div>
            <div class="setting-row"><span class="setting-label">屏蔽词</span><input type="text" v-model="listEditForm.exclude_keywords" placeholder="逗号分隔，命中即过滤" /></div>
          </div>
          <div class="panel-footer">
            <button class="btn btn-secondary" @click="closeListEditPanel()" type="button">取消</button>
            <button class="btn btn-primary" :class="{ 'is-loading': isPending('list:create') || isPending('list:update:' + listEditForm.id) }" :disabled="isPending('list:create') || isPending('list:update:' + listEditForm.id)" @click="handleSaveList()">保存</button>
          </div>
        </div>
      </div>
`;
