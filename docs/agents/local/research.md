# Game-knowledge research: what this repo adds

Local counterpart of `docs/agents/research.md` (issue #148, D109). The core file holds the external researcher, the
brief format and the verbatim-quote rules; below is this repo's own: the game, the wiki, PoB as the tool the answers
are checked against, and where the approved numbers land. Every block quoted below is the line as it stood in
`docs/agents/research.md` before the split.

## The header

> # Game-knowledge research (D62)
>
> Moved verbatim from CLAUDE.md on 2026-09-26 (#45); it binds every agent as if it were still written there. CLAUDE.md section "Game-knowledge research" (its machine-budget and
> launch bullets are in `docs/agents/machine.md`; the "Who spends what" bullet is superseded by the roles in
> CLAUDE.md, #45, and only its harness facts are kept below).
>
> Orchestration v2 (#45): the external researcher is GPT through the opencode bridge (`tools/agentops/`, websearch on,
> #46), Luna 5.6 for simple briefs and Terra 5.6 for complex ones (the brief's writer picks); the brief format and
> the verbatim-quote rules below stay. Until #46 lands, the Codex CLI route below is the working one.
>
> ## Game-knowledge research (D62; how we use GPT, do not improvise)

## The order of trust, and the wiki

The tool whose readbacks outrank everything is PoB; the wiki is poewiki.net and its anti-bot check passes after ~8 s.

> Order of trust: PoB's own data and readbacks, then the wiki, then Reddit / forums, then the
> user's memory (the user: the wiki outranks them). A number PoB does not compute is never typed
> from model memory: it is a fact with a source, stored with the place it plugs into.
>
> - **The wiki** (poewiki.net) is read by the main model itself in the Browser pane (its anti-bot
>   check passes after ~8 s; bots and GPT's fetchers are refused). Cache under `var/cache/wiki/`:
>   the raw page, and a compact extract (mechanics / interaction sections and gem numbers only),
>   which is the only form an agent reads afterwards.

## Reddit and forums

> through opencode's websearch with `OPENCODE_ENABLE_EXA=1` over the `tools/agentops` bridge (#46; measured
> 2026-09-26). opencode's page fetcher alone does not reach it. Write a
>
> system are the main model's (the user, 2026-09-18: a digested "9 orbs" hid "only without DD").

## GPT code workers

> - **GPT code workers** [#45: an option, not the default route; code goes to `worker` / `worker-strong`, and DeepSeek
> is paused until the owner re-enables it, `docs/agents/orch.md`] (2026-09-18, the Claude weekly limit is shared with Opus subagents): code
> tasks from a spec run through `python -m tools.agentops worker <spec>.md --model gpt-5.6-terra --minutes N
> [--issue N]` (`docs/specs/` is frozen since 2026-09-26, nothing is added there); opencode, model
>
> The bridge (`tools/agentops/worker.py`, ported from the GPT-era harness, now removed, #65) commits a worker's uncommitted tree

## Where a checked answer lands

> - GPT's answers are checked against PoB and the wiki before use, land as **pending** facts
>   (optimistic lane and a "would move the number by X%" note only), and enter the conservative
>   number after the user approves them from one table (fact, number, sources, confidence, which
>   builds it moves). Verdicts and approved numbers: `docs/readings/`, D62 (`docs/adr/0062-*.md`),
>   `src/junkroan/mechanics/`.

## Where the rules came from

- Game-knowledge research as a protocol, the order of trust and the pending / approved lane: D62.
- The text moved out of CLAUDE.md into `docs/agents/`: #45, 2026-09-26. The machine-budget and launch bullets of
  that section are in `docs/agents/machine.md`.
- The opencode bridge and `OPENCODE_ENABLE_EXA=1` for Reddit: #46, measured 2026-09-26.
- "A digested number hides its condition": the owner, 2026-09-18 ("9 orbs" hid "only without DD").
- GPT code workers are no longer the default route, DeepSeek paused: #45, the owner 2026-09-26.
- `tools/agentops/worker.py` ported from the GPT-era harness, now removed: #65.
- `docs/specs/` frozen, nothing added there: 2026-09-26.
