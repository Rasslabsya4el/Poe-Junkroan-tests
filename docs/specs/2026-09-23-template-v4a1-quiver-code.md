# Spec 2026-09-23: template v4 piece a1 -- the quiver takes the weapon shape (CODE ONLY, no PoB)

Lead: Opus 5.5. Worker: one coder, about 30 minutes. The lead measures with PoB afterwards; you do NOT.

## Hard limits for this task

- Do NOT run `scripts/machine_load.py`, `scripts/gear_transplant.py`, `scripts/benchmark.py`, `scripts/replay_bench.py`
  or anything that starts Path of Building. Do not run the whole test suite. Only the two test files named below.
- Do NOT explore the repository beyond the files named here. Everything you need is listed.
- Commit after step 3 even if step 4 is not done. No scratch files in the repository.

## Steps (in this order)

1. Read the reference implementation on another branch (it is correct for the quiver; ignore everything about
   "flexible lines" and "boots"):
   `git show sonnet-2026-09-22-template-v4:src/junkroan/optimizer/rails.py` (the `quiver_weapon_shape` field of the
   wishlist rails and its parsing), `git show sonnet-2026-09-22-template-v4:src/junkroan/optimizer/rails_default.json`
   (the `quiver_weapon_shape` key), `git show sonnet-2026-09-22-template-v4:src/junkroan/optimizer/wishlist_gear.py`
   (in `template_for`: the quiver branch; `_buys_value`: an instance method reading `self.rails`), and
   `git show sonnet-2026-09-22-template-v4:tests/test_wishlist_gear_flexible.py` (only the quiver tests).
2. Apply ONLY the quiver parts to this branch: the rails field `quiver_weapon_shape` (default **true** in
   `rails_default.json` and in the dataclass), its parsing, the quiver branch in `template_for`, `_buys_value` reading
   the instance rails (fix any existing call that used it unbound, as the reference did in `tests/test_wishlist_gear.py`).
3. Add the quiver tests to a new file `tests/test_wishlist_gear_quiver.py` (copy and trim from the reference; they use a
   fake PoB, no runtime). Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_wishlist_gear.py tests/test_wishlist_gear_quiver.py`
   Fix until green, then `git add` the changed files and commit.
4. Final message: begin with `=== FINAL REPORT ===`, then the commit hash, `git diff --stat`, the pytest summary line,
   and one sentence per file you changed.

Durations for a human (seconds under ~90 s, then minutes).
