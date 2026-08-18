// AstrBot Plugin Pages 业务 API 封装。所有请求走 bridge。

import { requireBridge } from './bridge.js';

function plainClone(value, seen = new Map()) {
  // 递归复制为普通对象/数组：Vue reactive 状态是 Proxy，structuredClone /
  // postMessage 无法克隆 Proxy（抛 "could not be cloned"）；这里改写后的普通
  // 结构可克隆，同时保留 undefined 键与 Date 不被 JSON 往返改写。
  if (value === null || typeof value !== 'object') return value;
  if (value instanceof Date) return new Date(value.getTime());
  if (seen.has(value)) return seen.get(value);
  if (Array.isArray(value)) {
    const out = [];
    seen.set(value, out);
    for (const item of value) out.push(plainClone(item, seen));
    return out;
  }
  const out = {};
  seen.set(value, out);
  for (const key of Object.keys(value)) {
    out[key] = plainClone(value[key], seen);
  }
  return out;
}

export function toBridgePayload(value) {
  if (value === undefined || value === null) return {};
  const plain = plainClone(value);
  if (typeof plain === 'object' && !Array.isArray(plain)) return plain;
  return { value: plain };
}

function normalizeFilterValue(value) {
  if (value && typeof value === 'object' && Array.isArray(value.values)) {
    return normalizeFilterValue(value.values);
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? '').trim()).filter(Boolean);
  }
  const normalized = String(value ?? '').trim();
  return normalized ? [normalized] : [];
}

async function apiGet(path, params = {}) {
  const bridge = requireBridge();
  const cleanParams = {};
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      const normalized = normalizeFilterValue(value);
      if (normalized.length) cleanParams[key] = normalized;
    } else {
      cleanParams[key] = value;
    }
  }
  return await bridge.apiGet(path, cleanParams);
}

async function apiPost(path, payload = {}) {
  const bridge = requireBridge();
  return await bridge.apiPost(path, toBridgePayload(payload));
}

// ─── 订阅 ───────────────────────────────────────────────

export async function getSubscriptions(filters = {}) {
  return await apiGet('subscriptions', filters);
}

export async function subscribe(url, options = {}) {
  return await apiPost('subscribe', { url, ...options });
}

export async function unsubscribe(subId, userId, deletePushHistory = false) {
  return await apiPost('unsubscribe', { sub_id: subId, user_id: userId, delete_push_history: deletePushHistory });
}

export async function updateSubscription(subId, options, userId) {
  return await apiPost('subscriptions/update', { sub_id: subId, user_id: userId, options });
}

export async function batchActivate(subIds, userId) {
  return await apiPost('batch/activate', { sub_ids: subIds, user_id: userId });
}

export async function batchDeactivate(subIds, userId) {
  return await apiPost('batch/deactivate', { sub_ids: subIds, user_id: userId });
}

export async function batchUnsubscribe(subIds, userId, deletePushHistory = false) {
  return await apiPost('batch/unsubscribe', { sub_ids: subIds, user_id: userId, delete_push_history: deletePushHistory });
}

// ─── Feed ───────────────────────────────────────────────

export async function getFeeds(filters = {}) {
  return await apiGet('feeds', filters);
}

export async function getFeedItems(feedId, page = 1, pageSize = 20) {
  return await apiGet('feeds/items', { feed_id: feedId, page, page_size: pageSize });
}

export async function refreshFeed(feedId) {
  return await apiPost('feeds/refresh', { feed_id: feedId });
}

export async function refreshFeeds(feedIds) {
  return await apiPost('feeds/refresh', { feed_ids: feedIds });
}

export async function updateFeed(feedId, options) {
  return await apiPost('feeds/update', { feed_id: feedId, options });
}

export async function deleteFeed(feedId, deletePushHistory = false) {
  return await apiPost('feeds/delete', { feed_ids: [feedId], delete_push_history: deletePushHistory });
}

export async function deleteFeeds(feedIds, deletePushHistory = false) {
  return await apiPost('feeds/delete', { feed_ids: feedIds, delete_push_history: deletePushHistory });
}

// ─── 用户 ───────────────────────────────────────────────

export async function getUsers(filters = {}) {
  return await apiGet('users', filters);
}

export async function getUserDetails(filters = {}) {
  return await apiGet('users/detail', filters);
}

export async function updateUser(userId, settings) {
  return await apiPost('users/update', { user_id: userId, settings });
}

export async function deleteUser(userId, deletePushHistory = false) {
  return await apiPost('users/delete', { user_id: userId, delete_push_history: deletePushHistory });
}

export async function deleteUsers(userIds, deletePushHistory = false) {
  return await apiPost('users/delete', { user_ids: userIds, delete_push_history: deletePushHistory });
}

// ─── Lists ──────────────────────────────────────────────

export async function getLists() {
  return await apiGet('lists');
}

export async function createList(payload) {
  return await apiPost('lists/create', payload);
}

export async function updateList(listId, payload) {
  return await apiPost('lists/update', { list_id: listId, ...payload });
}

export async function deleteList(listId) {
  return await apiPost('lists/delete', { list_id: listId });
}

export async function moveSubscriptionsToList(listId, subIds) {
  return await apiPost('lists/move-subscriptions', { target_list_id: listId, sub_ids: subIds });
}

export async function getEligibleSubscriptions(listId) {
  return await apiGet('lists/eligible-subscriptions', { list_id: listId });
}

export async function getListBatches(listId, page = 1, pageSize = 20) {
  return await apiGet('lists/batches', { list_id: listId, page, page_size: pageSize });
}

export async function retryListBatch(batchId) {
  return await apiPost('lists/batches/retry', { batch_id: batchId });
}

export async function flushList(listId) {
  return await apiPost('lists/flush', { list_id: listId });
}

export async function clearListQueue(listId) {
  return await apiPost('lists/clear-queue', { list_id: listId });
}

// ─── 推送历史 ───────────────────────────────────────────

export async function getPushHistory(filters = {}) {
  return await apiGet('push-history', filters);
}

export async function deletePushHistory(historyId) {
  return await apiPost('push-history/delete', { history_id: historyId });
}

export async function retryPushHistory(historyId) {
  return await apiPost('push-history/retry', { history_id: historyId });
}

export async function cleanupPushHistory(days = 30) {
  return await apiPost('push-history/cleanup', { days });
}

export async function clearPushHistory() {
  return await apiPost('push-history/clear', {});
}

// ─── 概览 / 统计 ────────────────────────────────────────

export async function getStats() {
  return await apiGet('stats');
}

export async function getDashboardCharts(range = '7d') {
  return await apiGet('dashboard/charts', { range });
}

// ─── 设置 ───────────────────────────────────────────────

export async function getPluginSettings() {
  return await apiGet('plugin-settings');
}

export async function setPluginSettings(settings) {
  return await apiPost('plugin-settings', settings);
}

export async function getSettings() {
  return await apiGet('settings');
}

export async function setSettings(settings, userId) {
  return await apiPost('settings', { user_id: userId, settings });
}

// ─── 数据管理 ───────────────────────────────────────────

export async function getDataManagementOverview() {
  return await apiGet('data-management/overview');
}

export async function getDataManagementExports() {
  return await apiGet('data-management/exports');
}

export async function clearDataManagementCache() {
  return await apiPost('data-management/cache/clear', {});
}

export async function clearDataManagementExports() {
  return await apiPost('data-management/exports/clear', {});
}

export async function deleteDataManagementExport(name) {
  return await apiPost('data-management/exports/delete', { name });
}

export async function getDataManagementExportContent(name) {
  return await apiGet('data-management/exports/content', { name });
}

// ─── 工具 ───────────────────────────────────────────────

export async function getSuggestions(scope, field, q = '', limit = 10) {
  return await apiGet('suggestions', { scope, field, q, limit });
}

export async function testSubscription(subId, userId, targetSession, platformName) {
  return await apiPost('test-subscription', { sub_id: subId, user_id: userId, target_session: targetSession, platform_name: platformName });
}

export async function testUrl(url) {
  return await apiPost('test-url', { url });
}

export async function checkUpdates() {
  return await apiGet('updates');
}
