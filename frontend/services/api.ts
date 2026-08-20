const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface DailyReport {
  date: string;
  overview: string;
  report: any;
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
