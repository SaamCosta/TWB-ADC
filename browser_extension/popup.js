// Popup: mostra o mundo da aba, se o painel esta no ar, e manda a sessao na
// mao. Quem manda de verdade e o background.js (mesma funcao do automatico).

const WORLD_RE = /^[a-z]{2,6}\d{1,4}$/;
const MARKETS = chrome.runtime.getManifest().host_permissions
  .filter((p) => p.startsWith("https://*."))
  .map((p) => p.slice("https://*.".length, -2));

function worldOf(host) {
  host = (host || "").toLowerCase();
  for (const market of MARKETS) {
    if (host.endsWith("." + market)) {
      const world = host.slice(0, -(market.length + 1));
      return WORLD_RE.test(world) ? { world, host } : null;
    }
  }
  return null;
}

const $ = (id) => document.getElementById(id);

function show(el, text, cls) {
  el.textContent = text;
  el.className = "row " + (cls || "");
}

function describe(result) {
  if (!result) return null;
  const when = new Date(result.at).toLocaleTimeString();
  let text = when + " - " + (result.world || "?") + ": " + result.message;
  if (result.flags) text += " [" + result.flags + "]";
  return text;
}

async function main() {
  const s = await chrome.storage.local.get({ port: 5000, auto: true, last: null });
  $("port").value = s.port;
  $("auto").checked = s.auto;
  if (s.last) show($("result"), describe(s.last), s.last.ok ? "ok" : "bad");

  $("port").addEventListener("change", () => {
    const port = parseInt($("port").value, 10);
    if (port > 0 && port < 65536) chrome.storage.local.set({ port });
  });
  $("auto").addEventListener("change", () => chrome.storage.local.set({ auto: $("auto").checked }));

  try {
    const res = await fetch("http://127.0.0.1:" + s.port + "/api/session");
    const body = await res.json();
    show($("panel"), body.panel === "twb" ? "Painel do bot: no ar" : "Porta responde, mas nao e o painel", body.panel === "twb" ? "ok" : "bad");
  } catch (e) {
    show($("panel"), "Painel do bot nao respondeu em 127.0.0.1:" + s.port + ". Abra o painel.", "bad");
  }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let w = null;
  try { w = tab && tab.url ? worldOf(new URL(tab.url).hostname) : null; } catch (e) { w = null; }
  if (!w) {
    show($("world"), "Abra uma aba do jogo (o mundo em que o bot joga) e clique de novo.", "muted");
    return;
  }
  show($("world"), "Mundo desta aba: " + w.world + " (" + w.host + ")");
  $("send").disabled = false;
  $("send").addEventListener("click", async () => {
    $("send").disabled = true;
    show($("result"), "Enviando e testando a sessao...", "muted");
    const result = await chrome.runtime.sendMessage({ type: "send", host: w.host });
    show($("result"), describe(result) || "sem resposta", result && result.ok ? "ok" : "bad");
    $("send").disabled = false;
  });
}

main();
