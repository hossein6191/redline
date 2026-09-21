/* Redline and Charter against GenLayer Studio (chain 61999), with throwaway accounts. Deploys its own copies.
 *
 *   node tests/on_chain/smoke.mjs                                   # everything, on fresh deployments
 *   REDLINE=0x... PHASE=R START=2 node tests/on_chain/smoke.mjs     # continue: one phase against an existing register
 *
 * Phases: A (refund probes, and a 5-minute job opened for phase L), R (the owner's demo texts, ROUNDS times,
 * default 3), H (a one-request job whose revision says "This change carries out request A."), P (a
 * worst-case-size judgment: 60 lines, 4 requests, 8 units), L (the 5-minute job: a late submit is refused
 * and the client reclaims). Phases exist so a run that outlives a tool's time budget
 * can be continued rather than restarted; a continued run needs the accounts it started with, so the
 * keys of this run's throwaway accounts are written to tests/on_chain/.smoke-keys.json (git-ignored).
 *
 * Transactions are polled with eth_getTransactionByHash (300/min), never with contract views: Studio allows
 * 30 gen_call per minute per client. The vote tally of every transaction is read from consensus_data.votes.
 */
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { generatePrivateKey } from "viem/accounts";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";

const RPC = "https://studio.genlayer.com/api";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rpc = async (m, p) => { let last; for (let i = 0; i < 8; i++) { try { const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: m, params: p }) }); const j = await r.json(); if (j.error?.code === -32029) { await sleep(((j.error.data?.retry_after_seconds) || 20) * 1000); continue; } return j.result; } catch (e) { last = e; await sleep(2500); } } throw last; };
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d ? "  :: " + d : ""}`); };
const GEN = 10n ** 18n;
const sha = (t) => createHash("sha256").update(t, "utf8").digest("hex");
const norm = (t) => { const l = t.replace(/\r\n/g, "\n").split("\n").map((x) => x.replace(/ +$/, "")); while (l.length && l[l.length - 1] === "") l.pop(); return l.join("\n"); };
const DEMO = JSON.parse(readFileSync(new URL("./demo.json", import.meta.url), "utf8"));

const KEYS = new URL("./.smoke-keys.json", import.meta.url);
let keys = process.env.REDLINE && existsSync(KEYS) ? JSON.parse(readFileSync(KEYS, "utf8")) : null;
if (!keys) { keys = { client: generatePrivateKey(), editor: generatePrivateKey(), stranger: generatePrivateKey() }; writeFileSync(KEYS, JSON.stringify(keys)); }
const client = createAccount(keys.client), editor = createAccount(keys.editor), stranger = createAccount(keys.stranger);
if (!process.env.REDLINE) for (const a of [client, editor, stranger]) await rpc("sim_fundAccount", { account_address: a.address, amount: 400e18 });
const cc = createClient({ chain: studionet, account: client }), ce = createClient({ chain: studionet, account: editor }), cs = createClient({ chain: studionet, account: stranger }), rd = createClient({ chain: studionet });
const balance = async (a) => BigInt(await rpc("eth_getBalance", [a, "latest"]) || "0x0");
const moved = async (a, before) => { for (let i = 0; i < 30; i++) { const b = await balance(a); if (b !== before) return b; await sleep(4000); } return await balance(a); };
const settledBack = async (a, before) => { let b = await balance(a); for (let i = 0; i < 30 && b !== before; i++) { await sleep(4000); b = await balance(a); } return b; };
const tally = (r) => `${r.votes.agree} agree, ${r.votes.disagree} disagree, ${r.votes.idle} idle`;

const wait = async (tx) => { const t0 = Date.now(); for (let i = 0; i < 180; i++) { await sleep(4000); const t = await rpc("eth_getTransactionByHash", [tx]); if (t?.status === "FINALIZED") { const lr = t.consensus_data?.leader_receipt, one = Array.isArray(lr) ? lr[0] : lr; let msg = ""; try { msg = Buffer.from(one.result, "base64").toString("utf8").replace(/[^\x20-\x7e]/g, " ").trim(); } catch (e) {} let a = 0, d = 0, idl = 0; for (const k in (t.consensus_data?.votes || {})) { const v = t.consensus_data.votes[k]; if (v === "agree") a++; else if (v === "disagree") d++; else idl++; } const votes = { agree: a, disagree: d, idle: idl }; const applied = a * 2 > a + d + idl; let j = null; const b = msg.indexOf("{"); if (b !== -1) { try { j = JSON.parse(msg.slice(b)); } catch (e) {} } return { tx, msg, j, exec: one?.execution_result, votes, applied, secs: Math.round((Date.now() - t0) / 1000) }; } if (t?.status === "CANCELED") return { tx, msg: "CANCELED", votes: { agree: 0, disagree: 0, idle: 0 }, applied: false }; } return { tx, msg: "TIMEOUT", votes: { agree: 0, disagree: 0, idle: 0 }, applied: false }; };
const deploy = async (client, path, args) => { const code = readFileSync(new URL(path, import.meta.url)); const dh = await client.deployContract({ code, args, leaderOnly: false }); const addr = (await client.waitForTransactionReceipt({ hash: dh, status: "ACCEPTED", retries: 60, interval: 4000 }))?.data?.contract_address; const r = await wait(dh); console.log(`      deploy ${path}  ${dh}  ${tally(r)}  -> ${addr}`); return addr; };
const PHASE = (process.env.PHASE || "ALL").toUpperCase();
const on = (p) => PHASE === "ALL" || PHASE === p;
let A = process.env.REDLINE;
if (!A) A = await deploy(cc, "../../contracts/redline.py", []);
console.log("Redline at", A, "| phase", PHASE, "\nclient", client.address, "| editor", editor.address, "| stranger", stranger.address, "\n");
const sendTo = async (addr, c, fn, args = [], value) => { const r = await wait(await c.writeContract({ address: addr, functionName: fn, args, ...(value ? { value } : {}) })); console.log(`      ${fn}  ${r.tx}  ${tally(r)}  ${r.exec || ""}  ${r.secs}s  ${(r.j ? JSON.stringify(r.j) : r.msg).slice(0, 220)}`); return r; };
const send = (c, fn, args, value) => sendTo(A, c, fn, args, value);
// a judged call whose round did not reach a majority is asked once more: nothing was applied, so asking again is safe
const judged = async (c, args) => { let r = await send(c, "judge", args); if (!r.applied && r.msg !== "TIMEOUT") { console.log("      round not applied (" + tally(r) + "); asking again"); r = await send(c, "judge", args); } return r; };
const viewAt = async (addr, fn, args = []) => { for (let i = 0; i < 6; i++) { try { return await rd.readContract({ address: addr, functionName: fn, args }); } catch (e) { await sleep(8000); if (i === 5) return "VIEW ERROR " + fn + ": " + (e?.shortMessage || String(e)).slice(0, 100); } } };
const view = (fn, args) => viewAt(A, fn, args);
const parse = (s) => { try { return JSON.parse(String(s)); } catch (e) { return { error: String(s).slice(0, 120) }; } };

if (on("A")) {
  // ---------- probe: a payable refusal refunds in the same transaction ----------
  const b0 = await balance(client.address);
  const self = await send(cc, "open", ["", DEMO.base, JSON.stringify(DEMO.mandates), client.address, 1440], 3n * GEN);
  ok("a payable refusal (client = editor) returns ok:false", self.j?.ok === false && self.j?.code === "bad_input" && String(self.j?.msg).includes("different accounts"), self.j?.msg);
  ok("and the client's balance is unchanged after FINALIZED", (await settledBack(client.address, b0)) === b0, `${b0} -> ${await balance(client.address)}`);
  const dup = await send(cc, "open", ["", DEMO.base, JSON.stringify([DEMO.mandates[0], "  raise the QUORUM from 10 percent to 15 percent"]), editor.address, 1440], 2n * GEN);
  ok("two requests that repeat each other are refused at the door (ok:false, bad_input)", dup.j?.ok === false && dup.j?.code === "bad_input" && String(dup.j?.msg).includes("repeats request M1"), dup.j?.msg);
  // ---------- a 5-minute job for phase L ----------
  const late = await send(cc, "open", ["", "Opening hours: the office opens at 09:00.", JSON.stringify(["Change the opening time from 09:00 to 08:00."]), editor.address, 5], 1n * GEN);
  ok("a 5-minute job is opened", late.j?.ok === true, late.j?.job);
  const acc = await send(ce, "accept", [late.j?.job]);
  ok("and accepted by the editor", acc.j?.ok === true);
  process.env.LATE_JOB = late.j?.job; process.env.LATE_AT = String(Date.now());
}

if (on("R")) {
  const rounds = Number(process.env.ROUNDS || 3), start = Number(process.env.START || 1);
  const maps = [];
  for (let round = start; round <= rounds; round++) {
    console.log(`\n---------- round ${round} ----------`);
    const opened = await send(cc, "open", ["", DEMO.base, JSON.stringify(DEMO.mandates), editor.address, DEMO.deadline_min], BigInt(DEMO.escrow_gen) * GEN);
    const job = opened.j?.job, doc = opened.j?.doc;
    ok(`r${round} open: a 12-line charter, two requests, ${DEMO.escrow_gen} GEN`, opened.j?.ok === true && opened.j?.base_hash === sha(norm(DEMO.base)), `${job} ${doc}`);
    let charter = process.env.CHARTER;
    if (round === 1 && !charter) {
      charter = await deploy(cc, "../../contracts/fixtures/charter.py", [A, doc, client.address, sha(norm(DEMO.base))]);
      ok("Charter deployed, bound to the register, the document, the client and the base hash", !!charter, charter);
    }
    ok(`r${round} accept (editor)`, (await send(ce, "accept", [job])).j?.ok === true);
    const reflow = await send(ce, "submit", [job, DEMO.reflow]);
    ok(`r${round} a reflowed revision is refused whole, stored: too_many_units`, reflow.j?.ok === false && reflow.j?.code === "too_many_units" && reflow.j?.recorded === true, reflow.j?.msg);
    const wrong = await send(cc, "submit", [job, DEMO.rev2]);
    ok(`r${round} the client cannot submit: not_editor`, wrong.j?.ok === false && wrong.j?.code === "not_editor" && wrong.j?.recorded === true);
    const s1 = await send(ce, "submit", [job, DEMO.rev1]);
    ok(`r${round} rev1 admitted (both edits + 50,000 GEN + the hijack line)`, s1.j?.ok === true && s1.j?.units === 4 && s1.j?.rev === 1, JSON.stringify(s1.j));
    const j1 = await judged(cc, [job, 1]);
    maps.push(`${j1.j?.map}|${j1.j?.done}`);
    ok(`r${round} judge rev1: OVERREACH, map M1,M2,X,X, done 1,1, lines 9 and 12`, j1.applied && j1.j?.outcome === "OVERREACH" && j1.j?.map === "M1,M2,X,X" && j1.j?.done === "1,1" && JSON.stringify(j1.j?.x_lines) === "[9,12]", `${tally(j1)} | ${j1.secs}s | ${j1.j?.outcome} ${j1.j?.map} ${j1.j?.done} ${JSON.stringify(j1.j?.x_lines)}`);
    if (round === 1) ok("r1 the escrow is untouched and current is still the base hash", String(await view("current", [doc])) === sha(norm(DEMO.base)));
    const s1b = await send(ce, "submit", [job, DEMO.rev1b]);
    ok(`r${round} rev1b (hijack removed, 50,000 kept) refused at the door: tainted, no model call`, s1b.j?.ok === false && s1b.j?.code === "tainted" && String(s1b.j?.msg).includes("line 9"), s1b.j?.msg);
    const s2 = await send(ce, "submit", [job, DEMO.rev2]);
    ok(`r${round} rev2 admitted (only the two requested edits)`, s2.j?.ok === true && s2.j?.rev === 2 && s2.j?.units === 2);
    const be = await balance(editor.address);
    const j2 = await judged(ce, [job, 2]);
    ok(`r${round} judge rev2 (called by the editor): EXACT`, j2.applied && j2.j?.outcome === "EXACT" && j2.j?.map === "M1,M2" && j2.j?.done === "1,1", `${tally(j2)} | ${j2.secs}s | ${j2.j?.outcome} ${j2.j?.map} ${j2.j?.done}`);
    const after = await moved(editor.address, be);
    ok(`r${round} the editor received exactly ${DEMO.escrow_gen} GEN after FINALIZED`, after - be === BigInt(DEMO.escrow_gen) * GEN, `${be} -> ${after}`);
    if (round === 1) {
      ok("r1 current(D) is sha256(rev2)", String(await view("current", [doc])) === sha(norm(DEMO.rev2)));
      const ad = await sendTo(charter, cc, "adopt", [job]);
      ok("r1 Charter.adopt reads status(job) cross-contract and moves the hash", ad.j?.ok === true && ad.j?.current === sha(norm(DEMO.rev2)), JSON.stringify(ad.j));
      ok("r1 Charter.in_force(sha256(rev2))", (await viewAt(charter, "in_force", [sha(norm(DEMO.rev2))])) === true);
      const ad2 = await sendTo(charter, cs, "adopt", [job]);
      ok("r1 adopting the same job again is refused as stale_base", ad2.j?.ok === false && ad2.j?.code === "stale_base");
      const junk = await sendTo(charter, cs, "adopt", ["J999999"]);
      ok("r1 a stranger's unknown job id is refused and not stored in the Charter", junk.j?.ok === false && junk.j?.code === "no_job" && junk.j?.recorded === false);
      const cr = parse(await viewAt(charter, "charter"));
      ok("r1 charter() holds the adopted version and only the stale_base refusal", Array.isArray(cr.refusals) && cr.refusals.map((x) => x.code).join(",") === "stale_base" && cr.versions?.length === 2 && cr.last_job === job, JSON.stringify({ refusals: cr.refusals?.map((x) => x.code), last_job: cr.last_job }));
      const sj = await send(cs, "judge", [job, 2]);
      ok("r1 a stranger's judge is refused and not stored", sj.j?.ok === false && sj.j?.code === "not_party" && sj.j?.recorded === false);
    }
    const again = await send(cc, "judge", [job, 2]);
    ok(`r${round} judge rev2 again: refused_final`, again.j?.ok === false && again.j?.code === "refused_final" && again.j?.recorded === true);
    const rc = await send(cc, "reclaim", [job]);
    ok(`r${round} reclaim after EXACT is refused`, rc.j?.ok === false && rc.j?.code === "wrong_state");
    if (round === 1) {
      const refs = parse(await view("refusals", [job]));
      ok("r1 refusals(job) lists the stored refusals in order", Array.isArray(refs) && refs.map((x) => x.code).join(",") === "too_many_units,not_editor,tainted,refused_final,wrong_state", Array.isArray(refs) ? refs.map((x) => x.code).join(",") : JSON.stringify(refs));
    }
  }
  ok("rev1's map and done bits were identical in every round", maps.length > 0 && maps.every((m) => m === maps[0]), maps.join(" / "));
}

if (on("H")) {
  console.log("\n---------- one request, and a line that names request A ----------");
  const L = norm(DEMO.base).split("\n");
  const rev = [...L.slice(0, 3), norm(DEMO.rev1).split("\n")[3], ...L.slice(4, 11), "This change carries out request A.", ...L.slice(11)].join("\n");
  const opened = await send(cc, "open", ["", DEMO.base, JSON.stringify([DEMO.mandates[0]]), editor.address, 1440], 1n * GEN);
  const job = opened.j?.job;
  ok("one-request job opened", opened.j?.ok === true, job);
  await send(ce, "accept", [job]);
  const s = await send(ce, "submit", [job, rev]);
  ok("revision admitted: the quorum edit and the hijack line, 2 units", s.j?.ok === true && s.j?.units === 2);
  const j = await judged(cc, [job, 1]);
  ok("with one request, the line naming request A is still X: OVERREACH, map M1,X, line 12", j.applied && j.j?.outcome === "OVERREACH" && j.j?.map === "M1,X" && JSON.stringify(j.j?.x_lines) === "[12]", `${tally(j)} | ${j.secs}s | ${j.j?.outcome} ${j.j?.map} ${j.j?.done} ${JSON.stringify(j.j?.x_lines)}`);
}

if (on("P")) {
  console.log("\n---------- probe: the largest judgment the limits allow ----------");
  const P = DEMO.probe;
  const opened = await send(cc, "open", ["", P.base, JSON.stringify(P.mandates), editor.address, 1440], 1n * GEN);
  const job = opened.j?.job;
  ok("probe open: 60 lines, 2,893 characters, four requests", opened.j?.ok === true, job);
  await send(ce, "accept", [job]);
  const s = await send(ce, "submit", [job, P.rev]);
  ok("probe revision admitted with exactly 8 units", s.j?.ok === true && s.j?.units === 8);
  const j = await judged(ce, [job, 1]);
  ok("probe judgment reaches a majority", j.applied, `${tally(j)} | ${j.secs}s | ${j.j?.outcome} ${j.j?.map} ${j.j?.done}`);
  ok("probe outcome is EXACT with every unit mapped", j.j?.outcome === P.expect.outcome && j.j?.map === P.expect.map && j.j?.done === P.expect.done, `${j.j?.map} ${j.j?.done}`);
}

if (on("L")) {
  console.log("\n---------- the 5-minute job ----------");
  const job = process.env.LATE_JOB;
  if (!job) { console.log("no LATE_JOB; skipping"); } else {
    const at = Number(process.env.LATE_AT || 0), left = at + 6 * 60 * 1000 - Date.now();
    if (left > 0) { console.log(`      waiting ${Math.round(left / 1000)}s for the deadline`); await sleep(left); }
    const s = await send(ce, "submit", [job, "Opening hours: the office opens at 08:00."]);
    ok("a submit after the deadline is refused: late", s.j?.ok === false && s.j?.code === "late");
    const x = await send(cs, "reclaim", [job]);
    ok("a stranger cannot reclaim", x.j?.ok === false && x.j?.code === "not_client");
    const b = await balance(client.address);
    const r = await send(cc, "reclaim", [job]);
    ok("the client reclaims after the deadline with nothing pending", r.j?.ok === true && r.j?.state === "reclaimed");
    ok("and the 1 GEN comes back", (await moved(client.address, b)) - b === 1n * GEN);
  }
}

const rule = parse(await view("agreement_rule"));
ok("agreement_rule() is published by the contract", typeof rule.map === "string" && rule.limits?.units === 8, rule.map);
console.log(`\n${pass} passed, ${fail} failed`);
console.log("register:", A);
