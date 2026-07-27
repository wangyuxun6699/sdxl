// 默认走同域 /api 反向代理，避免生产构建绑定某一台后端主机。
const rawApiBase = import.meta.env.VITE_API_BASE_URL || "/api";

export const API_BASE = rawApiBase.replace(/\/$/, "");

export function apiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalizedPath}`;
}

export function assetUrl(path) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  return apiUrl(path);
}
