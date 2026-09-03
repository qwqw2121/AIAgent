'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getReportRange, DailyReport, ReportNews } from '@/services/api';

export default function Home() {
  const [recentReports, setRecentReports] = useState<DailyReport[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const endDate = new Date().toISOString().split('T')[0];
        const startDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)
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

  const importantNews = recentReports
    .flatMap((report) => report.report.events.flatMap((event) => event.news || []))
    .reduce<ReportNews[]>((news, item) => {
      if (!news.some((existing) => existing.id === item.id)) news.push(item);
      return news;
    }, [])
    .sort((first, second) => (second.importance || 0) - (first.importance || 0))
    .slice(0, 8);

  const latestReport = recentReports[0];

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">加载中...</div>
      </div>
    );
  }

  return (
    <main className="min-h-screen p-8 bg-gray-50">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-4xl font-bold mb-8">🤖 AI 新闻日报</h1>
        
        {latestReport ? (
          <div className="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 className="text-2xl font-semibold mb-2">
              📰 最近日报 - {latestReport.date}
            </h2>
            <p className="text-gray-700 mb-4">{latestReport.overview}</p>
            <Link
              href={`/report/${latestReport.date}`}
              className="inline-block bg-blue-500 text-white px-6 py-2 rounded-lg hover:bg-blue-600 transition-colors"
            >
              查看完整日报 →
            </Link>
          </div>
        ) : (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 mb-8">
            <p className="text-yellow-700">暂无已生成的日报</p>
          </div>
        )}

        {recentReports.length > 0 && (
          <div className="bg-white rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold mb-4">📚 过往日报（最近 30 天）</h3>
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

        {importantNews.length > 0 && (
          <div className="bg-white rounded-lg shadow-md p-6 mt-8">
            <h3 className="text-lg font-semibold mb-4">🔥 重点新闻</h3>
            <div className="grid gap-4 md:grid-cols-2">
              {importantNews.map((news) => (
                <article key={news.id} className="border border-gray-100 rounded-lg p-4">
                  <div className="flex items-center justify-between gap-3 text-sm text-gray-500">
                    <span>{news.source || '未知来源'}</span>
                    <span>重要性 {news.importance || 0}/10</span>
                  </div>
                  <h4 className="font-medium mt-2">{news.title}</h4>
                  {news.summary && (
                    <p className="text-sm text-gray-600 mt-2 line-clamp-3">{news.summary}</p>
                  )}
                  <div className="flex gap-4 mt-3 text-sm">
                    <Link href={`/report/${recentReports.find((report) => report.report.events.some((event) => event.news?.some((item) => item.id === news.id)))?.date || latestReport?.date || ''}`} className="text-blue-600 hover:underline">
                      查看日报
                    </Link>
                    {news.url && (
                      <a href={news.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                        打开原文 ↗
                      </a>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
