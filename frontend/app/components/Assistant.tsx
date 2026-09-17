'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { streamAgent } from '@/services/api';

type Message = { role: 'user' | 'assistant'; content: string };
const MESSAGE_STORAGE_KEY = 'ai-news-assistant-messages';
const SESSION_STORAGE_KEY = 'ai-news-assistant-session';

function storedMessages(): Message[] {
  if (typeof window === 'undefined') return [];
  try {
    const value = JSON.parse(localStorage.getItem(MESSAGE_STORAGE_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function storedSessionId() {
  if (typeof window === 'undefined') return `chat-${Date.now()}`;
  const existing = localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing) return existing;
  const created = `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  localStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [downloadableReport, setDownloadableReport] = useState<string | null>(null);
  const sessionId = useRef(storedSessionId());
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

  useEffect(() => {
    setMessages(storedMessages());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(MESSAGE_STORAGE_KEY, JSON.stringify(messages));
  }, [messages, hydrated]);

  const submitQuestion = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || asking) return;
    setQuestion('');
    setMessages((current) => [...current, { role: 'user', content: text }]);
    setAsking(true);
    try {
      setMessages((current) => [...current, { role: 'assistant', content: '' }]);
      let answer = '';
      let completed = false;
      await streamAgent(text, sessionId.current, (streamEvent) => {
        if (streamEvent.type === 'token') {
          answer += streamEvent.content || '';
          setMessages((current) => current.map((message, index) => index === current.length - 1 ? { ...message, content: answer } : message));
        } else if (streamEvent.type === 'tool') {
          setMessages((current) => current.map((message, index) => index === current.length - 1 ? { ...message, content: `${answer}${answer ? '\n\n' : ''}正在${streamEvent.name || '检索新闻库'}…` } : message));
        } else if (streamEvent.type === 'error') {
          throw new Error(streamEvent.content || '请求失败，请稍后再试');
        }
        completed = true;
      });
      if (completed) {
        setMessages((current) => current.map((message, index) => index === current.length - 1 ? { ...message, content: answer } : message));
        setDownloadableReport(/日报|今日要闻|日报概览/.test(answer) && answer.length > 120 ? answer : null);
      }
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
