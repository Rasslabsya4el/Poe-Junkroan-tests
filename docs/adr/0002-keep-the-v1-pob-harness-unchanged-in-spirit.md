# 2026-09-11 D2. Keep the v1 PoB harness unchanged in spirit

Status: Accepted

`headless_runtime_worker.py`, `headless_runtime_adapter.py`,
`headless_wrapper.lua`, `release_manager.py`, `host_runtime.py`,
`calc_snapshot.py`, corpus loaders and data. It is a genuine in-process LuaJIT
PoB driver with pinned release, full stat readback, node power, and native
import verification. Only ergonomic wrappers (`session.py`) and roadmap Phase
1 changes are allowed on top.

