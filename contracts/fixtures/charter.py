# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""Charter: a document that only ever advances through accounted-for edits, in order.

This is the consequence on the other side of Redline. A charter is bound at
deployment to one Redline register, one document id, the client address its
deployer knew, and the hash of the text in force. `adopt(job)` reads the
register's compact `status(job)` through an ordinary cross-contract view and
moves the charter's hash only when all four hold:

    the job is on the bound document,
    the job's client is the bound client (compared as twenty bytes),
    the outcome is EXACT,
    the job's base hash is the hash in force here.

The last rule is the order: an EXACT edit of an older version is refused as
stale, so two edits can never both claim the same parent. A job is also never
adopted twice, nor after a later one: a document that went A to B and back to A
would otherwise let anyone present the first job again and move the charter to
B while the register says A. Jobs on one document are serialised by the
register and their ids only increase, so the charter keeps the number of the
last job it adopted and refuses any job at or below it (`replayed`).

Every refusal is returned as ok:false; nothing raises. A refusal is stored only
when it is about a job on the bound document (wrong_client, not_exact,
stale_base, replayed), one row per job and code, so nobody can fill the record
with unknown ids or other documents' jobs.

No model runs here and no validator is asked anything. It is a fixture: small
on purpose, and here to be read.
"""

import json
import typing

from genlayer import *


MAX_REFUSALS = 30
HEX = "0123456789abcdef"


def _hex(address: typing.Any) -> str:
    return address.as_hex if hasattr(address, "as_hex") else str(address)


def _addr(raw: typing.Any) -> str:
    s = _hex(raw).strip()
    if len(s) != 42 or s[:2] not in ("0x", "0X"):
        return ""
    body = s[2:].lower()
    if any(ch not in HEX for ch in body):
        return ""
    return "0x" + body


def _same(a: typing.Any, b: typing.Any) -> bool:
    x, y = _addr(a), _addr(b)
    if not x or not y:
        return False
    return bytes.fromhex(x[2:]) == bytes.fromhex(y[2:])


def _valid_hash(raw: typing.Any) -> bool:
    s = str(raw)
    return len(s) == 64 and all(ch in HEX for ch in s)


def _valid_id(raw: typing.Any, prefix: str) -> bool:
    s = str(raw)
    body = s[1:]
    return len(s) >= 2 and s[0] == prefix and 1 <= len(body) <= 6 and all(ch in "0123456789" for ch in body)


class Charter(gl.Contract):
    register: Address
    doc_id: str
    client: str
    current_hash: str
    n_versions: u256
    versions: TreeMap[str, str]       # "0" -> {"hash","job","prev"}
    last_job: u256                    # the number of the last adopted job; ids at or below it are refused
    n_ref: u256
    refusal_rows: TreeMap[str, str]   # "r1" -> {"code","job","detail"}
    refusal_keys: TreeMap[str, str]   # "J5:stale_base" -> "r1", so a repeat does not add a row

    def __init__(self, register: str, doc: str, client: str, base_hash: str) -> None:
        if not _addr(register) or not _addr(client):
            raise gl.vm.UserError("[EXPECTED] the register and the client are addresses")
        if not _valid_id(str(doc).strip(), "D"):
            raise gl.vm.UserError("[EXPECTED] the document id looks like D1")
        if not _valid_hash(str(base_hash).strip().lower()):
            raise gl.vm.UserError("[EXPECTED] the base hash is 64 lowercase hex characters")
        self.register = Address(register)
        self.doc_id = str(doc).strip()
        self.client = _addr(client)
        self.current_hash = str(base_hash).strip().lower()
        self.versions["0"] = json.dumps({"hash": self.current_hash, "job": "", "prev": ""})
        self.n_versions = u256(1)
        self.last_job = u256(0)
        self.n_ref = u256(0)

    def _refuse(self, code: str, job_id: str, detail: str, store: bool) -> str:
        """Returned, never raised. Stored only for a job on the bound document, once per job and code."""
        recorded = False
        if store:
            key = job_id + ":" + code
            if key in self.refusal_keys:
                recorded = True
            else:
                n = int(self.n_ref)
                if n < MAX_REFUSALS:
                    n += 1
                    self.refusal_rows["r" + str(n)] = json.dumps({"code": code, "job": job_id, "detail": detail})
                    self.refusal_keys[key] = "r" + str(n)
                    self.n_ref = u256(n)
                    recorded = True
        return json.dumps({"ok": False, "code": code, "msg": detail, "recorded": recorded})

    @gl.public.write
    def adopt(self, job: str) -> str:
        """Advance the charter to an EXACT edit of the version in force. Deliberately open to anyone:
        the result depends only on the register's state and on the jobs this charter already adopted;
        the caller chooses only which job to present, and a job already passed is refused."""
        job_id = str(job).strip()
        if not _valid_id(job_id, "J"):
            return self._refuse("no_job", "", "job ids look like J1", False)
        st = json.loads(str(gl.get_contract_at(self.register).view().status(job_id)))
        if not isinstance(st, dict) or "error" in st:
            return self._refuse("no_job", job_id, "the register holds no job " + job_id, False)
        if str(st.get("doc", "")) != str(self.doc_id):
            return self._refuse("wrong_doc", job_id, job_id + " edits another document, not " + str(self.doc_id), False)
        if not _same(st.get("client", ""), self.client):
            return self._refuse("wrong_client", job_id, job_id + " was opened by another account, not the bound client", True)
        if str(st.get("outcome", "")) != "EXACT":
            return self._refuse("not_exact", job_id, job_id + " has no EXACT outcome", True)
        if str(st.get("base_hash", "")) != str(self.current_hash):
            return self._refuse("stale_base", job_id, job_id + " edits a version that is not the one in force", True)
        if int(job_id[1:]) <= int(self.last_job):
            return self._refuse("replayed", job_id, job_id + " is not later than J" + str(int(self.last_job))
                                + ", the last job adopted here; a job is adopted once and in order", True)
        new_hash = str(st.get("new_hash", ""))
        if not _valid_hash(new_hash):
            return self._refuse("not_exact", job_id, job_id + " carries no revision hash", True)
        n = int(self.n_versions)
        self.versions[str(n)] = json.dumps({"hash": new_hash, "job": job_id, "prev": str(self.current_hash)})
        self.n_versions = u256(n + 1)
        self.current_hash = new_hash
        self.last_job = u256(int(job_id[1:]))
        return json.dumps({"ok": True, "job": job_id, "current": new_hash, "version": n})

    @gl.public.view
    def in_force(self, digest: str) -> bool:
        return str(digest).strip().lower() == str(self.current_hash)

    @gl.public.view
    def charter(self) -> str:
        n = int(self.n_versions)
        return json.dumps({
            "register": _hex(self.register), "doc": str(self.doc_id), "client": str(self.client),
            "current": str(self.current_hash), "last_job": "J" + str(int(self.last_job)) if int(self.last_job) > 0 else "",
            "versions": [json.loads(self.versions[str(i)]) for i in range(n)],
            "refusals": [json.loads(self.refusal_rows["r" + str(i)]) for i in range(1, int(self.n_ref) + 1)],
        })
