// PromptBreaker client.
// Streams /api/attack (SSE) and renders each turn as a stack of
// color-coded role lines: ATK (amber), DEF (cyan), JDG (mauve).

const form           = document.getElementById("attack-form");
const runBtn         = document.getElementById("run-btn");
const statusEl       = document.getElementById("status");
const topbarStatusEl = document.getElementById("topbar-status");
const turnsEl        = document.getElementById("turns");
const finalEl        = document.getElementById("final");

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = "status " + cls;
  topbarStatusEl.textContent = text;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// One role row inside a turn card. `who` is the column label, `cls` picks
// the color via the .line.{attacker,defender,judge,meta} CSS classes.
function lineHtml(cls, who, content) {
  return `
    <div class="line ${cls}">
      <div class="who">${escapeHtml(who)}</div>
      <div class="content">${escapeHtml(content)}</div>
    </div>
  `;
}

function renderTurn(t) {
  const wrap = document.createElement("div");
  wrap.className = "turn";

  const badgeCls  = t.secret_revealed ? "leaked"   : "blocked";
  const badgeText = t.secret_revealed ? "leaked"   : "blocked";

  wrap.innerHTML = `
    <div class="turn-header">
      <span class="turn-num">turn ${t.turn}</span>
      <span class="sep">|</span>
      <span>strategy:</span>
      <span class="strategy">${escapeHtml(t.attacker_move.new_strategy)}</span>
      <span class="spacer"></span>
      <span class="badge ${badgeCls}">${badgeText}</span>
    </div>
    <div class="turn-body">
      ${lineHtml("attacker", "ATK analysis",  t.attacker_move.analysis)}
      ${lineHtml("attacker", "ATK rationale", t.attacker_move.rationale)}
      ${lineHtml("attacker", "ATK payload",   t.attacker_move.payload)}
      ${lineHtml("defender", "DEF reply",     t.defender_response)}
      ${lineHtml("judge",    "JDG verdict",   t.judge_reason)}
    </div>
  `;
  turnsEl.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

function renderFinal(r) {
  if (r.success) {
    setStatus(`attack succeeded in ${r.turns_used} turn(s)`, "success");
    finalEl.className = "success";
    finalEl.innerHTML = `
      <h3>[!!] attack succeeded -- secret leaked</h3>
      <p><strong>turns used:</strong> ${r.turns_used} / ${r.max_turns}</p>
      <p><strong>winning payload:</strong></p>
      <pre>${escapeHtml(r.winning_payload || "")}</pre>
    `;
  } else {
    setStatus(`defender held for ${r.max_turns} turn(s)`, "fail");
    finalEl.className = "fail";
    finalEl.innerHTML = `
      <h3>[ok] defender survived</h3>
      <p>attacker tried ${r.turns_used} strategies without leaking the secret.</p>
    `;
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  turnsEl.innerHTML = "";
  finalEl.innerHTML = "";
  finalEl.className = "";
  runBtn.disabled = true;
  setStatus("launching attack...", "running");

  const body = {
    defender_prompt: document.getElementById("defender_prompt").value,
    secret:          document.getElementById("secret").value,
    max_turns:       parseInt(document.getElementById("max_turns").value, 10),
  };

  try {
    const res = await fetch("/api/attack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok || !res.body) {
      setStatus(`request failed: HTTP ${res.status}`, "error");
      runBtn.disabled = false;
      return;
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleSseBlock(raw);
      }
    }
  } catch (err) {
    setStatus(`network error: ${err.message}`, "error");
  } finally {
    runBtn.disabled = false;
  }
});

function handleSseBlock(block) {
  let event = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;
  let parsed;
  try { parsed = JSON.parse(dataLines.join("\n")); }
  catch { return; }

  if (event === "turn") {
    setStatus(`running turn ${parsed.turn}...`, "running");
    renderTurn(parsed);
  } else if (event === "result") {
    renderFinal(parsed);
  } else if (event === "error") {
    setStatus(parsed.error || "unknown error", "error");
  }
}
