// Geocode merchant addresses with the Kakao Local API and write data/geocode.json.
//
// Usage (Node 18+, from the repo root):
//   KAKAO_REST_KEY=xxxxxxxx node scripts/geocode.mjs data/source/queries.json
//
// queries.json is a JSON array of [no, name, address] rows, for example
//   [[5, "밥제작소", "경남 산청군 산청읍 웅석봉로 27"], ...]
// (python scripts/build_data.py --queries writes it from the spreadsheet).
//
// Only rows missing from the existing data/geocode.json are requested, so a
// monthly update only spends API calls on new merchants.
import fs from "node:fs";

const KEY = process.env.KAKAO_REST_KEY;
if (!KEY) {
  console.error("Set KAKAO_REST_KEY (Kakao Developers > App > REST API key).");
  process.exit(1);
}
const queries = JSON.parse(fs.readFileSync(process.argv[2] || "data/source/queries.json", "utf8"));
const OUT = "data/geocode.json";
const geo = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, "utf8")) : { cats: [], rows: [] };
const done = new Set(geo.rows.map((r) => r[0]));

const H = { headers: { Authorization: "KakaoAK " + KEY } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function api(path) {
  for (let t = 0; t < 4; t++) {
    const r = await fetch("https://dapi.kakao.com" + path, H).catch(() => null);
    if (r && r.status === 429) { await sleep(1500); continue; }
    if (r && r.ok) return r.json();
    await sleep(800);
  }
  return { documents: [] };
}

// Name similarity: strip legal-entity words, then compare character bigrams.
const norm = (s) => s.replace(/\(주\)|㈜|주식회사|농업회사법인|영농조합법인|유한회사|\(유\)|[\s().,·&_*\-]/g, "").toLowerCase();
function sim(a, b) {
  a = norm(a); b = norm(b);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (a.includes(b) || b.includes(a)) return 0.85;
  const bg = (s) => { const o = new Set(); for (let i = 0; i < s.length - 1; i++) o.add(s.slice(i, i + 2)); return o; };
  const A = bg(a), B = bg(b); let c = 0; A.forEach((x) => B.has(x) && c++);
  return (2 * c) / (A.size + B.size || 1);
}
const catIndex = (c) => {
  if (!c) return -1;
  let k = geo.cats.indexOf(c);
  if (k < 0) { geo.cats.push(c); k = geo.cats.length - 1; }
  return k;
};

let n = 0;
for (const [no, name, addr] of queries) {
  if (done.has(no)) continue;
  let x, y, prec = 0;
  const a = await api("/v2/local/search/address.json?size=1&query=" + encodeURIComponent(addr));
  let d = a.documents[0];
  if (!d) {
    // Fall back to the road itself (drops building number and branch-road suffix).
    const road = addr.replace(/(\S+?(?:로|길))\d+번[가나]?길 .*/, "$1").replace(/ \d+(-\d+)?$/, "");
    d = (await api("/v2/local/search/address.json?size=1&query=" + encodeURIComponent(road))).documents[0];
    if (d) prec = 2;
  }
  if (d) { x = +d.x; y = +d.y; }

  // Keyword search near the address to find the Kakao place page.
  const kq = name.replace(/\(주\)|㈜|주식회사|농업회사법인|\(유\)/g, " ").replace(/_.*$/, "").trim();
  let best = null;
  if (kq) {
    const near = x ? `&x=${x}&y=${y}&radius=2000&sort=distance` : "&rect=127.6,35.15,128.1,35.6";
    const k = await api("/v2/local/search/keyword.json?size=15&query=" + encodeURIComponent(kq) + near);
    for (const p of k.documents) {
      let s = sim(kq, p.place_name);
      const sameAddr = p.road_address_name && addr.includes(p.road_address_name.replace(/^경남 산청군 /, ""));
      if (sameAddr) s += 0.4;
      if (x && +p.distance > 600 && !sameAddr) s -= 0.3;
      if (s >= 0.6 && (!best || s > best.s)) best = { s, p };
    }
  }
  if (!x && best) { x = +best.p.x; y = +best.p.y; prec = 1; }
  if (x) {
    geo.rows.push([no, +y.toFixed(6), +x.toFixed(6), best ? best.p.id : "", catIndex(best && best.p.category_name), (best && best.p.phone) || "", prec]);
  } else {
    console.warn("not found:", no, name, addr);
  }
  if (++n % 50 === 0) console.log(n, "done");
  await sleep(60);
}

geo.rows.sort((a, b) => a[0] - b[0]);
geo.generated = new Date().toISOString().slice(0, 10);
fs.writeFileSync(OUT, JSON.stringify(geo));
console.log("geocoded", n, "new rows; total", geo.rows.length);
