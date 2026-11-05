import { apiRequest } from './api';
import type { ReportNews } from './types';

interface NewsOptions {
  limit?: number;
  q?: string;
  importance?: number;
}

interface ImportantNewsOptions {
  limit?: number;
  hours?: number;
  minImportance?: number;
}

export function getNewsList(options: NewsOptions = {}) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
  });

  if (options.q) params.set('q', options.q);

  if (options.importance !== undefined) {
    params.set('importance', String(options.importance));
  }

  return apiRequest<{
    data: ReportNews[];
    total: number;
  }>(`/api/news?${params.toString()}`);
}

export function getImportantNews(
  options: ImportantNewsOptions = {}
) {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 30),
  });

  if (options.hours !== undefined) {
    params.set('hours', String(options.hours));
  }

  if (options.minImportance !== undefined) {
    params.set('min_importance', String(options.minImportance));
  }

  return apiRequest<ReportNews[]>(
    `/api/news/important?${params.toString()}`,
    { cache: 'no-store' }
  );
}