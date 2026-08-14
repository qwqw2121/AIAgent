import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { News } from "../lib/api";

export default function NewsCard({ item }: { item: News }) {
  const keywords = (item.keywords || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 5);

  return (
    <article className="card card-hover p-6">
      <div className="flex flex-wrap gap-2 mb-3">
        {(item.llm_category || item.category) && (
          <span className="badge">{item.llm_category || item.category}</span>
        )}
        {item.importance && item.importance >= 4 && (
          <span className="badge badge-soft">★ 重要</span>
        )}
      </div>
      <Link href={`/news/${item.id}`} className="block">
        <h3 className="text-lg font-semibold leading-7 hover:text-violet-700">
          {item.title}
        </h3>
      </Link>
      {item.summary && (
        <p className="mt-3 text-sm leading-7 muted line-clamp-3">{item.summary}</p>
      )}
      {keywords.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-4">
          {keywords.map((keyword) => (
            <span key={keyword} className="text-xs text-zinc-400">#{keyword}</span>
          ))}
        </div>
      )}
      <div className="mt-5 pt-4 border-t border-zinc-100 flex items-center justify-between gap-4 text-xs text-zinc-400">
        <span>{item.source || "未知来源"}{item.published ? ` · ${item.published}` : ""}</span>
        <a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-violet-600" onClick={(e)=>e.stopPropagation()}>
          原文 <ArrowUpRight size={14} />
        </a>
      </div>
    </article>
  );
}
