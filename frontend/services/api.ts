const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export async function apiRequest<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);

  if (!response.ok) {
    const message =
      response.status === 404
        ? '请求的数据不存在'
        : `请求失败：${response.status}`;

    throw new Error(message);
  }

  return response.json() as Promise<T>;
}