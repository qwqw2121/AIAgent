import { apiRequest } from './api';
import type { DashboardStats, TrendData } from './types';

export function getDashboardStats() {
  return apiRequest<DashboardStats>(
    '/api/dashboard/stats',
    { cache: 'no-store' }
  );
}

export function getTrends(days = 30) {
  const params = new URLSearchParams({
    days: String(days),
  });

  return apiRequest<TrendData>(
    `/api/trends?${params.toString()}`
  );
}