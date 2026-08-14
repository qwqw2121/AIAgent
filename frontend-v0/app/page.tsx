"use client";

import { useEffect, useState } from "react";

interface News {
  id: number;
  title: string;
  url: string;
  source: string;
  published: string | null;
  summary: string | null;
  llm_category: string | null;
  keywords: string | null;
  importance: number | null;
}

export default function Home() {
  const [news, setNews] = useState<News[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("http://localhost:8000/api/news?limit=20")
      .then((response) => response.json())
      .then((data) => {
        setNews(data.data);
        setLoading(false);
      })
      .catch((error) => {
        console.error("获取新闻失败:", error);
        setLoading(false);
      });
  }, []);

  return (
    <main className="min-h-screen bg-[#f7f7f5] text-[#18181b]">

      {/* Header */}
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-8 py-5">

          <div>
            <h1 className="text-xl font-bold tracking-tight">
              AI NEWS AGENT
            </h1>

            <p className="mt-1 text-xs text-zinc-500">
              AI 前沿资讯 · 智能聚合 · 事件追踪
            </p>
          </div>

          <nav className="flex gap-8 text-sm text-zinc-600">
            <a href="#" className="font-medium text-black">
              首页
            </a>

            <a href="#" className="hover:text-black">
              新闻
            </a>

            <a href="#" className="hover:text-black">
              事件
            </a>

            <a href="#" className="hover:text-black">
              报告
            </a>
          </nav>

        </div>
      </header>


      {/* Hero */}
      <section className="mx-auto max-w-7xl px-8 pb-10 pt-16">

        <div className="max-w-3xl">

          <p className="mb-4 text-sm font-medium uppercase tracking-[0.2em] text-zinc-500">
            AI DAILY
          </p>

          <h2 className="text-5xl font-semibold tracking-tight">
            今天，AI 圈发生了什么？
          </h2>

          <p className="mt-5 text-lg leading-8 text-zinc-500">
            自动聚合全球 AI 前沿资讯，通过大模型进行理解、
            总结与分类，并根据事件关系发现 AI 行业热点。
          </p>

        </div>


        {/* Stats */}
        <div className="mt-12 grid grid-cols-3 gap-4">

          <Stat
            title="AI 新闻"
            value="1,240+"
          />

          <Stat
            title="事件聚类"
            value="—"
          />

          <Stat
            title="资讯来源"
            value="—"
          />

        </div>

      </section>


      {/* News */}
      <section className="mx-auto max-w-7xl px-8 pb-20">

        <div className="mb-6 flex items-end justify-between">

          <div>
            <h3 className="text-2xl font-semibold">
              最新资讯
            </h3>

            <p className="mt-1 text-sm text-zinc-500">
              AI 新闻实时聚合
            </p>
          </div>

          <button className="text-sm text-zinc-500 hover:text-black">
            查看全部 →
          </button>

        </div>


        {loading ? (
          <div className="py-20 text-center text-zinc-400">
            正在加载新闻……
          </div>
        ) : (

          <div className="grid gap-4">

            {news.map((item) => (
              <NewsCard
                key={item.id}
                news={item}
              />
            ))}

          </div>

        )}

      </section>

    </main>
  );
}


function Stat({
  title,
  value,
}: {
  title: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-6">

      <p className="text-sm text-zinc-500">
        {title}
      </p>

      <p className="mt-3 text-3xl font-semibold">
        {value}
      </p>

    </div>
  );
}


function NewsCard({
  news,
}: {
  news: News;
}) {
  return (
    <article className="group rounded-2xl border border-zinc-200 bg-white p-7 transition hover:border-zinc-300 hover:shadow-sm">

      <div className="flex items-start justify-between gap-8">

        <div className="flex-1">

          {/* category */}
          <div className="mb-3 flex items-center gap-2">

            {news.llm_category && (
              <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-600">
                {news.llm_category}
              </span>
            )}

            {news.importance && news.importance >= 4 && (
              <span className="text-xs text-zinc-500">
                ★ 重要
              </span>
            )}

          </div>


          {/* title */}
          <h4 className="text-xl font-semibold leading-8 group-hover:underline">
            {news.title}
          </h4>


          {/* summary */}
          {news.summary && (
            <p className="mt-4 max-w-4xl text-sm leading-7 text-zinc-500">
              {news.summary}
            </p>
          )}


          {/* keywords */}
          {news.keywords && (
            <div className="mt-5 flex flex-wrap gap-2">

              {news.keywords
                .split(",")
                .slice(0, 5)
                .map((keyword) => (
                  <span
                    key={keyword}
                    className="text-xs text-zinc-400"
                  >
                    #{keyword.trim()}
                  </span>
                ))}

            </div>
          )}

        </div>

      </div>


      {/* Footer */}
      <div className="mt-6 flex items-center justify-between border-t border-zinc-100 pt-5">

        <div className="text-xs text-zinc-400">

          {news.source}

          {news.published && (
            <>
              {" · "}
              {news.published}
            </>
          )}

        </div>


        <a
          href={news.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-zinc-700 hover:text-black"
        >
          阅读原文 →
        </a>

      </div>

    </article>
  );
}