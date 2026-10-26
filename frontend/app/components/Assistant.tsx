'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { streamAgent } from '@/services/api';

type Message = { role: 'user' | 'assistant'; content: string; isReport?: boolean };
type Session = { id: string; title: string; updatedAt: number; messages: Message[] };

const SESSIONS_KEY = 'ai-news-assistant-sessions-v2';
const ACTIVE_KEY = 'ai-news-assistant-active-v2';
const LEGACY_MESSAGES_KEY = 'ai-news-assistant-messages';
const LEGACY_SESSION_KEY = 'ai-news-assistant-session';
const MAX_SESSIONS = 30;
const REPORT_TOOL = 'get_daily_report';
const REQUEST_TIMEOUT_MS = 90_000;
const SLOW_HINT_SECONDS = 20;
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

const repairSessions = (list: Session[]): Session[] =>
  list.map((s) => ({
    ...s,
    messages: s.messages.map((m) =>
      m.role === 'assistant' && !m.content ? { ...m, content: '（回答被中断，请重新提问）' } : m
    ),
  }));

function loadSessions(): Session[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSIONS_KEY) || 'null');
    if (Array.isArray(raw) && raw.length) return repairSessions(raw);
  } catch {}
  try {
    const old = JSON.parse(localStorage.getItem(LEGACY_MESSAGES_KEY) || '[]');
    if (Array.isArray(old) && old.length) {
      const first = old.find((m: Message) => m.role === 'user');
      return repairSessions([{
        id: localStorage.getItem(LEGACY_SESSION_KEY) || newId(),
        title: first ? first.content.slice(0, 20) : '历史对话',
        updatedAt: Date.now(),
        messages: old,
      }]);
    }
  } catch {}
  return [blankSession()];
}

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [askingId, setAskingId] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  const panelRef = useRef<HTMLElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const userStoppedRef = useRef(false);

  const asking = askingId !== null;
  const activeAsking = askingId === activeId;

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

  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
      localStorage.setItem(ACTIVE_KEY, activeId);
    } catch {}
  }, [sessions, activeId, hydrated]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      const target = event.target as Node;
      if (open && !panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  // 已等待秒数
  useEffect(() => {
    if (!askingId) { setElapsed(0); return; }
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [askingId]);

  const active = sessions.find((s) => s.id === activeId);
  const messages = active?.messages ?? [];
  const history = sessions.filter((s) => s.id !== activeId && s.messages.length > 0);
  const lastEmpty = !messages[messages.length - 1]?.content;

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status, open, activeId]);

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
    const empty = sessions.find((s) => s.messages.length === 0);
    if (empty) {
      setActiveId(empty.id);
    } else {
      const s = blankSession();
      setSessions((prev) => [s, ...prev]);
      setActiveId(s.id);
    }
    setHistoryOpen(false);
  };

  const selectSession = (id: string) => {
    setActiveId(id);
    setHistoryOpen(false);
  };

  const deleteSession = (id: string) => {
    if (id === askingId) return;
    setSessions((prev) => {
      const rest = prev.filter((s) => s.id !== id);
      return rest.length ? rest : [blankSession()];
    });
  };

  const stop = () => {
    userStoppedRef.current = true;
    abortRef.current?.abort();
  };

  const submitQuestion = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || asking || !activeId) return;

    const id = activeId;
    const controller = new AbortController();
    abortRef.current = controller;
    userStoppedRef.current = false;
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    setQuestion('');
    setAskingId(id);
    setStatus('');
    updateMessages(id, (m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '' }]);

    let answer = '';
    let usedReportTool = false;
    const setLast = (content: string, isReport?: boolean) =>
      updateMessages(id, (m) =>
        m.map((msg, i) =>
          i === m.length - 1
            ? { ...msg, content, ...(isReport === undefined ? {} : { isReport }) }
            : msg
        )
      );

    try {
      await streamAgent(
        text,
        id,
        (ev) => {
          if (ev.type === 'token') {
            answer += ev.content || '';
            setStatus('');
            setLast(answer);
          } else if (ev.type === 'tool') {
            if (ev.name === REPORT_TOOL) usedReportTool = true;
            setStatus(`正在${TOOL_LABELS[ev.name || ''] || '处理'}…`);
          } else if (ev.type === 'error') {
            throw new Error(ev.content || '请求失败，请稍后再试');
          }
        },
        controller.signal,
      );
      if (!answer) {
        setLast('没有得到回答，请换个方式再问一次。', false);
      } else {
        setLast(answer, usedReportTool && answer.length > 120);
      }
    } catch (error) {
      if (controller.signal.aborted) {
        const tip = userStoppedRef.current
          ? '（已停止生成）'
          : '（等待超时，请稍后重试，或换个更具体的问法）';
        setLast(answer ? `${answer}\n\n${tip}` : tip, false);
      } else {
        setLast(answer || (error instanceof Error ? error.message : '请求失败，请稍后再试'), false);
      }
    } finally {
      clearTimeout(timeout);
      abortRef.current = null;
      setAskingId(null);
      setStatus('');
    }
  };

  const downloadReport = (content: string) => {
    const blob = new Blob(['\uFEFF' + content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `ai-news-report-${new Date().toISOString().slice(0, 10)}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
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
              <button className="assistant-new" onClick={newSession} aria-label="新对话" title="新对话">＋</button>
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
                      <button className="history-main" onClick={() => selectSession(s.id)} title={s.title}>
                        {s.title}
                      </button>
                      {s.id === askingId ? (
                        <span className="history-loading">生成中…</span>
                      ) : (
                        <button className="history-del" onClick={() => deleteSession(s.id)} aria-label="删除对话">×</button>
                      )}
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
            {messages.map((message, index) => {
              const streaming = activeAsking && index === messages.length - 1;
              return (
                <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
                  <span>{message.role === 'user' ? '你' : 'AI咨询助手'}</span>
                  {message.role === 'user' ? (
                    <p>{message.content}</p>
                  ) : (
                    message.content && (
                      <div className="markdown-body">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                      </div>
                    )
                  )}
                  {message.role === 'assistant' && message.isReport && !streaming && (
                    <button className="download-button" onClick={() => downloadReport(message.content)}>
                      下载日报 (.md) ↓
                    </button>
                  )}
                </div>
              );
            })}

            {activeAsking && (status || lastEmpty) && (
              <p className="assistant-hint">
                {status || 'AI咨询助手正在整理资料…'}（{elapsed}s）
                {elapsed > SLOW_HINT_SECONDS && ' 响应较慢，可点击输入框右侧的 ■ 停止后重试'}
              </p>
            )}
            {asking && !activeAsking && (
              <p className="assistant-hint">另一个对话正在生成回答，完成后才能继续提问。</p>
            )}
          </div>

          <form className="assistant-form" onSubmit={submitQuestion}>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={asking ? '回答生成中，请稍候…' : '输入你的问题...'}
              disabled={asking}
            />
            {asking ? (
              <button type="button" onClick={stop} aria-label="停止生成" title="停止生成">■</button>
            ) : (
              <button aria-label="发送">↑</button>
            )}
          </form>
        </aside>
      )}
    </>
  );
}