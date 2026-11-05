'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { streamAgent } from '@/services/chat';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  isReport?: boolean;
  reportDate?: string;
  reportPending?: boolean;
  reportStartedAt?: number;
  tools?: string[];
};

type Session = {
  id: string;
  title: string;
  updatedAt: number;
  messages: Message[];
  hasNewReport?: boolean; // 有用户还没看到的新日报
};

const SESSIONS_KEY = 'ai-news-assistant-sessions-v2';
const ACTIVE_KEY = 'ai-news-assistant-active-v2';
const LEGACY_MESSAGES_KEY = 'ai-news-assistant-messages';
const LEGACY_SESSION_KEY = 'ai-news-assistant-session';

const MAX_SESSIONS = 30;
const REQUEST_TIMEOUT_MS = 90_000;
const SLOW_HINT_SECONDS = 20;

const REPORT_API = '/api/daily-report';
const POLL_INTERVAL_MS = 20_000;
const PENDING_TTL_MS = 10 * 60 * 1000; // 超过 10 分钟不再等待
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const pad2 = (n: string) => n.padStart(2, '0');
const validMD = (m: string, d: string) => +m >= 1 && +m <= 12 && +d >= 1 && +d <= 31;

// 带年份：2026-11-01 / 2026/11/1 / 2026年11月1日
const strictDate = (text: string): string | undefined => {
  const m = text.match(/(\d{4})[-/.年]\s*(\d{1,2})[-/.月]\s*(\d{1,2})/);
  return m && validMD(m[2], m[3]) ? `${m[1]}-${pad2(m[2])}-${pad2(m[3])}` : undefined;
};

// 不带年份：11月1日 / 11.1 / 11/1，按当前年份补全
const looseDate = (text: string): string | undefined => {
  const m = text.match(/(\d{1,2})月\s*(\d{1,2})/) ?? text.match(/\b(\d{1,2})[./](\d{1,2})\b/);
  return m && validMD(m[1], m[2])
    ? `${new Date().getFullYear()}-${pad2(m[1])}-${pad2(m[2])}`
    : undefined;
};

// 工具事件没带日期时的兜底：回答里带年份的日期 > 提问里的日期 > 回答里的月日
const guessReportDate = (question: string, answer: string) =>
  strictDate(answer) ??
  strictDate(question) ??
  looseDate(question) ??
  looseDate(answer);

const TOOL_LABELS: Record<string, string> = {
  search_news_semantic: '检索新闻库',
  search_news: '查询新闻',
  get_daily_report: '读取日报',
  request_daily_report: '启动日报生成',
};

const REPORT_TOOLS = ['get_daily_report', 'request_daily_report'];
const REQUEST_TOOL = 'request_daily_report';

const toolName = (ev: any): string => {
  const raw =
    ev?.name ??
    ev?.tool_name ??
    ev?.tool ??
    ev?.tool_call?.name ??
    ev?.data?.name ??
    ev?.data?.tool_name;

  return typeof raw === 'string' ? raw : '';
};

const matchTool = (name: string, keys: string[]) =>
  keys.find((key) => name === key || name.endsWith(key));

const labelOf = (name: string) => {
  const key = matchTool(name, Object.keys(TOOL_LABELS));
  return key ? TOOL_LABELS[key] : name || '处理';
};

const isReportTool = (name: string) =>
  Boolean(matchTool(name, REPORT_TOOLS));

/**
 * 兼容工具参数是对象、JSON 字符串，以及常见嵌套结构。
 */
const parseObject = (value: any): Record<string, any> | null => {
  if (!value) return null;

  if (typeof value === 'object' && !Array.isArray(value)) {
    return value;
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed;
      }
    } catch {
      return null;
    }
  }

  return null;
};

const pickDate = (ev: any): string | undefined => {
  const candidates = [
    ev?.args,
    ev?.arguments,
    ev?.input,
    ev?.params,
    ev?.tool_input,
    ev?.data?.args,
    ev?.data?.arguments,
    ev?.data?.input,
    ev?.tool_call?.args,
    ev?.tool_call?.arguments,
  ];

  for (const candidate of candidates) {
    const obj = parseObject(candidate);
    if (!obj) continue;

    const value = obj.date ?? obj.report_date ?? obj.reportDate;

    if (typeof value === 'string' && DATE_RE.test(value)) {
      return value;
    }
  }

  return undefined;
};

const newId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;

const blankSession = (): Session => ({
  id: newId(),
  title: '新对话',
  updatedAt: Date.now(),
  messages: [],
});

const repairSessions = (list: Session[]): Session[] =>
  list.map((session) => ({
    ...session,
    messages: (session.messages || []).map((message) => {
      if (message.role !== 'assistant') return message;

      return {
        ...message,
        content: message.content || '（回答被中断，请重新提问）',
        // 未超时的“生成中”任务刷新页面后继续等待，超时的直接放弃
        reportPending: Boolean(
          message.reportPending &&
            message.reportStartedAt &&
            Date.now() - message.reportStartedAt < PENDING_TTL_MS,
        ),
      };
    }),
  }));

function loadSessions(): Session[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSIONS_KEY) || 'null');

    if (Array.isArray(raw) && raw.length) {
      return repairSessions(raw);
    }
  } catch {
    // 忽略损坏的本地会话数据
  }

  try {
    const old = JSON.parse(localStorage.getItem(LEGACY_MESSAGES_KEY) || '[]');

    if (Array.isArray(old) && old.length) {
      const first = old.find((m: Message) => m.role === 'user');

      return repairSessions([
        {
          id: localStorage.getItem(LEGACY_SESSION_KEY) || newId(),
          title: first ? first.content.slice(0, 20) : '历史对话',
          updatedAt: Date.now(),
          messages: old,
        },
      ]);
    }
  } catch {
    // 忽略旧格式数据
  }

  return [blankSession()];
}

type ReportStatus = {
  status: 'checking' | 'ready' | 'none' | 'generating';
  date?: string | null;
};

/**
 * 下载按钮：只在后端确认日报已存在（ready）时显示。
 * 生成中（wait=true）只显示提示，轮询和结果回填由 Assistant 统一处理。
 */
function ReportDownload({
  date,
  wait = false,
}: {
  date?: string;
  wait?: boolean;
}) {
  const [state, setState] = useState<ReportStatus>({ status: 'checking' });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stopped = false;

    if (!date || !DATE_RE.test(date)) {
      setState({ status: 'none' });
      return;
    }

    setState({ status: 'checking', date });

    (async () => {
      try {
        const res = await fetch(
          `${REPORT_API}/status?date=${encodeURIComponent(date)}`,
          { cache: 'no-store' },
        );
        if (!res.ok) throw new Error('status failed');
        const data: ReportStatus = await res.json();
        if (!stopped) setState(data);
      } catch {
        if (!stopped) setState({ status: 'none' });
      }
    })();

    return () => {
      stopped = true;
    };
  }, [date, wait]);

  const download = async () => {
    if (!date || state.status !== 'ready' || busy) return;

    setBusy(true);

    try {
      const res = await fetch(
        `${REPORT_API}/${encodeURIComponent(date)}/download`,
      );
      if (!res.ok) throw new Error(`下载失败：${res.status}`);

      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = `ai-news-report-${date}.md`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      alert('日报下载失败，请稍后重试');
    } finally {
      setBusy(false);
    }
  };

  if (wait) {
    return (
      <p className="assistant-hint">
        {date
          ? '日报正在后台生成，预计需要几分钟。完成后会自动显示在对话里，期间可以关闭窗口或继续提问。'
          : '已启动日报生成，但未能识别日期，完成后请重新提问获取。'}
      </p>
    );
  }

  if (date && state.status === 'ready') {
    return (
      <button className="download-button" onClick={download} disabled={busy}>
        {busy ? '下载中…' : '下载完整日报 (.md) ↓'}
      </button>
    );
  }

  return null;
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
  const sessionsRef = useRef<Session[]>([]);
  const askingRef = useRef<string | null>(null);
  const checkingRef = useRef<Set<string>>(new Set());
  const activeIdRef = useRef('');
  const openRef = useRef(false);

  const asking = askingId !== null;
  const activeAsking = askingId === activeId;

  sessionsRef.current = sessions;
  askingRef.current = askingId;
  activeIdRef.current = activeId;
  openRef.current = open;

  useEffect(() => {
    const list = loadSessions().slice(0, MAX_SESSIONS);
    const empty = list.find((s) => s.messages.length === 0);

    if (empty) {
      setSessions(list);
      setActiveId(empty.id);
    } else {
      const fresh = blankSession();
      setSessions([fresh, ...list].slice(0, MAX_SESSIONS));
      setActiveId(fresh.id);
    }

    setHydrated(true);
  }, []);

  // 只负责持久化，不能在这里 setSessions，否则会无限循环
  useEffect(() => {
    if (!hydrated) return;

    try {
      localStorage.setItem(
        SESSIONS_KEY,
        JSON.stringify(sessions.slice(0, MAX_SESSIONS)),
      );
      localStorage.setItem(ACTIVE_KEY, activeId);
    } catch {
      // 本地存储空间不足时不影响对话
    }
  }, [sessions, activeId, hydrated]);

  // 日报生成完成后，自动把完整日报追加到对应对话里
  const completeReport = useCallback((date: string, markdown: string) => {
    setSessions((prev) =>
      prev
        .map((session) => {
          let hit = false;
          const msgs = session.messages.map((m) => {
            if (m.reportPending && m.reportDate === date) {
              hit = true;
              return { ...m, reportPending: false, isReport: false };
            }
            return m;
          });
          if (!hit) return session;

          // 用户正在看这个会话时不打标记，否则标记为“新日报”
          const viewing = session.id === activeIdRef.current && openRef.current;

          return {
            ...session,
            hasNewReport: viewing ? session.hasNewReport : true,
            updatedAt: Date.now(),
            messages: [
              ...msgs,
              {
                role: 'assistant' as const,
                content: `✅ ${date} 的日报已生成完成：\n\n${markdown}`,
                isReport: true,
                reportDate: date,
              },
            ],
          };
        })
        .sort((a, b) => b.updatedAt - a.updatedAt),
    );
  }, []);

  useEffect(() => {
    if (!hydrated) return;

    const tick = async () => {
      // 标签页不可见时暂停查询，切回来时会立即补查一次
      if (document.hidden) return;

      const now = Date.now();
      const isExpired = (m: Message) =>
        !m.reportStartedAt || now - m.reportStartedAt > PENDING_TTL_MS;
      const dates = new Set<string>();

      for (const session of sessionsRef.current) {
        // 正在流式输出的会话先不动，避免追加消息打乱最后一条
        if (session.id === askingRef.current) continue;

        for (const m of session.messages) {
          // 即使已超时，也最后检查一次，避免用户离开较久后错过结果
          if (m.reportPending && m.reportDate && DATE_RE.test(m.reportDate)) {
            dates.add(m.reportDate);
          }
        }
      }

      for (const date of dates) {
        if (checkingRef.current.has(date)) continue;
        checkingRef.current.add(date);

        try {
          const st = await fetch(
            `${REPORT_API}/status?date=${encodeURIComponent(date)}`,
            { cache: 'no-store' },
          );
          if (!st.ok) continue;
          const data = await st.json();
          if (data.status !== 'ready') continue;

          const res = await fetch(
            `${REPORT_API}/${encodeURIComponent(date)}/download`,
            { cache: 'no-store' },
          );
          if (!res.ok) continue;

          const markdown = (await res.text()).replace(/^\uFEFF/, '');
          completeReport(date, markdown);
        } catch {
          // 网络错误，下个周期再试
        } finally {
          checkingRef.current.delete(date);
        }
      }

      // 检查完仍未生成且已超时的任务，不再等待（保留 isReport，之后有日报仍可手动下载）
      setSessions((prev) => {
        let changed = false;
        const next = prev.map((session) => {
          if (session.id === askingRef.current) return session;
          return {
            ...session,
            messages: session.messages.map((m) => {
              if (m.reportPending && isExpired(m)) {
                changed = true;
                return { ...m, reportPending: false };
              }
              return m;
            }),
          };
        });
        return changed ? next : prev;
      });
    };

    const onVisible = () => {
      if (!document.hidden) tick();
    };
    document.addEventListener('visibilitychange', onVisible);

    tick();
    const timer = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [hydrated, completeReport]);

  // 打开助手并查看某个会话后，清除它的“新日报”标记
  useEffect(() => {
    if (!open || !activeId) return;

    setSessions((prev) =>
      prev.some((s) => s.id === activeId && s.hasNewReport)
        ? prev.map((s) => (s.id === activeId ? { ...s, hasNewReport: false } : s))
        : prev,
    );
  }, [open, activeId, sessions]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      const target = event.target as Node;

      if (
        open &&
        !panelRef.current?.contains(target) &&
        !buttonRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  useEffect(() => {
    if (!askingId) {
      setElapsed(0);
      return;
    }

    setElapsed(0);

    const timer = setInterval(() => {
      setElapsed((value) => value + 1);
    }, 1000);

    return () => clearInterval(timer);
  }, [askingId]);

  const active = sessions.find((s) => s.id === activeId);
  const messages = active?.messages ?? [];
  const history = sessions.filter(
    (s) => s.id !== activeId && s.messages.length > 0,
  );
  const lastEmpty = !messages[messages.length - 1]?.content;

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status, open, activeId]);

  const updateMessages = useCallback(
    (id: string, updater: (messages: Message[]) => Message[]) => {
      setSessions((prev) =>
        prev
          .map((session) => {
            if (session.id !== id) return session;

            const next = updater(session.messages);
            const firstUser = next.find((m) => m.role === 'user');

            return {
              ...session,
              messages: next,
              updatedAt: Date.now(),
              title: firstUser ? firstUser.content.slice(0, 20) : session.title,
            };
          })
          .sort((a, b) => b.updatedAt - a.updatedAt),
      );
    },
    [],
  );

  const newSession = () => {
    const empty = sessions.find((s) => s.messages.length === 0);

    if (empty) {
      setActiveId(empty.id);
    } else {
      const session = blankSession();
      // 会话数量上限在创建时控制
      setSessions((prev) => [session, ...prev].slice(0, MAX_SESSIONS));
      setActiveId(session.id);
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

    updateMessages(id, (prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '' },
    ]);

    let answer = '';
    let usedReportTool = false;
    let reportDate: string | undefined;
    let reportRequested = false;
    let reportStartedAt: number | undefined;

    const toolsUsed: string[] = [];

    const setLast = (content: string, extra?: Partial<Message>) => {
      updateMessages(id, (prev) =>
        prev.map((message, index) =>
          index === prev.length - 1 ? { ...message, content, ...extra } : message,
        ),
      );
    };

    const reportExtra = (): Partial<Message> => ({
      isReport: usedReportTool,
      // 工具事件没带参数时，从回答文字里兜底取日期
      reportDate: reportDate ?? (usedReportTool ? guessReportDate(text, answer) : undefined),
      reportPending: reportRequested,
      reportStartedAt,
      tools: [...toolsUsed],
    });

    try {
      await streamAgent(
        text,
        id,
        (ev: any) => {
          if (ev.type === 'token') {
            answer += ev.content || '';
            setStatus('');
            setLast(answer);
            return;
          }

          if (ev.type === 'tool') {
            const name = toolName(ev);
            const label = labelOf(name);

            if (isReportTool(name)) {
              usedReportTool = true;
              reportDate = pickDate(ev) ?? reportDate;

              if (matchTool(name, [REQUEST_TOOL])) {
                reportRequested = true;
                if (!reportStartedAt) reportStartedAt = Date.now();
              }
            }

            if (!toolsUsed.includes(label)) {
              toolsUsed.push(label);
            }

            setStatus(`正在${label}…`);
            setLast(answer, reportExtra());
            return;
          }

          if (ev.type === 'error') {
            throw new Error(ev.content || '请求失败，请稍后再试');
          }
        },
        controller.signal,
      );

      setLast(answer || '没有得到回答，请换个方式再问一次。', reportExtra());
    } catch (error) {
      const tip = controller.signal.aborted
        ? userStoppedRef.current
          ? '（已停止生成）'
          : '（等待超时，请稍后重试，或换个更具体的问法）'
        : error instanceof Error
          ? error.message
          : '请求失败，请稍后再试';

      setLast(answer ? `${answer}\n\n${tip}` : tip, reportExtra());
    } finally {
      clearTimeout(timeout);
      abortRef.current = null;
      setAskingId(null);
      setStatus('');
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        className="assistant-orb"
        aria-label="打开机器人助手"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="robot-face" aria-hidden="true">
          🤖
        </span>
      </button>

      {open && (
        <aside ref={panelRef} className="assistant-panel">
          <div className="assistant-head">
            <div>
              <p className="eyebrow">AI NEWS AGENT</p>
              <h2>AI咨询助手</h2>
            </div>

            <div className="assistant-head-actions">
              <button
                className="assistant-new"
                onClick={newSession}
                aria-label="新对话"
                title="新对话"
              >
                ＋
              </button>

              <button aria-label="关闭助手" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>
          </div>

          {history.length > 0 && (
            <div className="assistant-history">
              <button
                className="assistant-history-toggle"
                onClick={() => setHistoryOpen((value) => !value)}
                aria-expanded={historyOpen}
              >
                <span>
                  历史对话（{history.length}）
                  {history.some((s) => s.hasNewReport) && (
                    <em className="history-badge">新日报</em>
                  )}
                </span>
                <span>{historyOpen ? '▾' : '▸'}</span>
              </button>

              {historyOpen && (
                <ul className="assistant-history-list">
                  {history.map((session) => (
                    <li key={session.id}>
                      <button
                        className="history-main"
                        onClick={() => selectSession(session.id)}
                        title={session.title}
                      >
                        {session.title}
                        {session.hasNewReport && (
                          <em className="history-badge">新日报</em>
                        )}
                      </button>

                      {session.id === askingId ? (
                        <span className="history-loading">生成中…</span>
                      ) : (
                        <button
                          className="history-del"
                          onClick={() => deleteSession(session.id)}
                          aria-label="删除对话"
                        >
                          ×
                        </button>
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
                你可以连续提问，不会丢失前面的回答。
                <br />
                例如：总结今天最重要的 AI 新闻
              </p>
            )}

            {messages.map((message, index) => {
              const streaming = activeAsking && index === messages.length - 1;

              return (
                <div
                  className={`chat-message ${message.role}`}
                  key={`${message.role}-${index}`}
                >
                  <span>{message.role === 'user' ? '你' : 'AI咨询助手'}</span>

                  {message.role === 'assistant' &&
                    Boolean(message.tools?.length) && (
                      <p className="tool-trace">
                        已调用：{message.tools!.join('、')}
                      </p>
                    )}

                  {message.role === 'user' ? (
                    <p>{message.content}</p>
                  ) : (
                    message.content && (
                      <div className="markdown-body">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    )
                  )}

                  {message.role === 'assistant' &&
                    message.isReport &&
                    !streaming && (
                      <ReportDownload
                        date={message.reportDate}
                        wait={message.reportPending}
                      />
                    )}
                </div>
              );
            })}

            {activeAsking && (status || lastEmpty) && (
              <p className="assistant-hint">
                {status || 'AI咨询助手正在整理资料…'}（{elapsed}s）
                {elapsed > SLOW_HINT_SECONDS &&
                  ' 响应较慢，可点击输入框右侧的 ■ 停止后重试'}
              </p>
            )}

            {asking && !activeAsking && (
              <p className="assistant-hint">
                另一个对话正在生成回答，完成后才能继续提问。
              </p>
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
              <button
                type="button"
                onClick={stop}
                aria-label="停止生成"
                title="停止生成"
              >
                ■
              </button>
            ) : (
              <button type="submit" aria-label="发送">
                ↑
              </button>
            )}
          </form>
        </aside>
      )}
    </>
  );
}