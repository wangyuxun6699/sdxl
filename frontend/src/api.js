import { API_BASE } from './config';

export async function request(path, options = {}) {
  const { timeout = 20000, ...init } = options;
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, signal: init.signal || AbortSignal.timeout(timeout) });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error(error.name === 'TimeoutError' ? '服务响应超时，请重试。' : '暂时无法连接后端，请确认服务已启动。');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : '';
    const error = new Error(detail || (response.status === 502 ? '后端尚未启动或代理无法连接。' : `请求未完成（${response.status}），请重试。`));
    error.status = response.status; throw error;
  }
  if (!data) throw new Error('服务返回格式异常，请检查 API 地址。');
  return data;
}

export const jsonRequest = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export function readLocal(key, fallback = null) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
export function writeLocal(key, value) {
  try { value == null ? localStorage.removeItem(key) : localStorage.setItem(key, JSON.stringify(value)); } catch { /* private browsing / quota: keep in-memory work usable */ }
}
