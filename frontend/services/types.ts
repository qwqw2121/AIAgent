export interface DailyReport {
  date: string;
  overview: string;
  report: DailyReportContent;
}

export interface DailyReportContent {
  overview: string;
  events: ReportEvent[];
}

export interface ReportEvent {
  title: string;
  summary?: string;
  why_it_matters?: string;
  news_ids?: number[];
  news?: ReportNews[];
}

export interface ReportNews {
  id: number;
  title: string;
  source?: string;
  published?: string;
  summary?: string;
  content?: string;
  llm_category?: string;
  category?: string;
  keywords?: string | string[];
  importance?: number;
  url?: string;
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
  total_reports?: number;
  events_30d?: number;
}