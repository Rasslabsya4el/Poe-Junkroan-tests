# Domain Docs: what this repo adds

Local counterpart of `docs/agents/domain.md` (issue #148, D109). The core file holds the rules; the `D<n>` /
amendment / superseded-`Status` convention lives in `docs/agents/core-block.md`'s "Domain docs" part (moved there,
#224); the lines below are this repo's own and stand here verbatim.

## File structure

The example tree in the core file is generic; this repo's first ADR is the concrete case:

```
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-restart-in-a-fresh-repository.md
│   └── ...
└── src/
```

## Decision numbers

Verbatim, this repo's numbers and its own history:

`D57` in code, comments, tests, specs, readings and commit messages is ADR 0057: `docs/adr/0057-*.md`. The ADRs continue the old decision numbers (D1-D103) one to one, so every existing `D<n>` reference stays valid; a new ADR takes the highest number in `docs/adr/` plus one. Amendments ("D62 amd 3") live inside their ADR, and a superseded decision says so in its `Status` line.

## Flag ADR conflicts

The example in this repo's own terms (`CombinedDPS` is the objective metric, D11):

> _Contradicts ADR-0057 (the objective stays CombinedDPS), but worth reopening because…_

## Where the rules came from

- The `D<n>` -> `docs/adr/<nnnn>-*.md` convention and the ADR bar: D103 and CLAUDE.md "Agent skills"; the split of
  this file into core and local: D109, issue #148.
