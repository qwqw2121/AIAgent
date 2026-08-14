"use client";

import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { getNewsById, type News } from "../../../lib/api";

export default function NewsDetail({ params }: { params: { id: string } }) {
  const [item, setItem] = useState<News | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getNewsById(params.id).then(setItem).catch((e) => setError(e.message)); }, [params.id]);
  if (error) return <main className="content"><div className="card p-8 text-red-600">{error}</div></main>;
  if (!item) return <main className="content"><div className="card p-8 muted">加载中……</div></main>;
  return <main className="content">
    <Link href="/news" className="text-sm text-violet-600 inline-flex items-center gap-2 mb-6"><ArrowLeft size={15}/>返回新闻中心</Link>
    <article className="card p-8 md:p-10">
      <div className="flex flex-wrap gap-2">{(item.llm_category || item.category) && <span className="badge">{item.llm_category || item.category}</span>}{item.importance && <span className="badge badge-soft">重要性 {item.importance}/5</span>}</div>
      <h1 className="text-3xl md:text-4xl font-semibold leading-tight mt-5">{item.title}</h1>
      <div className="text-sm muted mt-4">{item.source || "未知来源"} {item.published ? `· ${item.published}` : ""}</div>
      {item.summary && <section className="mt-8 rounded-2xl bg-violet-50 p-6"><div className="font-semibold text-violet-800">AI 摘要</div><p className="mt-3 text-sm leading-8 text-violet-950/80">{item.summary}</p></section>}
      <div className="mt-9 pt-6 border-t border-zinc-100 flex justify-between items-center"><span className="text-xs muted">原始 URL</span><a href={item.url} target="_blank" rel="noreferrer" className="btn btn-primary">打开来源 <ExternalLink size={15}/></a></div>
      {item.content && <details className="mt-6"><summary className="cursor-pointer text-sm font-medium">查看正文</summary><div className="mt-4 text-sm leading-8 whitespace-pre-wrap text-zinc-600">{item.content}</div></details>}
    </article>
  </main>;
}
