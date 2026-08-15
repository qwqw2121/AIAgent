'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getDailyReport, DailyReport } from '@/services/api';

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

  return (
    <main className="min-h-screen p-8 bg-gray-50">
      <div className="max-w-4xl mx-auto">
        <div className="mb-6">
          <Link href="/" className="text-blue-500 hover:underline">
            ← 返回首页
          </Link>
        </div>

        <div className="bg-white rounded-lg shadow-md p-8">
          <h1 className="text-3xl font-bold mb-2">📰 AI 新闻日报</h1>
          <p className="text-gray-500 mb-6">{report.date}</p>

          <div className="bg-gray-50 rounded-lg p-6 mb-6">
            <h2 className="text-xl font-semibold mb-3">📊 概览</h2>
            <p className="text-gray-700">{report.overview}</p>
          </div>

          <div>
            <h2 className="text-xl font-semibold mb-3">📋 详细报告</h2>
            <div className="bg-gray-50 rounded-lg p-6 overflow-auto">
              <pre className="text-sm whitespace-pre-wrap">
                {JSON.stringify(report.report, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
