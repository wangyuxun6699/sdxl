import { ref, onBeforeUnmount } from 'vue';
import { request, readLocal, writeLocal } from '../api';

export function useJob(key, onSuccess) {
  const job = ref(null), pending = ref(false), error = ref('');
  let timer, disposed = false, failures = 0, controller;
  async function poll(id) {
    if (disposed) return;
    controller = new AbortController();
    const abort = setTimeout(() => controller.abort(), 20000);
    try {
      const current = await request(`/jobs/${id}`, { signal: controller.signal });
      if (disposed) return;
      job.value = current; failures = 0; error.value = '';
      if (current.status === 'succeeded') {
        writeLocal(key, null); pending.value = false;
        await onSuccess(current.payload);
        return;
      }
      if (current.status === 'failed') {
        error.value = current.error || '任务未完成，请重新提交';
        writeLocal(key, null); pending.value = false; return;
      }
    } catch (e) {
      if (disposed) return;
      if(e.status === 404) { pending.value = false; job.value = {...job.value, status: 'failed'}; error.value = '该任务记录已不存在，请重新提交。'; writeLocal(key, null); return; }
      failures++;
      error.value = '暂时无法读取任务状态，恢复连接后将继续查询。';
      if (failures >= 5) { pending.value = false; return; }
    } finally { clearTimeout(abort); }
    timer = setTimeout(() => poll(id), failures ? 4000 : 1200);
  }
  function track(value) {
    clearTimeout(timer); job.value = value; pending.value = true; error.value = ''; failures = 0;
    writeLocal(key, value.id); poll(value.id);
  }
  function resume() {
    const id = readLocal(key);
    if (id) { track({ id, status: 'queued', stage: '恢复任务状态' }); return true; }
    return false;
  }
  onBeforeUnmount(() => { disposed = true; clearTimeout(timer); controller?.abort(); });
  return { job, pending, error, track, resume };
}
