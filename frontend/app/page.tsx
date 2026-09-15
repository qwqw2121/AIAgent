'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import Assistant from '@/app/components/Assistant';
import { DailyReport, getTodayReport } from '@/services/api';

export default function Home() {
  const [report, setReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTodayReport().then(setReport).catch(() => setReport(null)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading-screen"><span className="pulse-dot" />正在加载今日日报</div>;
  return <main className="app-shell"><Header /><div className="content-wrap home-page">
    <section className="hero"><div><p className="eyebrow">今日 AI 资讯</p><h1>今天发生了什么？</h1><p className="hero-copy">一份简洁的日报，帮你快速了解今天最重要的人工智能动态。</p></div>{report && <Link className="primary-button" href={`/report/${report.date}`}>查看完整日报 <span>↗</span></Link>}</section>
    {report ? <section className="today-report"><div className="section-heading"><div><p className="eyebrow">{report.date}</p><h2>今日日报</h2></div><span className="muted">{report.report.events.length} 个主要事件</span></div><p className="report-overview">{report.overview}</p><div className="event-list">{report.report.events.slice(0, 6).map((event, index) => <article className="daily-event" key={`${event.title}-${index}`}><span className="event-number">0{index + 1}</span><div><h3>{event.title}</h3><p>{event.summary || event.why_it_matters || '暂无补充说明。'}</p></div></article>)}</div></section> : <section className="empty-panel"><h2>今日日报尚未生成</h2><p>可以先查看趋势、重要新闻或使用右下角机器人助手。</p></section>}
  </div><Assistant /></main>;
}
