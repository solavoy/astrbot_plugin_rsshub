import assert from 'node:assert/strict';
import test from 'node:test';

import { toBridgePayload } from '../../pages/dashboard/js/api.js';

// Vue reactive 状态是 Proxy，postMessage 结构化克隆会抛
// "Failed to execute 'postMessage': ... could not be cloned."。
// toBridgePayload 必须把载荷归一化为普通对象/数组，才能通过 bridge 发送。
test('toBridgePayload 将 Proxy(如 Vue reactive) 载荷归一化为可克隆的普通数据', () => {
  const reactiveLike = new Proxy([1, 2, 3], {});
  assert.throws(() => structuredClone(reactiveLike), /could not be cloned/);

  const payload = toBridgePayload({ feed_ids: reactiveLike });
  assert.deepEqual(payload, { feed_ids: [1, 2, 3] });
  const cloned = structuredClone(payload);
  assert.deepEqual(cloned, { feed_ids: [1, 2, 3] });
});

test('toBridgePayload 保持标量与对象包裹语义', () => {
  assert.deepEqual(toBridgePayload(undefined), {});
  assert.deepEqual(toBridgePayload(null), {});
  assert.deepEqual(toBridgePayload({ sub_id: 1, user_id: 'u' }), {
    sub_id: 1,
    user_id: 'u',
  });
  assert.deepEqual(toBridgePayload('abc'), { value: 'abc' });
  assert.deepEqual(toBridgePayload([1, 2]), { value: [1, 2] });
});
