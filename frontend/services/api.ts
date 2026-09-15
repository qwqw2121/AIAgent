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

export async function getImportantNews(limit = 8): Promise<ReportNews[]> {
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
