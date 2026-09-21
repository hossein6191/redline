# Contracts

## Redline (`contracts/redline.py`)

**Purpose.** A change-order escrow for text that may only change as agreed: a DAO charter carrying out a passed
amendment, a config file, a system prompt, a legal redline, an edit handed to an agent. An edit is paid only when
every changed line is accounted for by a numbered request.

**Consensus.** `judge` runs one nondeterministic block that asks the same question in two readings: the requests
lettered A, B, C, D in order with the units listed forward, then the requests lettered P, Q, R, S in reverse order
with the units listed in reverse. The alphabets share no letter, so no letter names a request in both readings. Each
reading returns one token per unit (a letter or NONE) and yes/no per request; the contract maps letters back to
`M1..Mk`, and a letter from the other reading's alphabet is read as NONE. A unit keeps request Mj only if both readings name Mj; anything else is `X`. A request's done bit is
1 only if both readings say yes. The block returns `{"map": "M1,M2,X,X", "done": "1,1"}`; each validator re-runs the
whole block inside `try/except` (its own failure is a disagreement) and compares both strings exactly. No tolerance,
no model prose stored. Errors carry a class: `[EXPECTED]` agrees on the exact message, `[TRANSIENT]` by class,
`[LLM_ERROR]` never.

**State.** `n_jobs`, `n_docs` (`u256`), and `TreeMap[str, str]` of JSON rows: `docs` ("D3": owner, current hash,
active job, history count), `dhist` ("D3:1": hash, job, revision), `jobs` ("J5": doc, client, editor, escrow, base,
base hash, requests, times, state, attempts, pending, counters, outcome, new hash), `revs` ("J5:2": text, digest,
units, outcome, map, done, X lines, the contract's sentence, time, author), `seen` (digest dedupe), `taint` (barred
changes), `refusal_rows` ("J5:r3": code, caller, time, contract-written detail, count), `refusal_index`
("J5:pending:editor": the row that code and party already hold, so a repeat is counted, not added). No collection inside a dataclass;
no dataclass at all.

**Methods.**

| method | who | what |
|---|---|---|
| `open(doc, base_text, mandates, editor, deadline_min)` payable | anyone, becomes the client | funds a job on a new document (`doc = ""`) or on one the caller owns whose current hash equals the base; refuses and refunds in the same call |
| `accept(job)` | the editor | open to accepted, before the deadline |
| `cancel(job)` | the client | only while open; refunds the escrow |
| `submit(job, revised)` | the editor | normalises, diffs, numbers units; door refusals are stored and cost no attempt; at most 3 admitted revisions |
| `judge(job, rev)` | the client or the editor | the pending revision only, until 60 minutes after the deadline; the verdict is final |
| `reclaim(job)` | the client | after the deadline with nothing pending, 60 minutes later whatever is pending, or at once when all 3 revisions were judged and none was EXACT |
| views | anyone | `job`, `status`, `doc`, `current`, `history`, `revision`, `units`, `refusals`, `agreement_rule` |

**Reuse.** Any contract that must only accept a text after an agreed change reads `status(job)` (doc, client,
editor, base hash, new hash, outcome, state) and binds to the document id, the client address and the hash it
already trusts, as the Charter fixture does. The block itself (a code-computed index space, two relettered readings,
one collapse token, an exact string compare) carries over to any "map every item to a numbered authority" question.

**Limits.** 60 lines, 200 characters a line, 3,000 characters per text; printable ASCII and LF; 1 to 4 one-line
requests of up to 200 characters, no two the same; at most 8 units per revision, refused whole above that; 3 admitted
revisions per job; deadline 5 to 43,200 minutes; one stored refusal row per code per party (30-row backstop). A hijack
by wording, an instruction toward NONE in the client's own text, and a delete fused with an insert into one unit are
not defended; README "Limits" states each.

## Charter (`contracts/fixtures/charter.py`)

**Purpose.** The consequence on the other side: a document that only ever advances through accounted-for edits, in
order.

**Consensus.** None. It reads Redline's `status(job)` through a synchronous cross-contract view.

**State.** `register` (Address), `doc_id`, `client` (lowercase hex), `current_hash`, `n_versions`, `versions`
("0": hash, job, previous hash), `last_job` (the number of the last adopted job), `n_ref`, `refusal_rows`,
`refusal_keys` ("J5:stale_base", so a repeat adds no row).

**Methods.** Constructor `(register, doc, client, base_hash)`. `adopt(job)`, open to anyone (the result depends only
on the register's state and the jobs already adopted): advances `current_hash` to the job's new hash only when the job
is on the bound document, by the bound client (twenty bytes), with outcome EXACT, from the hash in force, and later
than the last job adopted; otherwise returns `ok:false` with `wrong_client`, `not_exact`, `stale_base` or `replayed`
(stored once per job and code) or `no_job` / `wrong_doc` (not stored). Views `in_force(digest)` and `charter()`.

**Limits.** It trusts the register it was bound to; it never decides which register is authoritative. 30-row refusal
backstop.
