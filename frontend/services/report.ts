import { apiRequest } from './api';
import type { DailyReport } from './types';

export function getDailyReport(date: string) {
  return apiRequest<DailyReport>(
    `/api/daily-report/${encodeURIComponent(date)}`
  );
}

export function getTodayReport() {
  return apiRequest<DailyReport>(
    '/api/daily-report/today'
  );
}

export function getLatestReport() {
  return apiRequest<DailyReport>(
    '/api/daily-report/latest',
    { cache: 'no-store' }
  );
}

export function getReportRange(
  startDate: string,
  endDate: string
) {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
  });

  return apiRequest<DailyReport[]>(
    `/api/daily-report/range?${params.toString()}`
  );
}