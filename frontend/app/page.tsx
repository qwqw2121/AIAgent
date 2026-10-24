'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import {
  DailyReport,
  ReportNews,
  getDashboardStats,
  getImportantNews,
  getLatestReport,
} from '@/services/api';

function formatTime(value?: string) {
  if (!value) return '';
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function Home() {
  const [report, setReport] = useState<DailyReport | null>(null);
  const [hot, setHot] = useState<ReportNews[]>([]);
  const [stats, setStats] = useState({ news: 0, reports: 0, events: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getLatestReport()
      .then(setReport)
      .catch(() => setReport(null))
      .finally(() => setLoading(false));

    getImportantNews({ limit: 6, hours: 24, minImportance: 7 })
      .then(setHot)
      .catch(() => setHot([]));

    getDashboardStats()
      .then((d) =>
        setStats({
          news: d.total_news,
          reports: d.total_reports ?? 0,
          events: d.events_30d ?? 0,
        })
      )
      .catch(() => undefined);
  }, []);

  if (loading) {
    return (
      <div className="loading-screen">
        <span className="pulse-dot" />
        正在加载今日日报
      </div>
    );
  }

  const reportHref = report ? `/reports?date=${report.date}` : '/reports';

  return (
    <main className="app-shell">
      <Header />
      <div className="content-wrap home-page">
        <section className="hero">
          <div>
            <h1>AI News Agent</h1>
            <p className="hero-copy">
              集中查看最新动态、重要事件和趋势方向，快速掌握人工智能世界正在发生什么。
            </p>
          </div>
          {report && (
            <Link className="primary-button" href={reportHref}>
              查看完整日报 <span>↗</span>
            </Link>
          )}
        </section>

        <section className="database-overview" aria-label="数据库统计">
          <div className="overview-heading">
            <div>
              <p className="eyebrow">DATABASE PULSE</p>
              <h2>数据库概览</h2>
            </div>
          </div>
          <div className="overview-cards">
            <Link className="overview-card" href="/news">
              <span className="overview-label">NEWS</span>
              <strong>{stats.news}</strong>
              <small>采集新闻总量</small>
            </Link>
            <Link className="overview-card" href="/reports">
              <span className="overview-label">DAILY REPORTS</span>
              <strong>{stats.reports}</strong>
              <small>已生成日报期数</small>
            </Link>
            <Link className="overview-card" href="/trends">
              <span className="overview-label">EVENTS</span>
              <strong>{stats.events}</strong>
              <small>近 30 天聚合事件</small>
            </Link>
          </div>
        </section>

        {report && (
          <section className="today-report">
            <div className="section-heading">
              <div>
                <p className="eyebrow">{report.date}</p>
                <h2>最新日报</h2>
              </div>
              <span className="muted">{report.report.events.length} 个主要事件</span>
            </div>
            <p className="report-overview report-overview-brief">{report.overview}</p>
            <Link className="text-link" href={reportHref}>
              阅读完整日报 ↗
            </Link>
          </section>
        )}

        {hot.length > 0 && (
          <section className="today-report hot-news">
            <div className="section-heading">
              <div>
                <p className="eyebrow">LAST 24 HOURS</p>
                <h2>近 24 小时重要新闻</h2>
              </div>
              <span className="muted">{hot.length} 条重要新闻</span>
            </div>

            <div className="event-list">
              {hot.map((n, index) => (
                <div className="daily-event" key={n.id}>
                  <span className="event-number">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>
                      {n.url ? (
                        <a className="hot-link" href={n.url} target="_blank" rel="noreferrer">
                          {n.title}
                        </a>
                      ) : (
                        n.title
                      )}
                    </h3>
                    <p className="hot-summary">{n.summary || '暂无摘要。'}</p>
                    <p className="hot-meta-line">
                      {n.source || '未知来源'} · {formatTime(n.published)} · 重要性 {n.importance ?? 0}/10
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <Link className="text-link" href="/important">
              查看更多重要新闻 ↗
            </Link>
          </section>
        )}
      </div>
    </main>
  );
}