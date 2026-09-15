'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Header from '@/app/components/Header';
import Assistant from '@/app/components/Assistant';
import { getNewsList, ReportNews } from '@/services/api';

function ImportantContent() {
  const searchParams = useSearchParams();
  const topic = searchParams.get('topic') || '';
  const [news, setNews] = useState<ReportNews[]>([]);
  const [total, setTotal] = useState(0);
  useEffect(() => { getNewsList({ limit: 50, q: topic || undefined, importance: topic ? undefined : 7 }).then((result) => { setNews(result.data); setTotal(result.total); }).catch(console.error); }, [topic]);

  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro"><p className="eyebrow">新闻精选</p><h1>{topic ? `${topic} 相关新闻` : '重要新闻'}</h1><p>{topic ? `包含标题、摘要或关键词中提到“${topic}”的新闻。` : '按重要程度整理最近值得关注的新闻。'} 共 {total} 条。</p></div><div className="news-grid news-grid-wide">{news.map((item, index) => <article className="news-card" key={item.id}><div className="news-meta"><span>0{index + 1} / {item.source || '未知来源'}</span><strong>{item.importance || 0}.0</strong></div><h3>{item.title}</h3><p>{item.summary || '暂无摘要。'}</p><div className="news-actions">{item.url && <a href={item.url} target="_blank" rel="noreferrer">查看原文 ↗</a>}<span>{item.published || ''}</span></div></article>)}</div>{!news.length && <section className="empty-panel"><h2>暂时没有相关新闻</h2><p>换一个技术方向，或者回到趋势页查看其他主题。</p></section>}</div><Assistant /></main>;
}

export default function ImportantPage() {
  return <Suspense fallback={<div className="loading-screen"><span className="pulse-dot" />正在加载重要新闻</div>}><ImportantContent /></Suspense>;
}
