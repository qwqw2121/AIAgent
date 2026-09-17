'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import { DailyReport, getReportRange } from '@/services/api';

export default function ReportsPage() {
  const [reports, setReports] = useState<DailyReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedMonth, setSelectedMonth] = useState('');
  useEffect(() => { const end = new Date().toISOString().split('T')[0]; const start = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]; getReportRange(start, end).then((data) => { setReports(data); setSelectedMonth(data[0]?.date.slice(0, 7) || end.slice(0, 7)); }).catch(console.error).finally(() => setLoading(false)); }, []);

  const monthOptions = Array.from(new Set(reports.map((report) => report.date.slice(0, 7)))).sort((left, right) => right.localeCompare(left));
  const selectedReports = reports.filter((report) => report.date.startsWith(selectedMonth));
  const reportDates = new Set(selectedReports.map((report) => report.date));
  const [yearValue, monthValue] = selectedMonth.split('-').map(Number);
  const daysInMonth = selectedMonth ? new Date(yearValue, monthValue, 0).getDate() : 0;
  const calendarDays = Array.from({ length: daysInMonth }, (_, index) => index + 1);
  const monthLabel = selectedMonth ? new Date(yearValue, monthValue - 1, 1).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' }) : '';

  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro compact-intro reports-intro"><div><h1>所有新闻日报</h1><p>按日期快速定位已经生成的日报。</p></div><label className="month-picker"><span>查看月份</span><select value={selectedMonth} onChange={(event) => setSelectedMonth(event.target.value)} disabled={!monthOptions.length}>{monthOptions.map((month) => <option value={month} key={month}>{new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' })}</option>)}</select></label></div>{loading ? <div className="loading-inline">正在加载日报列表…</div> : <>{selectedMonth && <section className="report-guide"><div className="guide-month">{monthLabel}</div><div className="guide-days">{calendarDays.map((day) => { const date = `${selectedMonth}-${String(day).padStart(2, '0')}`; return reportDates.has(date) ? <Link href={`/report/${date}`} className="guide-day has-report" key={date}>{day}</Link> : <span className="guide-day" key={date}>{day}</span>; })}</div></section>}<div className="report-calendar">{selectedReports.map((report) => <Link className="report-calendar-item" href={`/report/${report.date}`} key={report.date}><span className="report-date">{report.date}</span><strong>{report.report.events.length}</strong><small>个事件</small><p>{report.overview || '查看当天 AI 新闻摘要'}</p></Link>)}</div></>}{!loading && !selectedReports.length && <section className="empty-panel"><h2>该月份暂无日报</h2><p>请选择其他月份查看已生成的日报。</p></section>}</div></main>;
}
