// TWB - sessao para o bot (docs/backend.md §8.87).
//
// Quando o navegador ganha um `sid` novo num mundo do Tribal Wars (login),
// manda os cookies daquele mundo para o painel local do bot
// (http://127.0.0.1:<porta>/api/session). O painel prova a sessao com o mesmo
// teste do bot antes de gravar. O `sid` e HttpOnly: so a API `chrome.cookies`
// de uma extensao o le, nenhum script de pagina.
//
// Nada vai para fora da maquina: o unico destino e 127.0.0.1/localhost.

const DEFAULT_PORT = 5000;
const WORLD_RE = /^[a-z]{2,6}\d{1,4}$/;

// Mercados = os host_permissions https do manifest (uma lista so).
const MARKETS = chrome.runtime.getManifest().host_permissions
  .filter((p) => p.startsWith("https://*."))
  .map((p) => p.slice("https://*.".length, -2));

function worldOf(host) {
  host = (host || "").replace(/^\./, "").toLowerCase();
  for (const market of MARKETS) {
    if (host.endsWith("." + market)) {
      const world = host.slice(0, -(market.length + 1));
      return WORLD_RE.test(world) ? { world, host } : null;
    }
  }
  return null;
}

function worldUrl(host) {
  return "https://" + host + "/game.php";
}

async function settings() {
  const s = await chrome.storage.local.get({ port: DEFAULT_PORT, auto: true });
  return s;
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Abas abertas em tela de jogo; o url filtrado funciona so com host_permissions.
async function gameTabs() {
  const patterns = MARKETS.map((m) => "https://*." + m + "/game.php*");
  const tabs = await chrome.tabs.query({ url: patterns });
  return tabs.filter((t) => t.url && worldOf(new URL(t.url).hostname));
}

async function readSession(host) {
  const list = await chrome.cookies.getAll({ url: worldUrl(host) });
  const cookies = {};
  const flags = {};
  for (const c of list) {
    cookies[c.name] = c.value;
    flags[c.name] = {
      httpOnly: c.httpOnly, secure: c.secure, hostOnly: c.hostOnly,
      domain: c.domain, session: c.session,
    };
  }
  return { cookies, flags };
}

async function setBadge(ok) {
  await chrome.action.setBadgeText({ text: ok === null ? "" : ok ? "OK" : "!" });
  await chrome.action.setBadgeBackgroundColor({ color: ok ? "#2e7d32" : "#c62828" });
}

// Manda a sessao do mundo `host`. `manual` manda mesmo que este sid ja tenha
// sido aceito antes; o automatico nao repete sid aceito.
async function pushSession(host, manual) {
  const { port } = await settings();
  const { cookies, flags } = await readSession(host);
  const world = worldOf(host).world;
  if (!cookies.sid) {
    const result = { at: Date.now(), world, ok: false, message: "sem sid: entre no jogo neste mundo" };
    await chrome.storage.local.set({ last: result });
    return result;
  }
  const fingerprint = await sha256(host + "|" + cookies.sid);
  const { accepted } = await chrome.storage.local.get({ accepted: null });
  if (!manual && accepted === fingerprint) {
    return { at: Date.now(), world, ok: true, message: "ja enviada", skipped: true };
  }
  let result;
  try {
    const res = await fetch("http://127.0.0.1:" + port + "/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: worldUrl(host), cookies, flags, user_agent: navigator.userAgent }),
    });
    const body = await res.json().catch(() => ({}));
    result = {
      at: Date.now(), world, ok: !!body.ok,
      message: body.message || body.error || ("HTTP " + res.status),
      flags: body.flags || "",
    };
  } catch (e) {
    result = {
      at: Date.now(), world, ok: false, offline: true,
      message: "painel nao respondeu em 127.0.0.1:" + port + " (ele esta aberto?)",
    };
  }
  const update = { last: result, pending: result.offline ? host : null };
  if (result.ok) update.accepted = fingerprint;
  await chrome.storage.local.set(update);
  await setBadge(result.ok);
  return result;
}

const timers = {};
function schedulePush(host) {
  // O login grava varios cookies em sequencia; espera assentar.
  clearTimeout(timers[host]);
  timers[host] = setTimeout(() => pushSession(host, false), 3000);
}

chrome.cookies.onChanged.addListener(async ({ cookie, removed }) => {
  if (removed || cookie.name !== "sid") return;
  const { auto } = await settings();
  if (!auto) return;
  const w = worldOf(cookie.domain);
  if (w) {
    schedulePush(w.host);
    return;
  }
  // sid gravado no dominio do mercado, nao no do mundo: vale a aba aberta.
  for (const tab of await gameTabs()) schedulePush(new URL(tab.url).hostname);
});

async function pushOpenTabs() {
  const { auto } = await settings();
  if (!auto) return;
  const seen = new Set();
  for (const tab of await gameTabs()) {
    const host = new URL(tab.url).hostname;
    if (!seen.has(host)) {
      seen.add(host);
      await pushSession(host, false);
    }
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("retry", { periodInMinutes: 1 });
  pushOpenTabs();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("retry", { periodInMinutes: 1 });
  pushOpenTabs();
});

// Painel fechado na hora do login: tenta de novo a cada minuto ate ele abrir.
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "retry") return;
  const { pending } = await chrome.storage.local.get({ pending: null });
  if (pending) await pushSession(pending, false);
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return false;
  if (msg && msg.type === "send" && worldOf(msg.host)) {
    pushSession(msg.host, true).then(reply);
    return true;
  }
  return false;
});
