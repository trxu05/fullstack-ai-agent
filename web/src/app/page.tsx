'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8080';

type Course = { id: string; code: string; name: string; color: string };
type Task = {
  id: string;
  course_id?: string | null;
  title: string;
  due: string;
  done: boolean;
  priority: string;
};
type Material = {
  id: string;
  course_id?: string | null;
  title: string;
  preview?: string;
  content?: string;
  created_at?: string;
};
type Board = {
  courses: Course[];
  tasks: Task[];
  materials: Material[];
  stats: { courses: number; open_tasks: number; materials: number; quizzes_taken: number };
};
type ToolTrace = { name: string; args?: Record<string, unknown>; result?: string };
type Msg = {
  role: 'user' | 'assistant';
  text: string;
  provider?: string;
  tools?: ToolTrace[];
};

const QUICK = ['plan tonight', "what's on my board", 'explain my notes', 'quiz me', 'flashcards'];
const SESSION_KEY = 'studyboard.sessionId';
const WELCOME: Msg = {
  role: 'assistant',
  text: 'Click a chip below (try “quiz me”). You’ll see which tool ran, and which note was retrieved.',
};

function messagesKey(id: string) {
  return `studyboard.messages.${id}`;
}

function parseSources(text: string): string[] {
  const m = text.match(/Sources:\s*(.+)$/m);
  if (!m) return [];
  return m[1]
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState('plan tonight');
  const [messages, setMessages] = useState<Msg[]>([WELCOME]);
  const [courseCode, setCourseCode] = useState('');
  const [courseName, setCourseName] = useState('');
  const [taskTitle, setTaskTitle] = useState('');
  const [taskCourse, setTaskCourse] = useState('');
  const [taskDue, setTaskDue] = useState('tonight');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteBody, setNoteBody] = useState('');
  const [noteCourse, setNoteCourse] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!sessionId) return;
    localStorage.setItem(messagesKey(sessionId), JSON.stringify(messages));
  }, [messages, sessionId]);

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId;
    const saved = typeof window !== 'undefined' ? localStorage.getItem(SESSION_KEY) : null;
    const res = await fetch(`${API}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(saved ? { sessionId: saved } : {}),
    });
    if (!res.ok) throw new Error(`Could not create session (${res.status})`);
    const data = await res.json();
    const id = data.sessionId as string;
    localStorage.setItem(SESSION_KEY, id);
    setSessionId(id);
    const raw = localStorage.getItem(messagesKey(id));
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Msg[];
        if (Array.isArray(parsed) && parsed.length) setMessages(parsed);
      } catch {
        /* ignore */
      }
    }
    return id;
  }, [sessionId]);

  const refreshBoard = useCallback(
    async (id?: string) => {
      const sid = id || sessionId || (await ensureSession());
      const res = await fetch(`${API}/api/sessions/${sid}/board`);
      if (!res.ok) throw new Error(`Board failed (${res.status}) — is Java :8080 and Python :8001 up?`);
      const data = await res.json();
      setBoard(data as Board);
      return sid;
    },
    [ensureSession, sessionId],
  );

  useEffect(() => {
    refreshBoard().catch((e) => setError((e as Error).message));
  }, [refreshBoard]);

  async function sendChat(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setInput('');
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: 'user', text: trimmed }]);
    try {
      const id = await ensureSession();
      const history = messages
        .filter((m) => m.text && m.text !== WELCOME.text)
        .slice(-8)
        .map((m) => ({ role: m.role, text: m.text }));
      const res = await fetch(`${API}/api/sessions/${id}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed, history }),
      });
      if (!res.ok) throw new Error(`Chat failed (${res.status})`);
      const data = await res.json();
      const tools = (data.toolsUsed || data.tools_used || []) as ToolTrace[];
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: data.reply, provider: data.provider, tools },
      ]);
      await refreshBoard(id);
    } catch (err) {
      setMessages((m) => [...m, { role: 'assistant', text: `Error: ${(err as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function onChat(e: FormEvent) {
    e.preventDefault();
    await sendChat(input);
  }

  async function addCourse(e: FormEvent) {
    e.preventDefault();
    if (!courseCode.trim() || !courseName.trim()) return;
    const id = await ensureSession();
    const res = await fetch(`${API}/api/sessions/${id}/courses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: courseCode.trim(), name: courseName.trim() }),
    });
    if (!res.ok) throw new Error('add course failed');
    const data = await res.json();
    setBoard(data.board);
    setCourseCode('');
    setCourseName('');
  }

  async function addTask(e: FormEvent) {
    e.preventDefault();
    if (!taskTitle.trim()) return;
    const id = await ensureSession();
    const res = await fetch(`${API}/api/sessions/${id}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: taskTitle.trim(),
        course_id: taskCourse || null,
        due: taskDue || 'sometime',
        priority: 'medium',
      }),
    });
    if (!res.ok) throw new Error('add task failed');
    const data = await res.json();
    setBoard(data.board);
    setTaskTitle('');
  }

  async function completeTask(taskId: string) {
    const id = await ensureSession();
    const res = await fetch(`${API}/api/sessions/${id}/tasks/${taskId}/done`, { method: 'POST' });
    if (!res.ok) throw new Error('complete failed');
    const data = await res.json();
    setBoard(data.board);
  }

  async function addNote(e: FormEvent) {
    e.preventDefault();
    if (!noteTitle.trim() || !noteBody.trim()) return;
    const id = await ensureSession();
    if (editingNoteId) {
      const res = await fetch(`${API}/api/sessions/${id}/materials/${editingNoteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: noteTitle.trim(),
          content: noteBody.trim(),
          append: false,
        }),
      });
      if (!res.ok) throw new Error('edit notes failed');
      const data = await res.json();
      setBoard(data.board);
      setEditingNoteId(null);
      setNoteTitle('');
      setNoteBody('');
      return;
    }
    const res = await fetch(`${API}/api/sessions/${id}/materials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: noteTitle.trim(),
        content: noteBody.trim(),
        course_id: noteCourse || null,
      }),
    });
    if (!res.ok) throw new Error('add notes failed');
    const data = await res.json();
    setBoard(data.board);
    setNoteTitle('');
    setNoteBody('');
  }

  function startEditNote(m: Material) {
    setEditingNoteId(m.id);
    setNoteTitle(m.title);
    setNoteBody(m.content || m.preview || '');
    setNoteCourse(m.course_id || '');
  }

  function courseLabel(courseId?: string | null) {
    if (!courseId || !board) return 'General';
    return board.courses.find((c) => c.id === courseId)?.code || 'General';
  }

  const openTasks = board?.tasks.filter((t) => !t.done) || [];
  const lastTrace = [...messages].reverse().find((m) => m.role === 'assistant' && (m.tools?.length || m.provider));
  const cited = lastTrace ? parseSources(lastTrace.text) : [];

  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8 flex flex-col gap-3 border-b border-[var(--line)] pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mono text-xs font-medium uppercase tracking-[0.2em] text-[var(--accent)]">
              StudyBoard · retrieve → tool → board
            </p>
            <h1
              className="mt-1 text-4xl font-semibold tracking-tight text-[var(--ink)]"
              style={{ fontFamily: 'var(--font-display), Georgia, serif' }}
            >
              Your courses. Your plan. Your tutor.
            </h1>
            <p className="mt-2 max-w-xl text-[var(--muted)]">
              Keep classes, tasks, and notes in one place. The tutor retrieves from your notes,
              then plans, explains, or quizzes — and can update the board in the same turn.
            </p>
          </div>
          <div className="flex flex-col items-start gap-2 sm:items-end">
            {board ? (
              <div className="flex flex-wrap gap-3 text-sm text-[var(--muted)]">
                <Stat label="Courses" value={board.stats.courses} />
                <Stat label="Open tasks" value={board.stats.open_tasks} />
                <Stat label="Notes" value={board.stats.materials} />
                <Stat label="Quizzes" value={board.stats.quizzes_taken} />
              </div>
            ) : null}
            <button
              type="button"
              className="btn-ghost"
              onClick={async () => {
                if (sessionId) localStorage.removeItem(messagesKey(sessionId));
                localStorage.removeItem(SESSION_KEY);
                setMessages([WELCOME]);
                setError(null);
                const res = await fetch(`${API}/api/sessions`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({}),
                });
                if (!res.ok) {
                  setError(`Could not create session (${res.status})`);
                  return;
                }
                const data = await res.json();
                const id = data.sessionId as string;
                localStorage.setItem(SESSION_KEY, id);
                setSessionId(id);
                const boardRes = await fetch(`${API}/api/sessions/${id}/board`);
                if (!boardRes.ok) {
                  setError('Board failed after new session');
                  return;
                }
                setBoard((await boardRes.json()) as Board);
              }}
            >
              New session
            </button>
          </div>
        </header>

        {error ? (
          <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </p>
        ) : null}

        <div className="grid gap-6 lg:grid-cols-12">
          {/* Left: board */}
          <section className="space-y-6 lg:col-span-7">
            <Panel title="Courses">
              <div className="mb-4 flex flex-wrap gap-2">
                {(board?.courses || []).map((c) => (
                  <div
                    key={c.id}
                    className="rounded-lg border border-[var(--line)] bg-white px-3 py-2"
                    style={{ borderLeftWidth: 4, borderLeftColor: c.color }}
                  >
                    <div className="text-sm font-semibold">{c.code}</div>
                    <div className="text-xs text-[var(--muted)]">{c.name}</div>
                  </div>
                ))}
              </div>
              <form onSubmit={addCourse} className="flex flex-wrap gap-2">
                <input
                  className="field w-28"
                  placeholder="ECS 150"
                  value={courseCode}
                  onChange={(e) => setCourseCode(e.target.value)}
                />
                <input
                  className="field min-w-[12rem] flex-1"
                  placeholder="Operating Systems"
                  value={courseName}
                  onChange={(e) => setCourseName(e.target.value)}
                />
                <button type="submit" className="btn">
                  Add
                </button>
              </form>
            </Panel>

            <Panel title="To-do">
              <ul className="mb-4 space-y-2">
                {openTasks.length === 0 ? (
                  <li className="text-sm text-[var(--muted)]">No open tasks — add one below.</li>
                ) : (
                  openTasks.map((t) => (
                    <li
                      key={t.id}
                      className="flex items-start justify-between gap-3 rounded-lg border border-[var(--line)] bg-white px-3 py-2"
                    >
                      <div>
                        <div className="text-sm font-medium">{t.title}</div>
                        <div className="text-xs text-[var(--muted)]">
                          {courseLabel(t.course_id)} · due {t.due} · {t.priority}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn-ghost shrink-0"
                        onClick={() => completeTask(t.id).catch((e) => setError(e.message))}
                      >
                        Done
                      </button>
                    </li>
                  ))
                )}
              </ul>
              <form onSubmit={(e) => addTask(e).catch((err) => setError(err.message))} className="flex flex-wrap gap-2">
                <input
                  className="field min-w-[12rem] flex-1"
                  placeholder="Review midterm notes"
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                />
                <select
                  className="field"
                  value={taskCourse}
                  onChange={(e) => setTaskCourse(e.target.value)}
                >
                  <option value="">General</option>
                  {(board?.courses || []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code}
                    </option>
                  ))}
                </select>
                <input
                  className="field w-28"
                  placeholder="tonight"
                  value={taskDue}
                  onChange={(e) => setTaskDue(e.target.value)}
                />
                <button type="submit" className="btn">
                  Add
                </button>
              </form>
            </Panel>

            <Panel title="Notes">
              <ul className="mb-4 space-y-2">
                {(board?.materials || []).length === 0 ? (
                  <li className="text-sm text-[var(--muted)]">Paste lecture notes so the tutor can use them.</li>
                ) : (
                  board!.materials.map((m) => (
                    <li
                      key={m.id}
                      className={`rounded-lg border bg-white px-3 py-2 ${
                        cited.includes(m.title)
                          ? 'border-[var(--accent)] ring-2 ring-[var(--accent-soft)]'
                          : 'border-[var(--line)]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="text-sm font-medium">
                            {m.title}
                            {cited.includes(m.title) ? (
                              <span className="ml-2 text-[10px] uppercase tracking-wide text-[var(--accent)]">
                                retrieved
                              </span>
                            ) : null}
                          </div>
                          <div className="text-xs text-[var(--muted)]">
                            {courseLabel(m.course_id)} · {m.preview}
                          </div>
                        </div>
                        <button
                          type="button"
                          className="shrink-0 text-xs text-[var(--accent)] hover:underline"
                          onClick={() => startEditNote(m)}
                        >
                          Edit
                        </button>
                      </div>
                    </li>
                  ))
                )}
              </ul>
              <form onSubmit={(e) => addNote(e).catch((err) => setError(err.message))} className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  <input
                    className="field min-w-[12rem] flex-1"
                    placeholder="Note title"
                    value={noteTitle}
                    onChange={(e) => setNoteTitle(e.target.value)}
                  />
                  <select
                    className="field"
                    value={noteCourse}
                    onChange={(e) => setNoteCourse(e.target.value)}
                  >
                    <option value="">General</option>
                    {(board?.courses || []).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.code}
                      </option>
                    ))}
                  </select>
                </div>
                <textarea
                  className="field min-h-28 w-full"
                  placeholder="Paste notes here…"
                  value={noteBody}
                  onChange={(e) => setNoteBody(e.target.value)}
                />
                <button type="submit" className="btn">
                  {editingNoteId ? 'Save edits' : 'Save notes'}
                </button>
                {editingNoteId ? (
                  <button
                    type="button"
                    className="ml-2 text-xs text-[var(--muted)] hover:underline"
                    onClick={() => {
                      setEditingNoteId(null);
                      setNoteTitle('');
                      setNoteBody('');
                    }}
                  >
                    Cancel edit
                  </button>
                ) : null}
              </form>
            </Panel>
          </section>

          {/* Right: tutor */}
          <section className="lg:col-span-5">
            <div className="sticky top-4 flex h-[min(80vh,720px)] flex-col rounded-2xl border border-[var(--line)] bg-[var(--card)] shadow-sm">
              <div className="border-b border-[var(--line)] px-4 py-3">
                <h2 className="text-lg font-semibold" style={{ fontFamily: 'var(--font-display), Georgia, serif' }}>
                  Tutor
                </h2>
                <div className="mt-2 rounded-lg border border-dashed border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--accent)]">
                    Last agent trace
                  </p>
                  {lastTrace ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      <span className="rounded-full bg-white px-2 py-0.5 text-[10px] uppercase text-[var(--accent)]">
                        {lastTrace.provider}
                      </span>
                      {(lastTrace.tools || []).map((t, ti) => (
                        <span
                          key={`${t.name}-${ti}`}
                          className="rounded-full bg-white px-2 py-0.5 text-[10px] text-[var(--ink)]"
                        >
                          {t.name}
                        </span>
                      ))}
                      {cited.map((s) => (
                        <span key={s} className="rounded-full bg-white px-2 py-0.5 text-[10px] text-[var(--muted)]">
                          src: {s}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-1 text-xs text-[var(--ink)]">Idle — click quiz me to watch retrieve_notes / generate_quiz fire.</p>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {QUICK.map((q) => (
                    <button
                      key={q}
                      type="button"
                      className="rounded-full border border-[var(--line)] bg-white px-2.5 py-1 text-xs text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-50"
                      disabled={busy}
                      onClick={() => sendChat(q)}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={`max-w-[95%] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm leading-relaxed ${
                      m.role === 'user'
                        ? 'ml-auto bg-[var(--accent-soft)] text-[var(--ink)]'
                        : 'mr-auto bg-white border border-[var(--line)]'
                    }`}
                  >
                    {m.text}
                    {m.role === 'assistant' && (m.provider || (m.tools && m.tools.length > 0)) ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {m.provider ? (
                          <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[var(--accent)]">
                            {m.provider}
                          </span>
                        ) : null}
                        {(m.tools || []).map((t, ti) => (
                          <span
                            key={`${t.name}-${ti}`}
                            className="rounded-full border border-[var(--line)] px-2 py-0.5 text-[10px] text-[var(--muted)]"
                            title={t.result || ''}
                          >
                            {t.name}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
                <div ref={bottomRef} />
              </div>
              <form onSubmit={onChat} className="flex gap-2 border-t border-[var(--line)] p-3">
                <input
                  className="field flex-1"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="plan tonight / explain … / quiz me on …"
                  disabled={busy}
                />
                <button type="submit" className="btn" disabled={busy}>
                  {busy ? '…' : 'Ask'}
                </button>
              </form>
            </div>
          </section>
        </div>
      </div>

      <style jsx global>{`
        .field {
          border: 1px solid var(--line);
          background: white;
          border-radius: 0.75rem;
          padding: 0.55rem 0.75rem;
          font-size: 0.875rem;
          outline: none;
        }
        .field:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px var(--accent-soft);
        }
        .btn {
          border-radius: 0.75rem;
          background: var(--accent);
          color: white;
          padding: 0.55rem 1rem;
          font-size: 0.875rem;
          font-weight: 500;
        }
        .btn:disabled {
          opacity: 0.6;
        }
        .btn-ghost {
          border-radius: 0.5rem;
          border: 1px solid var(--line);
          background: white;
          padding: 0.25rem 0.6rem;
          font-size: 0.75rem;
          color: var(--muted);
        }
        .btn-ghost:hover {
          border-color: var(--accent);
          color: var(--accent);
        }
      `}</style>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--card)] px-3 py-2 text-center">
      <div className="text-lg font-semibold text-[var(--ink)]">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-[var(--line)] bg-[var(--card)] p-4 shadow-sm">
      <h2
        className="mb-3 text-lg font-semibold text-[var(--ink)]"
        style={{ fontFamily: 'var(--font-display), Georgia, serif' }}
      >
        {title}
      </h2>
      {children}
    </div>
  );
}
