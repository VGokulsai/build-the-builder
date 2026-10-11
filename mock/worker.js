// Mock of Freya Bank's statement/debt services (service contract 2026-10-01) for the Build the Builder final.
// Serves exactly the bodies and status codes of test-customers.json, looked up as test-customers.md says.
import DATA from "./test-customers.json";

const CORS = { "Access-Control-Allow-Origin": "*" };
const BASE = "/voice/v1/";

function json(body, status = 200) {
  return Response.json(body, { status: status, headers: CORS });
}

function errorBody(status, code, message, type) {
  const guid = crypto.randomUUID().replace(/-/g, "");
  return json({ result: { guid, returnCode: code, messageText: message, code, message, type,
    details: { guid, rootCause: status === 404 ? "NotFoundException" : "InvalidArgumentsException", errorOrigin: "freya-statement-mock" } } }, status);
}

const NOT_FOUND = {
  "cards.list": ["FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı."],
  "cards.balance": ["FB_IVR_CHANNEL_120", "Kart bakiye servisi hatası: kart bulunamadı"],
  "statement.week.get": ["FB_IVR_CHANNEL_121", "Kart bulunamadı"],
  "statement.pdf.send": ["FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı"],
};

function missing(service, field) {
  const nf = NOT_FOUND[service];
  if (nf && !field) return errorBody(404, nf[0], nf[1], "WARNING");
  return errorBody(400, "INVALID_ARGUMENTS_ERROR", (field || "record") + " cannot be empty", "ERROR");
}

const str = (v) => (v === undefined || v === null ? "" : String(v).trim());
const isTemplate = (v) => typeof v === "string" && (v.startsWith("{{") || v.startsWith("%7B%7B"));

// Index: customer -> services; card -> customer.
const BY_CUSTOMER = {};
const BY_CARD = {};
for (const c of DATA.customers) {
  BY_CUSTOMER[str(c.customerNo)] = c;
  const cards = (((c.services["cards.list"] || {}).response || {}).data || {}).cards || [];
  for (const card of cards) BY_CARD[card.cardNumber] = c;
  for (const svc of ["cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change"]) {
    const entry = c.services[svc];
    if (entry && typeof entry === "object") for (const k of Object.keys(entry)) if (k.includes("*")) BY_CARD[k] = BY_CARD[k] || c;
  }
}

// An entry is {http, response[, delaySeconds]}, possibly nested under a key (card number, week).
const isAnswer = (e) => e && typeof e === "object" && "http" in e && "response" in e;

async function answer(entry) {
  if (entry.delaySeconds) await new Promise((r) => setTimeout(r, entry.delaySeconds * 1000));
  return json(entry.response, entry.http);
}

function find(entry, keys) {
  let e = entry;
  for (const k of keys) {
    if (isAnswer(e)) return e;
    if (!e || typeof e !== "object") return null;
    e = e[k];
  }
  return isAnswer(e) ? e : null;
}

async function handle(service, body) {
  const d = (body && body.data) || {};
  const first = DATA.customers[0];
  if (["cards.list", "contact.email.get", "statement.pdf.send"].includes(service)) {
    if (!str(d.customerNo)) return missing(service, "customerNo");
    if (service === "contact.email.get" && !str(d.intAddressInfoType)) return missing(service, "intAddressInfoType");
    const c = isTemplate(d.customerNo) ? first : BY_CUSTOMER[str(d.customerNo)];
    const e = c && find(c.services[service], [str(d.cardNumber)]);
    return e ? answer(e) : missing(service);
  }
  if (!str(d.cardNumber)) return missing(service, "card number");
  const card = str(d.cardNumber);
  const c = BY_CARD[card];
  if (!c) return missing(service);
  const svc = c.services[service];
  const keys = [card];
  if (service === "statement.week.decide" || service === "statement.week.change") keys.push(str(d.newStatementWeek));
  const e = find(svc, keys) || find(svc, keys.slice(1));
  return e ? answer(e) : missing(service);
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: { ...CORS, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "*" } });
    if (request.method === "GET" && url.pathname === "/health") return json({ durum: "ok", customers: DATA.customers.length });
    if (request.method === "POST" && url.pathname === "/oauth2/token") return json({ access_token: "mock-token", token_type: "Bearer", expires_in: 1800 });
    if (request.method === "POST" && url.pathname.startsWith(BASE)) {
      let body = null;
      try { body = await request.json(); } catch { body = null; }
      return handle(url.pathname.slice(BASE.length), body);
    }
    return json({ hata: "bulunamadı" }, 404);
  },
};
