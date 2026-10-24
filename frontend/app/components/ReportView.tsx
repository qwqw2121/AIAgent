'use client';

import { DailyReport, DailyReportContent, ReportNews } from '@/services/api';

function formatPublished(value?: string) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN');
}

function keywordsOf(news: ReportNews): string[] {
  if (Array.isArray(news.keywords)) return news.keywords;
  if (!news.keywords) return [];
  try {
    const parsed = JSON.parse(news.keywords);
    return Array.isArray(parsed) ? parsed : [news.keywords];
  } catch {
    return [news.keywords];
  }
}

export default function ReportView({
  report,
  embedded = false,
}: {
  report: DailyReport;
  embedded?: boolean;
}) {
  const events = (report.report as DailyReportContent).events ?? [];

  return (
    <>
      <header className="report-header">
        <p className="eyebrow">DAILY BRIEF</p>
        {embedded ? (
          <h2>{report.date} 日报</h2>
        ) : (
          <>
            <h1>AI 新闻日报</h1>
            <p className="report-date-large">{report.date}</p>
          </>
        )}
      </header>

      <section className="report-lede">
        <span>编辑摘要</span>
        <p>{report.overview}</p>
      </section>

      <div className="report-section-heading">
        <h2>今日要闻</h2>
        <span>{events.length} 个事件</span>
      </div>

      <div className="report-events">
        {events.map((event, index) => (
          <article key={`${event.title}-${index}`} className="report-event-card">
            <div className="report-event-index">{String(index + 1).padStart(2, '0')}</div>
            <div className="report-event-main">
              <h3>{event.title}</h3>
              {event.summary && <p className="report-event-summary">{event.summary}</p>}
              {event.why_it_matters && (
                <p className="report-why">
                  <strong>为什么重要</strong>
                  {event.why_it_matters}
                </p>
              )}
              <div className="report-news-list">
                {event.news?.map((news) => (
                  <div key={news.id} className="report-news-item">
                    <div className="report-news-meta">
                      <span>{news.source || '未知来源'}</span>
                      {news.published && <span>{formatPublished(news.published)}</span>}
                      {news.importance !== undefined && <span>重要性 {news.importance}/10</span>}
                    </div>
                    <h4>{news.title}</h4>
                    {news.summary && <p>{news.summary}</p>}
                    {keywordsOf(news).length > 0 && (
                      <div className="keyword-list">
                        {keywordsOf(news).map((keyword, i) => (
                          <span key={`${keyword}-${i}`}>{keyword}</span>
                        ))}
                      </div>
                    )}
                    {news.content && (
                      <details>
                        <summary>查看正文</summary>
                        <p>{news.content}</p>
                      </details>
                    )}
                    {news.url && (
                      <a href={news.url} target="_blank" rel="noreferrer">
                        打开原文 ↗
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}