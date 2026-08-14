"use client";

import { useEffect, useState } from "react";
import NewsCard from "../../components/NewsCard";
import { getNews, type News } from "../../lib/api";

export default function NewsPage() {
  const [items, setItems] = useState<News[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    getNews(`?limit=50${q ? `&q=${encodeURIComponent(q)}` : ""}`)
      .then((data) => { setItems(data.data); setTotal(data.total); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return <main className="content">
    <div className="mb-7"><div className="text-xs uppercase tracking-[.18em] text-violet-500">NEWS CENTER</div><h1 className="text-3xl font-semibold mt-2">新闻中心</h1><p className="muted mt-2">当前共 {total.toLocaleString()} 条去重后的新闻。</p></div>
    <div className="card p-4 mb-5 flex gap-3"><input value={q} onChange={(e)=>setQ(e.target.value)} onKeyDown={(e)=>e.key === "Enter" && load()} placeholder="搜索标题、摘要、关键词……" className="flex-1 outline-none text-sm"/><button onClick={load} className="btn btn-primary">搜索</button></div>
    {loading ? <div className="card p-10 text-center muted">正在从 FastAPI 读取 SQLite……</div> : <div className="grid gap-4">{items.map((item)=><NewsCard key={item.id} item={item}/>)}</div>}
  </main>;
}
