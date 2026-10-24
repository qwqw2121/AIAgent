'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { streamAgent } from '@/services/api';

type Message = { role: 'user' | 'assistant'; content: string };
type Session = { id: string; title: string; updatedAt: number; messages: Message[] };

const SESSIONS_KEY = 'ai-news-assistant-sessions-v2';
const ACTIVE_KEY = 'ai-news-assistant-active-v2';
const LEGACY_MESSAGES_KEY = 'ai-news-assistant-messages';
const LEGACY_SESSION_KEY = 'ai-news-assistant-session';
const MAX_SESSIONS = 30;
const TOOL_LABELS: Record<string, string> = {
  search_news_semantic: '检索新闻库',
  search_news: '查询新闻',
  get_daily_report: '读取日报',
  request_daily_report: '启动日报生成',
};

const newId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;

const blankSession = (): Session => ({ id: newId(), title: '新对话', updatedAt: Date.now(), messages: [] });

function loadSessions(): Session[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSIONS_KEY) || 'null');
    if (Array.isArray(raw) && raw.length) return raw;
  } catch {}
  // 迁移旧版单会话数据
  try {
    const old = JSON.parse(localStorage.getItem(LEGACY_MESSAGES_KEY) || '[]');
    if (Array.isArray(old) && old.length) {
      const first = old.find((m: Message) => m.role === 'user');
      return [{
        id: localStorage.getItem(LEGACY_SESSION_KEY) || newId(),
        title: first ? first.content.slice(0, 20) : '历史对话',
        updatedAt: Date.now(),
        messages: old,
      }];
    }
  } catch {}
  return [blankSession()];
}

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [status, setStatus] = useState('');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [downloadableReport, setDownloadableReport] = useState<string | null>(null);

  const panelRef = useRef<HTMLElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // 初始化
 // 初始化：每次加载页面都进入一个空白新对话，旧对话留在历史里
useEffect(() => {
  const list = loadSessions();
  const empty = list.find((s) => s.messages.length === 0);
  if (empty) {
    setSessions(list);
    setActiveId(empty.id);
  } else {
    const fresh = blankSession();
    setSessions([fresh, ...list]);
    setActiveId(fresh.id);
  }
  setHydrated(true);
}, []);

  // 持久化
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
      localStorage.setItem(ACTIVE_KEY, activeId);
    } catch {}
  }, [sessions, activeId, hydrated]);

  // 点击面板外部关闭
  useEffect(() => {
    const close = (event: MouseEvent) => {
      const target = event.target as Node;
      if (open && !panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const active = sessions.find((s) => s.id === activeId);
  const messages = active?.messages ?? [];
  const history = sessions.filter((s) => s.id !== activeId && s.messages.length > 0);

  // 新消息自动滚到底
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status, open]);

  const updateMessages = useCallback((id: string, updater: (m: Message[]) => Message[]) => {
    setSessions((prev) =>
      prev
        .map((s) => {
          if (s.id !== id) return s;
          const next = updater(s.messages);
          const firstUser = next.find((m) => m.role === 'user');
          return {
            ...s,
            messages: next,
            updatedAt: Date.now(),
            title: firstUser ? firstUser.content.slice(0, 20) : s.title,
          };
        })
        .sort((a, b) => b.updatedAt - a.updatedAt)
    );
  }, []);

  const newSession = () => {
    if (asking) return;
    const empty = sessions.find((s) => s.messages.length === 0);
    if (empty) {
      setActiveId(empty.id);
    } else {
      const s = blankSession();
      setSessions((prev) => [s, ...prev]);
      setActiveId(s.id);
    }
    setDownloadableReport(null);
    setHistoryOpen(false);
  };

  const selectSession = (id: string) => {
    if (asking) return;
    setActiveId(id);
    setDownloadableReport(null);
    setHistoryOpen(false);
  };

  const deleteSession = (id: string) => {
    if (asking && id === activeId) return;
    setSessions((prev) => {
      const rest = prev.filter((s) => s.id !== id);
      return rest.length ? rest : [blankSession()];
    });
  };

  const submitQuestion = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || asking || !activeId) return;

    const id = activeId; // 固定会话，避免流式过程中写错对话
    setQuestion('');
    setAsking(true);
    setStatus('');
    setDownloadableReport(null);
    updateMessages(id, (m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '' }]);

    let answer = '';
    const setLast = (content: string) =>
      updateMessages(id, (m) => m.map((msg, i) => (i === m.length - 1 ? { ...msg, content } : msg)));

    try {
      await streamAgent(text, id, (ev) => {
        if (ev.type === 'token') {
          answer += ev.content || '';
          setStatus('');
          setLast(answer);
        } else if (ev.type === 'tool') {
          setStatus(`正在${TOOL_LABELS[ev.name || ''] || '处理'}…`);
        } else if (ev.type === 'error') {
          throw new Error(ev.content || '请求失败，请稍后再试');
        }
      });
      if (!answer) setLast('没有得到回答，请换个方式再问一次。');
      setDownloadableReport(/日报|今日要闻|日报概览/.test(answer) && answer.length > 120 ? answer : null);
    } catch (error) {
      setLast(answer || (error instanceof Error ? error.message : '请求失败，请稍后再试'));
    } finally {
      setAsking(false);
      setStatus('');
    }
  };

  const downloadAnswer = () => {
    if (!downloadableReport) return;
    const url = URL.createObjectURL(new Blob([downloadableReport], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `ai-news-report-${new Date().toISOString().slice(0, 10)}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <button ref={buttonRef} className="assistant-orb" aria-label="打开机器人助手" onClick={() => setOpen((c) => !c)}>
        <span className="robot-face" aria-hidden="true">🤖</span>
      </button>

      {open && (
        <aside ref={panelRef} className="assistant-panel">
          <div className="assistant-head">
            <div>
              <p className="eyebrow">AI NEWS AGENT</p>
              <h2>AI咨询助手</h2>
            </div>
            <div className="assistant-head-actions">
              <button className="assistant-new" onClick={newSession} disabled={asking} aria-label="新对话" title="新对话">＋</button>
              <button aria-label="关闭助手" onClick={() => setOpen(false)}>×</button>
            </div>
          </div>

          {history.length > 0 && (
            <div className="assistant-history">
              <button
                className="assistant-history-toggle"
                onClick={() => setHistoryOpen((o) => !o)}
                aria-expanded={historyOpen}
              >
                <span>历史对话（{history.length}）</span>
                <span>{historyOpen ? '▾' : '▸'}</span>
              </button>
              {historyOpen && (
                <ul className="assistant-history-list">
                  {history.map((s) => (
                    <li key={s.id}>
                      <button className="history-main" onClick={() => selectSession(s.id)} title={s.title} disabled={asking}>
                        {s.title}
                      </button>
                      <button className="history-del" onClick={() => deleteSession(s.id)} aria-label="删除对话">×</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="assistant-body" ref={bodyRef}>
            {!messages.length && (
              <p className="assistant-hint">
                你可以连续提问，不会丢失前面的回答。<br />例如：总结今天最重要的 AI 新闻
              </p>
            )}
            {messages.map((message, index) => (
              <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
                <span>{message.role === 'user' ? '你' : 'AI咨询助手'}</span>
                <p>{message.content}</p>
              </div>
            ))}
            {asking && <p className="assistant-hint">{status || 'AI咨询助手正在整理资料…'}</p>}
            {downloadableReport && !asking && (
              <button className="download-button" onClick={downloadAnswer}>下载日报 ↓</button>
            )}
          </div>

          <form className="assistant-form" onSubmit={submitQuestion}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="输入你的问题..." />
            <button disabled={asking} aria-label="发送">{asking ? '…' : '↑'}</button>
          </form>
        </aside>
      )}
    </>
  );
}