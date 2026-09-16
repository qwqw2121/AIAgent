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
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
  useEffect(() => {
    const { start, end } = dateRange();
    Promise.all([getTrends(), getReportRange(start, end)]).then(([data, reportData]) => { setTrend(data); setReports(reportData); }).catch(console.error);
  }, []);
  const max = trend.hot_tech[0]?.count || 1;
  const eventReport = (title: string) => reports.find((report) => report.report.events.some((event) => event.title === title));

  const visibleEvents = showAllEvents ? trend.events : trend.events.slice(0, 5);
  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro"><h1>趋势与方向</h1><p>看看最近一个月，AI 讨论的重点正在向哪里移动。</p></div><section className="metrics-grid">{[['新闻总数', trend.total_news], ['重要新闻', trend.important_news], ['主要事件', trend.main_events], ['热门方向', trend.hot_directions]].map(([label, value]) => <div className="metric" key={label as string}><span>{label}</span><strong>{value}</strong><small>过去 30 天</small></div>)}</section><section className="section-grid"><div className="panel"><div className="section-heading"><div><h2>热门技术</h2></div></div><div className="tech-list">{trend.hot_tech.map((tech, index) => <Link className="tech-row tech-link" href={`/important?topic=${encodeURIComponent(tech.name)}`} key={tech.name}><span>{tech.name}</span><div className="bar-track"><div className={`bar bar-${index}`} style={{ width: `${Math.max(12, tech.count / max * 100)}%` }} /></div><b>{tech.count} 篇</b></Link>)}</div></div><div className="panel"><div className="section-heading"><div><h2>重要事件</h2></div><span className="muted">展开查看事件详情</span></div>{visibleEvents.map((event) => { const report = eventReport(event.title); const detail = report?.report.events.find((item) => item.title === event.title); const isExpanded = expandedEvent === event.title; return <div className="event-entry" key={`${event.rank}-${event.title}`}><button className="event-row event-link" onClick={() => setExpandedEvent(isExpanded ? null : event.title)}><span>0{event.rank}</span><p>{event.title}<small>{isExpanded ? '收起详情 ↑' : '查看事件详情 ↓'}</small></p></button>{isExpanded && <div className="event-detail"><p>{detail?.summary || '暂无事件摘要。'}</p>{detail?.why_it_matters && <p><strong>关注理由：</strong>{detail.why_it_matters}</p>}</div>}</div>; })}{trend.events.length > 5 && <button className="show-all-button" onClick={() => setShowAllEvents((current) => !current)}>{showAllEvents ? '收起其他事件' : `展开其余 ${trend.events.length - 5} 个事件`}</button>}</div></section></div><Assistant /></main>;
}
