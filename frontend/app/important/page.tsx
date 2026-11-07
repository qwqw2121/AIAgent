'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import Header from '@/app/components/Header';
import { getImportantNews, getTechNews } from '@/services/news';
import { ReportNews } from '@/services/types';

function formatTime(value?: string) {
  if (!value) return '';
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString('zh-CN', {
    hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

function ImportantContent() {
  const searchParams = useSearchParams();
  const topic = searchParams.get('topic') || '';
  const days = Number(searchParams.get('days') || 30);

  const [news, setNews] = useState<ReportNews[]>([]);
  const [total, setTotal] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const request: Promise<ReportNews[]> = topic
      ? getTechNews(topic, days).then((r) => {
          setTotal(r.total);
          return r.items; // 后端已按时间倒序，不再前端二次过滤
        })
      : getImportantNews({ limit: 100, hours: 24 * 7, minImportance: 7 }).then((data) => {
          const sorted = [...data].sort(
            (l, r) =>
              (r.importance || 0) - (l.importance || 0) ||
              String(r.published || '').localeCompare(String(l.published || ''))
          );
          setTotal(sorted.length);
          return sorted;
        });

    request
      .then((data) => {
        setNews(data);
        setShowAll(false);
        setError(null);
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : '获取新闻列表失败')
      );
  }, [topic, days]);

  const visibleNews = showAll ? news : news.slice(0, 8);

  return (
    <main className="app-shell">
      <Header />
      <div className="content-wrap subpage">
        <div className="page-intro compact-intro">
          {topic && (
            <Link href="/trends" className="back-link">← 返回趋势</Link>
          )}
          <h1>{topic ? `${topic} 相关新闻` : '重要新闻'}</h1>
          <p>
            {topic
              ? `近 ${days} 天共 ${total} 篇，按发布时间排序。`
              : '近 7 天重要性 ≥ 7 的新闻，按重要程度排序。'}
          </p>
        </div>
        {error ? (
          <section className="empty-panel error-panel">
            <h2>新闻列表暂时无法加载</h2>
            <p>{error}，请稍后重试。</p>
            <button className="secondary-button" onClick={() => window.location.reload()}>重新加载</button>
          </section>
        ) : (
          <>
            <div className="news-grid news-grid-wide">
              {visibleNews.map((item, index) => (
                <article className="news-card" key={item.id}>
                  <div className="news-meta">
                    <span>{String(index + 1).padStart(2, '0')} / {item.source || '未知来源'}</span>
                    <strong>{item.importance ?? 0}</strong>
                  </div>
                  <h3>{item.title}</h3>
                  <p className="news-summary">{item.summary || '暂无摘要。'}</p>
                  <div className="news-actions">
                    {item.url && <a href={item.url} target="_blank" rel="noreferrer">查看原文 ↗</a>}
                    <span>{formatTime(item.published)}</span>
                  </div>
                </article>
              ))}
            </div>
            {news.length > 8 && (
              <button className="show-all-button" onClick={() => setShowAll((c) => !c)}>
                {showAll ? '收起其余新闻' : `展开其余 ${news.length - 8} 条`}
              </button>
            )}
            {!news.length && (
              <section className="empty-panel">
                <h2>暂时没有相关新闻</h2>
                <p>换一个技术方向，或者回到趋势页查看其他主题。</p>
              </section>
            )}
            {topic && (
              <Link href="/trends" className="back-link back-link-bottom">← 返回趋势</Link>
            )}
          </>
        )}
      </div>
    </main>
  );
}

export default function ImportantPage() {
  return (
    <Suspense fallback={<div className="loading-screen"><span className="pulse-dot" />正在加载重要新闻</div>}>
      <ImportantContent />
    </Suspense>
  );
}