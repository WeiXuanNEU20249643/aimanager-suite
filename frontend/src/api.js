export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch('/api' + path, {
      ...options,
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'aimanager', ...options.headers},
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError('无法连接服务，请检查网络后重试', 0);
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if ([401, 403].includes(response.status) && !path.startsWith('/auth/')) {
      window.dispatchEvent(new CustomEvent('api-access-error', {detail: response.status}));
    }
    throw new ApiError(data?.detail || data?.error_message || '请求失败，请稍后重试', response.status);
  }
  return data;
}

export const projectApi = (projectId, path, options) => api(`/projects/${projectId}${path}`, options);
