# Poe Junkroan v2

Machine search for Path of Exile builds. Path of Building runs headless as the
numeric oracle; a deterministic optimizer builds tree, gear and config for each
candidate build skeleton; a search loop over skeletons finds strong, including
non-meta, builds. The LLM proposes hypotheses and explains results; it does not
pick nodes.

- `CLAUDE.md`: working rules for agent sessions. Read first.
- `docs/ARCHITECTURE.md`: design.
- `docs/STATE.md`: what the machines run now; work items are GitHub issues.
- `docs/ROADMAP.md`: the plan up to 2026-09-26, frozen history.
- `docs/adr/`: why things are the way they are, one decision per file (D57 = `docs/adr/0057-*.md`).
- `GLOSSARY.md`: the project's vocabulary.
- `docs/LEGACY.md`: what was taken from v1 and what was dropped.

```powershell
python -m pytest -q
python scripts/smoke_pob.py
```

Requires Python 3.12 and Windows (PoB runtime is `lua51.dll` based). The pinned
PoB release (v2.64.0) is downloaded to `var/` on first use if absent.
