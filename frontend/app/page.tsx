'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import { DailyReport, getDashboardStats, getLatestReport, getReportRange, getTodayReport } from '@/services/api';

export default function Home() {
  const [report, setReport] = useState<DailyReport | null>(null);
  const [stats, setStats] = useState({ news: 0, reports: 0, events: 0 });
  const [loading, setLoading] = useState(true);
  const now = new Date();
  const updatedAt = `更新于 ${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  useEffect(() => {
    getTodayReport().catch(() => getLatestReport()).then(setReport).catch(() => setReport(null)).finally(() => setLoading(false));
    Promise.all([
      getDashboardStats(),
      getReportRange('2000-01-01', new Date().toISOString().split('T')[0]),
    ]).then(([dashboard, reports]) => {
      setStats({ news: dashboard.total_news, reports: reports.length, events: reports.reduce((total, item) => total + item.report.events.length, 0) });
    }).catch(() => undefined);
  }, []);

  if (loading) return <div className="loading-screen"><span className="pulse-dot" />正在加载今日日报</div>;
  return <main className="app-shell"><Header /><div className="content-wrap home-page">
    <section className="hero"><div><h1>AI News Agent</h1><p className="hero-copy">集中查看最新动态、重要事件和趋势方向，快速掌握人工智能世界正在发生什么。</p></div>{report && <Link className="primary-button" href={`/report/${report.date}`}>查看完整日报 <span>↗</span></Link>}</section>
    <section className="database-overview" aria-label="数据库统计"><div className="overview-heading"><div><p className="eyebrow">DATABASE PULSE</p><h2>数据库概览</h2></div><span className="overview-updated">{updatedAt}</span></div><div className="overview-cards"><Link className="overview-card" href="/news"><span className="overview-label">NEWS</span><strong>{stats.news}</strong><small>采集新闻总量</small></Link><Link className="overview-card" href="/reports"><span className="overview-label">DAILY REPORTS</span><strong>{stats.reports}</strong><small>已生成日报期数</small></Link><Link className="overview-card" href="/trends"><span className="overview-label">EVENTS</span><strong>{stats.events}</strong><small>近 30 天聚合事件</small></Link></div></section>
    {report && <section className="today-report"><div className="section-heading"><div><p className="eyebrow">{report.date}</p><h2>最新日报</h2></div><span className="muted">{report.report.events.length} 个主要事件</span></div><p className="report-overview report-overview-brief">{report.overview}</p><Link className="text-link" href={`/report/${report.date}`}>阅读完整日报 ↗</Link></section>}
  </div></main>;
}
