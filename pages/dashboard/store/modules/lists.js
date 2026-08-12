import {
  clearListQueue,
  createList,
  deleteList,
  flushList,
  getEligibleSubscriptions,
  getListBatches,
  getLists,
  moveSubscriptions,
  retryListBatch,
  updateList,
} from '../../js/api.js';
import { createEmptyListEditForm } from '../helpers.js';

function toKeywordList(value) {
  if (!value) return [];
  return String(value)
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export const listsModule = {
  async loadLists() {
    this.listsLoading = true;
    try {
      const result = await getLists();
      this.lists = result.items || [];
    } catch (err) {
      this.showToast(`加载 Lists 失败: ${err.message}`, 'error');
    } finally {
      this.listsLoading = false;
    }
  },

  openListCreatePanel() {
    this.listEditForm = createEmptyListEditForm();
    this.listEditPanelVisible = true;
  },

  openListEditPanel(list) {
    this.listEditForm = {
      id: list.id,
      name: list.name || '',
      user_id: list.user_id || '',
      target_session: list.target_session || '',
      platform_name: list.platform_name || '',
      state: list.state,
      batch_size: list.batch_size || 10,
      max_wait_minutes: list.max_wait_minutes || 120,
      content_mode: list.content_mode || 'full',
      full_delivery_mode: list.full_delivery_mode || 'split',
      ai_summary_enabled: Boolean(list.ai_summary_enabled),
      ai_summary_prompt: list.ai_summary_prompt || '',
      include_keywords: (list.include_keywords || []).join(', '),
      exclude_keywords: (list.exclude_keywords || []).join(', '),
    };
    this.listEditPanelVisible = true;
  },

  closeListEditPanel() {
    this.listEditPanelVisible = false;
  },

  async handleSaveList() {
    const form = this.listEditForm;
    if (!form.name || !form.user_id || !form.target_session) {
      this.showToast('名称、用户 ID 与目标会话为必填', 'error');
      return;
    }
    const payload = {
      name: form.name,
      user_id: form.user_id,
      target_session: form.target_session,
      platform_name: form.platform_name || '',
      batch_size: Number(form.batch_size) || 10,
      max_wait_minutes: Number(form.max_wait_minutes) || 120,
      content_mode: form.content_mode,
      full_delivery_mode: form.full_delivery_mode,
      ai_summary_enabled: Boolean(form.ai_summary_enabled),
      ai_summary_prompt: form.ai_summary_prompt || '',
      include_keywords: toKeywordList(form.include_keywords),
      exclude_keywords: toKeywordList(form.exclude_keywords),
    };
    const key = form.id ? `list:update:${form.id}` : 'list:create';
    try {
      await this.runPending(key, async () => {
        if (form.id) {
          await updateList({ list_id: form.id, ...payload });
        } else {
          await createList(payload);
        }
      });
      this.closeListEditPanel();
      this.showToast(form.id ? 'List 已更新' : 'List 已创建');
      await this.loadLists();
    } catch (err) {
      this.showToast(`保存失败: ${err.message}`, 'error');
    }
  },

  async toggleListState(list) {
    const nextState = list.state === 1 ? 0 : 1;
    try {
      await updateList({ list_id: list.id, state: nextState });
      this.showToast(nextState === 1 ? 'List 已启用' : 'List 已停用');
      await this.loadLists();
    } catch (err) {
      this.showToast(`更新失败: ${err.message}`, 'error');
    }
  },

  async handleDeleteList(list) {
    const confirm = await this.showConfirm(
      `确定删除 List「${list.name}」？`,
      '删除 List',
      '删除',
      'btn-danger',
      { optionLabel: '同时删除该 List 下的订阅' }
    );
    if (!confirm.ok) return;
    try {
      await deleteList(list.id, confirm.optionChecked);
      this.showToast(
        confirm.optionChecked ? 'List 及订阅已删除' : 'List 已解散，订阅恢复即时推送'
      );
      if (this.activeList && this.activeList.id === list.id) {
        this.activeList = null;
      }
      await this.loadLists();
    } catch (err) {
      this.showToast(`删除失败: ${err.message}`, 'error');
    }
  },

  async openListDetail(list) {
    this.activeList = list;
    this.listBatches = [];
    this.listEligibleGroups = {};
    this.listEligibleTotal = 0;
    await Promise.all([this.loadListBatches(list.id), this.loadListEligible(list.id)]);
  },

  async loadListBatches(listId) {
    try {
      const result = await getListBatches(listId);
      this.listBatches = result.items || [];
    } catch (err) {
      this.showToast(`加载批次失败: ${err.message}`, 'error');
    }
  },

  async loadListEligible(listId) {
    try {
      const result = await getEligibleSubscriptions(listId);
      this.listEligibleGroups = result.groups || {};
      this.listEligibleTotal = result.total || 0;
    } catch (err) {
      this.showToast(`加载可加入订阅失败: ${err.message}`, 'error');
    }
  },

  async flushActiveList() {
    const list = this.activeList;
    if (!list) return;
    try {
      const result = await flushList(list.id);
      this.showToast(result.message || '已触发立即推送');
      await this.loadLists();
      await this.loadListBatches(list.id);
    } catch (err) {
      this.showToast(`推送失败: ${err.message}`, 'error');
    }
  },

  async clearActiveListQueue() {
    const list = this.activeList;
    if (!list) return;
    const confirm = await this.showConfirm(
      `确定清空「${list.name}」的待发送队列？`,
      '清空队列',
      '清空',
      'btn-danger'
    );
    if (!confirm.ok) return;
    try {
      const result = await clearListQueue(list.id);
      this.showToast(result.message || '队列已清空');
      await this.loadLists();
    } catch (err) {
      this.showToast(`清空失败: ${err.message}`, 'error');
    }
  },

  async retryListBatch(batch) {
    if (!batch) return;
    try {
      await retryListBatch(batch.id);
      this.showToast('批次已加入重试');
      if (this.activeList) await this.loadListBatches(this.activeList.id);
    } catch (err) {
      this.showToast(`重试失败: ${err.message}`, 'error');
    }
  },

  async moveEligibleSubscriptions(domain, subIds) {
    if (!subIds || subIds.length === 0) return;
    const list = this.activeList;
    if (!list) return;
    const key = `list:move:${subIds[0]}`;
    try {
      await this.runPending(key, async () => {
        const result = await moveSubscriptions(subIds, list.id);
        this.showToast(result.message || `已加入 ${result.moved || 0} 个订阅`);
      });
      await this.loadLists();
      if (this.activeList) {
        await this.loadListEligible(this.activeList.id);
      }
    } catch (err) {
      this.showToast(`移动失败: ${err.message}`, 'error');
    }
  },

  domainSubCount(domain) {
    const group = this.listEligibleGroups[domain];
    return group ? group.length : 0;
  },
};
