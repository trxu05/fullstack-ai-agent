const logEl = document.getElementById("log");
const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const button = form.querySelector("button");

let sessionId = null;

function addBubble(role, text, meta = "") {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("span");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

async function ensureSession() {
  if (sessionId) return sessionId;
  const res = await fetch("/api/sessions", { method: "POST" });
  if (!res.ok) throw new Error("failed to create session");
  const data = await res.json();
  sessionId = data.sessionId;
  addBubble("assistant", "Session ready. Ask me to calculate, check time, or remember a key.");
  return sessionId;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  input.value = "";
  button.disabled = true;
  addBubble("user", message);

  try {
    const id = await ensureSession();
    const res = await fetch(`/api/sessions/${id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) throw new Error(`chat failed (${res.status})`);
    const data = await res.json();
    const tools = (data.toolsUsed || data.tools_used || [])
      .map((t) => t.name)
      .join(", ");
    const meta = `provider=${data.provider || "unknown"}${tools ? ` · tools=${tools}` : ""}`;
    addBubble("assistant", data.reply, meta);
  } catch (err) {
    addBubble("assistant", `Error: ${err.message}. Is the Python agent running on :8001?`);
  } finally {
    button.disabled = false;
    input.focus();
  }
});

ensureSession().catch((err) => {
  addBubble("assistant", `Could not start session: ${err.message}`);
});
