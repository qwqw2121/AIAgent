'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import Assistant from '@/app/components/Assistant';
import { DailyReport, getReportRange } from '@/services/api';

export default function ReportsPage() {
  const [reports, setReports] = useState<DailyReport[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { const end = new Date().toISOString().split('T')[0]; const start = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]; getReportRange(start, end).then(setReports).catch(console.error).finally(() => setLoading(false)); }, []);
  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro"><p className="eyebrow">日报归档</p><h1>所有新闻日报</h1><p>按日期查看已经生成的日报和当天聚合的重点事件。</p></div>{loading ? <div className="loading-inline">正在加载日报列表…</div> : <div className="report-list">{reports.map((report) => <Link className="report-list-item" href={`/report/${report.date}`} key={report.date}><div><span className="report-date">{report.date}</span><h2>{report.overview || '查看当天 AI 新闻摘要'}</h2><p>{report.report.events.length} 个主要事件</p></div><span className="report-arrow">↗</span></Link>)}</div>}{!loading && !reports.length && <section className="empty-panel"><h2>暂无日报</h2><p>日报生成后会显示在这里。</p></section>}</div><Assistant /></main>;
}
