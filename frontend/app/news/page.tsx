'use client';

import { useEffect, useState } from 'react';
import Header from '@/app/components/Header';
import { getNewsList, ReportNews } from '@/services/api';

export default function NewsPage() {
  const [news, setNews] = useState<ReportNews[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    getNewsList({ limit: 50 }).then((result) => setNews(result.data)).catch(console.error).finally(() => setLoading(false));
  }, []);
  return <main className="app-shell"><Header /><div className="content-wrap subpage"><div className="page-intro compact-intro"><h1>全部新闻</h1><p>按最新发布时间查看数据库中已收录的新闻。</p></div>{loading ? <div className="loading-inline">正在加载新闻…</div> : <div className="news-grid news-grid-wide">{news.map((item, index) => <article className="news-card" key={item.id}><div className="news-meta"><span>{String(index + 1).padStart(2, '0')} / {item.source || '未知来源'}</span><strong>{item.importance || 0}.0</strong></div><h3>{item.title}</h3><p className="news-summary">{item.summary || '暂无摘要。'}</p><div className="news-actions">{item.url && <a href={item.url} target="_blank" rel="noreferrer">查看原文 ↗</a>}<span>{item.published || ''}</span></div></article>)}</div>}{!loading && !news.length && <section className="empty-panel"><h2>暂无新闻</h2><p>数据库中还没有可展示的新闻。</p></section>}</div></main>;
}