'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';

type Msg = { role: 'user' | 'assistant'; text: string; meta?: string };

const API = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8080';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState('digest AI chips');
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: 'assistant',
      text: 'News Digest Agent ready. Ask for a topic briefing, or watch a topic then say “digest”.',
    },
  ]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function ensureSession() {
    if (sessionId) return sessionId;
    const res = await fetch(`${API}/api/sessions`, { method: 'POST' });
    if (!res.ok) throw new Error(`session failed (${res.status})`);
    const data = await res.json();
    setSessionId(data.sessionId);
    return data.sessionId as string;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    setMessages((m) => [...m, { role: 'user', text }]);
    try {
      const id = await ensureSession();
      const res = await fetch(`${API}/api/sessions/${id}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error(`chat failed (${res.status}) — is Java :8080 and Python :8001 up?`);
      const data = await res.json();
      const tools = (data.toolsUsed || data.tools_used || [])
        .map((t: { name: string }) => t.name)
        .join(', ');
      const meta = `provider=${data.provider || 'unknown'}${tools ? ` · tools=${tools}` : ''}`;
      setMessages((m) => [...m, { role: 'assistant', text: data.reply, meta }]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: `Error: ${(err as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-50 via-sky-50 to-slate-100 text-slate-900">
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-8">
        <header className="mb-6">
          <p className="text-sm font-medium uppercase tracking-wide text-sky-700">
            Next.js · React · TypeScript · Tailwind · Java · FastAPI
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">News Digest Agent</h1>
          <p className="mt-2 text-slate-600">
            Tell it a topic → collects public RSS headlines → returns a usable recap for industry catch-up.
          </p>
          <p className="mt-2 text-sm text-slate-500">
            Try <code className="rounded bg-white px-1.5 py-0.5 border">digest AI chips</code>{' '}
            <code className="rounded bg-white px-1.5 py-0.5 border">watch topic cloud networking</code>{' '}
            <code className="rounded bg-white px-1.5 py-0.5 border">digest</code>
          </p>
        </header>

        <section className="flex-1 overflow-y-auto rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm">
          <div className="flex flex-col gap-3">
            {messages.map((m, i) => (
              <div
                key={i}
                className={`max-w-[95%] whitespace-pre-wrap rounded-xl px-4 py-3 text-sm leading-relaxed ${
                  m.role === 'user'
                    ? 'ml-auto bg-sky-100 text-slate-900'
                    : 'mr-auto bg-slate-100 text-slate-800'
                }`}
              >
                {m.text}
                {m.meta ? <span className="mt-2 block text-xs text-slate-500">{m.meta}</span> : null}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </section>

        <form onSubmit={onSubmit} className="mt-4 flex gap-2">
          <input
            className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none ring-sky-400 focus:ring-2"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="digest semiconductor and AI infrastructure"
            disabled={busy}
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-slate-900 px-5 py-3 text-sm font-medium text-white disabled:opacity-60"
          >
            {busy ? 'Working…' : 'Run'}
          </button>
        </form>
      </div>
    </main>
  );
}
