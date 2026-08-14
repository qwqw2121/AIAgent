"use client";

import Link from "next/link";
import { ArrowRight, Database, Newspaper, Rss, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import NewsCard from "../components/NewsCard";
import { getDashboardStats, getNews, type DashboardStats, type News } from "../lib/api";

export default function Home() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [news, setNews] = useState<News[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getDashboardStats(), getNews("?limit=6")])
      .then(([s, n]) => { setStats(s); setNews(n.data); })
      .catch((e) => setError(`无法连接 FastAPI：${e.message}`));
  }, []);

  return (
    <main className="content">
      <div className="purple-panel rounded-3xl p-8 md:p-10 mb-7">
        <div className="flex items-center gap-2 text-sm text-white/80"><Sparkles size={16}/> LIVE FROM YOUR NEWS DATABASE</div>
        <h1 className="text-4xl md:text-5xl font-semibold mt-4">今天，AI 圈发生了什么？</h1>
        <p className="mt-4 max-w-3xl text-white/80 leading-8">现在这块已经不再使用 Demo 数据，而是直接读取你的 <code>storage/news.db</code>，通过 FastAPI 提供给 Next.js。</p>
      </div>

      {error && <div className="card p-5 mb-7 border-red-200 text-red-600">{error}<div className="text-xs mt-2 text-red-400">确认 FastAPI 已在 http://localhost:8000 启动。</div></div>}

      <div className="grid-4 mb-7">
        <Stat icon={<Newspaper size={17}/>} label="新闻总量" value={stats ? stats.total_news.toLocaleString() : "—"}/>
        <Stat icon={<Sparkles size={17}/>} label="今日新闻" value={stats ? stats.today_news.toLocaleString() : "—"}/>
        <Stat icon={<Rss size={17}/>} label="信息来源" value={stats ? stats.sources.toLocaleString() : "—"}/>
        <Stat icon={<Database size={17}/>} label="重要新闻" value={stats ? stats.important_news.toLocaleString() : "—"}/>
      </div>

      <div className="grid-2 mb-9">
        <section className="card p-7">
          <div className="flex items-center justify-between"><div><h2 className="text-xl font-semibold">新闻分类</h2><p className="text-sm muted mt-1">来自 news.llm_category / category</p></div></div>
          <div className="mt-6 space-y-4">
            {(stats?.categories || []).slice(0, 6).map((x) => {
              const max = Math.max(...(stats?.categories || []).map((a) => a.count), 1);
              const width = `${Math.round((x.count / max) * 100)}%`;
              return <div key={x.name}><div className="flex justify-between text-sm mb-2"><span>{x.name}</span><span className="muted">{x.count}</span></div><div className="h-2 rounded-full bg-zinc-100"><div className="h-2 rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-400" style={{width}}/></div></div>;
            })}
          </div>
        </section>
        <section className="purple-panel rounded-2xl p-7">
          <div className="text-sm font-medium">下一阶段</div>
          <h2 className="text-2xl font-semibold mt-3">让事件、RAG 和报告真正接入</h2>
          <p className="mt-3 text-sm text-white/80 leading-7">当前网页已经通过统一 API 把 SQLite 新闻数据接进来了。事件聚类、日报/月报和 RAG 后续只需要继续实现对应 FastAPI 服务，不需要改整体网页结构。</p>
          <div className="flex gap-3 mt-6"><Link className="btn bg-white text-violet-700 border-white" href="/events">事件中心 <ArrowRight size={15}/></Link><Link className="btn bg-transparent text-white border-white/30" href="/rag">RAG 工作台</Link></div>
        </section>
      </div>

      <div className="flex items-end justify-between mb-4"><div><h2 className="text-2xl font-semibold">最新资讯</h2><p className="text-sm muted mt-1">实时读取 SQLite</p></div><Link href="/news" className="text-sm text-violet-600 inline-flex items-center gap-1">全部新闻 <ArrowRight size={15}/></Link></div>
      <div className="grid gap-4">{news.map((item) => <NewsCard key={item.id} item={item}/>)}</div>
    </main>
  );
}

function Stat({icon, label, value}: {icon: React.ReactNode; label:string; value:string}) {
  return <div className="card p-5"><div className="flex items-center gap-2 text-violet-600">{icon}<span className="text-xs muted">{label}</span></div><div className="text-3xl font-semibold mt-3">{value}</div></div>;
}
