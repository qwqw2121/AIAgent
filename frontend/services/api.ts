const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export interface DailyReport {
  date: string;
  overview: string;
  report: DailyReportContent;
}

export interface ReportNews {
  id: number;
  title: string;
  source?: string;
  published?: string;
  summary?: string;
  content?: string;
  llm_category?: string;
  keywords?: string | string[];
  importance?: number;
  url?: string;
}

export interface ReportEvent {
  title: string;
  summary?: string;
  why_it_matters?: string;
  news_ids?: number[];
  news?: ReportNews[];
}

export interface DailyReportContent {
  overview: string;
  events: ReportEvent[];
}

export interface TrendData {
  days: number;
  total_news: number;
  important_news: number;
  main_events: number;
  hot_directions: number;
  hot_tech: { name: string; count: number }[];
  daily_counts: { date: string; count: number }[];
  events: { rank: number; title: string }[];
}

export interface DashboardStats {
  total_news: number;
  today_news: number;
  important_news: number;
}

export async function getDailyReport(date: string): Promise<DailyReport> {
  const response = await fetch(`${API_BASE}/api/daily-report/${date}`);
  
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`未找到 ${date} 的日报`);
    }
    throw new Error('获取日报失败');
  }
  
  return response.json();
}

export async function getTodayReport(): Promise<DailyReport> {
  const response = await fetch(`${API_BASE}/api/daily-report/today`);
  
  if (!response.ok) {
    throw new Error('获取今日日报失败');
  }
  
  return response.json();
}

export async function getLatestReport(): Promise<DailyReport> {
  const endDate = new Date().toISOString().split('T')[0];
  const response = await fetch(`${API_BASE}/api/daily-report/range?start_date=2000-01-01&end_date=${endDate}`);
  if (!response.ok) throw new Error('获取最新日报失败');
  const reports = await response.json() as DailyReport[];
  if (!reports.length) throw new Error('暂无日报');
  return reports.sort((left, right) => right.date.localeCompare(left.date))[0];
}

export async function getReportRange(startDate: string, endDate: string): Promise<DailyReport[]> {
  const response = await fetch(
    `${API_BASE}/api/daily-report/range?start_date=${startDate}&end_date=${endDate}`
  );
  
  if (!response.ok) {
    throw new Error('获取日报范围失败');
  }
  
  return response.json();
}

export async function getTrends(days = 30): Promise<TrendData> {
  const response = await fetch(`${API_BASE}/api/trends?days=${days}`);
  if (!response.ok) throw new Error('获取趋势数据失败');
  return response.json();
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await fetch(`${API_BASE}/api/dashboard/stats`);
  if (!response.ok) throw new Error('获取数据库统计失败');
  return response.json();
}

export async function getImportantNews(limit = 30): Promise<ReportNews[]> {
  const response = await fetch(`${API_BASE}/api/news/important?limit=${limit}`);
  if (!response.ok) throw new Error('获取重要新闻失败');
  return response.json();
}

export async function getNewsList(options: { limit?: number; q?: string; importance?: number } = {}) {
  const params = new URLSearchParams({ limit: String(options.limit || 50) });
  if (options.q) params.set('q', options.q);
  if (options.importance) params.set('importance', String(options.importance));
  const response = await fetch(`${API_BASE}/api/news?${params.toString()}`);
  if (!response.ok) throw new Error('获取新闻列表失败');
  return response.json() as Promise<{ data: ReportNews[]; total: number }>;
}

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

export async function streamAgent(question: string, sessionId: string, onEvent: (event: ChatEvent) => void) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question, session_id: sessionId }),
  });
  if (!response.ok || !response.body) throw new Error('AI 助手暂时不可用');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
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
