// Client for PromptBreaker. Sends the defender config to /api/attack and
// renders the SSE stream (one event per attacker turn, then a final result).

const form    = document.getElementById("attack-form");
const runBtn  = document.getElementById("run-btn");
const statusEl = document.getElementById("status");
const turnsEl  = document.getElementById("turns");
const finalEl  = document.getElementById("final");

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = "status " + cls;
}

function renderTurn(t) {
  const wrap = document.createElement("div");
  wrap.className = "turn";

  const badgeCls = t.secret_revealed ? "leaked" : "blocked";
  const badgeText = t.secret_revealed ? "LEAKED" : "blocked";

  wrap.innerHTML = `
    <div class="turn-header">
      <span>Turn ${t.turn} — strategy: <code>${escapeHtml(t.attacker_move.new_strategy)}</code></span>
      <span class="badge ${badgeCls}">${badgeText}</span>
    </div>
    <dl>
      <dt>Attacker analysis</dt><dd>${escapeHtml(t.attacker_move.analysis)}</dd>
      <dt>Attacker rationale</dt><dd>${escapeHtml(t.attacker_move.rationale)}</dd>
      <dt>Payload sent to defender</dt><dd>${escapeHtml(t.attacker_move.payload)}</dd>
      <dt>Defender response</dt><dd>${escapeHtml(t.defender_response)}</dd>
      <dt>Judge verdict</dt><dd>${escapeHtml(t.judge_reason)}</dd>
    </dl>
  `;
  turnsEl.appendChild(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "end" });
}

function renderFinal(r) {
  finalEl.className = r.success ? "success" : "fail";
  if (r.success) {
    setStatus(`Attack succeeded in ${r.turns_used} turn(s).`, "success");
    finalEl.innerHTML = `
      <h3 style="margin-top:0;color:var(--success)">✅ Attack succeeded</h3>
      <p><strong>Turns used:</strong> ${r.turns_used} / ${r.max_turns}</p>
      <p><strong>Winning payload:</strong></p>
      <pre>${escapeHtml(r.winning_payload || "")}</pre>
    `;
  } else {
    setStatus(`Defender held for ${r.max_turns} turns.`, "fail");
    finalEl.innerHTML = `
      <h3 style="margin-top:0;color:var(--danger)">🛡️ Defender survived</h3>
      <p>The Attacker tried ${r.turns_used} strategies without leaking the secret.</p>
    `;
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  turnsEl.innerHTML = "";
  finalEl.innerHTML = "";
  finalEl.className = "";
  runBtn.disabled = true;
  setStatus("Launching attack…", "running");

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
      setStatus(`Request failed: HTTP ${res.status}`, "error");
      runBtn.disabled = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // SSE messages are separated by a blank line.
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleSseBlock(raw);
      }
    }
  } catch (err) {
    setStatus(`Network error: ${err.message}`, "error");
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
    setStatus(`Running turn ${parsed.turn}…`, "running");
    renderTurn(parsed);
  } else if (event === "result") {
    renderFinal(parsed);
  } else if (event === "error") {
    setStatus(parsed.error || "Unknown error", "error");
  }
}
