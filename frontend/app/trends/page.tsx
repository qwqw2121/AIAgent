'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import Assistant from '@/app/components/Assistant';
import { DailyReport, getReportRange, getTrends, TrendData } from '@/services/api';

const emptyTrend: TrendData = { days: 30, total_news: 0, important_news: 0, main_events: 0, hot_directions: 0, hot_tech: [], daily_counts: [], events: [] };
const dateRange = () => {
  const end = new Date().toISOString().split('T')[0];
  const start = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  return { start, end };
};

export default function TrendsPage() {
  const [trend, setTrend] = useState(emptyTrend);
  const [reports, setReports] = useState<DailyReport[]>([]);
  useEffect(() => {
    const { start, end } = dateRange();
    Promise.all([getTrends(), getReportRange(start, end)]).then(([data, reportData]) => { setTrend(data); setReports(reportData); }).catch(console.error);
  }, []);
  const max = trend.hot_tech[0]?.count || 1;
  const eventReport = (title: string) => reports.find((report) => report.report.events.some((event) => event.title === title));

  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro"><p className="eyebrow">近 30 天</p><h1>趋势与方向</h1><p>看看最近一个月，AI 讨论的重点正在向哪里移动。</p></div><section className="metrics-grid">{[['新闻总数', trend.total_news], ['重要新闻', trend.important_news], ['主要事件', trend.main_events], ['热门方向', trend.hot_directions]].map(([label, value]) => <div className="metric" key={label as string}><span>{label}</span><strong>{value}</strong><small>过去 30 天</small></div>)}</section><section className="section-grid"><div className="panel"><div className="section-heading"><div><p className="eyebrow">关键词热度</p><h2>热门技术</h2></div><span className="muted">点击查看相关新闻</span></div><div className="tech-list">{trend.hot_tech.map((tech, index) => <Link className="tech-row tech-link" href={`/important?topic=${encodeURIComponent(tech.name)}`} key={tech.name}><span>{tech.name}</span><div className="bar-track"><div className={`bar bar-${index}`} style={{ width: `${Math.max(12, tech.count / max * 100)}%` }} /></div><b>{tech.count} 篇</b></Link>)}</div></div><div className="panel"><div className="section-heading"><div><p className="eyebrow">事件聚合</p><h2>重要事件</h2></div><span className="muted">点击查看日报</span></div>{trend.events.slice(0, 10).map((event) => { const report = eventReport(event.title); return <Link className="event-row event-link" href={report ? `/report/${report.date}` : '/reports'} key={`${event.rank}-${event.title}`}><span>0{event.rank}</span><p>{event.title}<small>查看详情 ↗</small></p></Link>; })}</div></section></div><Assistant /></main>;
}
