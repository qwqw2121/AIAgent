'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getDailyReport, DailyReport, DailyReportContent, ReportNews } from '@/services/api';

function formatPublished(value?: string) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN');
}

function keywordsOf(news: ReportNews) {
  if (Array.isArray(news.keywords)) return news.keywords;
  if (!news.keywords) return [];
  try {
    const parsed = JSON.parse(news.keywords);
    return Array.isArray(parsed) ? parsed : [news.keywords];
  } catch {
    return [news.keywords];
  }
}

export default function ReportPage() {
  const params = useParams();
  const router = useRouter();
  const date = params.date as string;
  
  const [report, setReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (date) {
      if (date === 'today') {
        const today = new Date().toISOString().split('T')[0];
        router.replace(`/report/${today}`);
        return;
      }

      getDailyReport(date)
        .then(data => {
          setReport(data);
          setLoading(false);
        })
        .catch(err => {
          setError(err.message);
          setLoading(false);
        });
    }
  }, [date, router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="text-red-500 text-xl mb-4">❌ {error}</div>
          <Link href="/" className="text-blue-500 hover:underline">
            返回首页
          </Link>
        </div>
      </div>
    );
  }

  if (!report) return null;

  return (
    <main className="min-h-screen p-8 bg-gray-50">
      <div className="max-w-4xl mx-auto">
        <div className="mb-6">
          <Link href="/" className="text-blue-500 hover:underline">
            ← 返回首页
          </Link>
        </div>

        <div className="bg-white rounded-lg shadow-md p-8">
          <h1 className="text-3xl font-bold mb-2">📰 AI 新闻日报</h1>
          <p className="text-gray-500 mb-6">{report.date}</p>

          <div className="bg-gray-50 rounded-lg p-6 mb-6">
            <h2 className="text-xl font-semibold mb-3">📊 概览</h2>
            <p className="text-gray-700">{report.overview}</p>
          </div>

          <div>
            <h2 className="text-xl font-semibold mb-4">📋 今日要闻</h2>
            <div className="space-y-6">
              {(report.report as DailyReportContent).events?.map((event, index) => (
                <article key={`${event.title}-${index}`} className="border border-gray-200 rounded-lg p-5">
                  <h3 className="text-lg font-semibold">{index + 1}. {event.title}</h3>
                  {event.summary && <p className="text-gray-700 mt-3 leading-7">{event.summary}</p>}
                  {event.why_it_matters && (
                    <p className="mt-3 border-l-4 border-blue-400 pl-3 text-gray-600 leading-7">
                      <strong>关注理由：</strong>{event.why_it_matters}
                    </p>
                  )}

                  <div className="mt-5 space-y-4">
                    {event.news?.map((news) => (
                      <div key={news.id} className="bg-gray-50 rounded-lg p-4">
                        <div className="flex flex-wrap items-center gap-2 text-sm text-gray-500">
                          <span>{news.source || '未知来源'}</span>
                          {news.published && <span>· {formatPublished(news.published)}</span>}
                          {news.importance !== undefined && <span>· 重要性 {news.importance}/10</span>}
                        </div>
                        <h4 className="font-medium text-gray-900 mt-2">{news.title}</h4>
                        {news.summary && <p className="text-gray-700 mt-2 leading-7">{news.summary}</p>}
                        {keywordsOf(news).length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-3">
                            {keywordsOf(news).map((keyword) => (
                              <span key={keyword} className="text-xs bg-white border border-gray-200 rounded px-2 py-1 text-gray-600">
                                {keyword}
                              </span>
                            ))}
                          </div>
                        )}
                        {news.content && (
                          <details className="mt-4">
                            <summary className="cursor-pointer text-sm text-blue-600">查看正文</summary>
                            <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700 leading-7">{news.content}</p>
                          </details>
                        )}
                        {news.url && (
                          <a href={news.url} target="_blank" rel="noreferrer" className="inline-block mt-3 text-sm text-blue-600 hover:underline">
                            打开原文 ↗
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
