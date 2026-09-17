'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Header from '@/app/components/Header';
import { getNewsList, ReportNews } from '@/services/api';

function ImportantContent() {
  const searchParams = useSearchParams();
  const topic = searchParams.get('topic') || '';
  const [news, setNews] = useState<ReportNews[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getNewsList({ limit: 100, q: topic || undefined })
      .then((result) => {
        const sorted = result.data
          .filter((item) => !topic || `${item.title} ${item.summary || ''} ${item.content || ''} ${item.keywords || ''}`.toLowerCase().includes(topic.toLowerCase()))
          .sort((left, right) => (right.importance || 0) - (left.importance || 0) || String(right.published || '').localeCompare(String(left.published || '')));
        setNews(sorted);
        setShowAll(false);
        setError(null);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : '获取新闻列表失败'));
  }, [topic]);

  const visibleNews = showAll ? news : news.slice(0, 8);
  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro compact-intro"><h1>{topic ? `${topic} 相关新闻` : '重要新闻'}</h1><p>{topic ? '按重要程度整理，并优先显示较新的相关新闻。' : '按重要程度整理最近值得关注的新闻。'}</p></div>{error ? <section className="empty-panel error-panel"><h2>新闻列表暂时无法加载</h2><p>{error}，请稍后重试。</p><button className="secondary-button" onClick={() => window.location.reload()}>重新加载</button></section> : <><div className="news-grid news-grid-wide">{visibleNews.map((item, index) => <article className="news-card" key={item.id}><div className="news-meta"><span>{String(index + 1).padStart(2, '0')} / {item.source || '未知来源'}</span><strong>{item.importance || 0}.0</strong></div><h3>{item.title}</h3><p className="news-summary">{item.summary || '暂无摘要。'}</p><div className="news-actions">{item.url && <a href={item.url} target="_blank" rel="noreferrer">查看原文 ↗</a>}<span>{item.published || ''}</span></div></article>)}</div>{news.length > 8 && <button className="show-all-button" onClick={() => setShowAll((current) => !current)}>{showAll ? '收起其余新闻' : `展开其余 ${news.length - 8} 条`}</button>}{!news.length && <section className="empty-panel"><h2>暂时没有相关新闻</h2><p>换一个技术方向，或者回到趋势页查看其他主题。</p></section>}</>}</div></main>;
}

export default function ImportantPage() {
  return <Suspense fallback={<div className="loading-screen"><span className="pulse-dot" />正在加载重要新闻</div>}><ImportantContent /></Suspense>;
}
