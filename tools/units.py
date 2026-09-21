"""Print the units Redline's `submit` would compute for a revision, before an attempt is spent.

    python tools/units.py base.txt revised.txt

It loads contracts/redline.py itself (with the offline stub runtime from tests/conftest.py) and calls the
contract's own `_text_problem`, `_normalise` and `_diff`, so the units printed are the contract's, not a copy.
It does not know the job's taint set or earlier digests. A view doing the same was tried and dropped: on Studio
61999, a contract view called with an argument longer than about 200 characters failed through `gen_call` from
genlayer-js 1.1.8, so it could not take a real revision.
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import conftest  # noqa: E402,F401  (installs the stub `genlayer` module)

spec = importlib.util.spec_from_file_location("redline_units", ROOT / "contracts" / "redline.py")
rl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rl)


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().split("\n\n")[1])
        return 2
    base, rev = (pathlib.Path(a).read_text(encoding="utf-8") for a in argv[1:])
    for text, what in ((base, "the base text"), (rev, "the revision")):
        problem = rl._text_problem(text, what)
        if problem:
            print("refused at the door: " + problem)
            return 1
    units = rl._diff(rl._normalise(base), rl._normalise(rev))
    for u in units:
        if u["kind"] == "replace":
            print(u["id"] + " replace: old line " + str(u["old_ln"]) + " becomes new line " + str(u["new_ln"]))
        elif u["kind"] == "insert":
            print(u["id"] + " insert: new line " + str(u["new_ln"]))
        else:
            print(u["id"] + " delete: old line " + str(u["old_ln"]))
        if u["kind"] != "insert":
            print("   OLD| " + u["old"])
        if u["kind"] != "delete":
            print("   NEW| " + u["new"])
    if not units:
        print("no units: submit would refuse it (no_units)")
    elif len(units) > rl.MAX_UNITS:
        print(str(len(units)) + " units: submit would refuse it whole (too_many_units, at most " + str(rl.MAX_UNITS) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
