"""Search: a request in, ranked optimized builds out.

    python scripts/search.py Fireball                       # every ascendancy, blanks filled by PoB
    python scripts/search.py Fireball --hypotheses h.json   # LLM/human hypotheses (docs/HYPOTHESES.md)
    python scripts/search.py Fireball --ascendancies Elementalist,Inquisitor --top 2 --workers 3

Stages (each PoB-judged, processes in parallel):
  1. supports: greedy link on a rig for the first candidate, shared by the screen
  2. prepare: per ascendancy, bases and ascendancy nodes by PoB
  3. screen: cheap pipeline (loot N=60, greedy tree) -> rank
  4. full: top-K skeletons (+ a unique variant each when the unique screen finds >= 10%),
     each built `--seeds` times (default 3, D71) as separate jobs in the same pool; the
     best build by Score is delivered, the other seeds are kept next to it for the spread
  5. report: artifacts/search-<skill>/report.md, import codes, PoB folder
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.objective_select import objective_for  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.search.generator import SkeletonGenerator  # noqa: E402
from junkroan.search.evaluations import append_row, format_rho, parse_full_ranks, row_for, selected_screen_ranks, skeleton_label, spearman  # noqa: E402
from junkroan.search.hypothesis import ascendancies, load_hypotheses, normalize_ascendancy_ids, validate  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402
from junkroan.search.request import DEFAULT_SEEDS, full_done_line, mutation_done_line, prepared_line, rig_supports_line, screen_done_line, total_line  # noqa: E402
from junkroan.search.trace_out import write_trace_out  # noqa: E402
from junkroan.search.runner import apply_unique_picks, best_by_seed, format_seeds, optimize, pick_unique_variant, prepare_candidate, seed_jobs, seed_spread, unique_pick_ok, variant_screen_line, weapon_alternative_ok  # noqa: E402
from junkroan.search.skeleton import Skeleton  # noqa: E402
from junkroan.runs.yield_plan import limited_completions  # noqa: E402


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def rig_supports(rig: Skeleton, rails: Rails, *, log=print) -> list[str]:
    """Supports for the screen, chosen once by PoB on a rig: bases, ascendancy, cheap gear
    and half a tree first (a bare rig deals ~200 DPS, so flat-damage supports such as Decay
    win every time and multipliers never show their value)."""

    from junkroan.optimizer.loot_gear import LootGear
    from junkroan.optimizer.tree_optimizer import TreeOptimizer

    with PobSession(run_id=f"search-rig-{os.getpid()}") as pob:
        gen = SkeletonGenerator(pob, rails, objective=objective_for(rails, rig.main_link[0], mode=rig.mode).without_sustain(), log=log)
        rig.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        gen.refresh_castability()
        gen.screen_bases(rig)
        gen.pick_ascendancy_nodes(rig)
        LootGear(pob, gen.objective, rails, log=log).fill(rig.rare_bases, passes=1, n=40, seed=3)
        TreeOptimizer(pob, gen.objective.without("EffectiveMovementSpeedMod"), max_trials=300, log=log).allocate(rails.passive_points // 2)
        gen.pick_supports(rig, n_supports=5)
    return list(rig.main_link[1:])


def _commit() -> str | None:
    try:
        value = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def _stage_value(result: dict, *, loop_pass: bool) -> float | None:
    stages = result.get("stages") or []
    if loop_pass:
        stage = next((stage for stage in stages if stage.get("name") == "loop pass 1"), None)
    else:
        loop_start = next((index for index, stage in enumerate(stages) if stage.get("name") == "loop pass 1"), None)
        construction = stages[:loop_start] if loop_start is not None else [stage for stage in stages if stage.get("name") not in {"config (final lanes)", "fixed point check"}]
        stage = construction[-1] if construction else None
    value = (stage or {}).get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _full_rank_key(result: dict) -> tuple[bool, float, float]:
    return (not bool(result.get("feasible")), float(result.get("violation") or 0.0), -float(result.get("value") or 0.0))


def echo_line(echo: str, run_dir: Path) -> str:
    """The request echo (#524's plan line) plus the dated folder this run writes into (#526)."""
    return f"{echo}\nresults: {run_dir}"


def write_build_files(run_dir: Path, stem: str, r: dict, spares: list[dict]) -> None:
    """One ranked build into the run's own dated folder: the import code, the json, the seeds it beat."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{stem}.pob.txt").write_text(r["import_code"], encoding="utf-8")
    (run_dir / f"{stem}.json").write_text(json.dumps({k: v for k, v in r.items() if k not in ("xml", "import_code")}, indent=1, ensure_ascii=False), encoding="utf-8")
    for sp in sorted(spares, key=lambda s: int(s.get("seed") or 0)):  # the seeds this build beat, for the spread
        (run_dir / f"{stem}-s{int(sp.get('seed') or 0)}.pob.txt").write_text(sp["import_code"], encoding="utf-8")


def publish_report(out_dir: Path, run_dir: Path, report: list[str]) -> None:
    """The run's report.md in its folder; the skill root's report.md is the latest run's, first line names the folder."""
    body = "\n".join(report) + "\n"
    (run_dir / "report.md").write_text(body, encoding="utf-8")
    (out_dir / "report.md").write_text(f"Latest run: {run_dir}\n" + body, encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # requests carry the user's own words; a cp1252 console must not kill the run
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("skill")
    ap.add_argument("--hypotheses", help="JSON file of hypotheses (docs/HYPOTHESES.md)")
    ap.add_argument("--request", help="build request JSON (docs/REQUEST.md); expands to hypotheses")
    ap.add_argument("--dry-run", action="store_true", help="with --request: print the echo and stop")
    ap.add_argument("--ascendancies", help="comma-separated ascendancy ids to try (default: all)")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--full-ranks", type=parse_full_ranks, help="comma-separated one-based screen ranks to optimize in full; variants are disabled")
    ap.add_argument("--seeds", type=int, default=None, help=f"full builds per finalist skeleton; the best by Score is delivered (default {DEFAULT_SEEDS}, D71)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--loop-seconds", type=float, help="maximum seconds for each full improvement loop")
    ap.add_argument("--gear", choices=("loot", "wishlist"), default="loot", help="day-1 gear model")
    ap.add_argument("--unique-min-gain", type=float, default=0.10)
    ap.add_argument("--no-unique-variants", action="store_true")
    ap.add_argument("--reopt-rounds", type=int, default=2, help="no-op since D58: the loop is the pipeline")
    ap.add_argument("--no-mutation", action="store_true", help="skip the second round (unique variants of the finished builds)")
    ap.add_argument("--trace-out", help="write the summed trace counters (move x class x generated/evaluated, plus a total) as JSON to this path")
    args = ap.parse_args()
    if args.full_ranks:
        # This mode measures the original screen candidates. A unique or mutation variant
        # would be an additional, differently-screened skeleton rather than the selected rank.
        args.no_unique_variants = True
        args.no_mutation = True

    t_all = time.perf_counter()
    considered_parts: list = []  # each worker result's TRACE.considered() (--trace-out)
    rails = Rails.load()
    if args.request:  # the skill comes from the request; the positional is a placeholder
        from junkroan.search.request import load_request

        request = load_request(Path(args.request))
        args.skill = request.skill or args.skill
        if args.gear == "loot" and request.gear != "loot":
            args.gear = request.gear
    out_dir = ROOT / "artifacts" / f"search-{slugify(args.skill)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = time.localtime()
    run_stamp = time.strftime("%Y-%m-%d %H%M", now)  # the PoB folder of this run is named by its start
    run_dir = out_dir / time.strftime("%Y%m%d-%H%M", now)  # #526: this run's ranked set, never deleted by a later run
    logs = out_dir / "logs"
    logs.mkdir(exist_ok=True)
    evaluations_path = out_dir / "evaluations.jsonl"
    commit = _commit()
    report: list[str] = [f"# Search: {args.skill}", ""]

    def say(msg: str) -> None:
        print(msg, flush=True)
        report.append(msg)

    # -- 1. candidates ------------------------------------------------------------
    skeletons: list[Skeleton] = []
    if args.request:
        from junkroan.search.request import expand, load_request

        req = load_request(Path(args.request))
        composition = None
        wants_probe = req.skill and (not [m for m in req.modes if m != "auto"] or any(m in ("ignite", "poison", "bleed") for m in req.modes))
        if wants_probe:
            from junkroan.search.modes import probe_composition

            with PobSession(run_id="composition") as pob:
                composition = probe_composition(pob, req.skill, rails)
        exp = expand(req, rails, composition=composition, unique_variants=not args.no_unique_variants, mutation=not args.no_mutation)
        print(echo_line(exp.echo, run_dir), flush=True)
        if args.dry_run or not exp.ok:
            return 0 if exp.ok else 1
        args.hypotheses = args.request  # downstream flags treat it like a hypotheses file
        args.top, args.workers = req.top, req.workers
        if args.seeds is None:  # the flag wins over the request file, which the echo was computed from
            args.seeds = req.seeds
        for v in exp.validations:
            v.skeleton.source_label = f"{args.skill}: {exp.echo}"
            skeletons.append(v.skeleton)
        report.append(exp.echo)
    elif args.hypotheses:
        for h in load_hypotheses(Path(args.hypotheses)):
            v = validate(h)
            if not v.ok:
                say(f"- rejected hypothesis {h.name!r}: {'; '.join(v.problems)}")
                continue
            v.skeleton.notes = h.why or h.name
            v.skeleton.source_label = f"{args.skill}: {h.name}"
            skeletons.append(v.skeleton)
    else:
        wanted = normalize_ascendancy_ids(args.ascendancies.split(",")) if args.ascendancies else None
        for asc in ascendancies().values():
            if wanted and asc["ascendancy_id"] not in wanted:
                continue
            skeletons.append(Skeleton(class_name=asc["class_name"], ascendancy=asc["ascendancy_id"], level=rails.level, main_link=[args.skill], notes=f"{asc['class_name']} {asc['ascendancy_id']}", source_label=args.skill))
    if not skeletons:
        say("no candidates")
        return 1
    args.seeds = max(1, args.seeds or DEFAULT_SEEDS)
    say(f"{len(skeletons)} candidate skeletons; {args.seeds} seed(s) per finalist")

    # -- 2. shared supports on a rig (first candidate) -----------------------------------
    shared_supports: list[str] | None = None
    need_supports = [sk for sk in skeletons if len(sk.main_link) < 6]
    if need_supports:
        t0 = time.perf_counter()
        rig = Skeleton.from_json(need_supports[0].to_json())
        shared_supports = rig_supports(rig, rails, log=lambda m: print("  rig:", m, flush=True))
        say(rig_supports_line(rig.class_name, rig.ascendancy, time.perf_counter() - t0, shared_supports))

    # -- 3. prepare in parallel ---------------------------------------------------------
    t0 = time.perf_counter()
    prepared: list[Skeleton] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:  # #958: one skeleton per worker, gives way to the yield
        for fut, sk in limited_completions(lambda sk: pool.submit(prepare_candidate, sk.to_json(), log_path=str(logs / f"prepare-{sk.ascendancy}.log"), shared_supports=shared_supports, gear_mode=args.gear), skeletons, args.workers):
            res = fut.result()
            considered_parts.append(res.get("considered"))
            if not res["ok"]:
                say(f"- prepare failed {sk.class_name}/{sk.ascendancy}: {res['error']}")
                continue
            prepared_sk = Skeleton.from_json(res["skeleton"])
            rig = dict(res.get("rig") or {})
            if rig:
                rig["seconds"] = res["seconds"]
                append_row(evaluations_path, row_for(request=prepared_sk.source_label or args.skill, skeleton=prepared_sk, rung="rig", result=rig, seed=None, commit=commit))
            prepared.append(prepared_sk)
            print(f"  prepared {sk.class_name}/{sk.ascendancy} in {human_duration(res['seconds'])}: {[(p['what'], p['choice']) for p in res['picks']]}", flush=True)
    say(prepared_line(len(prepared), time.perf_counter() - t0))

    # -- 4. screen --------------------------------------------------------------------
    t0 = time.perf_counter()
    screened: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:  # #958: one skeleton per worker, gives way to the yield
        for fut, sk in limited_completions(lambda sk: pool.submit(optimize, sk.to_json(), log_path=str(logs / f"screen-{sk.ascendancy}.log"), screen=True, gear_mode=args.gear, unique_screen=not args.no_unique_variants and sk.unique_slots != "none"), prepared, args.workers):
            res = fut.result()
            considered_parts.append(res.get("considered"))
            if not res["ok"]:
                say(f"- screen failed {sk.class_name}/{sk.ascendancy}: {res['error']}")
                continue
            screened_sk = Skeleton.from_json(res["skeleton"])
            append_row(evaluations_path, row_for(request=screened_sk.source_label or args.skill, skeleton=screened_sk, rung="screen", result=res, seed=None, commit=commit))
            screened.append(res)
            print(f"  screened {sk.class_name}/{sk.ascendancy}: {res['value']:,.0f} (viol {res['violation']:.3f}) in {human_duration(res['seconds'])}; uniques {[(u['slot'], u['name'], f'{u['gain']:+.0%}') for u in res['uniques'][:3]]}", flush=True)
    # Value first, violation only breaks ties: the full optimize repairs a screen's missed floor (every screen-infeasible
    # skeleton that reached full depth ended feasible, violations 0.008-0.276), and feasibility-first sank Raise Zombie's
    # full-depth winner (Guardian, 0.008 short) from screen rank 2 to 15 (docs/readings/2026-09-22-winner-recall.md).
    screened.sort(key=lambda r: (r["value"], -r["violation"]), reverse=True)
    say(screen_done_line(time.perf_counter() - t0))
    say("")
    say("| # | skeleton | screen DPS | viol | best unique |")
    say("|---|---|---|---|---|")
    for i, r in enumerate(screened, 1):
        sk = Skeleton.from_json(r["skeleton"])
        u = r["uniques"][0] if r["uniques"] else None
        say(f"| {i} | {sk.class_name}/{sk.ascendancy} | {r['value']:,.0f} | {r['violation']:.3f} | {f'{u['name']} ({u['slot']}, {u['gain']:+.0%})' if u else '-'} |")
    say("")

    # -- 5. finalists (+ unique variants) ------------------------------------------------
    selected_ranks = selected_screen_ranks(args.full_ranks or [], len(screened))
    finalist_rows = [(rank, screened[rank - 1]) for rank in selected_ranks] if args.full_ranks else [(rank, row) for rank, row in enumerate(screened[:args.top], 1)]
    finalists: list[Skeleton] = []
    finalist_screen_ranks: list[int | None] = []
    for rank, r in finalist_rows:
        sk = Skeleton.from_json(r["skeleton"])
        finalists.append(sk)
        finalist_screen_ranks.append(rank if args.full_ranks else None)
        if not args.no_unique_variants:
            var, considered = pick_unique_variant(sk, r["uniques"], args.unique_min_gain, rails.gear.max_uniques)
            considered_parts.append(considered)
            if var is not None:
                finalists.append(var)
                finalist_screen_ranks.append(None)
    from junkroan.search.request import full_optimize_line

    say(full_optimize_line(len(finalists), args.seeds or DEFAULT_SEEDS, workers=args.workers, mutation_finalists=0 if args.no_mutation else len(finalist_rows)))
    spare_seeds: list[dict] = []  # the seeds a finalist did not win with; written next to the winner

    def run_full(batch: list[tuple[Skeleton, str, int]], *, seeds: int = 1) -> list[dict]:
        """Build every (skeleton, tag, first seed) of the batch `seeds` times, all jobs in one
        pool, and return the best build per skeleton (D71: the seed is worth ~17 points)."""

        out: list[dict] = []
        jobs = seed_jobs(batch, seeds)

        def full_kwargs(sk: Skeleton, tag: str, seed: int) -> dict:
            kwargs = {"log_path": str(logs / f"full-{tag}-s{seed}.log"), "screen": False, "seed": seed,
                      "gear_mode": args.gear, "repick_supports": len(sk.fixed_supports) < 5,
                      "unique_screen": not args.no_mutation and sk.unique_slots != "none"}
            if args.loop_seconds is not None:
                kwargs["loop_seconds"] = args.loop_seconds
            return kwargs

        with ProcessPoolExecutor(max_workers=args.workers) as pool:  # #958: one build per worker, gives way to the yield
            for fut, (sk, tag, sd) in limited_completions(lambda job: pool.submit(optimize, job[0].to_json(), **full_kwargs(*job)), jobs, args.workers):
                res = fut.result()
                considered_parts.append(res.get("considered"))
                if not res["ok"]:
                    say(f"- full optimize failed {tag} seed {sd}: {res['error']}")
                    continue
                res["tag"], res["seed"] = tag, sd
                full_sk = Skeleton.from_json(res["skeleton"])
                append_row(evaluations_path, row_for(request=full_sk.source_label or args.skill, skeleton=full_sk, rung="full", result=res, seed=sd, commit=commit))
                out.append(res)
                print(f"  full {tag} seed {sd}: {res['value']:,.0f} (viol {res['violation']:.3f}) in {human_duration(res['seconds'])}; uniques {[(u['slot'], u['name'], f'{u['gain']:+.0%}') for u in res['uniques'][:3]]}", flush=True)
        winners, others = best_by_seed(out)
        spare_seeds.extend(others)
        for w in winners:
            if len(w["seed_runs"]) > 1:
                say(f"  {w['tag']}: {format_seeds(w)}")
        return winners

    t0 = time.perf_counter()
    full_batch = [(sk, f"screen-{rank}" if rank is not None else f"{sk.ascendancy}-{i}", 1) for i, (sk, rank) in enumerate(zip(finalists, finalist_screen_ranks))]
    finals = run_full(full_batch, seeds=args.seeds)
    say(full_done_line(time.perf_counter() - t0, len(finalists), args.seeds))

    if args.full_ranks:
        by_screen_rank = {int(str(result["tag"]).removeprefix("screen-")): result for result in finals if str(result.get("tag") or "").startswith("screen-")}
        full_ranked = sorted(by_screen_rank.items(), key=lambda pair: _full_rank_key(pair[1]))
        full_ranks = {screen_rank: rank for rank, (screen_rank, _result) in enumerate(full_ranked, 1)}
        say("")
        say("| screen rank | skeleton | screen value | full value | full rank | time |")
        say("|---|---|---|---|---|---|")
        for screen_rank in selected_ranks:
            full = by_screen_rank.get(screen_rank)
            screen = screened[screen_rank - 1]
            if full is None:
                say(f"| {screen_rank} | {skeleton_label(Skeleton.from_json(screen['skeleton']))} | {screen['value']:,.0f} | failed | - | - |")
                continue
            say(f"| {screen_rank} | {skeleton_label(Skeleton.from_json(full['skeleton']))} | {screen['value']:,.0f} | {full['value']:,.0f} | {full_ranks[screen_rank]} | {human_duration(full['seconds'])} |")
        paired = [(rank, screened[rank - 1], full) for rank, full in by_screen_rank.items()]
        screen_values = [screen["value"] for _rank, screen, _full in paired]
        full_values = [full["value"] for _rank, _screen, full in paired]
        rho = spearman(screen_values, full_values)
        say(f"Spearman rho (screen value, full value) = {format_rho(rho)} (n = {len(paired)})")
        if full_ranked:
            winner_screen_rank = full_ranked[0][0]
            say(f"the full-depth winner sits at screen rank {winner_screen_rank}: inside top 2: {'yes' if winner_screen_rank <= 2 else 'no'}, top 3: {'yes' if winner_screen_rank <= 3 else 'no'}, top 5: {'yes' if winner_screen_rank <= 5 else 'no'}")
        construction = [_stage_value(full, loop_pass=False) for _rank, _screen, full in paired]
        loop_one = [_stage_value(full, loop_pass=True) for _rank, _screen, full in paired]
        stages = "; ".join(f"{rank}: {construction[index]:,.0f} / {loop_one[index]:,.0f}" if construction[index] is not None and loop_one[index] is not None else f"{rank}: n/a" for index, (rank, _screen, _full) in enumerate(paired))
        say(f"construction / loop pass 1 by screen rank: {stages}; Spearman rho (construction, full) = {format_rho(spearman(construction, full_values))}; Spearman rho (loop pass 1, full) = {format_rho(spearman(loop_one, full_values))}")

    # -- 6. mutation round: uniques that beat the finished builds' rares, and every structural
    # keystone the finished builds took rebuilt without it (D40: Blood Magic vs auras is one decision)
    if not args.no_mutation:
        t0 = time.perf_counter()
        batch: list[tuple[Skeleton, str, int]] = []  # (skeleton, tag, seed): a variant continues from the seed its parent won with
        from junkroan.optimizer.tree_graph import TreeGraph

        graph = TreeGraph.load()
        for r in sorted(finals, key=lambda r: (r["feasible"], -r["violation"], r["value"]), reverse=True)[: args.top]:
            base = Skeleton.from_json(r["skeleton"])
            parent_seed = int(r.get("seed") or 1)
            fixed = {graph.nodes[int(i)].name.lower() for i in base.keystones if int(i) in graph.nodes}  # the request asked for these: not a variant
            for keystone in r.get("keystones") or []:
                if keystone.lower() in {k.lower() for k in base.forbid_keystones} or keystone.lower() in fixed:
                    continue
                var = Skeleton.from_json(r["skeleton"])
                var.drop_picked_utilities()
                var.forbid_keystones = [*base.forbid_keystones, keystone]
                var.notes = (var.notes or "") + f" -> without {keystone}"
                batch.append((var, f"{var.ascendancy}-no-{slugify(keystone)}", parent_seed))
            for alt in base.weapon_alternatives[:2]:  # runner-up weapon types from the base screen, as whole builds (D41)
                if not weapon_alternative_ok(base, alt):
                    continue  # it would change a forced base or a forced-affix slot's class (#510)
                var = Skeleton.from_json(r["skeleton"])
                var.drop_picked_utilities()
                var.weapon_alternatives = []
                var.rare_bases["Weapon 1"] = alt["Weapon 1"]
                var.sockets.pop("Weapon 1", None)
                if alt.get("Weapon 2"):
                    var.rare_bases["Weapon 2"] = alt["Weapon 2"]
                else:
                    var.rare_bases.pop("Weapon 2", None)
                var.sockets.pop("Weapon 2", None)
                var.notes = (var.notes or "") + f" -> weapon {alt['Weapon 1']}"
                batch.append((var, f"{var.ascendancy}-w-{slugify(alt['Weapon 1'])}", parent_seed))
        seen = {json.dumps(Skeleton.from_json(r["skeleton"]).uniques, sort_keys=True) + Skeleton.from_json(r["skeleton"]).ascendancy for r in finals}
        for r in sorted(finals, key=lambda r: (r["feasible"], -r["violation"], r["value"]), reverse=True)[: args.top]:
            base = Skeleton.from_json(r["skeleton"])
            parent_seed = int(r.get("seed") or 1)
            picked = dict(base.uniques)
            for u in r["uniques"]:
                if u["gain"] >= args.unique_min_gain and u["slot"] not in picked and len(picked) < rails.gear.max_uniques and unique_pick_ok(base, u["slot"], u["name"].split(", ")[0]):
                    picked[u["slot"]] = u["name"].split(", ")[0]
            key = json.dumps(picked, sort_keys=True) + base.ascendancy
            if picked == base.uniques or key in seen:
                continue
            seen.add(key)
            var = Skeleton.from_json(r["skeleton"])
            var.drop_picked_utilities()
            apply_unique_picks(var, picked, replace=True)
            var.notes = (var.notes or "") + f" -> mutation uniques {picked}"
            batch.append((var, f"{var.ascendancy}-mut{len(batch)}", parent_seed))
        if batch:
            say(f"mutation round: {len(batch)} variants of the finished builds (" + ", ".join(tag for _sk, tag, _sd in batch) + ")")
            # screen the variants first (3 min each) and give the full 20 min only to those that hold up:
            # a Smite sceptre variant that finished at 31k after 15 min screened at a fraction of the sword
            floor_value = 0.5 * max((r["value"] for r in screened[: args.top]), default=0.0)
            kept: list[tuple[Skeleton, str, int]] = []
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                for fut, (sk, tag, sd) in limited_completions(lambda job: pool.submit(optimize, job[0].to_json(), log_path=str(logs / f"screen-{job[1]}.log"), screen=True, seed=job[2], gear_mode=args.gear), batch, args.workers):  # #958
                    res = fut.result()
                    considered_parts.append(res.get("considered"))
                    if not res["ok"]:
                        say(f"- variant screen failed {tag}: {res['error']}")
                        continue
                    variant_sk = Skeleton.from_json(res["skeleton"])  # a variant screen is an evaluation like any other
                    append_row(evaluations_path, row_for(request=variant_sk.source_label or args.skill, skeleton=variant_sk, rung="screen", result=res, seed=sd, commit=commit))
                    ok, line = variant_screen_line(tag, res, floor_value)
                    print(line, flush=True)
                    if ok:
                        kept.append((sk, tag, sd))
            if kept:  # a variant is one build on its parent's winning seed: the seeds were spent on the finalists
                finals.extend(run_full(kept))
            say(mutation_done_line(time.perf_counter() - t0, len(kept), len(batch)))
    finals.sort(key=lambda r: (not r.get("audit_errors"), r["feasible"], -r["violation"], r["value"]), reverse=True)  # audit errors sink a build
    say("")
    from junkroan.optimizer.explain import pareto_front

    from junkroan.optimizer.objective import bossing_defence
    from junkroan.optimizer.audit import floors_cell
    front = pareto_front([{"value": r["value"] if r["feasible"] and not r.get("audit_errors") else 0, "ehp": bossing_defence(r["final"] or {})} for r in finals])  # the defence axis is the bossing one (D53)
    say("| rank | build | DPS (conservative) | seed | spread | optimistic | life | max hit (boss) | EHP (map) | MS | uniques | audit | floors | pareto | time |")
    say("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    pob_dir = Path.home() / "Documents" / "Path of Building" / "Builds" / "Junkroan" / f"search {slugify(args.skill)} {run_stamp}"  # one folder per run, dated
    run_dir.mkdir(parents=True, exist_ok=True)
    spares_by_tag: dict[str, list[dict]] = {}
    for sp in spare_seeds:
        spares_by_tag.setdefault(str(sp.get("tag") or ""), []).append(sp)
    for i, r in enumerate(finals, 1):
        sk = Skeleton.from_json(r["skeleton"])
        f = r["final"]
        name = f"{sk.class_name}/{sk.ascendancy}" + (f" + {', '.join(sk.uniques.values())}" if sk.uniques else "") + (f" (no {', '.join(sk.forbid_keystones)})" if sk.forbid_keystones else "") + (f" [{sk.rare_bases['Weapon 1']}]" if sk.rare_bases.get("Weapon 1") else "")
        audit = f"{r.get('audit_errors', 0)} errors / {len(r.get('audit', [])) - r.get('audit_errors', 0)} warnings" if r.get("audit") else "clean"
        runs = r.get("seed_runs") or []
        spread = f"{seed_spread(r.get('seed_values') or []):.1%} ({len(runs)} seeds)" if len(runs) > 1 else "-"
        say(f"| {i} | {name} | {r['value']:,.0f} | {r.get('seed', 1)} | {spread} | {r['optimistic'] or 0:,.0f} | {f.get('Life')} | {bossing_defence(f):,.0f} | {f.get('TotalEHP', 0):,.0f} | {f.get('EffectiveMovementSpeedMod', 0):.2f} | {', '.join(sk.uniques.values()) or '-'} | {audit} | {floors_cell(r.get('floors_missed'))} | {'front' if (i - 1) in front else ''} | {human_duration(r['seconds'])} |")
        stem = f"{i:02d} {slugify(name)}"
        r["stem"] = stem
        write_build_files(run_dir, stem, r, spares_by_tag.get(str(r.get("tag") or ""), []))
        if pob_dir.parent.parent.is_dir():
            pob_dir.mkdir(parents=True, exist_ok=True)
            (pob_dir / f"{stem}.xml").write_text(r["xml"], encoding="utf-8")
    say("")
    for i, r in enumerate(finals, 1):
        sk = Skeleton.from_json(r["skeleton"])
        say(f"## {i}. {sk.class_name}/{sk.ascendancy}: {' - '.join(sk.main_link)}")
        say(f"why: {sk.notes}")
        say(f"ascendancy nodes {sk.ascendancy_nodes}; bases {sk.rare_bases}; uniques {sk.uniques}; keystones {r.get('keystones') or []}" + (f" (forbidden {sk.forbid_keystones})" if sk.forbid_keystones else ""))
        if r.get("seed_runs"):
            others = [d for d in r["seed_runs"] if not d["best"]]
            say(f"seeds: {format_seeds(r)}" + (f" The other seeds' builds: {', '.join(f'{r['stem']}-s{d['seed']}.pob.txt ({d['value']:,.0f})' for d in others)}." if others else ""))
        if r.get("explanation"):
            from junkroan.optimizer.explain import explain as _explain
            from junkroan.search.skeleton import Skeleton as _Sk

            base_notes = sk.notes or ""
            variants = []
            for o in finals:
                osk = _Sk.from_json(o["skeleton"])
                if o is not r and osk.ascendancy == sk.ascendancy and (osk.notes or "").startswith(base_notes + " -> "):
                    variants.append(((osk.notes or "")[len(base_notes) + 4:], o["value"]))
            say("")
            text = r["explanation"] if not variants else r["explanation"] + "\n- Variants rebuilt as whole builds: " + ", ".join(f"{label} {v:,.0f}" for label, v in variants) + "."
            if len(r.get("seed_runs") or []) > 1:  # the same skeleton built several times: the delivered one is the best of them
                text += "\n- Seeds: " + format_seeds(r)
            say(text)
        say("```")
        say(r["summary"])
        say("```")
    say(total_line(time.perf_counter() - t_all))
    publish_report(out_dir, run_dir, report)
    (out_dir / f"report-{run_dir.name}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"report: {run_dir / 'report.md'}")
    if args.trace_out:
        write_trace_out(args.trace_out, considered_parts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
