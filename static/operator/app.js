const API = "/api/operator";
const STORAGE_KEY = "operator_workspace_token";

const $ = (id) => document.getElementById(id);

function authHeaders() {
  const t = sessionStorage.getItem(STORAGE_KEY);
  const h = { Accept: "application/json" };
  if (t) h["Authorization"] = "Bearer " + t;
  return h;
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { ...authHeaders(), ...opts.headers },
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const err = new Error(data?.detail || res.statusText || "Request failed");
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

let selectedId = null;

function showGate(msg, isErr) {
  const el = $("gateMsg");
  el.hidden = false;
  el.textContent = msg;
  el.className = "msg " + (isErr ? "err" : "ok");
}

function openApp(enabled) {
  $("gate").hidden = enabled;
  $("app").hidden = !enabled;
}

async function checkStatus() {
  try {
    const s = await fetch(API + "/status").then((r) => r.json());
    if (!s.workspace_enabled) {
      showGate(
        "На сервері не задано OPERATOR_WORKSPACE_TOKEN. Додайте змінну в Railway і перезапустіть сервіс.",
        true,
      );
      openApp(false);
      return false;
    }
    return true;
  } catch {
    showGate("Не вдалося звʼязатися з API статусу.", true);
    return false;
  }
}

function renderList(rows) {
  const ul = $("convList");
  ul.innerHTML = "";
  for (const r of rows) {
    const li = document.createElement("li");
    li.dataset.id = String(r.telegram_id);
    if (r.telegram_id === selectedId) li.classList.add("active");
    const pending = r.has_pending_draft
      ? '<span class="badge">чернетка</span>'
      : "";
    li.innerHTML =
      `<div class="tid">Клієнт ${esc(r.telegram_id)}${pending}</div>` +
      `<div class="prev">${esc(r.last_message_preview || "—")}</div>`;
    li.addEventListener("click", () => selectConversation(r.telegram_id));
    ul.appendChild(li);
  }
  $("statusPill").textContent = rows.length ? `${rows.length} у списку` : "порожньо";
}

async function loadList() {
  const rows = await apiFetch("/conversations?limit=100");
  renderList(rows);
}

async function selectConversation(telegramId) {
  selectedId = telegramId;
  document.querySelectorAll("#convList li").forEach((li) => {
    li.classList.toggle("active", li.dataset.id === String(telegramId));
  });
  $("empty").hidden = true;
  $("detail").hidden = false;
  $("dTitle").textContent = "Клієнт " + telegramId;
  const d = await apiFetch("/conversations/" + telegramId);
  $("dMeta").textContent =
    "Оновлено: " + (d.last_updated || "—") + (d.pending_draft ? " · є чернетка" : "");
  const hist = $("history");
  hist.innerHTML = "";
  for (const turn of d.history || []) {
    const role = turn.role === "assistant" ? "assistant" : "user";
    const div = document.createElement("div");
    div.className = "bubble " + role;
    div.innerHTML =
      `<div class="who">${role === "user" ? "Клієнт" : "Відповідь / бот"}</div>` +
      esc(turn.content ?? "");
    hist.appendChild(div);
  }
  const draftEl = $("draft");
  if (d.pending_draft) {
    draftEl.textContent = d.pending_draft;
    $("btnSendDraft").disabled = false;
  } else {
    draftEl.textContent = "Немає збереженої чернетки (можна надіслати власний текст нижче).";
    $("btnSendDraft").disabled = true;
  }
  $("actionMsg").hidden = true;
  $("customText").value = "";
}

function flashAction(msg, isErr) {
  const el = $("actionMsg");
  el.hidden = false;
  el.textContent = msg;
  el.className = "msg " + (isErr ? "err" : "ok");
}

async function init() {
  $("saveToken").addEventListener("click", async () => {
    const v = $("token").value.trim();
    if (!v) {
      showGate("Введіть токен.", true);
      return;
    }
    sessionStorage.setItem(STORAGE_KEY, v);
    showGate("Токен збережено в сесії браузера.", false);
    try {
      await apiFetch("/conversations?limit=1");
      openApp(true);
      await loadList();
    } catch (e) {
      sessionStorage.removeItem(STORAGE_KEY);
      showGate(e.body?.detail || e.message || "Помилка авторизації", true);
      openApp(false);
    }
  });

  $("refresh").addEventListener("click", async () => {
    try {
      await loadList();
      if (selectedId != null) await selectConversation(selectedId);
    } catch (e) {
      flashAction(e.body?.detail || e.message, true);
    }
  });

  $("btnSendDraft").addEventListener("click", async () => {
    if (selectedId == null) return;
    try {
      await apiFetch("/conversations/" + selectedId + "/send-draft", { method: "POST" });
      flashAction("Чернетку надіслано клієнту в Telegram.", false);
      await loadList();
      await selectConversation(selectedId);
    } catch (e) {
      flashAction(e.body?.detail || e.message, true);
    }
  });

  $("btnSendCustom").addEventListener("click", async () => {
    if (selectedId == null) return;
    const text = $("customText").value.trim();
    if (!text) {
      flashAction("Введіть текст повідомлення.", true);
      return;
    }
    try {
      await apiFetch("/conversations/" + selectedId + "/reply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      flashAction("Повідомлення надіслано клієнту.", false);
      $("customText").value = "";
      await loadList();
      await selectConversation(selectedId);
    } catch (e) {
      flashAction(e.body?.detail || e.message, true);
    }
  });

  $("btnEscalate").addEventListener("click", async () => {
    if (selectedId == null) return;
    try {
      await apiFetch("/conversations/" + selectedId + "/escalate", { method: "POST" });
      flashAction("Ескалацію надіслано координатору (MANAGER_CHAT_ID / OPERATOR_CHAT_ID).", false);
    } catch (e) {
      flashAction(e.body?.detail || e.message, true);
    }
  });

  const ok = await checkStatus();
  if (!ok) return;
  const existing = sessionStorage.getItem(STORAGE_KEY);
  if (existing) {
    $("token").value = existing;
    try {
      await apiFetch("/conversations?limit=1");
      openApp(true);
      await loadList();
    } catch {
      sessionStorage.removeItem(STORAGE_KEY);
      openApp(false);
    }
  }
}

init();
