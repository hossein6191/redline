"""Remove each defence of Redline and Charter in turn and record the test that killed it.

    ~/gl-primitives/.venv/bin/python tools/mutate.py     # writes tests/MUTATIONS.md; exit 1 if any mutant survives

The harness refuses to run over a failing baseline, refuses an anchor that is
not found exactly once, and treats a mutant that does not even import as a
broken anchor, never as a kill. Each mutant is its own file, fed to the suite
through REDLINE_SOURCE or CHARTER_SOURCE, with bytecode caching off so a stale
.pyc can never be the thing that was tested.
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = {
    "R": ("REDLINE_SOURCE", ROOT / "contracts" / "redline.py"),
    "C": ("CHARTER_SOURCE", ROOT / "contracts" / "fixtures" / "charter.py"),
}
PYTEST = [sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", str(ROOT / "tests" / "test_pure.py")]

EXACT_BLOCK = '''        if outcome == EXACT:
            row["state"] = S_EXACT
            row["new_hash"] = str(r["digest"])
            self._put(job_id, row)
            doc_id = str(row["doc"])
            d = json.loads(self.docs[doc_id])
            n = int(d["history_n"])
            self.dhist[doc_id + ":" + str(n)] = json.dumps({"hash": str(r["digest"]), "job": job_id, "rev": str(rev_n)})
            d["history_n"] = n + 1
            d["current"] = str(r["digest"])
            d["active_job"] = ""
            self.docs[doc_id] = json.dumps(d)
            _Payee(Address(row["editor"])).emit_transfer(value=u256(int(row["escrow"])))
'''
PAY_FIRST = '''        if outcome == EXACT:
            _Payee(Address(row["editor"])).emit_transfer(value=u256(int(row["escrow"])))
            row["state"] = S_EXACT
            row["new_hash"] = str(r["digest"])
            self._put(job_id, row)
            doc_id = str(row["doc"])
            d = json.loads(self.docs[doc_id])
            n = int(d["history_n"])
            self.dhist[doc_id + ":" + str(n)] = json.dumps({"hash": str(r["digest"]), "job": job_id, "rev": str(rev_n)})
            d["history_n"] = n + 1
            d["current"] = str(r["digest"])
            d["active_job"] = ""
            self.docs[doc_id] = json.dumps(d)
'''
LLM_RULE = '''        if _cls(mine) == "LLM_ERROR" or _cls(mine) != _cls(leader_msg):
            return False
        if _cls(mine) == "EXPECTED":
            return mine == leader_msg
        return _cls(mine) == "TRANSIENT"'''
LLM_AGREES = '''        if _cls(mine) != _cls(leader_msg):
            return False
        if _cls(mine) == "EXPECTED":
            return mine == leader_msg
        return True'''

MUTATIONS = [
    # --- who may call (M1-M6)
    ("R", "M1 anyone may accept", '        if not _same(sender, row["editor"]):\n            return self._refuse(job_id, row, "not_editor", "only the editor of " + job_id + " accepts it", sender)\n', ''),
    ("R", "M2 anyone may submit", '        if not _same(sender, row["editor"]):\n            return self._refuse(job_id, row, "not_editor", "only the editor of " + job_id + " submits revisions", sender)\n', ''),
    ("R", "M3 anyone may cancel", '        if not _same(sender, row["client"]):\n            return self._refuse(job_id, row, "not_client", "only the client of " + job_id + " cancels it", sender)\n', ''),
    ("R", "M4 anyone may reclaim", '        if not _same(sender, row["client"]):\n            return self._refuse(job_id, row, "not_client", "only the client of " + job_id + " reclaims it", sender)\n', ''),
    ("R", "M5 anyone may ask for a judgment", '        if not (_same(sender, row["client"]) or _same(sender, row["editor"])):\n            return self._refuse(job_id, row, "not_party"', '        if False:\n            return self._refuse(job_id, row, "not_party"'),
    ("R", "M6 the client may be the editor", '        elif _same(editor_hex, sender):', '        elif False:'),
    # --- lifecycle (M7-M12)
    ("R", "M7 cancel allowed after accept", '        if row["state"] != S_OPEN:\n            return self._refuse(job_id, row, "wrong_state", job_id + " is " + str(row["state"]) + "; only an open job is cancelled", sender)\n', ''),
    ("R", "M8 no deadline on submit", '        if now >= int(row["deadline_s"]):\n            return self._refuse(job_id, row, "late", "the deadline of " + job_id + " has passed", sender)\n        if row["pending"] != "":', '        if row["pending"] != "":'),
    ("R", "M8b no deadline on accept", '        if now >= int(row["deadline_s"]):\n            return self._refuse(job_id, row, "late", "the deadline of " + job_id + " has passed", sender)\n        row["state"] = S_ACCEPTED', '        row["state"] = S_ACCEPTED'),
    ("R", "M9 reclaim ignores a pending revision", '        if row["pending"] != "" and now <= deadline + GRACE_MIN * 60:', '        if False:'),
    ("R", "M10 the grace override is removed from reclaim", '        if row["pending"] != "" and now <= deadline + GRACE_MIN * 60:', '        if row["pending"] != "":'),
    ("R", "M11 judge accepts a revision that is not pending", '        if str(rev_n) != row["pending"]:', '        if False:'),
    ("R", "M12 a second judgment is allowed", '            if earlier["outcome"] != "":', '            if False:'),
    ("R", "judge has no grace limit", '        if now >= int(row["deadline_s"]) + GRACE_MIN * 60:', '        if False:'),
    ("R", "reclaim before the deadline", '        if now <= deadline and not exhausted:\n            return self._refuse(job_id, row, "too_early"', '        if False:\n            return self._refuse(job_id, row, "too_early"'),
    ("R", "the deadline range is not checked", 'elif not isinstance(deadline_min, int) or deadline_min < MIN_DEADLINE_MIN or deadline_min > MAX_DEADLINE_MIN:', 'elif not isinstance(deadline_min, int):'),
    ("R", "an unreadable clock is accepted at open", '        elif now < 0:\n            code = "clock"', '        elif False:\n            code = "clock"'),
    ("R", "an empty escrow is accepted", '        if value == u256(0):\n            problem = ', '        if False:\n            problem = '),
    # --- the door (M13-M19)
    ("R", "M13 MAX_UNITS raised", 'MAX_UNITS = 8 ', 'MAX_UNITS = 80 '),
    ("R", "M14 units truncated to 8 instead of refused", '        if len(units) > MAX_UNITS:\n            return self._refuse(', '        if len(units) > MAX_UNITS:\n            units = units[:MAX_UNITS]\n        if False:\n            return self._refuse('),
    ("R", "M15 no digest dedupe", '        if (job_id + ":" + digest) in self.seen:', '        if False:'),
    ("R", "M16 no taint check", '                if (job_id + ":" + key) in self.taint:', '                if False:'),
    ("R", "M17 taint not recorded on X", '                            self.taint[job_id + ":" + key] = str(rev_n)', '                            pass'),
    ("R", "M17b an X line may return as another kind of change", '    if str(u["new"]).strip():\n        keys.append(_sha("line|" + str(u["new"])))\n', '    if str(u["new"]).strip():\n        pass\n'),
    ("R", "M18 no attempts cap", '        if int(row["attempts"]) >= MAX_ATTEMPTS:', '        if False:'),
    ("R", "M19 a door refusal consumes an attempt", '                    row["n_ref"] = n\n', '                    row["n_ref"] = n\n                    row["attempts"] = int(row["attempts"]) + 1\n'),
    ("R", "a revision that changes nothing is admitted", '        if not units:\n            return self._refuse(', '        if False:\n            return self._refuse('),
    ("R", "a stranger's refusal fills the rows", '        if row is not None and (_same(sender, row["client"]) or _same(sender, row["editor"])):', '        if row is not None:'),
    ("R", "refusal rows are not capped", '                if n < MAX_REFUSALS:', '                if True:'),
    ("R", "the refusal cap raised to 3000", 'MAX_REFUSALS = 30 ', 'MAX_REFUSALS = 3000 '),
    ("R", "a repeated refusal adds a row instead of counting (either party can fill the record)", '            if ikey in self.refusal_index:', '            if False:'),
    # --- state gates (review round 3)
    ("R", "accept works on a job that is not open (a second EXACT could pay twice)", '        if row["state"] != S_OPEN:\n            return self._refuse(job_id, row, "wrong_state", job_id + " is " + str(row["state"]) + ", not open", sender)\n', ''),
    ("R", "submit works on a job that is not accepted", '        if row["state"] != S_ACCEPTED:\n            return self._refuse(job_id, row, "wrong_state", job_id + " is " + str(row["state"]) + "; revisions go to an accepted job", sender)\n', ''),
    ("R", "submit ignores a pending revision", '        if row["pending"] != "":\n            return self._refuse(job_id, row, "pending"', '        if False:\n            return self._refuse(job_id, row, "pending"'),
    ("R", "judge works on a job that is not accepted", '        if row["state"] != S_ACCEPTED:\n            return self._refuse(job_id, row, "wrong_state", job_id + " is " + str(row["state"]) + "; nothing is judged", sender)\n', ''),
    ("R", "judge runs with an unreadable clock", '        if now < 0:\n            return self._refuse(job_id, row, "clock", "the network clock could not be read; try again", sender)\n        if now >= int(row["deadline_s"]) + GRACE_MIN * 60:', '        if now >= int(row["deadline_s"]) + GRACE_MIN * 60:'),
    ("R", "the zero address may be the editor", 'elif not editor_hex or editor_hex == ZERO:', 'elif not editor_hex:'),
    ("R", "the raw length is not checked before normalisation", '    if len(t) > MAX_RAW_CHARS:', '    if False:'),
    ("R", "repeated requests are admitted", '        if key in earlier:', '        if False:'),
    ("R", "reclaim stays shut after every revision failed", 'if now <= deadline and not exhausted:', 'if now <= deadline:'),
    ("R", "a removal found X may return as a blank line", '    elif u["kind"] != "insert" and str(u["old"]).strip():\n        keys.append(_sha("gone|" + str(u["old"])))\n', ''),
    # --- combine and remap (M20-M26)
    ("R", "M20 NONE/NONE kept as a mandate", 'tokens.append(a if (a == b and a != NONE) else X)', 'tokens.append(a if a == b else X)'),
    ("R", "M21 a one-order match is accepted", 'tokens.append(a if (a == b and a != NONE) else X)', 'tokens.append(a if (a == b or a != NONE) else X)'),
    ("R", "M22 done bits use OR", '(r1["done"][mid] == "yes" and r2["done"][mid] == "yes")', '(r1["done"][mid] == "yes" or r2["done"][mid] == "yes")'),
    ("R", "M23 EXACT does not require every request served", '        if bits[j - 1] != "1" or ("M" + str(j)) not in tokens:', '        if bits[j - 1] != "1":'),
    ("R", "M24 INCOMPLETE treated as EXACT", '        if outcome == EXACT:\n            row["state"] = S_EXACT', '        if outcome in (EXACT, INCOMPLETE):\n            row["state"] = S_EXACT'),
    ("R", "M25 the second reading is mapped back with the first lettering", '(_prompt(mandates, units, lines, True), _letter_map(k, True))', '(_prompt(mandates, units, lines, True), _letter_map(k, False))'),
    ("R", "M26 the second lettering is not reversed", '    if reverse:\n        ids.reverse()\n', ''),
    ("R", "the two readings share one alphabet (a letter hijack survives with 1 or 3 requests)", 'LETTERS_2 = "PQRS"', 'LETTERS_2 = "ABCD"'),
    ("R", "a letter from the other reading is a model error instead of NONE", '        elif len(v) == 1 and v in LETTERS_1 + LETTERS_2:\n            units[uid] = NONE', '        elif False:\n            units[uid] = NONE'),
    ("R", "M26b the second reading lists the units in the same order", '    shown = list(reversed(units)) if reverse else list(units)', '    shown = list(units)'),
    ("R", "the leader asks the first reading twice", '            for p, letters in readings:', '            for p, letters in [readings[0], readings[0]]:'),
    ("R", "the reply need not name exactly the units", 'len(got_units) != len(raw["units"]) or sorted(got_units.keys()) != sorted(unit_ids)', 'False'),
    ("R", "the agreed value is stored unchecked", '    if len(tokens) != n or any(t not in allowed for t in tokens):', '    if False:'),
    # --- validator (M27-M29)
    ("R", "M27 the validator compares only the map", 'return mine["map"] == theirs.get("map") and mine["done"] == theirs.get("done")', 'return mine["map"] == theirs.get("map")'),
    ("R", "M28 the validator's own run is not wrapped", '            try:\n                mine = leader_fn()\n            except Exception:\n                return False\n', '            mine = leader_fn()\n'),
    ("R", "M29 an LLM error agrees", LLM_RULE, LLM_AGREES),
    ("R", "the validator accepts a leader value of any shape", '            if not isinstance(theirs, dict):\n                return False\n', ''),
    # --- money and the version pointer (M30-M34)
    ("R", "M30 the transfer happens before the latch", EXACT_BLOCK, PAY_FIRST),
    ("R", "M31 current advances on OVERREACH", '        else:\n            self._put(job_id, row)\n        return json.dumps({"ok": True, "job": job_id, "rev": rev_n,', '        else:\n            self._put(job_id, row)\n            dd = json.loads(self.docs[str(row["doc"])])\n            dd["current"] = str(r["digest"])\n            self.docs[str(row["doc"])] = json.dumps(dd)\n        return json.dumps({"ok": True, "job": job_id, "rev": rev_n,'),
    ("R", "EXACT pays half the escrow", '            _Payee(Address(row["editor"])).emit_transfer(value=u256(int(row["escrow"])))', '            _Payee(Address(row["editor"])).emit_transfer(value=u256(int(row["escrow"]) // 2))'),
    ("R", "EXACT does not advance current", '            d["current"] = str(r["digest"])\n', ''),
    ("R", "M32 no document-chaining hash check", '                elif d["current"] != base_hash:', '                elif False:'),
    ("R", "M33 no single active job per document", '                elif d["active_job"] != "":', '                elif False:'),
    ("R", "another account may open a job on the document", '                if not _same(d["owner"], sender):', '                if False:'),
    ("R", "M34 a payable refusal keeps the money", '            if value > u256(0):\n                _Payee(sender).emit_transfer(value=value)\n', ''),
    ("R", "cancel does not refund", '        _Payee(Address(row["client"])).emit_transfer(value=u256(int(row["escrow"])))\n        return json.dumps({"ok": True, "job": job_id, "state": S_CANCELLED', '        return json.dumps({"ok": True, "job": job_id, "state": S_CANCELLED'),
    ("R", "reclaim is allowed after EXACT", '        if row["state"] not in (S_OPEN, S_ACCEPTED):', '        if False:'),
    # --- the prompt boundary (M35-M36)
    ("R", "M35 fence does nothing", 'return str(raw).replace("<", "(").replace(">", ")")', 'return str(raw)'),
    ("R", "M35 fence deletes instead of replacing", 'return str(raw).replace("<", "(").replace(">", ")")', 'return str(raw).replace("<", "").replace(">", "")'),
    ("R", "M35 a request goes in unfenced", '_fence(mandates[int(mid[1:]) - 1])', 'mandates[int(mid[1:]) - 1]'),
    ("R", "M35 an old line goes in unfenced", '_fence(u["old"])', 'u["old"]'),
    ("R", "M35 a new line goes in unfenced", '_fence(u["new"])', 'u["new"]'),
    ("R", "M35 a document line goes in unfenced", '_fence(lines[i])', 'lines[i]'),
    ("R", "unit labels are not re-checked where the prompt is built", '        if kind not in KINDS or not _valid_id(uid, "U") or int(uid[1:]) > MAX_UNITS:', '        if False:'),
    ("R", "M36 angle brackets admitted in a text", '    if "<" in t or ">" in t:', '    if False:'),
    ("R", "M36 angle brackets admitted in a request", '        if "<" in m or ">" in m:', '        if False:'),
    ("R", "non-ASCII admitted", '        if ch != "\\n" and not (" " <= ch <= "~"):', '        if False:'),
    ("R", "the line length is not checked", '        if len(lines[i]) > MAX_LINE_CHARS:', '        if False:'),
    ("R", "the line count is not checked", '    if len(lines) > MAX_LINES:', '    if False:'),
    # --- normalisation and the diff (M37-M38)
    ("R", "M37 CRLF is not normalised", '    t = str(raw).replace("\\r\\n", "\\n")\n    lines = ', '    t = str(raw)\n    lines = '),
    ("R", "M37 trailing spaces are kept", '    lines = [ln.rstrip(" ") for ln in t.split("\\n")]', '    lines = t.split("\\n")'),
    ("R", "M37 trailing empty lines are kept", '    while lines and lines[-1] == "":\n        lines.pop()\n', ''),
    ("R", "M38 positional pairing removed (a changed line becomes a delete and an insert)", '    q = min(len(dels), len(ins))', '    q = 0'),
    ("R", "M38 gaps are not closed at anchors (a hunk spans unchanged lines)", '            raw.extend(_gap_units(dels, ins))\n            dels, ins = [], []\n', ''),
    # --- addresses (M42)
    ("R", "M42 address comparison made case-sensitive", '    return bytes.fromhex(x[2:]) == bytes.fromhex(y[2:])', '    return _hex(a) == _hex(b)'),
    # --- Charter (M39-M41)
    ("C", "M39 Charter: no client check", '        if not _same(st.get("client", ""), self.client):', '        if False:'),
    ("C", "M40 Charter: no base check", '        if str(st.get("base_hash", "")) != str(self.current_hash):', '        if False:'),
    ("C", "M41 Charter: no EXACT check", '        if str(st.get("outcome", "")) != "EXACT":', '        if False:'),
    ("C", "Charter: no document check", '        if str(st.get("doc", "")) != str(self.doc_id):', '        if False:'),
    ("C", "Charter: refusal rows not capped", '                if n < MAX_REFUSALS:', '                if True:'),
    ("C", "Charter: a repeated refusal adds a row", '            if key in self.refusal_keys:', '            if False:'),
    ("C", "Charter: a stranger's unknown id is stored", 'return self._refuse("no_job", job_id, "the register holds no job " + job_id, False)', 'return self._refuse("no_job", job_id, "the register holds no job " + job_id, True)'),
    ("C", "Charter: another document's job is stored", 'job_id + " edits another document, not " + str(self.doc_id), False)', 'job_id + " edits another document, not " + str(self.doc_id), True)'),
    ("C", "Charter: an adopted job may be presented again (replay after a revert)", '        if int(job_id[1:]) <= int(self.last_job):', '        if False:'),
    ("C", "Charter: the last adopted job is not recorded", '        self.last_job = u256(int(job_id[1:]))\n', ''),
    ("C", "Charter: an EXACT row without a valid revision hash is adopted", '        if not _valid_hash(new_hash):\n            return self._refuse("not_exact"', '        if False:\n            return self._refuse("not_exact"'),
    ("C", "M42 Charter: address comparison made case-sensitive", '    return bytes.fromhex(x[2:]) == bytes.fromhex(y[2:])', '    return _hex(a) == _hex(b)'),
]


def _env(**extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.update(extra)
    return env


def run(var: str, mutant: pathlib.Path) -> str:
    out = subprocess.run(PYTEST, env=_env(**{var: str(mutant)}), capture_output=True, text=True, cwd=ROOT)
    if out.returncode == 0:
        return ""
    text = out.stdout + out.stderr
    if "error during collection" in text or "IndentationError" in text or "SyntaxError" in text:
        raise RuntimeError("the mutant does not even import; that is a broken anchor, not a killed defence:\n" + text[-600:])
    m = re.search(r"FAILED tests/test_pure\.py::(\S+)", text)
    if not m:
        raise RuntimeError("a test failed but its name could not be read:\n" + text[-800:])
    return m.group(1)


def main() -> int:
    baseline = subprocess.run(PYTEST, env=_env(), capture_output=True, text=True, cwd=ROOT)
    if baseline.returncode != 0:
        print("the unmutated suite does not pass; a mutation table over a failing suite proves nothing")
        print((baseline.stdout + baseline.stderr)[-600:])
        return 3
    sources = {tag: path.read_text(encoding="utf-8") for tag, (_, path) in FILES.items()}
    rows, escaped = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for tag, name, old, new in MUTATIONS:
            src = sources[tag]
            if src.count(old) != 1:
                print(f"  ! anchor not found exactly once ({src.count(old)}): {name}")
                return 2
            var, path = FILES[tag]
            mutant = pathlib.Path(tmp) / f"mutant_{len(rows) + len(escaped)}_{path.name}"
            mutant.write_text(src.replace(old, new), encoding="utf-8")
            killer = run(var, mutant)
            (rows if killer else escaped).append((path.name, name, killer))
            print(f"  {'killed ' if killer else 'ESCAPED'}  {name}" + (f"  <- {killer}" if killer else ""))
    if escaped:
        print(f"\n{len(escaped)} mutant(s) escaped; no table written.")
        return 1
    table = ["# Mutations", "",
             f"{len(rows)} defences in `contracts/redline.py` and `contracts/fixtures/charter.py`, each removed or inverted "
             "in turn, and the test that failed because of it. Generated by `tools/mutate.py`; it refuses to write this "
             "file if any mutant survives, if an anchor is not found exactly once, or if the unmutated suite is not green. "
             "M-numbers refer to the mutation list in the design (docs/DESIGN.md); unnumbered rows are defences added beyond it.", "",
             "| file | defence removed | killed by |", "|---|---|---|"] + [f"| {f} | {n} | `{k}` |" for f, n, k in rows] + [""]
    (ROOT / "tests" / "MUTATIONS.md").write_text("\n".join(table), encoding="utf-8")
    print(f"\n{len(rows)} / {len(rows)} killed; tests/MUTATIONS.md written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
