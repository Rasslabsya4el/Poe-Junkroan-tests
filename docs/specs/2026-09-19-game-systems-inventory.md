# Spec (research, no code change in src/): an inventory of every source of character power PoB 3.29 knows

The user (2026-09-19) plans the far goal -- one build delivered with loadouts for day-1 T10, T16, endgame and mirror
endgame -- and needs, before any rails are written, "a list of what there is in the game at all, so that I can
conveniently divide it between the loadouts and compose a rulebook per loadout". The list must come from DATA
(the pinned PoB v2.67.2 source under `vendor/pob/source/src/`, our corpora under `src/junkroan/pob/corpus_data/`,
the harness under `src/junkroan/pob/`), never from model memory (CLAUDE.md principle 3). Where the data does not say
something, write "not in data (wiki)" -- the lead reads the wiki himself.

## Deliverable: `docs/research/2026-09-19-game-systems-inventory.md`

One table, one row per SYSTEM (a system = a distinct way a character gains power that a loadout could allow or
forbid). Enumerate them by walking the data, e.g. (not exhaustive -- find the rest): passive points by level and
quest, ascendancy points, bandits, pantheon, masteries, keystones; skill gem level / quality, Vaal gems, awakened
and other exceptional supports, transfigured gems; item bases by drop level; explicit mod tiers by item level;
bench crafts (`ModMaster.lua`), veiled mods, essences, fractured / synthesised implicits, influence mods (Shaper,
Elder, the four Conquerors), eldritch implicits (Searing Exarch / Eater of Worlds), corruption implicits, enchants,
anointments, quality / catalysts; regular, abyss, cluster and timeless jewels; flasks and their mods, tinctures;
tattoos, runegrafts or whatever league content the data holds; uniques by PoB "Source:" class and by our drop-rate
tiers (`corpus_data/unique_tiers.json`); item sockets and links; minion-specific gear; anything else you find in
`Data/` that changes a character's numbers.

Columns:
1. system;
2. what it changes (one line, from the data's own wording);
3. three examples copied from the data;
4. data file(s) and the record count;
5. gates visible IN THE DATA (required level, item level of tiers, drop level of bases, "Source:" text, league tag,
   quest / lab step) -- quote the field, do not interpret;
6. PoB support: does PoB compute it (yes / partly / no) -- from the data and `Modules/`, with the file that shows it;
7. our harness: can `PobSession` apply and evaluate it today (yes / partly / no, naming the method), and does the
   pipeline USE it today (grep the optimizer / search code; e.g. `--cluster-candidates`, `screen_uniques`);
8. "loadout" -- leave EMPTY: the user fills it (day-1 / T16 / endgame / mirror / never).

Below the table: (a) the systems PoB knows but our harness cannot touch, as a short list -- that is the harness
backlog the far goal implies; (b) the systems with no gate in the data (wiki needed); (c) how you enumerated, so the
run can be repeated at the next PoB bump (a small read-only script under `scripts/research/` is welcome, with its
output pasted; no change under `src/`).

No PoB session is needed for most of this; if you open one, one at a time (a 5-worker benchmark is running). You
are the worker: do it yourself, do not delegate. Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit the
document (and the script, if any) on your branch; the final message is a 15-line summary with the row count.
