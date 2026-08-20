'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getTodayReport, getReportRange, DailyReport } from '@/services/api';

export default function Home() {
  const [todayReport, setTodayReport] = useState<DailyReport | null>(null);
  const [recentReports, setRecentReports] = useState<DailyReport[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const today = await getTodayReport();
        setTodayReport(today);
      } catch (error) {
        console.error('获取今日日报失败:', error);
      }

      try {
        const endDate = new Date().toISOString().split('T')[0];
        const startDate = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
          .toISOString().split('T')[0];
        const reports = await getReportRange(startDate, endDate);
        setRecentReports(reports);
      } catch (error) {
        console.error('获取最近日报失败:', error);
      }

      setLoading(false);
    };

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">加载中...</div>
      </div>
    );
  }

  return (
    <main className="min-h-screen p-8 bg-gray-50">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold mb-8">🤖 AI 新闻日报</h1>
        
        {todayReport ? (
          <div className="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 className="text-2xl font-semibold mb-2">
              📰 今日日报 - {todayReport.date}
            </h2>
            <p className="text-gray-700 mb-4">{todayReport.overview}</p>
            <Link href={`/report/${todayReport.date}`}>
              <button className="bg-blue-500 text-white px-6 py-2 rounded-lg hover:bg-blue-600 transition-colors">
                查看完整日报 →
              </button>
            </Link>
          </div>
        ) : (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 mb-8">
            <p className="text-yellow-700">今日日报尚未生成</p>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-md p-6 mb-8">
          <h3 className="text-lg font-semibold mb-4">📅 查看其他日期</h3>
          <form 
            onSubmit={(e) => {
              e.preventDefault();
              const formData = new FormData(e.target as HTMLFormElement);
              const date = formData.get('date') as string;
              if (date) {
                window.location.href = `/report/${date}`;
              }
            }}
            className="flex gap-4"
          >
            <input
              type="date"
              name="date"
              className="flex-1 border rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              max={new Date().toISOString().split('T')[0]}
              required
            />
            <button
              type="submit"
              className="bg-gray-800 text-white px-6 py-2 rounded-lg hover:bg-gray-700 transition-colors"
            >
              查看
            </button>
          </form>
        </div>

        {recentReports.length > 0 && (
          <div className="bg-white rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold mb-4">📚 最近日报</h3>
            <div className="space-y-3">
              {recentReports.map((report) => (
                <Link
                  key={report.date}
                  href={`/report/${report.date}`}
                  className="block hover:bg-gray-50 p-3 rounded-lg transition-colors border border-gray-100"
                >
                  <div className="flex justify-between items-center">
                    <span className="font-medium">{report.date}</span>
                    <span className="text-blue-500 text-sm">查看详情 →</span>
                  </div>
                  <p className="text-sm text-gray-600 mt-1 line-clamp-2">
                    {report.overview}
                  </p>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
