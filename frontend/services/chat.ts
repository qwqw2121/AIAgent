const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export async function askAgent(question: string) {
  const response = await fetch(`${API_BASE}/api/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) throw new Error('AI 助手暂时不可用');
  return response.json() as Promise<{ answer: string }>;
}

export type ChatEvent = { type: 'token' | 'tool' | 'error'; content?: string; name?: string };

export async function streamAgent(
  text: string,
  sessionId: string,
  onEvent: (ev: ChatEvent) => void,
  signal?: AbortSignal,
) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: text, session_id: sessionId }),  // 字段名沿用你原来的
    signal,
  });
  if (!response.ok || !response.body) throw new Error('AI 助手暂时不可用');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();   //使用 `TextDecoder` 将字节解码为文本。
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() || '';
    for (const frame of frames) {
      const line = frame.split('\n').find((item) => item.startsWith('data: '));
      if (!line) continue;
      const data = line.slice(6);
      if (data === '[DONE]') return;
      onEvent(JSON.parse(data) as ChatEvent);
    }
    if (done) return;
  }
}