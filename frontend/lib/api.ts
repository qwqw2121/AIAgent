export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type News = {
  id: number;
  url: string;
  title: string;
  source?: string | null;
  language?: string | null;
  category?: string | null;
  published?: string | null;
  crawl_time?: string | null;
  content?: string | null;
  summary?: string | null;
  llm_category?: string | null;
  keywords?: string | null;
  importance?: number | null;
  status?: string | null;
};

export type DashboardStats = {
  total_news: number;
  today_news: number;
  sources: number;
  important_news: number;
  categories: { name: string; count: number }[];
  sources_top: { name: string; count: number; latest?: string | null }[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}

export function getDashboardStats() {
  return request<DashboardStats>("/api/dashboard/stats");
}

export function getNews(params = "") {
  return request<{ data: News[]; total: number }>(`/api/news${params}`);
}

export function getNewsById(id: string | number) {
  return request<News>(`/api/news/${id}`);
}

export function getSources() {
  return request<{ data: { name: string; count: number; latest?: string | null }[] }>("/api/sources");
}

export function getEvents() {
  return request<{ implemented: boolean; message?: string; data: any[] }>("/api/events");
}

export function getDailyReport() {
  return request<{ implemented: boolean; message: string }>("/api/reports/daily");
}

export function getMonthlyReport() {
  return request<{ implemented: boolean; message: string }>("/api/reports/monthly");
}

export function askRag(question: string) {
  return request<{ implemented: boolean; question: string; message: string; sources: any[] }>("/api/rag/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}
