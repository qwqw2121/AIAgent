'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { askAgent } from '@/services/api';

type Message = { role: 'user' | 'assistant'; content: string };

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [downloadableReport, setDownloadableReport] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (open && !panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOnOutsideClick);
    return () => document.removeEventListener('mousedown', closeOnOutsideClick);
  }, [open]);

  const submitQuestion = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || asking) return;
    setQuestion('');
    setMessages((current) => [...current, { role: 'user', content: text }]);
    setAsking(true);
    try {
      const result = await askAgent(text);
      setMessages((current) => [...current, { role: 'assistant', content: result.answer }]);
      const hasConcreteDate = /(20\d{2}[年/-]\d{1,2}[月/-]\d{1,2}日?|\d{1,2}月\d{1,2}日|今天|昨日|昨天)/.test(text);
      const askedForReport = /日报|每日报告/.test(text) && hasConcreteDate;
      const answerIsReport = /日报|今日要闻|日报概览/.test(result.answer) && result.answer.length > 120;
      setDownloadableReport(askedForReport || answerIsReport ? result.answer : null);
    } catch (error) {
      setMessages((current) => [...current, { role: 'assistant', content: error instanceof Error ? error.message : '请求失败，请稍后再试' }]);
    } finally {
      setAsking(false);
    }
  };

  const downloadAnswer = () => {
    const report = downloadableReport;
    if (!report) return;
    const url = URL.createObjectURL(new Blob([report], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `ai-news-report-${new Date().toISOString().slice(0, 10)}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <button ref={buttonRef} className="assistant-orb" aria-label="打开机器人助手" onClick={() => setOpen((current) => !current)}>
        <span className="robot-face" aria-hidden="true">🤖</span>
      </button>
      {open && <aside ref={panelRef} className="assistant-panel">
        <div className="assistant-head"><div><p className="eyebrow">AI NEWS AGENT</p><h2>AI咨询助手</h2></div><button aria-label="关闭助手" onClick={() => setOpen(false)}>×</button></div>
        <div className="assistant-body">
          {!messages.length && <p className="assistant-hint">你可以连续提问，不会丢失前面的回答。<br />例如：总结今天最重要的 AI 新闻</p>}
          {messages.map((message, index) => <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}><span>{message.role === 'user' ? '你' : 'AI咨询助手'}</span><p>{message.content}</p></div>)}
          {asking && <p className="assistant-hint">AI咨询助手正在整理资料…</p>}
          {downloadableReport && <button className="download-button" onClick={downloadAnswer}>下载日报 ↓</button>}
        </div>
        <form className="assistant-form" onSubmit={submitQuestion}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入你的问题..." /><button disabled={asking} aria-label="发送">{asking ? '…' : '↑'}</button></form>
      </aside>}
    </>
  );
}
