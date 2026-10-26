'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Header from '@/app/components/Header';
import ReportView from '@/app/components/ReportView';
import { DailyReport, getReportRange } from '@/services/api';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
const pad = (n: number) => String(n).padStart(2, '0');
const todayStr = () => new Date().toISOString().split('T')[0];

function shiftMonth(month: string, delta: number) {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  const weekdayOf = (date: string) =>
  WEEKDAYS[(new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7];
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`;
}

export default function ReportsPage() {
  const [reports, setReports] = useState<DailyReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedMonth, setSelectedMonth] = useState(todayStr().slice(0, 7));
  const [selectedDate, setSelectedDate] = useState('');

  useEffect(() => {
    getReportRange('2000-01-01', todayStr())
      .then((data) => {
        setReports(data);
        const sorted = data.map((r) => r.date).sort();
        const wanted = new URLSearchParams(window.location.search).get('date');
        if (wanted && sorted.includes(wanted)) {
          setSelectedDate(wanted);
          setSelectedMonth(wanted.slice(0, 7));
        } else if (sorted.length) {
          setSelectedMonth(sorted[sorted.length - 1].slice(0, 7));
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const reportMap = useMemo(() => new Map(reports.map((r) => [r.date, r])), [reports]);
  const dates = useMemo(() => reports.map((r) => r.date).sort(), [reports]);

  const monthReports = useMemo(
    () =>
      reports
        .filter((r) => r.date.startsWith(selectedMonth))
        .sort((a, b) => b.date.localeCompare(a.date)),
    [reports, selectedMonth],
  );

  const minMonth = dates.length ? dates[0].slice(0, 7) : selectedMonth;
  const maxMonth = dates.length ? dates[dates.length - 1].slice(0, 7) : selectedMonth;
  const clamp = (m: string) => (m < minMonth ? minMonth : m > maxMonth ? maxMonth : m);
  const canGo = (delta: number) => clamp(shiftMonth(selectedMonth, delta)) !== selectedMonth;

  const go = (delta: number) => {
    const next = clamp(shiftMonth(selectedMonth, delta));
    setSelectedMonth(next);
    if (selectedDate && !selectedDate.startsWith(next)) {
      setSelectedDate('');
      window.history.replaceState(null, '', '/reports');
    }
  };

  const selectDate = (date: string) => {
    setSelectedDate(date);
    window.history.replaceState(null, '', `/reports?date=${date}`);
  };

  const clearSelection = () => {
    setSelectedDate('');
    window.history.replaceState(null, '', '/reports');
  };

  const selectedReport = reportMap.get(selectedDate);
  const monthCount = monthReports.length;

  const [year, month] = selectedMonth.split('-').map(Number);
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const firstWeekday = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
  const today = todayStr();
  const weekdayOf = (date: string) =>
  WEEKDAYS[(new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7];
  
  return (
    <main className="app-shell">
      <Header />
      <div className="content-wrap subpage">
        <div className="page-intro compact-intro reports-intro">
          <div className="reports-intro-text">
            <h1>所有新闻日报</h1>
            <p>按日期快速定位已经生成的日报。</p>
          </div>

          {!loading && (
            <section className="report-guide">
              <div className="guide-head">
                <div className="guide-nav-group">
                  <button className="guide-nav" onClick={() => go(-12)} disabled={!canGo(-12)} aria-label="上一年">«</button>
                  <button className="guide-nav" onClick={() => go(-1)} disabled={!canGo(-1)} aria-label="上个月">‹</button>
                </div>
                <div className="guide-month">{year} 年 {month} 月</div>
                <div className="guide-nav-group">
                  <button className="guide-nav" onClick={() => go(1)} disabled={!canGo(1)} aria-label="下个月">›</button>
                  <button className="guide-nav" onClick={() => go(12)} disabled={!canGo(12)} aria-label="下一年">»</button>
                </div>
              </div>

              <div className="guide-weekdays">
                {WEEKDAYS.map((w) => (
                  <span key={w}>{w}</span>
                ))}
              </div>

              <div className="guide-grid">
                {Array.from({ length: firstWeekday }, (_, i) => (
                  <span className="guide-cell" key={`blank-${i}`} />
                ))}
                {Array.from({ length: daysInMonth }, (_, i) => {
                  const day = i + 1;
                  const date = `${selectedMonth}-${pad(day)}`;
                  const r = reportMap.get(date);
                  const cls = `guide-day${r ? ' has-report' : ''}${date === today ? ' is-today' : ''}${date === selectedDate ? ' is-selected' : ''}`;
                  return (
                    <span className="guide-cell" key={date}>
                      {r ? (
                        <button
                          type="button"
                          className={cls}
                          onClick={() => selectDate(date)}
                          title={`${r.report.events.length} 个事件`}
                          aria-pressed={date === selectedDate}
                        >
                          {day}
                        </button>
                      ) : (
                        <span className={cls}>{day}</span>
                      )}
                    </span>
                  );
                })}
              </div>
              <p className="guide-foot">本月共 {monthCount} 期日报</p>
            </section>
          )}
        </div>

        {loading ? (
          <div className="loading-inline">正在加载日报…</div>
        ) : selectedReport ? (
          <section className="report-embedded">
            <div className="embedded-actions">
              <button type="button" className="text-link" onClick={clearSelection}>
                ← 返回本月列表
              </button>
              <Link className="text-link" href={`/report/${selectedReport.date}`}>
                在单独页面打开 ↗
              </Link>
            </div>
            <ReportView report={selectedReport} embedded />
          </section>
       ) : monthReports.length > 0 ? (
          <section className="month-overview">
            <div className="month-overview-head">
              <h2>{year} 年 {month} 月 · 日报总结</h2>
              <span>共 {monthCount} 期</span>
            </div>
            <div className="report-calendar">
              {monthReports.map((report) => (
                <button
                  type="button"
                  className="report-calendar-item"
                  key={report.date}
                  onClick={() => selectDate(report.date)}
                >
                  <div className="report-calendar-head">
                    <span className="report-date">
                      {report.date.slice(8)} 日
                      <em>周{weekdayOf(report.date)}</em>
                    </span>
                    <span className="report-count">
                      <strong>{report.report.events.length}</strong>
                      <small> 个事件</small>
                    </span>
                  </div>
                  <p>{report.overview || '查看当天 AI 新闻摘要'}</p>
                </button>
              ))}
            </div>
          </section>
        ) : (
          <section className="empty-panel">
            <h2>该月份暂无日报</h2>
            <p>请选择其他月份查看已生成的日报。</p>
          </section>
        )}
      </div>
    </main>
  );
}