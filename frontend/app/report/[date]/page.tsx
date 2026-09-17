'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getDailyReport, DailyReport, DailyReportContent, ReportNews } from '@/services/api';
import Header from '@/app/components/Header';

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

  return <main className="app-shell report-page"><Header /><div className="content-wrap report-reader">
    <Link href="/" className="back-link">← 返回首页</Link>
    <header className="report-header"><p className="eyebrow">DAILY BRIEF</p><h1>AI 新闻日报</h1><p className="report-date-large">{report.date}</p></header>
    <section className="report-lede"><span>编辑摘要</span><p>{report.overview}</p></section>
    <div className="report-section-heading"><h2>今日要闻</h2><span>{report.report.events.length} 个事件</span></div>
    <div className="report-events">{(report.report as DailyReportContent).events?.map((event, index) => <article key={`${event.title}-${index}`} className="report-event-card"><div className="report-event-index">{String(index + 1).padStart(2, '0')}</div><div className="report-event-main"><h3>{event.title}</h3>{event.summary && <p className="report-event-summary">{event.summary}</p>}{event.why_it_matters && <p className="report-why"><strong>为什么重要</strong>{event.why_it_matters}</p>}<div className="report-news-list">{event.news?.map((news) => <div key={news.id} className="report-news-item"><div className="report-news-meta"><span>{news.source || '未知来源'}</span>{news.published && <span>{formatPublished(news.published)}</span>}{news.importance !== undefined && <span>重要性 {news.importance}/10</span>}</div><h4>{news.title}</h4>{news.summary && <p>{news.summary}</p>}{keywordsOf(news).length > 0 && <div className="keyword-list">{keywordsOf(news).map((keyword) => <span key={keyword}>{keyword}</span>)}</div>}{news.content && <details><summary>查看正文</summary><p>{news.content}</p></details>}{news.url && <a href={news.url} target="_blank" rel="noreferrer">打开原文 ↗</a>}</div>)}</div></div></article>)}</div>
  </div></main>;
}
