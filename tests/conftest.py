"""A stand-in `genlayer` module, so the suite runs on any machine with no network and no Studio.

It models only what the contracts touch: storage types as plain containers,
`gl.message` / `gl.message_raw` set per call by the tests, `gl.vm.UserError`,
`gl.vm.Return`, and slots the tests fill for `gl.nondet.exec_prompt`,
`gl.vm.run_nondet_unsafe` and `gl.get_contract_at`.
"""

import sys
import types

if "genlayer" not in sys.modules:
    stub = types.ModuleType("genlayer")

    class _Any:
        def __getattr__(self, n): return _Any()
        def __call__(self, *a, **k): return _Any()
        def __getitem__(self, n): return _Any()

    class _UserError(Exception):
        def __init__(self, message=""):
            super().__init__(message)
            self.message = message

    class _Result:
        pass

    class _Return(_Result):
        def __init__(self, calldata=None):
            self.calldata = calldata

    class _VMError(_Result):
        def __init__(self, message=""):
            self.message = message

    class _VM:
        UserError = _UserError
        Result = _Result
        Return = _Return
        VMError = _VMError
        run_nondet_unsafe = None

    class _Public:
        view = staticmethod(lambda f: f)

        class _Write:
            def __call__(self, f): return f
            payable = staticmethod(lambda f: f)
        write = _Write()

    class _GL:
        vm = _VM()
        public = _Public()
        nondet = types.SimpleNamespace(exec_prompt=None)
        get_contract_at = None

        class Contract:
            pass

        def __getattr__(self, n): return _Any()

    class _T:
        def __init__(self, *a, **k): pass
        def __class_getitem__(cls, item): return cls

    stub.gl = _GL()
    stub.allow_storage = lambda c: c
    stub.Address = str
    stub.DynArray = _T
    stub.TreeMap = _T
    stub.u256 = int
    stub.u32 = int
    stub.u64 = int
    stub.i64 = int
    stub.__all__ = ["gl", "allow_storage", "Address", "DynArray", "TreeMap", "u256", "u32", "u64", "i64"]
    sys.modules["genlayer"] = stub
