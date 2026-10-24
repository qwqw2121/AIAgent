'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getDailyReport, DailyReport } from '@/services/api';
import Header from '@/app/components/Header';
import ReportView from '@/app/components/ReportView';

export default function ReportPage() {
  const params = useParams();
  const router = useRouter();
  const date = params.date as string;

  const [report, setReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!date) return;
    if (date === 'today') {
      router.replace(`/report/${new Date().toISOString().split('T')[0]}`);
      return;
    }
    setLoading(true);
    getDailyReport(date)
      .then((data) => {
        setReport(data);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '获取日报失败'))
      .finally(() => setLoading(false));
  }, [date, router]);

  if (loading) {
    return (
      <div className="loading-screen">
        <span className="pulse-dot" />
        正在加载日报
      </div>
    );
  }

  return (
    <main className="app-shell report-page">
      <Header />
      <div className="content-wrap report-reader">
        <div className="back-row">
          <Link href="/reports" className="back-link">← 所有新闻日报</Link>
          <Link href="/" className="back-link">返回首页</Link>
        </div>
        {error || !report ? (
          <section className="empty-panel error-panel">
            <h2>日报暂时无法显示</h2>
            <p>{error || '没有找到这一天的日报'}</p>
          </section>
        ) : (
          <ReportView report={report} />
        )}
      </div>
    </main>
  );
}