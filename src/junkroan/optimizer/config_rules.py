"""Config rules: a config toggle is on only if the build has a source for it.

Two lanes:
- optimistic: every input PoB shows for the build (its predicate says something
  in the build benefits from it) is enabled;
- conservative (boss lane): an input is enabled only if the build also
  *generates* the condition, judged from PoB's own numbers where they exist
  (ailment chances, leech rates) and otherwise from the text of the build's
  own mods (items, allocated nodes, gems) for charge / buff generators.

Numeric inputs keep PoB's defaults in both lanes except the enemy settings
from the rails. No hand list of builds; the only curated knowledge is which
*kind* of source satisfies which *kind* of condition.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from junkroan.optimizer.ramp import AilmentStacks, ailment_stacks
from junkroan.optimizer.ramp_inputs import BuildFacts, Gem, cruelty_excess_mod, poison_stack_limit_mod, pride_ramp_mod, ramped_input, stack_option, uncapped_ailment_stack_xml
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.pob.session import PobSession

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data" / "config_surfaces.json"

# Conditions the main skill sustains by being used against a boss.
COMBAT_SUSTAINED = {
    "HitRecently", "CritRecently", "UsedSkillRecently", "AttackedRecently", "CastSpellRecently",
    "UsedMovementSkillRecently", "SkillHitRecently", "UsedFireSkillRecently", "UsedColdSkillRecently",
    "UsedLightningSkillRecently", "UsedChaosSkillRecently", "UsedPhysicalSkillRecently", "HitRecentlyWithWeapon",
    "DealtCritRecently", "SkillCritRecently", "Combat", "InCombat", "UsedWarcryRecently", "UsedTravelSkillRecently", "SpentManaRecently", "UsedMinionSkillRecently",
    "ChannellingRecently",
}
# ... but only when the build actually has a gem of that kind (a Fireball build has not used a warcry recently)
SUSTAINED_NEEDS_GEM_TAG = {
    "UsedWarcryRecently": "warcry", "UsedMovementSkillRecently": "movement", "UsedTravelSkillRecently": "travel", "ChannellingRecently": "channelling", "UsedMinionSkillRecently": "minion",
    "UsedFireSkillRecently": "fire", "UsedColdSkillRecently": "cold", "UsedLightningSkillRecently": "lightning", "UsedChaosSkillRecently": "chaos",
    "UsedPhysicalSkillRecently": "physical", "HitRecentlyWithWeapon": "attack", "AttackedRecently": "attack", "CastSpellRecently": "spell",
}
# "have you crit recently" is how PoB's Elemental Overload takes effect (the keystone's own text:
# "Skills that have dealt a Critical Strike in the past 8 seconds"), so it is proven the way an
# ailment is: by uptime, not by a flat crit-chance bar. `_crit_recently` writes the numbers into
# the reason. 8 s is the keystone's window (research 2026-09-18).
CRIT_RECENTLY_CONDITIONS = {"CritRecently", "SkillCritRecently", "DealtCritRecently"}
from junkroan.optimizer.keystone_floors import CRIT_RECENTLY_MIN_UPTIME, CRIT_RECENTLY_WINDOW_SECONDS  # one rule for the config inputs, the audit and the objective's floor
PROXY_DELIVERY_TAGS = frozenset({"totem", "trap", "mine"})
# A proxy's hit, critical strike, and channelling state belong to the proxy. These are
# the parser conditions that currently derive those facts from the main skill's use.
PROXY_MAIN_CONDITIONS = frozenset({
    "HitRecently", "SkillHitRecently", "HitRecentlyWithWeapon", "HitSpellRecently",
    "AttackedRecently", "CritRecently", "SkillCritRecently", "DealtCritRecently",
    "Channelling", "ChannellingRecently",
})
PROXY_SUBJECT = re.compile(r"\b(?:your |a |the )?(?:totems?|traps?|mines?)\b", re.IGNORECASE)
PROXY_SUBJECT_PREFIXES = (("Totems", "totem"), ("Traps", "trap"), ("Mines", "mine"))
# Conditions that need a kill, i.e. not sustained on a single boss.
KILL_CONDITIONS = {"KilledRecently", "KilledCorruptedEnemyRecently", "KilledRareOrUniqueRecently", "KilledUniqueRecently"}
# Player-state assumptions that a conservative lane never grants for free.
STATE_ASSUMPTIONS = {"FullLife", "LowLife", "FullMana", "LowMana", "FullEnergyShield", "LowEnergyShield", "Stationary", "Moving", "OnShockedGround", "OnBurningGround", "OnChilledGround", "Blinded", "Cursed"}
# The corpse cycle (rule 21 of the user's reading 2026-09-18). "Consumed a corpse recently" was a
# kill condition, which is right for a build that waits for something to die and wrong for one that
# makes its own corpses: Desecrate creates them and Volatile Dead eats three per cast, on a boss as
# anywhere. Both halves are read from PoB's own skill data (`pob/skill_facts`), the same source
# `ramp_inputs.corpses_consumed_recently` already counts the corpses with; a corpse a *kill* leaves
# is not a gem, so it never proves the condition and stays under the on-kill verdict.
# var value = does this condition need the consumer too (spawning one needs only the creator).
CORPSE_CONDITIONS = {"SpawnedCorpseRecently": False, "ConsumedCorpseRecently": True}
CORPSE_COUNT_VAR = "multiplierCorpseConsumedRecently"  # the count of the same fact: off whenever its condition is off

# enemy condition -> PoB chance stat whose applied probability proves the build keeps it up
AILMENT_PROOF = {
    "Ignited": ("IgniteChance", "IgniteChanceOnHit"),
    "Burning": ("IgniteChance", "IgniteChanceOnHit"),
    "Poisoned": ("PoisonChance",),
    "Bleeding": ("BleedChance",),
    "Scorched": ("ScorchChance",), "Brittle": ("BrittleChance",), "Sapped": ("SapChance",),
    "Maimed": ("MaimChance",), "Hindered": ("HinderChance",), "Blinded": ("BlindChance",),
    "Intimidated": ("IntimidateChance",), "Unnerved": ("UnnerveChance",), "Taunted": ("TauntChance",),
}
# A damaging ailment needs both: damage it actually deals (PoB's own DPS key > 0) and a chance
# that keeps it applied. Ignited/Burning turned on by a 33.6% ignite chance at 3.9 hits/s while
# IgniteDPS was 0 (no fire in the hit: the ignite cannot exist, toxic_rain) and by an IgniteDPS
# of 10.67 from one item's fire damage with a 2% chance (cold_dot) are the two measured mistakes
# of the old chance-or-damage rule (the user's reading, 2026-09-16). The non-damaging ailments
# (blind, maim, ...) keep the chance-only rule.
AILMENT_DAMAGE_PROOF = {
    "Ignited": ("IgniteDPS",),
    "Burning": ("IgniteDPS",),
    "Poisoned": ("PoisonDPS", "TotalPoisonDPS"),
    "Bleeding": ("BleedDPS", "TotalBleedDPS"),
}
AILMENT_DAMAGE_SOURCE = {"Ignited": "fire", "Burning": "fire", "Poisoned": "poison", "Bleeding": "bleed"}

# Non-damaging ailments (Shock, Chill, Scorch, Brittle, Sap) from the main skill's own hits are NOT applied by PoB:
# `val.effect` (50 * (damage / threshold)^0.4 * effectMod) only fills the breakdown (CalcOffence.lua:5230, 5323);
# ShockVal / ChillVal / ... are written only by the config's "Effect of ..." input (ConfigOptions.lua:1921, behind
# its "Is the enemy ...?" checkbox) and by guaranteed sources (CalcPerform.lua:3500-3540). So the checkbox is not
# "another source only": `own_hit_ailments` derives what the build's own hits earn from PoB's hit numbers and the
# boss threshold and types both inputs. OTHER_SKILL_AILMENTS is what a second enabled skill of that element adds.
OTHER_SKILL_AILMENTS = {"Chilled": "cold", "Frozen": None, "Shocked": "lightning", "Scorched": None, "Brittle": None, "Sapped": None}  # freezing a boss: optimistic only
AUX_SKILL_EXCLUDED_TAGS = {"minion", "golem", "aura", "herald", "banner", "trigger", "warcry", "guard", "curse", "hex", "mark", "totem", "link"}  # not hitting the boss with the element

# PoB display / debug switches that are not assumptions about the fight; never in any lane
NEVER_A_LANE_INPUT = {"PvpScaling", "ignoreJewelLimits", "enemyMaxResist", "DisableEHPGainOnBlock", "EHPUnluckyWorstOf"}

# Facts of the fight, not assumptions: a boss hits you, so both lanes hold them. PoB's default
# is false, which is the *optimistic* state for a "less damage taken if you haven't been hit"
# keystone (Wind Dancer: the optimizer took it on the default, toxic_rain physical max hit
# 5,403 with it vs 4,439 with the condition on; the user's reading 2026-09-16). Element- and
# savage-hit-specific variants are not facts and keep the normal rules.
FIGHT_FACTS = {
    "conditionBeenHitRecently": "a boss hits you",
    "conditionBeenHitByAttackRecently": "a boss attacks you",
}

# Boolean Skill Options that PoB guards with `ifSkill` and that mean "you used that skill's
# effect": having the gem *is* the proof, because using the gem that way is the only reason it
# is in the build. Kinetic Fusillade carried Flame Wall in a socket group with
# `flameWallAddedDamage` off -- the wall was paying for a link slot and giving nothing (the
# user's reading 2026-09-18). PoB only shows these inputs when the skill is in the build, so no
# further check is needed. Everything else behind `ifSkill` stays an assumption (a *BypassCD is
# charges spent; `meatShieldEnemyNearYou` is positioning; `conditionSummonedZombieInPast8Sec`
# is a cast you may not have made): optimistic lane only.
ENABLER_GEM_INPUTS = {
    "flameWallAddedDamage": "Flame Wall in the build: projectiles are fired through the wall you placed",
    "bannerPlanted": "a banner in the build: a banner is planted and stays planted",
    "channellingCycloneCheck": "Cyclone in the build: channelling it is how it is used",
    "iceNovaCastOnFrostbolt": "Ice Nova of Frostbolts in the build: it is cast on your own Frostbolt",
    "vortexCastOnFrostbolt": "Vortex of Projection in the build: it is cast on your own Frostbolt",
    "infusedChannellingInfusion": "Infused Channelling in the build: the infusion is what channelling grants",
    "linkedToMinion": "a link skill in the build: it is cast on your own minion",
    "deathmarkDeathmarkActive": "Predator in the build: Signal Prey is what marks the target",
    "raiseSpectreEnableBuffs": "Raise Spectre in the build: the spectres cast what they have",
    "raiseSpectreEnableCurses": "Raise Spectre in the build: the spectres cast what they have",
    "summonElementalRelicEnableAngerAura": "Summon Elemental Relic in the build: the relic carries its aura",
    "summonElementalRelicEnableHatredAura": "Summon Elemental Relic in the build: the relic carries its aura",
    "summonElementalRelicEnableWrathAura": "Summon Elemental Relic in the build: the relic carries its aura",
    "summonHolyRelicEnableHolyRelicBoon": "Summon Holy Relic in the build: the relic carries its aura",
    "summonLightningGolemEnableWrath": "Summon Lightning Golem in the build: the golem carries its aura",
    "feedingFrenzyFeedingFrenzyActive": "Feeding Frenzy in an enabled link: the support grants its minions' buff",
}

# generator text patterns, matched against the build's own mod text
GENERATORS = {
    "PowerCharges": r"gain (a|an|\d+) power charges?|power charge on (kill|crit|hit|block)|power charges? when|generate .*power charge",
    "FrenzyCharges": r"gain (a|an|\d+) frenzy charges?|frenzy charge on (kill|crit|hit|block)|frenzy charges? when|generate .*frenzy charge",
    "EnduranceCharges": r"gain (a|an|\d+) endurance charges?|endurance charge on (kill|crit|hit|block)|endurance charges? when|generate .*endurance charge|enduring cry",
    "Onslaught": r"onslaught",
    "FeedingFrenzy": r"feeding frenzy",
    "Fortified": r"fortif",
    "Fortify": r"fortif",
    "Leeching": r"leech",
    "Rampage": r"rampage",
    "Adrenaline": r"adrenaline",
    "Phasing": r"phasing",
    "UnholyMight": r"unholy might",
    "Tailwind": r"tailwind",
    "Elusive": r"elusive",
    "ArcaneSurge": r"arcane surge",
    "Focused": r"focus",
    "Blind": r"blind",
    # creators only: "effect of consecrated ground you create" is a modifier, not a source
    "OnConsecratedGround": r"have consecrated ground|creates? consecrated ground|consecrated ground (around you|on use|when you|for \d+ seconds)|bottled faith|consecrated path",
}
# -- a generator needs its enabler (the user's reading 2026-09-18) ---------------------
# "Gain 3 Endurance / Frenzy Charges when you consume maximum Valour to place a Banner" is a
# proof only for a build that can place a banner; shockwave_cyclone and static_strike took
# maximum frenzy and endurance charges off that cluster with no banner gem anywhere. The kinds
# are gem corpus tags (`active_gems.json` tag_keys, the same field the support-legality code
# reads), so Blastchain Mine Support counts as a mine skill and Trap Support as a trap.
GENERATOR_ENABLERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbanners?\b"), "banner"),
    (re.compile(r"\bwarcr(y|ies)\b"), "warcry"),
    (re.compile(r"\bmines?\b"), "mine"),
    (re.compile(r"\btraps?\b"), "trap"),
    (re.compile(r"\btotems?\b"), "totem"),
    (re.compile(r"\bmarks?\b|\bmarked\b"), "mark"),
    (re.compile(r"\bwhile channelling\b"), "channelling"),
)
# a source that needs a kill: no kills on a boss (mechanics/unsupported_lines.json,
# `on_kill_generator`). It filters buff proofs as well as charges since the user's reading of
# impale_cyclone, where `buffOnslaught` stood on "20% chance to gain Onslaught ... on Kill".
ON_KILL_TRIGGER = re.compile(
    r"\bon kill\b|\bwhen you kill\b|\bkill(s|ed|ing)\b|\bslain\b|\bculling\b|close to death|"
    r"\b(?:[a-z]+\s+){0,4}(?:enemy|enemies)\s+(?:that\s+)?die(?:s)?\b"
)


def missing_enabler(line: str, gem_tags: frozenset[str], main_tags: frozenset[str] | None = None) -> str | None:
    """The skill kind a generator line names that the build cannot use, or None.

    Most enablers are satisfied by any enabled gem in the build. Channelling is
    different: a utility channel does not keep a main-skill generator running,
    so only the main active skill's tags can prove it. Existing callers without
    `main_tags` retain the historical union-of-gem-tags behavior.
    """

    for pattern, kind in GENERATOR_ENABLERS:
        if not pattern.search(line):
            continue
        tags = main_tags if kind == "channelling" and main_tags is not None else gem_tags
        if kind not in tags:
            return kind
    return None


NUMERIC_ASSUMPTION_DEFAULTS = {
    "mine_detonation_window_seconds": 4.0, "mine_detonation_fraction": 1.0,  # "recently" is 4 s; every thrown mine detonated (D57 rule 3)
    "trinity_resonance_when_all_three_elements": 50.0, "rage_fraction_of_max": 0.5,
    "withered_stacks_from_wither_skill": 15.0, "chill_seconds_on_boss": 10.0,
    "toxic_rain_pods_fraction_of_projectiles": 1.0, "stack_options_ceiling": 50.0,
}
# Stack-type skill options ("# of Intensity", "Stages", "Stacks"): a state the player builds by using the
# skill and holds, the same class as a stacked skill part (D36, D42), never an assumption about the fight.
# Options PoB already fills when unset ("(if not maximum)", "(if not average)") are left to PoB.
STACK_OPTION_LABEL = re.compile(r"\b(intensity|stages?|stacks?)\b", re.IGNORECASE)
STACK_OPTION_PRESET = re.compile(r"\(if not (maximum|average)\)", re.IGNORECASE)
# The one preset option admitted by its var (#17): `MomentumStacks` ("# of Momentum (if not average)") is a stack the
# support builds one per use, and PoB caps the input at the gem's MomentumStacksMax (CalcOffence.lua:1005-1014,
# `ReplaceMod`), so `judge_stack_options` measures the cap like any other. Every other "(if not ...)" stays PoB's.
STACK_OPTION_PRESET_ADMITTED = frozenset({"MomentumStacks"})
# `judge_stack_options` answers for one build; the build's own export is the key (see the function).
# A handful of entries is enough: the pipeline alternates between the build and one mutated copy of it.
_STACK_JUDGEMENTS: "OrderedDict[tuple, dict[str, tuple[int | None, str, int | None, float]]]" = OrderedDict()
_STACK_JUDGEMENTS_MAX = 8
_POB_COLOR = re.compile(r"\^x[0-9A-Fa-f]{6}|\^\d")
ELEMENT_HIT_KEYS = ("MainHand.FireHitAverage", "MainHand.ColdHitAverage", "MainHand.LightningHitAverage", "FireHitAverage", "ColdHitAverage", "LightningHitAverage")
CHARGE_VARS = {"usePowerCharges": "PowerCharges", "useFrenzyCharges": "FrenzyCharges", "useEnduranceCharges": "EnduranceCharges"}
BUFF_VARS = {
    "buffOnslaught": "Onslaught", "buffFortification": "Fortified", "buffFortify": "Fortify", "buffPhasing": "Phasing",
    "buffUnholyMight": "UnholyMight", "buffTailwind": "Tailwind", "buffAdrenaline": "Adrenaline", "buffElusive": "Elusive",
    "buffArcaneSurge": "ArcaneSurge", "conditionLeeching": "Leeching", "conditionLeechingLife": "LeechingLife",
    "conditionLeechingEnergyShield": "LeechingEnergyShield", "conditionLeechingMana": "LeechingMana", "buffRampage": "Rampage",
    "feedingFrenzyFeedingFrenzyActive": "FeedingFrenzy",  # the support's buff: minions hitting keep it up
}

def parse_mods_batch(pob: PobSession, lines: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Parse unique build lines in one PoB call, memoized for this process.

    The returned rows are indexed by their exact input text.  The helper is
    deliberately the only stateful boundary: proof consumers receive the
    resulting rows explicitly and remain pure.
    """

    unique = tuple(dict.fromkeys(str(line) for line in lines if str(line)))
    if not unique:
        return {}
    cache: dict[str, dict[str, Any]] = getattr(parse_mods_batch, "_cache", {})
    missing = [line for line in unique if line not in cache]
    if missing:
        parsed = pob.parse_mods(missing)
        for line, row in zip(missing, parsed, strict=False):
            cache[line] = dict(row) if isinstance(row, Mapping) else {"line": line, "ok": False, "unsupported": True, "mods": []}
        parse_mods_batch._cache = cache
    return {line: cache[line] for line in unique if line in cache}


def clear_parse_mods_cache() -> None:
    """Clear process-local parser results, primarily for tests and PoB bumps."""

    parse_mods_batch._cache = {}


def _iter_direct_mods(mod: Mapping[str, Any]):
    """Yield only top-level player mods; nested actor modifier lists do not count."""

    if str(mod.get("name", "")) in {"MinionModifier", "EnemyModifier"}:
        return
    yield mod


def _parsed_sources(parsed: Mapping[str, Mapping[str, Any]], condition: str) -> list[tuple[str, tuple[str, ...]]]:
    target = f"Condition:{condition}"
    found: list[tuple[str, tuple[str, ...]]] = []
    for line, row in parsed.items():
        if not row.get("ok") or row.get("unsupported"):
            continue
        for mod in row.get("mods") or ():
            if not isinstance(mod, Mapping):
                continue
            for direct in _iter_direct_mods(mod):
                if direct.get("name") != target or direct.get("type") != "FLAG":
                    continue
                tags = tuple(
                    str(tag.get("var"))
                    for tag in direct.get("tags") or ()
                    if isinstance(tag, Mapping) and tag.get("type") == "Condition" and tag.get("var")
                )
                found.append((line, tags))
    return found


def _input_condition(option: Mapping[str, Any]) -> str | None:
    """The player condition a config input itself enables, as read from PoB."""

    flags = option.get("condition_flags") or ()
    for flag in flags:
        if not isinstance(flag, Mapping):
            continue
        conditions = [str(value) for value in flag.get("conditions") or () if value not in {"Combat"}]
        # Elusive is the important case: the checkbox supplies Condition:Elusive
        # behind Condition:CanBeElusive, while a parsed source supplies the latter.
        if conditions:
            return conditions[0]
        name = flag.get("name")
        if isinstance(name, str) and name and name != "Combat":
            return name
    # Fakes from older unit tests may use the pre-structured worker shape.
    return next((str(flag) for flag in flags if isinstance(flag, str) and flag != "Combat"), None)


def _condition_allows(condition: str, stats: Mapping[str, Any], gem_tags: frozenset[str], main_tags: frozenset[str], source_line: str = "", *, proxy_subject: bool = False) -> tuple[bool, str] | None:
    """Whether a parser source's ``Condition`` tag is valid in the boss lane."""

    for prefix, delivery in PROXY_SUBJECT_PREFIXES:
        if not condition.startswith(prefix):
            continue
        if "Killed" in condition:
            return False, f"{condition} needs kills (boss lane)"
        if delivery in main_tags:
            return True, f"{condition} is sustained by the {delivery} main skill"
        return False, f"{condition} needs a {delivery} main skill; none in the build"
    if condition in PROXY_MAIN_CONDITIONS and main_tags & PROXY_DELIVERY_TAGS and not proxy_subject and not PROXY_SUBJECT.search(source_line):
        return False, f"{condition} comes from the proxy main skill; its hits and channelling are not the player's"
    if condition in KILL_CONDITIONS:
        return False, f"{condition} needs kills (boss lane)"
    if condition in STATE_ASSUMPTIONS:
        return False, f"{condition} is a state assumption"
    if condition in CRIT_RECENTLY_CONDITIONS:
        ok, why = _crit_recently(stats, main_tags)
        return ok, f"{condition}: {why}"
    if condition in COMBAT_SUSTAINED:
        tag = SUSTAINED_NEEDS_GEM_TAG.get(condition)
        if tag and tag not in (main_tags if condition == "ChannellingRecently" else gem_tags):
            return False, f"{condition} needs a {tag} {'main skill' if condition == 'ChannellingRecently' else 'gem'}; none in the build"
        return True, f"{condition} is sustained by using the main skill"
    if condition == "Channelling":
        if "channelling" in main_tags:
            return True, "Channelling is sustained by the main skill"
        return False, "Channelling needs a channelling main skill; none in the build"
    if condition in {"HitSpellRecently", "CastSpellRecently"}:
        if "spell" in main_tags:
            return True, f"{condition} is sustained by the spell main skill"
        return False, f"{condition} needs a spell main skill; none in the build"
    if condition in {"HitRecently", "SkillHitRecently", "AttackedRecently", "HitRecentlyWithWeapon"}:
        if "attack" in main_tags or "spell" in main_tags:
            return True, f"{condition} is sustained by the main skill"
        return False, f"{condition} needs a hitting main skill; none in the build"
    return None


def _parsed_condition_allows(
    condition: str,
    stats: Mapping[str, Any],
    parsed: Mapping[str, Mapping[str, Any]],
    gem_tags: frozenset[str],
    main_tags: frozenset[str],
    seen: frozenset[str] = frozenset(),
) -> tuple[bool, str]:
    """Conservatively resolve a parser condition tag, including another source."""

    direct = _condition_allows(condition, stats, gem_tags, main_tags)
    if direct is not None:
        return direct
    if condition in seen:
        return False, f"{condition} depends on itself"
    for line, preconditions in _parsed_sources(parsed, condition):
        failures = []
        for tag in preconditions:
            direct = _condition_allows(tag, stats, gem_tags, main_tags, line)
            ok, why = direct if direct is not None else _parsed_condition_allows(tag, stats, parsed, gem_tags, main_tags, seen | {condition})
            if not ok:
                failures.append(why)
        if not failures:
            return True, f"Condition:{condition} source parsed by PoB: {line[:90]}"
    return False, f"{condition} has no conservative proof rule"


def parsed_buff_proof(
    var: str,
    stats: Mapping[str, Any],
    parsed: Mapping[str, Mapping[str, Any]],
    option: Mapping[str, Any] | None,
    gem_tags: frozenset[str],
    main_tags: frozenset[str],
    gem_names: Sequence[str] = (),
    proof_lines: list[str] | None = None,
) -> tuple[bool, str]:
    """Prove a player buff only from PoB's parsed player ``Condition`` source.

    A condition tag on that source is its own prerequisite.  The parser, not a
    word match, distinguishes a generator from consumers, caps, effect
    modifiers and minion-only conditions.
    """

    leech_rates = {
        "conditionLeeching": ("LifeLeechGainRate", "ManaLeechGainRate", "EnergyShieldLeechGainRate"),
        "conditionLeechingLife": ("LifeLeechGainRate",),
        "conditionLeechingEnergyShield": ("EnergyShieldLeechGainRate",),
        "conditionLeechingMana": ("ManaLeechGainRate",),
    }
    if var in leech_rates:
        rates = leech_rates[var]
        positive = [key for key in rates if isinstance(stats.get(key), (int, float)) and stats[key] > 0]
        if positive:
            return True, f"PoB's own positive leech rate ({', '.join(positive)})"
        return False, "PoB shows no positive life, mana, or energy shield leech gain rate"
    condition = _input_condition(option or {})
    if not condition:
        return False, "PoB exposes no player Condition flag for this input"
    rejected: list[str] = []
    accepted: list[tuple[str, tuple[str, ...]]] = []
    ending_lines = _skill_use_ending_buff_lines(var, gem_names)
    for line, preconditions in _parsed_sources(parsed, condition):
        if line in ending_lines:
            continue
        failures = []
        for tag in preconditions:
            direct = _condition_allows(tag, stats, gem_tags, main_tags, line)
            ok, why = direct if direct is not None else _parsed_condition_allows(tag, stats, parsed, gem_tags, main_tags, frozenset({condition}))
            if not ok:
                failures.append(why)
        if not failures:
            accepted.append((line, preconditions))
            continue
        rejected.append(f"{line[:90]} ({'; '.join(failures)})")
    if accepted:
        if proof_lines is not None:
            proof_lines.extend(line for line, _preconditions in accepted)
        line, preconditions = accepted[0]
        detail = f"source parsed by PoB: {line[:90]}"
        if preconditions:
            detail += f" (preconditions: {', '.join(preconditions)})"
        return True, detail
    if rejected:
        return False, "no parsed source with valid preconditions: " + "; ".join(rejected[:2])
    ending_sources = _skill_use_ending_buff_sources(var, gem_names)
    if ending_sources:
        return False, "; ".join(source.conservative_reason for source in ending_sources)
    return False, f"no player Condition:{condition} FLAG source parsed by PoB"




# -- charge generators, quantified (mechanics/unsupported_lines.json, decided with the user 2026-09-14) ----------
CHARGE_KIND = {"usePowerCharges": "Power", "useFrenzyCharges": "Frenzy", "useEnduranceCharges": "Endurance"}
DEFAULT_RAMP_BUDGET_S = 2.5  # the ramp budget (seconds) of a caller that has no rails assumptions; derive_config reads its own from them and passes it down
AILMENT_STACK_OVERRIDES = frozenset(("overrideBleedStackPotential", "overrideIgniteStackPotential"))
_CHARGE_LINE = r"(?P<chance>\d+)?%?\s*chance to (?P<verb>gain|steal)|(?P<verb2>gain|steal)"
_KILL_ENABLER = re.compile(r"writhing worm spawns every (\d+(?:\.\d+)?) seconds", re.IGNORECASE)
# Azadi Crest's own line, as PoB reports it (Data/Uniques/shield.lua): lucky effects roll three times, not two.
_THREE_ROLL_LUCKY = re.compile(r"your lucky or unlucky effects use the best or\s+worst from three rolls instead of two", re.IGNORECASE)
_FLASK_WORMS = re.compile(r"(\d+) enemy writhing worms? escape the flask when used", re.IGNORECASE)
_CHARGES_PER_USE = re.compile(r"(\d+(?:\.\d+)?)% (reduced|increased) charges per use", re.IGNORECASE)
ADD_KILLS_STAT = "AddSpawningKillsPerSecond"  # derived below from PoB's own outputs; read by `charge_rule`
_MINE_TRIGGER = re.compile(r"\bwhen your mine is detonated\b")
_TRAP_TRIGGER = re.compile(r"\bwhen your trap is triggered\b")
_MANA_SPENT_TRIGGER = re.compile(r"\bafter spending a total of (\d+(?:\.\d+)?) mana\b")


# A skill's own text says "grants" or "gives" where an item says "gain": Frenzy "gives the
# character a frenzy charge if it hits", "Grants an Endurance Charge on Hit" (PoB's rendering of
# `add_endurance_charge_on_skill_hit_%`). Those lines reach the proofs since R1.2 (`build_text`).
_GRANT_VERB = r"gain|steal|grants?|granting|gives?|giving"


def charge_sources(kind: str, text: str, gem_tags: frozenset[str] | None = None, main_tags: frozenset[str] | None = None) -> list[dict]:
    """Every line of the build's text that generates charges of `kind`, classified by
    trigger: {"chance": 0-1, "count": n, "trigger": hit|crit|block|kill|periodic|mine|trap|mana_spent|banner|steal|other,
    "period": seconds (periodic), "line": text, "needs": missing enabler kind or None}.
    With `gem_tags`, a line whose trigger names a skill kind the build has not got
    (a banner, a warcry, a mine, a trap, a totem, a mark) carries that kind in "needs".
    Channelling uses `main_tags`: only a channelled main skill proves a "while
    channelling" source.
    """

    kind_l = kind.lower()
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip().lower()
        if f"{kind_l} charge" not in line and not (kind_l in line and "charges" in line and "steal" in line):
            continue
        if "maximum" in line and "gain" not in line and "steal" not in line:
            continue  # "+1 to maximum frenzy charges": a cap, not a source
        if "lose" in line and "gain" not in line:
            continue
        needs = missing_enabler(line, gem_tags, main_tags) if gem_tags is not None else None
        if "steal" in line and "charge" in line:
            sm = re.search(r"(\d+)% chance to steal", line)
            out.append({"chance": float(sm.group(1)) / 100.0 if sm else 1.0, "count": 1, "trigger": "steal", "period": None, "line": raw.strip(), "needs": needs})
            continue
        m = re.search(rf"(?:(\d+)% chance to )?({_GRANT_VERB}) (?:a|an|(\d+)) ", line)
        if not m or not re.search(rf"({_GRANT_VERB}) (?:a|an|\d+) (?:[a-z, ]*?){kind_l} charges?", line):
            if re.search(rf"({_GRANT_VERB})[^.]*{kind_l} charges?", line):
                m = re.search(rf"(?:(\d+)% chance to )?({_GRANT_VERB})", line)
            else:
                continue
        chance = float(m.group(1)) / 100.0 if m.group(1) else 1.0
        verb = m.group(2)
        count = int(m.group(3)) if m.lastindex and m.lastindex >= 3 and m.group(3) else 1
        if verb == "steal":
            trigger = "steal"
        elif _MINE_TRIGGER.search(line):
            trigger = "mine"
        elif _TRAP_TRIGGER.search(line):
            trigger = "trap"
        elif _MANA_SPENT_TRIGGER.search(line):
            trigger = "mana_spent"
        elif re.search(r"when you are hit\b", line):
            trigger = "when_hit"
        elif ON_KILL_TRIGGER.search(line):
            trigger = "kill"
        elif re.search(r"when you block|on block|block(ed|ing)? ", line):
            trigger = "block"
        elif re.search(r"critical strike|on crit|when you crit", line):
            trigger = "crit"
        elif re.search(r"on (melee )?hit|when you hit|hit with|hits? (a|an) |if it hits|if they hit|when it hits", line):
            trigger = "hit"
        elif re.search(r"every (\d+(?:\.\d+)?) seconds?", line) or re.search(r"\beach second\b", line):
            trigger = "periodic"
        elif re.search(r"\bplace a banner\b", line):
            trigger = "banner"
        else:
            trigger = "other"
        period = None
        pm = re.search(r"every (\d+(?:\.\d+)?) seconds?", line)
        if pm:
            period = float(pm.group(1))
        elif re.search(r"\beach second\b", line):
            period = 1.0
        source = {"chance": chance, "count": count, "trigger": trigger, "period": period, "line": raw.strip(), "needs": needs}
        if trigger == "mana_spent":
            source["threshold"] = float(_MANA_SPENT_TRIGGER.search(line).group(1))
        out.append(source)
    return out


def flask_base_charges_used(base_name: str) -> int | None:
    """`chargesUsed` of a flask base, from the pinned runtime's own Data/Bases/flask.lua."""

    from junkroan.pob.skill_facts import _LOCK, PROJECT_ROOT

    lock = json.loads(_LOCK.read_text(encoding="utf-8"))
    path = PROJECT_ROOT / "var" / "cache" / "pob" / str(lock["tag"]) / str(lock["extract_subdir"]) / "Data" / "Bases" / "flask.lua"
    text = path.read_text(encoding="utf-8", errors="replace")
    block = re.search(r'itemBases\["%s"\]\s*=\s*\{(.*?)\n\}' % re.escape(base_name), text, re.S)
    m = re.search(r"chargesUsed\s*=\s*(\d+)", block.group(1)) if block else None
    return int(m.group(1)) if m else None


def flask_add_kills_per_second(pob: PobSession, text: str) -> tuple[float, list[str]]:
    """Kills per second from flasks that spawn killable adds when used (The Writhing Jar: "2 Enemy Writhing
    Worms escape the Flask when used"): worms per use x uses per second, per such flask, with
    uses/s = charges per second the flask gains / charges per use.

    Charges per second: PoB's calcs outputs `FlaskChargeGen` (every flask), `LifeFlaskChargeGen` and
    `ManaFlaskChargeGen` (each already includes `FlaskChargeGen`; `Modules/CalcPerform.lua:1595-1598`), a
    Hybrid flask gets the generic part plus the life part plus the mana part. Charges per use: PoB keeps it
    only inside the item (`Classes/Item.lua:2398`), so it is the base's `chargesUsed` (Data/Bases/flask.lua) x
    (1 + the item's own "N% reduced/increased Charges per use" line as the item reports it), floored as PoB
    floors it; a global "Charges Used" modifier from elsewhere is not read. Returns (kills/s, notes)."""

    if not _FLASK_WORMS.search(text):
        return 0.0, []
    from junkroan.optimizer.item_bases import base_record

    state = pob.read_state()
    gear = state.get("gear_slots") or state.get("items_state") or {}
    slots = gear.get("slots") if isinstance(gear, dict) else None
    out = (pob.calc_raw().get("baseline") or {}).get("calcs_output") or {}
    generic, life, mana = (float(out.get(k) or 0.0) for k in ("FlaskChargeGen", "LifeFlaskChargeGen", "ManaFlaskChargeGen"))
    utility = float(out.get("UtilityFlaskChargeGen") or 0.0)
    total, notes = 0.0, []
    for slot, entry in (slots or {}).items():
        item = entry.get("item") if isinstance(entry, dict) else None
        if not isinstance(item, dict) or "Flask" not in str(slot):
            continue
        lines = [str(x) for key in ("implicit_affixes", "explicit_affixes") for x in item.get(key) or []]
        worms = sum(int(m.group(1)) for line in lines for m in [_FLASK_WORMS.search(line)] if m)
        base = str(item.get("base_type") or "")
        base_used = flask_base_charges_used(base)
        if not worms or not base_used:
            continue
        inc = sum((-1 if m.group(2).lower() == "reduced" else 1) * float(m.group(1)) for line in lines for m in [_CHARGES_PER_USE.search(line)] if m)
        per_use = int(base_used * (1 + inc / 100.0))
        sub = str((base_record(base) or {}).get("sub_type") or "")
        per_second = {"Life": life, "Mana": mana, "Hybrid": life + mana - generic}.get(sub, utility)
        if per_use <= 0 or per_second <= 0:
            notes.append(f"{slot}: {base} gains {per_second:g} charges/s in PoB: no uses")
            continue
        uses = per_second / per_use
        total += worms * uses
        notes.append(f"{slot}: {base} {per_second:g} charges/s / {per_use} per use (base {base_used}, {inc:+g}%) = {uses:.4f} uses/s x {worms} worms")
    return total, notes


def warcry_charge_effect_ids(gems: Sequence[Gem]) -> tuple[str, ...]:
    """Enabled warcry effects whose own data grants a charge per Warcry Power."""

    from junkroan.pob.skill_facts import constant_stats_matching, skill_types

    return tuple(dict.fromkeys(
        gem.effect_id for gem in gems
        if gem.effect_id and "warcry" in skill_types(gem.effect_id)
        and constant_stats_matching(gem.effect_id, r"_charge_granted_per_X_monster_power")
    ))


def warcry_usage_proof(gems: Sequence[Gem]) -> tuple[bool, str]:
    """The shared proof that the player uses a warcry on cooldown."""

    from junkroan.pob.skill_facts import skill_types

    for gem in gems:
        if not gem.effect_id or "warcry" not in skill_types(gem.effect_id):
            continue
        if gem.effect_id == "Autoexertion" or gem.triggered or gem.autoexerted:
            continue
        return True, f"{gem.name} is an enabled warcry the player can press"
    return False, "no enabled warcry the player presses (warcries are triggered or autoexerted)"


def warcry_charge_sources(gems: Sequence[Gem], skill_stats: Mapping[str, Mapping[str, Any]], *, usage_proven: bool = True) -> list[dict]:
    """Warcry charge grants derived from constant stats and live PoB skill output."""

    from junkroan.pob.skill_facts import constant_stats_matching

    if not usage_proven:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for gem in gems:
        if (not gem.effect_id or gem.effect_id in seen or gem.effect_id not in warcry_charge_effect_ids((gem,))
                or gem.triggered or gem.autoexerted):
            continue
        seen.add(gem.effect_id)
        row = skill_stats.get(gem.effect_id) or {}
        power, cooldown = row.get("WarcryPower"), row.get("Cooldown")
        if not isinstance(power, (int, float)) or power <= 0 or not isinstance(cooldown, (int, float)) or cooldown <= 0:
            continue
        for stat, per_power in constant_stats_matching(gem.effect_id, r"_charge_granted_per_X_monster_power"):
            if per_power <= 0:
                continue
            out.append({
                "kind": stat.split("_charge_granted", 1)[0].title(),
                "count": int(float(power) // per_power),
                "power": float(power),
                "per_power": float(per_power),
                "cooldown": float(cooldown),
                "effect_id": gem.effect_id,
                "line": gem.name,
                "trigger": "warcry",
                "chance": 1.0,
                "period": None,
                "needs": None,
            })
    return out


def charge_rule(var: str, stats: Mapping[str, Any], text: str, gem_tags: frozenset[str], ramp_seconds: float = 2.5,
                main_tags: frozenset[str] | None = None, warcry_sources: Sequence[Mapping[str, Any]] = (),
                source_contexts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                proof_lines: list[str] | None = None) -> tuple[bool, str, int | None, float]:
    """The boss lane's answer for use<Kind>Charges: (use, reason, override count or None,
    charges gained per second). Sustained charges = sum over sources of chance x rate x
    charge duration (PoB's <Kind>ChargesDuration), capped at PoB's <Kind>ChargesMax:
    on hit uses hits per second, on critical strike also the crit chance, "every N seconds"
    or "each second" 1/N, on kill only through an add-spawning enabler (Squirming Terror: a worm
    every 2 s), on block only with a retaliation skill in the build (it blocks or it has
    no damage: full), stealing never (bosses carry no charges). An unclassified source
    is not proof on the conservative lane."""

    kind = CHARGE_KIND[var]
    kmax = stats.get(f"{kind}ChargesMax")
    kmax = float(kmax) if isinstance(kmax, (int, float)) and kmax > 0 else 3.0
    duration = stats.get(f"{kind}ChargesDuration")
    duration = float(duration) if isinstance(duration, (int, float)) and duration > 0 else 10.0
    hits = float(stats.get("HitSpeed") or stats.get("Speed") or 0.0)
    crit = float(stats.get("CritChance") or 0.0) / 100.0
    sources = [*charge_sources(kind, text, gem_tags, main_tags), *(source for source in warcry_sources if source.get("kind") == kind)]
    if not sources:
        return False, "charge generator not found in build text", None, 0.0
    kills_per_second = 0.0
    for m in _KILL_ENABLER.finditer(text):
        kills_per_second += 1.0 / max(0.1, float(m.group(1)))
    kills_per_second += float(stats.get(ADD_KILLS_STAT) or 0.0)  # The Writhing Jar: `flask_add_kills_per_second`
    rate = 0.0
    warcry_rate = 0.0
    warcry_budget = 0.0
    warcry_sustained = 0.0
    timed_budget_adjustment = 0.0
    timed_sustained_adjustment = 0.0
    assumptions = NUMERIC_ASSUMPTION_DEFAULTS
    full: list[str] = []
    ignored: list[str] = []
    counted: list[str] = []
    half_held = 0.0
    context_positions: dict[str, int] = {}
    proxy_main = bool((main_tags or frozenset()) & PROXY_DELIVERY_TAGS)

    def count_source(source: Mapping[str, Any]) -> None:
        if proof_lines is not None:
            proof_lines.append(str(source["line"]))

    def context_for(source: Mapping[str, Any]) -> Mapping[str, Any] | None:
        line = str(source.get("line") or "").lower()
        rows = (source_contexts or {}).get(line) or ()
        position = context_positions.get(line, 0)
        context_positions[line] = position + 1
        return rows[position] if position < len(rows) else None

    def generator_rate(context: Mapping[str, Any] | None) -> tuple[float, float, float]:
        if context is None:
            return hits, 1.0, crit
        own_stats = context.get("stats") or {}
        speed = float(own_stats.get("Speed") or own_stats.get("HitSpeed") or 0.0)
        hit_chance = float(own_stats.get("HitChance") or 0.0) / 100.0
        own_crit = float(own_stats.get("CritChance") or 0.0) / 100.0
        return speed, hit_chance, own_crit

    def hand_totem_amounts(context: Mapping[str, Any], per_second: float) -> tuple[float, float, str]:
        """Charge amounts for a hand-used generator beside a totem main skill."""

        own_stats = context.get("stats") or {}
        limit = float(stats.get("ActiveTotemLimit") or 0.0)
        placement = float(stats.get("TotemPlacementTime") or 0.0)
        duration_seconds = float(stats.get("TotemDuration") or duration)
        per_placement = float(context.get("totems_per_placement") or 1.0)
        placements = int((limit + per_placement - 1) // per_placement) if limit > 0 else 0
        placing = placements * placement
        left = max(0.0, float(ramp_seconds) - placing)
        share = max(0.0, (duration_seconds - placing) / duration_seconds) if duration_seconds > 0 else 0.0
        reachable = (limit * placement / per_placement <= float(ramp_seconds)) if limit > 0 and placement > 0 else True
        note = (f"{context.get('name', 'generator skill')}'s own PoB Speed {float(own_stats.get('Speed') or 0.0):.2f}/s after "
                f"{placements} placements x {placement:.3f} s leaves {left:.2f} s; "
                f"{share:.0%} of a {duration_seconds:.2f} s totem cycle is free"
                + ("; PoB does not expose totems per placement, using 1" if per_placement == 1.0 else ""))
        if not reachable:
            note += f"; the {limit:.0f}-totem limit cannot be reached inside the {ramp_seconds:g} s budget"
        return per_second * duration_seconds * share, per_second * left, note

    for s in sources:
        c, n, t = s["chance"], s["count"], s["trigger"]
        context = context_for(s)
        if s.get("needs"):
            ignored.append(f"{s['line']} (needs a {s['needs']} skill; none in the build)")
        elif context is not None and context.get("proxy"):
            ignored.append(f"{s['line']} ({context.get('name', 'generator skill')} is delivered by a proxy; the proxy cannot hold player charges)")
        elif proxy_main and context is None and t in {"hit", "crit", "kill", "periodic"} and not PROXY_SUBJECT.search(str(s["line"])):
            ignored.append(f"{s['line']} (the proxy main skill's {t} is not the player's)")
        elif t == "steal":
            ignored.append(f"{s['line']} (stealing: bosses carry no charges)")
        elif t == "kill":
            if kills_per_second > 0:
                rate += c * n * kills_per_second
                counted.append(f"{s['line']} x {kills_per_second:.2f} kills/s from adds")
                count_source(s)
            else:
                ignored.append(f"{s['line']} (no kills on a boss)")
        elif t == "block":
            if "retaliation" in gem_tags:
                full.append(f"{s['line']} (a retaliation skill: the build blocks or has no damage)")
                count_source(s)
            elif _THREE_ROLL_LUCKY.search(text):
                # Lucky block rolls three times: half value. Full value (a retaliation skill) holds the charge at its
                # maximum, i.e. kmax / duration charges per second; the half of that rate is fed on.
                half_rate = 0.5 * kmax / duration
                rate += half_rate
                half_held += half_rate * duration
                counted.append(f"{s['line']} at half value (Azadi Crest's three-roll lucky block, no retaliation skill): {half_rate:.3f}/s of the full {kmax / duration:.3f}/s")
                count_source(s)
            else:
                ignored.append(f"{s['line']} (block on a boss is not a source: many boss abilities are not blockable)")
        elif t == "crit":
            speed, hit_chance, crit_chance = generator_rate(context)
            contribution = c * n * speed * (hit_chance if context is not None else 1.0) * crit_chance
            if context is not None and not context.get("triggered") and proxy_main:
                delivery = main_tags or frozenset()
                if "totem" in delivery:
                    sustained_amount, budget_amount, note = hand_totem_amounts(context, contribution)
                    rate += contribution
                    timed_sustained_adjustment += sustained_amount - contribution * duration
                    timed_budget_adjustment += budget_amount - contribution * max(0.0, float(ramp_seconds))
                    counted.append(f"{s['line']} x {note} x {crit_chance:.0%} crit")
                    count_source(s)
                else:
                    ignored.append(f"{s['line']} (a hand-used generator has no time beside continuous {next(iter(delivery & {'mine', 'trap'}), 'proxy')} throws)")
            else:
                rate += contribution
                counted.append(f"{s['line']} x {speed:.2f} {'own ' if context is not None else ''}hits/s x {crit_chance:.0%} crit")
                count_source(s)
        elif t == "hit":
            speed, hit_chance, _crit_chance = generator_rate(context)
            contribution = c * n * speed * (hit_chance if context is not None else 1.0)
            if context is not None and not context.get("triggered") and proxy_main:
                delivery = main_tags or frozenset()
                if "totem" in delivery:
                    sustained_amount, budget_amount, note = hand_totem_amounts(context, contribution)
                    rate += contribution
                    # The normal rate path is replaced by this source's actual startup
                    # window and the usable share of a totem refresh cycle.
                    timed_sustained_adjustment += sustained_amount - contribution * duration
                    timed_budget_adjustment += budget_amount - contribution * max(0.0, float(ramp_seconds))
                    counted.append(f"{s['line']} x {note}")
                    count_source(s)
                else:
                    ignored.append(f"{s['line']} (a hand-used generator has no time beside continuous {next(iter(delivery & {'mine', 'trap'}), 'proxy')} throws)")
            else:
                rate += contribution
                own = f"{context.get('name', 'generator skill')}'s own " if context is not None else ""
                counted.append(f"{s['line']} x {own}Speed {speed:.2f}/s x {hit_chance:.0%} hit chance" if context is not None else f"{s['line']} x {speed:.2f} hits/s")
                count_source(s)
        elif t == "mine":
            if "mine" in (main_tags or frozenset()):
                fraction = float(assumptions["mine_detonation_fraction"])
                rate += c * n * hits * fraction
                counted.append(f"{s['line']} x {hits:.2f} mines/s x {fraction:.0%} detonated (one mine per throw; PoB per-throw count not read, conservative)")
                count_source(s)
            else:
                ignored.append(f"{s['line']} (the main skill is not a mine)")
        elif t == "trap":
            if "trap" in (main_tags or frozenset()):
                rate += c * n * hits
                counted.append(f"{s['line']} x {hits:.2f} traps/s (every thrown trap is triggered by the stationary boss)")
                count_source(s)
            else:
                ignored.append(f"{s['line']} (the main skill is not a trap)")
        elif t == "mana_spent" and s.get("threshold", 0.0) > 0:
            mana_per_second = float(stats.get("ManaPerSecondCost") or 0.0)
            if mana_per_second > 0:
                rate += n * mana_per_second / float(s["threshold"])
                counted.append(f"{s['line']} x {mana_per_second:.2f} mana/s / {s['threshold']:g} mana")
                count_source(s)
            else:
                ignored.append(f"{s['line']} (the build spends no mana)")
        elif t == "periodic" and s["period"]:
            rate += c * n / s["period"]
            counted.append(f"{s['line']}")
            count_source(s)
        elif t == "warcry":
            cooldown = float(s["cooldown"])
            gained = c * n
            contribution = gained / cooldown
            rate += contribution
            warcry_rate += contribution
            warcry_budget += gained * (1 + int(max(0.0, float(ramp_seconds)) // cooldown))
            warcry_sustained += gained * (1 + int(duration // cooldown))
            counted.append(f"{s['line']}: {s['power']:g} Warcry Power / {s['per_power']:g} per charge (PoB) = {gained:g} per use; {cooldown:.3f} s effective cooldown (PoB)")
            count_source(s)
        elif t == "when_hit":
            ignored.append(f"{s['line']} (needs the enemy's hit rate: pending fact enemy_hits_per_second)")
        elif t == "banner":
            full.append(f"{s['line']} (banner placement is the classified source)")
        else:
            ignored.append(f"{s['line']} (unclassified source: not counted)")
    if half_held and not full:
        held = min(int(half_held), int(kmax))
        if held >= 1:
            override = held if held < kmax - 1e-9 else None
            return True, f"{'; '.join(counted[:2])}: {held} of {int(kmax)} max held", override, rate
    if full:
        return True, "; ".join(full[:2] + ([f"and {len(full) - 2} more"] if len(full) > 2 else [])), None, rate
    # what the build holds: the sustained count, and never more than the ramp budget's seconds of gaining (D39: the
    # number is what the build reaches within the budget; a Smite seed spent its whole tree under a ramp relation the
    # charges alone violated, at 58k instead of 500k, before this cap)
    sustained = (rate - warcry_rate) * duration + warcry_sustained + timed_sustained_adjustment
    within_budget = (rate - warcry_rate) * max(0.0, float(ramp_seconds)) + warcry_budget + timed_budget_adjustment
    if sustained >= 1.0 and within_budget >= 1.0:
        held = min(sustained, within_budget, kmax)
        override = int(held) if held < kmax - 1e-9 else None
        why = f"{'; '.join(counted[:2])}: {sustained:.1f} sustained over a {duration:.0f} s charge, {within_budget:.1f} within the {ramp_seconds:g} s ramp budget ({int(held)} of {int(kmax)} max)" + (f"; the rest ignored: {'; '.join(ignored[:2])}" if ignored else "")
        return True, why, override, rate
    if sustained >= 1.0:
        why = f"off: {'; '.join(counted[:2])}: {sustained:.1f} sustained but only {within_budget:.2f} within the {ramp_seconds:g} s ramp budget" + (f"; ignored: {'; '.join(ignored[:2])}" if ignored else "")
        return False, why, None, rate
    why = f"off: {'; '.join(counted[:2]) if counted else 'no counted source'}: {sustained:.2f} sustained over a {duration:.0f} s charge" + (f"; ignored: {'; '.join(ignored[:2])}" if ignored else "")
    return False, why, None, rate


def conservative_generator_issue(var: str, stats: Mapping[str, Any], text: str, gem_tags: frozenset[str], main_tags: frozenset[str] | None = None,
                                  warcry_sources: Sequence[Mapping[str, Any]] = (), *, parsed: Mapping[str, Mapping[str, Any]] | None = None,
                                  option: Mapping[str, Any] | None = None, gem_names: Sequence[str] = (),
                                  source_contexts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                                  ramp_seconds: float = DEFAULT_RAMP_BUDGET_S) -> str | None:
    """Why an enabled charge/buff is not proven by the conservative rule."""

    if var in CHARGE_VARS:
        use, why, _override, _rate = charge_rule(var, stats, text, gem_tags, ramp_seconds=ramp_seconds, main_tags=main_tags, warcry_sources=warcry_sources, source_contexts=source_contexts)
        return None if use else why
    if var in BUFF_VARS:
        allowed, why = _conservative_allows(
            var,
            {},
            stats,
            text,
            gem_tags,
            main_tags=main_tags,
            parsed=parsed or {},
            option=option,
            gem_names=gem_names,
            ramp_seconds=ramp_seconds,
        )
        return None if allowed else why
    return None


@dataclass(slots=True)
class LaneConfig:
    inputs: dict[str, Any] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    # Exact build-text lines that hold each conservative input.  The pipeline
    # uses these to distinguish a tree's only proof from an item/gem or a
    # second passive carrying the same proof.
    proof_lines: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProofRecheck:
    """What one conservative input's own rule says when some build-text lines are masked out.

    `inputs` is what the conservative lane would then hold for that input and the companions
    the same rule writes (`{}` = the input goes off); None means the rule cannot be re-run
    without PoB, and the caller must fall back to the sole-proof test.
    """

    rule: str
    keys: tuple[str, ...]  # the config keys this rule writes for the var (the var itself first)
    inputs: dict[str, Any] | None


def _proof_rule_name(var: str) -> str:
    """Which derivation answers this conservative input, for the log."""

    if var in CHARGE_VARS:
        return "charge_rule"
    if var in BUFF_VARS:
        return "parsed_buff_proof"
    if var in ENABLER_GEM_INPUTS:
        return "enabler gem"
    return "_conservative_allows"


def mask_text(text: str, masked: Mapping[str, int] | Iterable[str]) -> str:
    """`text` without `masked` occurrences of each line.

    Counted, not set-wise: two allocated nodes carrying the same line are two proofs, and
    masking one node's copy must leave the other's standing.
    """

    budget = dict(masked) if isinstance(masked, Mapping) else {str(line).strip().lower(): 1 for line in masked}
    budget = {str(line).strip().lower(): int(n) for line, n in budget.items() if int(n) > 0}
    if not budget:
        return text
    kept: list[str] = []
    for raw in text.splitlines():
        key = raw.strip().lower()
        if budget.get(key, 0) > 0:
            budget[key] -= 1
            continue
        kept.append(raw)
    return "\n".join(kept)


@dataclass(slots=True)
class DerivedConfig:
    conservative: LaneConfig
    optimistic: LaneConfig
    shown: list[dict[str, Any]]
    choices: dict[str, list[str]] = field(default_factory=dict)  # list-type skill options for the pipeline to judge
    stack_caps: dict[str, tuple[int, float]] = field(default_factory=dict)  # stack-type skill options: var -> (the cap PoB enforces now, share of the number the stacks carry)
    charge_rates: dict[str, tuple[int, float]] = field(default_factory=dict)  # use<Kind>Charges the boss lane counts: var -> (charges held, gained per second)
    custom_mods: list[tuple[str, ...]] = field(default_factory=list)  # (mod line, block title) the conservative lane needs on top of PoB's own config (Pride's ramp, D62 amendment)
    ailment_stack_caps: dict[str, AilmentStacks] = field(default_factory=dict)  # uncapped PoB application rate and conservative whole stacks (D78)
    # Re-run one conservative input's own derivation with build-text lines masked out, over this
    # same derivation's evidence and with no PoB call. The pipeline asks it whether an allocated
    # node is a NECESSARY proof of an input (the input goes off, or its number falls, without the
    # node's lines) rather than its only one. None = the var was not derived from build text here.
    recheck: Callable[[str, Mapping[str, int] | Iterable[str]], ProofRecheck | None] | None = None


@lru_cache(maxsize=1)
def config_surfaces() -> dict[str, dict[str, Any]]:
    recs = json.loads(CORPUS.read_text(encoding="utf-8"))["records"]
    return {r["var"]: r for r in recs if isinstance(r.get("var"), str)}


def build_text(pob: PobSession, graph: TreeGraph | None = None, *, gem_level: int = 18) -> str:
    """All mod text the build owns: equipped items, allocated passives, gem names *and the
    text of what those gems grant*.

    The gems' own text is proof text (the user's reading 2026-09-18): only names reached the
    proofs, so Frenzy's "gives the character a frenzy charge if it hits" -- the skill's whole
    point -- was invisible and `useFrenzyCharges` stayed off on vd_spellslinger (Frenzy as the
    Spellslinger trigger) and burning_arrow_snipe (Manaforged Arrows + Frenzy). A triggered
    Frenzy still hits, so it still generates. The lines come from PoB's own skill data
    (`skill_facts.granted_effect_lines`, the source `skill_facts` already reads) at the rails'
    gem level, for every enabled gem of an enabled group that has an enabled active gem."""

    state = pob.read_state()
    parts: list[str] = []
    gear = state.get("gear_slots") or state.get("items_state") or {}
    slots = gear.get("slots") if isinstance(gear, dict) else None
    if isinstance(slots, dict):
        for slot in slots.values():
            item = slot.get("item") if isinstance(slot, dict) else None
            if isinstance(item, dict):
                for key in ("raw_item_text", "raw", "text"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
                for key in ("explicit_affixes", "implicit_affixes", "implicit_mods", "mods", "lines"):
                    val = item.get(key)
                    if isinstance(val, list):
                        parts.extend(str(v) for v in val)
    graph = graph or TreeGraph.load()
    for node_id in state.get("tree_state", {}).get("user_allocated_node_ids", []):
        node = graph.node(int(node_id))
        if node:
            parts.extend(node.stats)
    asc_stats = _ascendancy_node_stats()
    for node_id in state.get("tree_state", {}).get("allocated_ascendancy_node_ids", []) or []:
        parts.extend(asc_stats.get(int(node_id), ()))
    for effect in state.get("tree_state", {}).get("mastery_effect_ids", []):
        try:
            node_id, effect_id = (int(x) for x in str(effect).split(":"))
        except ValueError:
            continue
        node = graph.node(node_id)
        if node:
            for eid, stats in node.mastery_effects:
                if eid == effect_id:
                    parts.extend(stats)
    from junkroan.pob.skill_facts import granted_effect_lines

    records = _active_gem_records()
    skills = state.get("skills_state") or {}
    for group in _iter_groups(skills):
        if not isinstance(group, dict) or group.get("enabled") is False or not _group_has_active_gem(group):
            continue  # a group with no active gem grants nothing (a helmet holding only "Fortify"); a disabled group grants nothing at all
        for gem in group.get("gems", []):
            if not isinstance(gem, dict) or not gem.get("enabled", True):
                continue  # a disabled gem is in the build but not in play (guard skills, optimizer/buff_gems)
            name = str(gem.get("gem_name") or gem.get("name") or "")
            parts.append(name)
            rec = records.get(name.strip().lower())
            if rec and rec.get("grants_active_skill"):
                parts.extend(granted_effect_lines(str(rec.get("granted_effect_id") or ""), level=gem_level))
    return "\n".join(parts).lower()


@lru_cache(maxsize=1)
def _ascendancy_node_stats() -> dict[int, tuple[str, ...]]:
    """Ascendancy nodes are not in TreeGraph (not user-allocatable in the same sense); their text still counts as a source."""

    recs = json.loads((CORPUS.parent / "ascendancies.json").read_text(encoding="utf-8"))["records"]
    return {int(n["node_id"]): tuple(n.get("stats") or ()) for r in recs for n in (r.get("nodes") or []) if n.get("node_id") is not None}


def _iter_groups(skills: Any):
    if isinstance(skills, dict):
        for key in ("skill_sets", "socket_groups", "groups"):
            val = skills.get(key)
            if isinstance(val, list):
                for entry in val:
                    if isinstance(entry, dict) and "socket_groups" in entry:
                        yield from entry["socket_groups"]
                    else:
                        yield entry


def _numeric_rule(var: str, stats: Mapping[str, Any], text: str, gem_names: list[str], assumptions: Mapping[str, float], facts: BuildFacts | None = None) -> tuple[Any, str] | None:
    """From-scratch numeric inputs: a value only when PoB shows the input and the
    build proves the source. Values themselves come from the rails' assumptions,
    except the ramp-type counts, which are arithmetic (`ramp_inputs`, D62 amendment):
    what the build's own rates reach inside the ramp budget, capped by the skill."""

    if facts is not None:
        ramped = ramped_input(var, facts)
        if ramped is not None:
            return ramped
    a = {**NUMERIC_ASSUMPTION_DEFAULTS, **dict(assumptions or {})}
    lower = [g.lower() for g in gem_names]
    if var in ("configResonanceCount", "configUnholyResonanceCount"):
        elements = {k.split(".")[-1].replace("HitAverage", "") for k in ELEMENT_HIT_KEYS if isinstance(stats.get(k), (int, float)) and stats.get(k) > 0}
        if {"Fire", "Cold", "Lightning"} <= elements:
            return int(a["trinity_resonance_when_all_three_elements"]), "Trinity linked and hits carry fire, cold and lightning (PoB per-element hit averages)"
        return None, f"Trinity linked but hits carry only {sorted(elements) or 'no elements'}: resonance cannot build"
    if var == "multiplierRage":  # reached only without BuildFacts (tests): with them rage is `ramp_inputs.rage_stacks`
        mx = stats.get("MaximumRage")
        if isinstance(mx, (int, float)) and mx > 0:
            return int(mx * a["rage_fraction_of_max"]), f"PoB says the build can gain rage; {a['rage_fraction_of_max']:.0%} of maximum {mx:.0f} sustained (rails)"
        return None, "no rage source"
    if var == "multiplierChilledByYouSeconds":
        if isinstance(stats.get("ChillChance"), (int, float)) and stats["ChillChance"] >= 50:
            return int(a["chill_seconds_on_boss"]), "build chills reliably; sustained on a boss (rails)"
        return None, "build does not chill reliably"
    if var == "toxicRainPodOverlap":
        n = stats.get("ProjectileCount")
        if isinstance(n, (int, float)) and n > 0:
            pods = max(1, int(round(n * a["toxic_rain_pods_fraction_of_projectiles"])))
            return pods, f"{pods} of {int(n)} pods overlap on a stationary boss (rails; PoB: maximum is the projectile count)"
        return None, "no projectile count"
    if var == "configSnipeStages":
        if "snipe" in lower:
            return int(a["snipe_stages"]), "Snipe linked: channelled to full stages before release (rails)"
        return None, "no Snipe"
    if var == "multiplierMineDetonatedRecently":
        # throughput PoB cannot derive alone (ROADMAP 7.2, D57 rule 3): "recently" is a 4 s window, and a mine
        # build throws PoB's Speed mines per second (laying speed x mines per throw: Pyroclast 1.909 x 5 = 9.54,
        # Exsanguinate mines 10.57, measured 2026-09-16); the mods cap their own "up to" inside PoB
        tags = _active_gem_tags()
        is_mine = any("mine" in tags.get(g, set()) for g in gem_names) or any(g in ("blastchain mine", "high-impact mine") for g in lower)
        speed = stats.get("Speed")
        if is_mine and isinstance(speed, (int, float)) and speed > 0:
            n = max(1, int(round(a["mine_detonation_window_seconds"] * float(speed) * a["mine_detonation_fraction"])))
            return n, f"{speed:.2f} mines per second (PoB) x {a['mine_detonation_window_seconds']:g} s window x {a['mine_detonation_fraction']:.0%} detonated (rails)"
        return None, "no mine skill or no throw rate"
    if var == "multiplierNonInstantSpellCastRecently":
        n = _non_instant_spell_count(gem_names)
        return (n, f"{n} castable non-instant spell gems in the build") if n else (None, "no castable spells")
    return None


@lru_cache(maxsize=1)
def _active_gem_records() -> dict[str, dict]:
    """The active-gem corpus keyed by lower-case name (granted_effect_id, tag_keys)."""

    from junkroan.search.hypothesis import active_gems

    return active_gems()


@lru_cache(maxsize=1)
def _active_gem_tags() -> dict[str, set[str]]:
    recs = json.loads((CORPUS.parent / "active_gems.json").read_text(encoding="utf-8"))["records"]
    return {r["name"]: set(r.get("tag_keys") or []) for r in recs}


def _skill_use_ending_buff_sources(var: str, gem_names: Sequence[str]):
    """Enabled gems whose listed buff cannot coexist with using the main skill."""

    from junkroan.mechanics.skill_use_ending_buffs import sources_for_input

    records = _active_gem_records()
    effect_ids = [
        str((records.get(name.strip().lower()) or {}).get("granted_effect_id") or "")
        for name in gem_names
    ]
    return sources_for_input((effect_id for effect_id in effect_ids if effect_id), var)


def _skill_use_ending_buff_lines(var: str, gem_names: Sequence[str]) -> frozenset[str]:
    """PoB parser candidates granted by a source that ends when the main skill is used."""

    from junkroan.pob.skill_facts import granted_effect_lines

    return frozenset(
        line.lower()
        for fact in _skill_use_ending_buff_sources(var, gem_names)
        for line in granted_effect_lines(fact.effect_id, level=18)
    )


@lru_cache(maxsize=1)
def _support_gem_tags() -> dict[str, set[str]]:
    from junkroan.search.hypothesis import support_gems

    return {name: set(record.get("tag_keys") or []) for name, record in support_gems().items()}


def _gem_tags(gem_names: Sequence[str]) -> frozenset[str]:
    """Tags of every enabled gem, including delivery supports for generator needs."""

    active = _active_gem_tags()
    support = _support_gem_tags()
    return frozenset(tag for name in gem_names for tag in (active.get(name, ()) or support.get(name.lower(), ())))


def _non_instant_spell_count(gem_names: list[str]) -> int:
    tags = _active_gem_tags()
    out = 0
    for name in gem_names:
        t = tags.get(name)
        if not t or "spell" not in t:
            continue
        if t & {"aura", "herald", "banner", "trigger", "minion", "golem", "mark", "curse", "hex", "warcry", "guard", "instant"}:
            continue
        out += 1
    return out


def _main_skill_name(pob: PobSession) -> str | None:
    """The active gem selected as the main skill in PoB's main socket group."""

    state = pob.read_state()
    skills = state.get("skills_state") or {}
    main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    groups = list(_iter_groups(skills))
    group = next((g for g in groups if isinstance(g, dict) and main_id and g.get("socket_group_id") == main_id), groups[0] if groups else None)
    if not isinstance(group, dict):
        return None
    main_active_id = group.get("main_active_skill_id") or skills.get("main_active_skill_id")
    main_entry = next((entry for entry in group.get("active_skill_entries") or [] if isinstance(entry, dict) and entry.get("active_skill_id") == main_active_id), None)
    if isinstance(main_entry, dict) and main_entry.get("name"):
        return str(main_entry["name"])
    for gem in group.get("gems", []):
        if isinstance(gem, dict) and not gem.get("is_support") and gem.get("enabled", True):
            return str(gem.get("gem_name") or gem.get("name") or "")
    return None


def _main_skill_tags(pob: PobSession, main_skill: str | None) -> frozenset[str]:
    """Tags of the main skill after delivery supports are applied."""

    tags = set(_active_gem_tags().get(main_skill or "", ()))
    state = pob.read_state()
    skills = state.get("skills_state") or {}
    main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    groups = list(_iter_groups(skills))
    group = next((g for g in groups if isinstance(g, dict) and main_id and g.get("socket_group_id") == main_id), groups[0] if groups else None)
    if isinstance(group, dict):
        for gem in group.get("gems", []):
            if not isinstance(gem, dict) or not gem.get("enabled", True) or not gem.get("is_support"):
                continue
            name = str(gem.get("gem_name") or gem.get("name") or "").strip().lower()
            tags.update(_support_gem_tags().get(name, ()))
    return frozenset(tags)


@lru_cache(maxsize=1)
def _active_gem_names() -> frozenset[str]:
    from junkroan.search.hypothesis import active_gems

    return frozenset(active_gems())  # keyed by lower-case name


def _group_has_active_gem(group: Mapping[str, Any]) -> bool:
    """A socket group proves nothing unless an enabled active gem is in it: a support gem
    alone is not granted to anything. A helmet holding only "Fortify" put Fortification on
    in both lanes (PoB: FortificationStacks 20) until this (the user's reading 2026-09-16)."""

    actives = _active_gem_names()
    for gem in group.get("gems", []) or []:
        if not isinstance(gem, dict) or not gem.get("enabled", True):
            continue
        if str(gem.get("gem_name") or gem.get("name") or "").strip().lower() in actives:
            return True
    return False


def _item_grants_triggered_skill(state: Mapping[str, Any], group: Mapping[str, Any], name: str) -> bool:
    """Whether this item socket group grants its named skill through a Trigger line."""

    if group.get("source_kind") != "item" or not (slot_name := group.get("slot")):
        return False
    gear = state.get("gear_slots") or state.get("items_state") or {}
    slots = gear.get("slots") if isinstance(gear, Mapping) else None
    slot = slots.get(str(slot_name)) if isinstance(slots, Mapping) else None
    item = slot.get("item") if isinstance(slot, Mapping) else None
    if not isinstance(item, Mapping):
        return False
    name_pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    lines: list[str] = []
    for key in ("raw_item_text", "raw", "text"):
        if isinstance(item.get(key), str):
            lines.extend(str(item[key]).splitlines())
    for key in ("explicit_affixes", "implicit_affixes", "implicit_mods", "mods", "lines"):
        if isinstance(item.get(key), list):
            lines.extend(str(line) for line in item[key])
    return any(re.match(r"\s*trigger\b", line, re.IGNORECASE) and name_pattern.search(line) for line in lines)


def _gem_names(pob: PobSession) -> list[str]:
    names: list[str] = []
    for group in _iter_groups(pob.read_state().get("skills_state") or {}):
        if not isinstance(group, dict) or group.get("enabled") is False or not _group_has_active_gem(group):
            continue
        for gem in group.get("gems", []):
            if isinstance(gem, dict) and gem.get("enabled", True):
                names.append(str(gem.get("gem_name") or gem.get("name") or ""))
    return list(dict.fromkeys(n for n in names if n))  # both skill sets are enumerated; keep each gem once


def generator_source_contexts(pob: PobSession, main_tags: frozenset[str]) -> dict[str, list[dict[str, Any]]]:
    """Per-active-gem delivery and PoB rates for charge lines in their own text.

    A generated line in a gem is not a property of the main skill.  This keeps
    Frenzy's own attack rate separate from a Ballista's firing rate and records
    whether that particular link is delivered by a proxy.
    """

    if not (main_tags & PROXY_DELIVERY_TAGS) or not hasattr(pob, "active_skill_stats"):
        return {}
    from junkroan.pob.skill_facts import granted_effect_lines

    state = pob.read_state()
    records = _active_gem_records()
    active = _active_gem_tags()
    support = _support_gem_tags()
    rows: list[tuple[str, dict[str, Any]]] = []
    effects: list[str] = []
    seen_groups: set[str] = set()
    for group in _iter_groups(state.get("skills_state") or {}):
        if not isinstance(group, dict) or group.get("enabled") is False or not _group_has_active_gem(group):
            continue
        group_id = str(group.get("socket_group_id") or "")
        if group_id and group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        entries = [entry for entry in group.get("gems", ()) if isinstance(entry, dict) and entry.get("enabled", True)]
        link_tags = {
            tag for entry in entries
            for tag in (support.get(str(entry.get("gem_name") or entry.get("name") or "").strip().lower(), ()) if entry.get("is_support") else ())
        }
        triggered = "trigger" in link_tags or any(bool(entry.get("triggered")) for entry in group.get("active_skill_entries") or ())
        for entry in entries:
            if entry.get("is_support"):
                continue
            name = str(entry.get("gem_name") or entry.get("name") or "").strip()
            record = records.get(name.lower())
            if not record or not record.get("grants_active_skill"):
                continue
            effect = str(entry.get("skill_id") or record.get("granted_effect_id") or "")
            if not effect:
                continue
            level = entry.get("level")
            context = {
                "name": name,
                "effect": effect,
                "proxy": bool((link_tags | set(active.get(name, ()))) & PROXY_DELIVERY_TAGS),
                "triggered": triggered,
                # PoB does not expose the per-placement count in the skill output.
                "totems_per_placement": 1.0,
            }
            charge_lines = [
                line.lower()
                for line in granted_effect_lines(effect, level=int(level) if isinstance(level, (int, float)) else 18)
                if "charge" in line.lower() and re.search(_GRANT_VERB, line, re.IGNORECASE)
            ]
            if charge_lines:
                rows.extend((line, context) for line in charge_lines)
                effects.append(effect)
    if not rows:
        return {}
    values = pob.active_skill_stats(tuple(dict.fromkeys(effects)), ("Speed", "HitSpeed", "HitChance", "CritChance"))
    out: dict[str, list[dict[str, Any]]] = {}
    for line, context in rows:
        out.setdefault(line, []).append({**context, "stats": values.get(context["effect"], {})})
    return out


@lru_cache(maxsize=1)
def _effect_ids() -> dict[str, str]:
    """Active gem name (lower case) -> PoB granted effect id ("wither" -> "Wither")."""

    recs = json.loads((CORPUS.parent / "active_gems.json").read_text(encoding="utf-8"))["records"]
    return {str(r["name"]).lower(): str(r.get("granted_effect_id") or "") for r in recs if r.get("name")}


def build_facts(pob: PobSession, stats: Mapping[str, Any], budget: float, inputs: Mapping[str, Any], text: str = "", assumptions: Mapping[str, float] | None = None) -> BuildFacts:
    """What the ramp arithmetic needs about this build: PoB's numbers, its gems with their levels
    and the supports beside them, whether the main skill is triggered (it does not share the
    player's casting time), and the stance the lane holds."""

    state = pob.read_state()
    skills = state.get("skills_state") or {}
    ids = _effect_ids()
    gems: list[Gem] = []
    triggered = False
    main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    for group in _iter_groups(skills):
        if not isinstance(group, dict) or group.get("enabled") is False or not _group_has_active_gem(group):
            continue
        entries = [g for g in group.get("gems", []) or [] if isinstance(g, dict) and g.get("enabled", True)]
        supports = tuple(str(g.get("gem_name") or g.get("name") or "").lower() for g in entries if g.get("is_support"))
        autoexertion_present = any(str(g.get("gem_name") or g.get("name") or "").strip().lower() == "autoexertion" for g in entries)
        triggered_names = {
            str(entry.get("name") or "").strip().lower()
            for entry in group.get("active_skill_entries") or []
            if isinstance(entry, dict) and entry.get("triggered")
        }
        if (not main_id or group.get("socket_group_id") == main_id) and any(e.get("triggered") for e in group.get("active_skill_entries") or []):
            triggered = True
        for gem in entries:
            name = str(gem.get("gem_name") or gem.get("name") or "").lower()
            effect = str(gem.get("skill_id") or ids.get(name) or "")
            level = gem.get("level")
            gems.append(Gem(
                name=name,
                effect_id=effect,
                level=int(level) if isinstance(level, (int, float)) else 20,
                supports=supports,
                gem_id=str(gem.get("gem_id")) if gem.get("gem_id") else None,
                triggered=bool(gem.get("triggered") or name in triggered_names or _item_grants_triggered_skill(state, group, name)),
                autoexerted=autoexertion_present,
            ))
    main_name = (_main_skill_name(pob) or "").lower()
    main_effect = ids.get(main_name) or next((g.effect_id for g in gems if g.name == main_name), "")
    return BuildFacts(stats=stats, budget=budget, gems=tuple(gems), main_effect_id=main_effect, text=text, triggered=triggered,
                      stance=str(inputs.get("bloodSandStance") or ""), extra={**NUMERIC_ASSUMPTION_DEFAULTS, **dict(assumptions or {})})


def is_stack_option(rec: Mapping[str, Any]) -> bool:
    """A count-type Skill Option whose label names a stack the skill builds (intensity, stages, stacks)."""

    if rec.get("type") not in ("count", "countAllowZero", "integer") or rec.get("section") != "Skill Options":
        return False
    if rec.get("var") in STACK_OPTION_PRESET_ADMITTED:
        return True
    label = _POB_COLOR.sub("", str(rec.get("label") or ""))
    return bool(STACK_OPTION_LABEL.search(label)) and not STACK_OPTION_PRESET.search(label)


def judge_stack_options(pob: PobSession, pending: list[Mapping[str, Any]], *, ceiling: int, boss: str = "Pinnacle") -> dict[str, tuple[int | None, str, int | None, float]]:
    """PoB judges each stack-type option: the input is set to the rails ceiling and kept only
    when PoB caps it below (the number stops rising before the ceiling; Spark with Pinpoint:
    3 intensity, 4 with the mastery). The kept input is the ceiling itself, so tree and gear
    that raise the cap are credited in every later trial; an option PoB does not cap is an
    assumption about the fight and stays off. Returns var -> (value, reason, cap now, share):
    share = 1 - number at 0 stacks / number at the cap, what the stacks carry (the ramp rail
    scales only that part while the stacks build, D39)."""

    if not pending:
        return {}
    keys = ("CombinedDPS", "FullDPS")
    snapshot = pob.export_xml()
    # The judgement is 9 config writes and 9 recalcs per option (value(0), value(ceiling),
    # value(ceiling-1) and six bisection steps), and `derive_config` asks for it again on every call
    # -- with prefer_rules=True a stack option can never take the "kept from the build's config"
    # shortcut, so the pipeline re-ran the whole search ~19 s per derivation on Spark, the slowest
    # core14 reference. The key is the build's own export: `value()` sets one input on this build and
    # reads PoB's numbers, so two builds with the same XML (and the same option set, ceiling and boss)
    # cannot give different probes. Identical XML means an identical build; a cosmetic difference only
    # costs a recomputation, never a wrong answer (7.1h).
    cache_key = (hashlib.blake2b(snapshot.encode("utf-8"), digest_size=16).hexdigest(),
                 tuple(sorted(str(o["var"]) for o in pending)), int(ceiling), str(boss))
    cached = _STACK_JUDGEMENTS.get(cache_key)
    if cached is not None:
        _STACK_JUDGEMENTS.move_to_end(cache_key)
        return dict(cached)
    state = pob.read_state().get("config_state") or {}
    ident = dict(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None", pantheon_minor=state.get("pantheon_minor") or "None", enemy_state={"is_boss": boss}, preserve="all")

    def value(var: str, n: int) -> tuple[float, ...]:
        pob.set_config(inputs={var: n}, **ident)
        s = pob.stats(keys)
        return tuple(round(float(s.get(k) or 0.0), 2) for k in keys)

    out: dict[str, tuple[int | None, str, int | None, float]] = {}
    # #540: a session puts its config state back in place (checkpoint / rollback in the worker); a stand-in
    # without the pair, or JUNKROAN_STACK_RESTORE_BY_RELOAD=1 (the diag's base side), keeps the reload.
    in_place = (not os.environ.get("JUNKROAN_STACK_RESTORE_BY_RELOAD") and callable(getattr(pob, "config_checkpoint", None))
                and callable(getattr(pob, "config_rollback", None)))
    if in_place:
        pob.config_checkpoint()
    try:
        for opt in pending:
            var = str(opt["var"])
            label = _POB_COLOR.sub("", str(opt.get("label") or var)).strip(": ")
            v0, v_top, v_below = value(var, 0), value(var, ceiling), value(var, ceiling - 1)
            if v_top == v0:
                out[var] = (None, f"off: {label} has no effect on the numbers", None, 0.0)
            elif v_top != v_below:
                out[var] = (None, f"off: PoB does not cap {label} within {ceiling}; an assumption about the fight, not a state the skill builds", None, 0.0)
            else:
                lo, hi = 0, ceiling - 1  # the smallest n PoB caps at: value(n) == value(ceiling)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if value(var, mid) == v_top:
                        hi = mid
                    else:
                        lo = mid + 1
                top = max(v_top)
                share = max(0.0, min(1.0, 1.0 - max(v0) / top)) if top > 0 else 0.0
                out[var] = (ceiling, f"{label}: held at the cap PoB enforces ({lo} now, {share:.0%} of the number; the input {ceiling} is capped by PoB, so a tree or item raising the cap counts); a state built by using the skill (D36), the ramp rail judges the time", lo, share)
    finally:
        if in_place:
            pob.config_rollback()
        else:
            pob.load_xml(snapshot)
    _STACK_JUDGEMENTS[cache_key] = dict(out)
    while len(_STACK_JUDGEMENTS) > _STACK_JUDGEMENTS_MAX:
        _STACK_JUDGEMENTS.popitem(last=False)
    return out


def uncapped_ailment_stats(pob: Any, stats: dict[str, Any]) -> dict[str, Any]:
    """The build's stats without D78's ailment-stack surfaces; ``stats`` itself when it holds none.

    A session reads it in place (`PobSession.stats_without_ailment_caps`: the surfaces lifted out of
    the live Baseline config set and put back). A stand-in without that call keeps the reference
    path, `uncapped_ailment_stats_by_reload`, the one the in-place read is proven equal to.
    """

    reader = getattr(pob, "stats_without_ailment_caps", None)
    if callable(reader):
        uncapped = reader()
        return stats if uncapped is None else uncapped
    return uncapped_ailment_stats_by_reload(pob, stats)


def uncapped_ailment_stats_by_reload(pob: Any, stats: dict[str, Any]) -> dict[str, Any]:
    """The pre-#508 path: export, strip the surfaces from the XML, load it, read, load the snapshot back
    (two whole-build loads per read, ~1.7 s of ~3.1 s per `read_lanes`)."""

    if hasattr(pob, "export_xml") and hasattr(pob, "load_xml"):
        snapshot = pob.export_xml()
        uncapped_xml = uncapped_ailment_stack_xml(snapshot)
        if uncapped_xml != snapshot:
            try:
                pob.load_xml(uncapped_xml)
                return pob.stats()
            finally:
                pob.load_xml(snapshot)
    return stats


def derive_config(pob: PobSession, *, boss: str = "Pinnacle", graph: TreeGraph | None = None, assumptions: Mapping[str, float] | None = None,
                  prefer_rules: bool = False, cap_ailment_stacks: bool = True) -> DerivedConfig:
    """prefer_rules: a numeric or list input the rules can derive is derived again even
    when the build already carries a value. The pipeline's own config is never authored,
    so a value it wrote at the bare-rig stage must not freeze: Poison Spectral Throw's
    "# of poison on enemy" was PoB's estimate of 4 stacks on the rig, kept "from the
    build's config" through every later lane while PoB's estimate had grown to 19 (The
    Wasp Nest's added chaos needs 5), 26% of the finished number. False keeps an
    existing build's own numbers (D26), for reading a build as it is."""

    surfaces = config_surfaces()
    predicates = {var: rec.get("predicates") or {} for var, rec in surfaces.items()}
    try:
        options = pob.config_options(predicates, condition_flag_vars=tuple(BUFF_VARS))
    except TypeError:  # small test fakes before config-options exposed parser flags
        options = pob.config_options(predicates)
    shown = [o for o in options if o.get("shown")]
    stats = pob.stats()
    stats.update({k: v for k, v in pob.stats(ELEMENT_HIT_KEYS).items()})
    text = build_text(pob, graph)
    if hasattr(pob, "calc_raw"):
        flask_kills, _flask_notes = flask_add_kills_per_second(pob, text)
        if flask_kills > 0:
            stats[ADD_KILLS_STAT] = flask_kills
    gem_names = _gem_names(pob)
    gem_tags = _gem_tags(gem_names)
    main_skill = _main_skill_name(pob)
    main_tags = _main_skill_tags(pob, main_skill)
    source_contexts = generator_source_contexts(pob, main_tags)
    parsed = parse_mods_batch(pob, buff_candidate_lines(text)) if callable(getattr(pob, "parse_mods", None)) else {}
    aux_gem_tags = frozenset(
        t for n in gem_names if n != main_skill
        for t in _active_gem_tags().get(n, ())
        if "grants_active_skill" in _active_gem_tags().get(n, ()) and not (_active_gem_tags().get(n, set()) & AUX_SKILL_EXCLUDED_TAGS)
    )
    if assumptions is None:
        from junkroan.optimizer.rails import Rails

        assumptions = Rails.load().assumptions
    ramp_seconds = float(dict(assumptions).get("ramp_seconds", DEFAULT_RAMP_BUDGET_S))

    optimistic, conservative = LaneConfig(), LaneConfig()
    for lane in (optimistic, conservative):
        lane.inputs["enemyIsBoss"] = boss
        lane.reasons["enemyIsBoss"] = "rails boss target"

    existing = pob.config_inputs()
    facts = build_facts(pob, stats, ramp_seconds, existing, text, assumptions)
    warcry_effects = warcry_charge_effect_ids(facts.gems)
    warcry_stats = pob.active_skill_stats(warcry_effects, ("Cooldown", "WarcryPower")) if warcry_effects and hasattr(pob, "active_skill_stats") else {}
    warcry_proven, _warcry_proof = warcry_usage_proof(facts.gems)
    warcry_sources = warcry_charge_sources(facts.gems, warcry_stats, usage_proven=warcry_proven)
    corpse = corpse_cycle(facts.gems)  # (creator, consumer): what the corpse conditions and their count stand on
    custom_mods: list[tuple[str, ...]] = []
    # A previous conservative lane may already contain the native bleed/ignite
    # cap, `multiplierBleedsOnEnemy`, or the poison modifier. Read the build
    # once without only those D78 surfaces so a new tree/gear rate is measured
    # from PoB's steady state rather than from the old cap.
    uncapped_stats = uncapped_ailment_stats(pob, stats)
    ailment_stack_caps = ailment_stacks(uncapped_stats, facts.budget) if cap_ailment_stacks else {}
    choices: dict[str, list[str]] = {}
    pending_stacks: list[Mapping[str, Any]] = []
    charge_rates: dict[str, tuple[int, float]] = {}  # use<Kind>Charges -> (charges held, gained per second): the ramp's business
    check_options: dict[str, Mapping[str, Any]] = {}  # the check-type inputs `_conservative_allows` answered: the only re-runnable rules
    for opt in shown:
        var = opt["var"]
        rec = surfaces.get(var, {})
        kind = rec.get("type")
        if kind in ("count", "countAllowZero", "integer", "float"):
            if var in AILMENT_STACK_OVERRIDES:
                continue  # written below from the unmodified stack rate; never inherited into the optimistic lane
            # numeric inputs: keep what the build already has; otherwise use PoB's own
            # estimate where one exists (poison stacks from duration x rate).
            has_own = var in existing and not isinstance(existing[var], bool)
            if has_own and not prefer_rules:
                for lane in (conservative, optimistic):
                    lane.inputs[var] = existing[var]
                    lane.reasons[var] = "kept from the build's config"
            elif var == "multiplierPoisonOnEnemy" and isinstance(stats.get("PoisonStacks"), (int, float)) and stats["PoisonStacks"] > 0:
                for lane in (conservative, optimistic):
                    lane.inputs[var] = int(stats["PoisonStacks"])
                    lane.reasons[var] = f"PoB estimates {stats['PoisonStacks']:.1f} sustained poison stacks"
            else:
                rule = _numeric_rule(var, stats, text, gem_names, assumptions, facts)
                if rule is not None:
                    # a ramp-type count: the conservative lane holds what the build reaches inside the
                    # budget, the optimistic lane the cap (D62 amendment); everything else is the same number
                    upper = ramped_input(var, facts, optimistic=True) or rule
                    for lane, (value, why) in ((conservative, rule), (optimistic, upper)):
                        if value is not None:
                            lane.inputs[var] = value
                            lane.reasons[var] = why
                        else:
                            lane.reasons[var] = f"off: {why}"
                elif is_stack_option({**rec, "var": var}):
                    pending_stacks.append({**rec, "var": var})
                elif has_own:  # no rule for it: the build's own number is all there is
                    for lane in (conservative, optimistic):
                        lane.inputs[var] = existing[var]
                        lane.reasons[var] = "kept from the build's config (no rule derives it)"
            continue
        if kind == "list" and rec.get("section") == "Skill Options" and rec.get("list_values"):
            values = [str(v.get("value")) for v in rec["list_values"] if v.get("value") is not None]
            if var in existing and not isinstance(existing[var], bool) and not (prefer_rules and values):
                for lane in (conservative, optimistic):
                    lane.inputs[var] = existing[var]
                    lane.reasons[var] = "kept from the build's config"
                continue
            # a list choice whose maximum is itself a ramp is not a free choice: the conservative lane
            # takes PoB's minimum and adds the part of the ramp the build reaches inside the budget
            # as a custom modifier (D62 amendment); the optimistic lane keeps the maximum
            ramp_mod = pride_ramp_mod(facts) if var == "prideEffect" else None
            if ramp_mod is not None:
                line, title, why = ramp_mod
                conservative.inputs[var], optimistic.inputs[var] = "MIN", "MAX"
                conservative.reasons[var] = optimistic.reasons[var] = why
                custom_mods.append((line, title))
            elif values:
                choices[var] = values  # the pipeline lets PoB pick (stance, exposure type ...)
            continue
        if kind not in ("check",) or var in NEVER_A_LANE_INPUT:
            continue
        if var in FIGHT_FACTS:  # a fact of the fight: true in both lanes, no proof to look for
            for lane in (optimistic, conservative):
                lane.inputs[var] = True
                lane.reasons[var] = FIGHT_FACTS[var]
            continue
        preds = rec.get("predicates") or {}
        refs = ", ".join(f"{r['kind']}:{r['key']} <- {', '.join(r['sources'][:3])}" for r in opt.get("refs", [])) or "shown by PoB"

        # optimistic: everything the build references is on
        optimistic.inputs[var] = True
        optimistic.reasons[var] = refs

        # conservative: needs a generator / proof
        check_options[var] = opt
        proof_lines: list[str] = []
        ok, why = _conservative_allows(
            var,
            preds,
            stats,
            text,
            gem_tags,
            aux_gem_tags,
            main_tags,
            corpse=corpse,
            warcry_sources=warcry_sources,
            source_contexts=source_contexts,
            parsed=parsed,
            option=opt,
            gem_names=gem_names,
            proof_lines=proof_lines,
            ramp_seconds=ramp_seconds,
        )
        if ok:
            conservative.inputs[var] = True
            conservative.reasons[var] = f"{why}; {refs}"
            if proof_lines:
                conservative.proof_lines[var] = tuple(proof_lines)
        else:
            conservative.reasons[var] = f"off: {why}"
    # #702: the Shock, Chill, Scorch, Brittle and Sap the build's own hits earn are typed from PoB's hit numbers (PoB writes none of them)
    from junkroan.optimizer.trace import TRACE as _TRACE

    for own in own_hit_ailments(pob, stats, boss=boss, ramp_seconds=ramp_seconds):
        if not own.applies:
            continue
        checkbox, effect_var, _kind, _k = OWN_HIT_AILMENTS[own.ailment]
        kept = effect_var in existing and not isinstance(existing[effect_var], bool) and not prefer_rules
        for lane in (conservative, optimistic):
            if lane.inputs.get(checkbox) is not True:
                lane.inputs[checkbox] = True
                lane.reasons[checkbox] = own.why
            elif own.why not in lane.reasons.get(checkbox, ""):
                lane.reasons[checkbox] = f"{own.why}; {lane.reasons.get(checkbox, '')}".rstrip("; ")
            if kept:
                lane.inputs[effect_var] = existing[effect_var]
                lane.reasons[effect_var] = "kept from the build's config"
            else:
                lane.inputs[effect_var] = own.typed
                lane.reasons[effect_var] = own.why
        if not kept:
            _TRACE.add_generated([effect_var])
    # The native overrides take whole stack counts. Only write an override when
    # the budget is shorter than the build's own steady-state stack time; an
    # unstacking ignite/bleed is left byte-for-byte as PoB already models it.
    for name, var in (("bleed", "overrideBleedStackPotential"), ("ignite", "overrideIgniteStackPotential")):
        stack = ailment_stack_caps.get(name)
        condition = "conditionEnemyBleeding" if name == "bleed" else "conditionEnemyIgnited"
        evidence = _ailment_evidence("Bleeding" if name == "bleed" else "Ignited", uncapped_stats)
        if stack is None or not stack.limited or evidence is None or not evidence[0]:
            continue
        # `ifOption: conditionEnemyBleeding` hides the native override until
        # this same condition is on. The PoB-stat evidence is the conservative
        # proof, so write both in the one lane derivation rather than waiting a
        # pass for the UI predicate to expose it.
        optimistic.inputs[condition] = True
        optimistic.reasons[condition] = evidence[1]
        conservative.inputs[condition] = True
        conservative.reasons[condition] = evidence[1]
        conservative.inputs[var] = stack.counted
        conservative.reasons[var] = (f"{name}: {stack.counted} of {stack.steady:.2f} steady stacks inside {facts.budget:g} s "
                                     f"({stack.rate:.2f} applied/s, {min(facts.budget, stack.duration):g} s before expiry); PoB stack-potential override")
        if name == "bleed":
            conservative.inputs["multiplierBleedsOnEnemy"] = stack.counted
            conservative.reasons["multiplierBleedsOnEnemy"] = f"{conservative.reasons[var]}; PoB effective-DPS bleed count"
    # #610: an overleech source (leech not removed at full Life / Energy Shield, read from PoB's parser data) means the
    # build is leeching all fight, so "while Leeching" effects are on; the proof names the source line
    from junkroan.optimizer.overleech import count_overleech, overleech_leeching, overleech_sources_in

    leech_on, leech_why = overleech_leeching(text, stats)
    was_set = leech_on and conservative.inputs.get("conditionLeeching") is not True
    if leech_on:
        for lane in (conservative, optimistic):
            lane.inputs["conditionLeeching"] = True
        conservative.reasons["conditionLeeching"] = f"{leech_why}; {conservative.reasons.get('conditionLeeching', '')}".rstrip("; ")
        optimistic.reasons.setdefault("conditionLeeching", leech_why)
        conservative.proof_lines["conditionLeeching"] = (*conservative.proof_lines.get("conditionLeeching", ()), *(line for line, _flag in overleech_sources_in(text)))
    count_overleech(
        bool(overleech_sources_in(text)) and any(isinstance(stats.get(k), (int, float)) and stats[k] > 0 for k in ("LifeLeechGainRate", "ManaLeechGainRate", "EnergyShieldLeechGainRate")),
        conservative.inputs.get("conditionLeeching") is True,
        was_set,
    )
    held = conservative.inputs.get("overrideCruelty", existing.get("overrideCruelty"))
    cruelty = cruelty_excess_mod(facts, float(held) if isinstance(held, (int, float)) and not isinstance(held, bool) else None)
    if cruelty is not None:  # PoB clamps overrideCruelty at 40: the mastery's excess is a custom mod (#400)
        custom_mods.append(cruelty)
        conservative.reasons["overrideCruelty"] = cruelty[2]
    poison = ailment_stack_caps.get("poison")
    if poison is not None and (mod := poison_stack_limit_mod(counted=poison.counted, steady=poison.steady, budget=facts.budget)) is not None:
        line, title, why = mod
        custom_mods.append((line, title))
        conservative.reasons["poisonRampStacks"] = why
        held = conservative.inputs.get("multiplierPoisonOnEnemy")
        if isinstance(held, (int, float)) and not isinstance(held, bool):
            conservative.inputs["multiplierPoisonOnEnemy"] = min(int(held), poison.counted)
            conservative.reasons["multiplierPoisonOnEnemy"] = f"{why}; PoB effective-DPS poison count capped at {poison.counted}"
    # charges the boss lane counts: a partial count goes to PoB's own "# of charges (if not maximum)", and the
    # gain rate to the ramp (charges build one at a time at chance x rate per second)
    for var in CHARGE_VARS:
        if conservative.inputs.get(var) is True:
            use, _why, override, rate = charge_rule(var, stats, text, gem_tags, ramp_seconds=ramp_seconds, main_tags=main_tags, warcry_sources=warcry_sources, source_contexts=source_contexts)
            override_var = var.replace("use", "override", 1)
            if override is not None and override_var in surfaces:
                conservative.inputs[override_var] = override
                conservative.reasons[override_var] = f"sustained charges below the maximum ({override})"
            if rate > 0:
                kmax = stats.get(f"{CHARGE_KIND[var]}ChargesMax")
                charge_rates[var] = (int(override or (kmax if isinstance(kmax, (int, float)) else 3)), rate)
    # the count of corpses consumed and the condition that one was are one fact: a corpse the boss
    # lane does not grant cannot be counted either, whichever way the number arrived (the author's
    # own config is otherwise "kept from the build's config" with no proof at all)
    consumed_ok, consumed_why = _corpse_cycle_allows("ConsumedCorpseRecently", corpse)
    if not consumed_ok and CORPSE_COUNT_VAR in conservative.inputs:
        del conservative.inputs[CORPSE_COUNT_VAR]
        conservative.reasons[CORPSE_COUNT_VAR] = f"off: {consumed_why}"
    stack_caps: dict[str, tuple[int, float]] = {}
    a = {**NUMERIC_ASSUMPTION_DEFAULTS, **dict(assumptions or {})}
    labels = {str(o["var"]): _POB_COLOR.sub("", str(o.get("label") or o["var"])).strip(": ") for o in pending_stacks}
    for var, (value, why, cap, share) in judge_stack_options(pob, pending_stacks, ceiling=int(a["stack_options_ceiling"]), boss=boss).items():
        for lane in (conservative, optimistic):
            lane.reasons[var] = why
        if value is None:  # PoB does not cap it: an assumption about the fight, off in both lanes
            continue
        optimistic.inputs[var] = value  # the ceiling, which PoB caps: the optimistic lane holds the cap
        if cap is not None:
            stack_caps[var] = (cap, share)
        # the conservative lane holds what the build stacks inside the ramp budget, never a ceiling (D62 amendment)
        held = stack_option(var, labels.get(var, var), float(cap) if cap is not None else None, facts)
        if held is None:
            conservative.inputs[var] = value
        elif held[0] > 0:
            conservative.inputs[var] = held[0]
            conservative.reasons[var] = f"{held[1]}; PoB: {why}"
        else:
            conservative.reasons[var] = f"off: nothing built inside the {facts.budget:g} s ramp budget; PoB: {why}"
    def recheck(var: str, masked: Mapping[str, int] | Iterable[str]) -> ProofRecheck | None:
        """This input's own rule, re-run over the same evidence with `masked` lines removed.

        Pure Python: `stats`, `parsed`, the gems and the ascendancy text stay exactly as PoB
        reported them for this derivation, and only the build text the masked lines occupy is
        withdrawn. That is what makes a node a *necessary* proof rather than a sole one -- every
        other source (an ascendancy node, an item, a gem, another passive) is still standing.
        """

        if var not in conservative.proof_lines:
            return None  # nothing in the build text held it: no tree line can be necessary for it
        rule = _proof_rule_name(var)
        opt = check_options.get(var)
        if opt is None:
            # written outside the `_conservative_allows` loop (an ailment condition from PoB stats,
            # a stack option PoB itself caps): the rule needs PoB to answer again
            return ProofRecheck(rule=rule, keys=(var,), inputs=None)
        keys: tuple[str, ...] = (var,)
        override_var = var.replace("use", "override", 1) if var in CHARGE_VARS else None
        if override_var and override_var in surfaces:
            keys = (var, override_var)
        masked_text = mask_text(text, masked)
        if masked_text == text:
            return ProofRecheck(rule=rule, keys=keys, inputs={k: conservative.inputs[k] for k in keys if k in conservative.inputs})
        remaining = {line.strip().lower() for line in masked_text.splitlines() if line.strip()}
        masked_parsed = {line: row for line, row in parsed.items() if str(line).strip().lower() in remaining}
        ok, _why = _conservative_allows(
            var,
            (surfaces.get(var, {}).get("predicates") or {}),
            stats,
            masked_text,
            gem_tags,
            aux_gem_tags,
            main_tags,
            corpse=corpse,
            warcry_sources=warcry_sources,
            source_contexts=source_contexts,
            parsed=masked_parsed,
            option=opt,
            gem_names=gem_names,
            ramp_seconds=ramp_seconds,
        )
        if not ok:
            return ProofRecheck(rule=rule, keys=keys, inputs={})
        out: dict[str, Any] = {var: True}
        if override_var:
            _use, _why2, override, _rate = charge_rule(var, stats, masked_text, gem_tags, ramp_seconds=ramp_seconds,
                                                       main_tags=main_tags, warcry_sources=warcry_sources, source_contexts=source_contexts)
            if override is not None and override_var in surfaces:
                out[override_var] = override
        return ProofRecheck(rule=rule, keys=keys, inputs=out)

    return DerivedConfig(conservative=conservative, optimistic=optimistic, shown=shown, choices=choices, stack_caps=stack_caps,
                          charge_rates=charge_rates, custom_mods=custom_mods, ailment_stack_caps=ailment_stack_caps,
                          recheck=recheck)


AILMENT_DURATIONS = {"Ignite": 4.0, "Bleed": 5.0, "Poison": 2.0, "Shock": 2.0, "Chill": 2.0, "Freeze": 0.3, "Scorch": 4.0, "Brittle": 4.0, "Sap": 4.0}

# --- #702: the Shock, Chill, Scorch, Brittle and Sap the build's own hits earn ---------------------------------
# ailment -> (checkbox, "Effect of ..." input, damage type it is measured from (data.nonDamagingAilment.associatedType),
# K of `K * (damage / threshold)^0.4 * effectMod` (CalcOffence.lua:5222-5250))
OWN_HIT_AILMENTS: dict[str, tuple[str, str, str, float]] = {
    "Shock": ("conditionEnemyShocked", "conditionShockEffect", "Lightning", 50.0),
    "Chill": ("conditionEnemyChilled", "conditionEnemyChilledEffect", "Cold", 50.0),
    "Scorch": ("conditionEnemyScorched", "conditionScorchedEffect", "Fire", 50.0),
    "Brittle": ("conditionEnemyBrittle", "conditionBrittleEffect", "Cold", 10.0),
    "Sap": ("conditionEnemySapped", "conditionSapEffect", "Lightning", 100.0 / 3.0),
}
OWN_HIT_MIN_UPTIME = 0.90  # the checkbox is set only when the enemy is under the ailment this much of the time (the bar of ElementalOverloadUptime)
_PROBED_VALUE = 40  # the typed effect of the second probe: makes PoB write Maximum<A> and shows how much DamageTaken one point of shock adds


@dataclass(frozen=True)
class OwnHitAilment:
    ailment: str
    threshold: float  # PoB's boss ailment threshold (CalcOffence.lua:5209-5218), read from the session
    d0: float  # the chance-weighted blend of the source type's non-crit and crit hit damage
    other_damage_taken: float | None  # D of `d_k = d0 * (1 + S_(k-1) / (100 + D))`; None where the ailment adds no damage taken
    hits: int  # hits that start inside the ramp budget
    effects: tuple[float, ...]  # S_1 .. S_n
    steady: float
    mean: float  # mean effect a hit meets inside the budget, S_0 = 0
    typed: int
    uptime: float
    applies: bool
    why: str


def ailment_ramp(*, d0: float, threshold: float, k: float, effect_mod: float, maximum: float, other_damage_taken: float | None, hits: int, chained: bool = True) -> tuple[tuple[float, ...], float, float]:
    """(S_1 .. S_n, mean of S_0 .. S_(n-1), steady state) of `S_k = min(maximum, k * (d_k / threshold)^0.4 * effect_mod)`.

    Hit k meets the effect hit k-1 earned (the ailment outlasts the gap between hits: `chained`); for an ailment
    that adds damage taken, `d_k = d0 * (1 + S_(k-1) / (100 + D))`, otherwise `d_k = d0`."""

    def earned(met: float) -> float:
        damage = d0 * (1 + met / (100 + other_damage_taken)) if other_damage_taken is not None else d0
        return min(maximum, k * (damage / threshold) ** 0.4 * effect_mod)

    effects: list[float] = []
    met = [0.0]
    for _ in range(hits):
        effects.append(earned(met[-1] if chained else 0.0))
        met.append(effects[-1])
    steady = 0.0
    for _ in range(200):
        steady = earned(steady if chained else 0.0)
    return tuple(effects), sum(met[:hits]) / hits, steady


def _own_stat(stats: Mapping[str, Any], key: str) -> float | None:
    for name in (key, f"MainHand.{key}"):
        value = stats.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def own_hit_ailments(pob: Any, stats: Mapping[str, Any], *, boss: str, ramp_seconds: float) -> list[OwnHitAilment]:
    """What the build's own hits earn of Shock, Chill, Scorch, Brittle and Sap against the boss, from PoB's numbers.

    PoB never applies it: the effect is the config's typed "Effect of ..." (CalcOffence.lua:5230, 5323;
    ConfigOptions.lua:1921). Per ailment the session is probed with the checkbox on (so "against Shocked Enemies" mods
    count) and the effect typed 0 and `_PROBED_VALUE`; the config state is put back afterwards. `stats` are the
    build's own, unprobed outputs: an ailment is probed only when PoB gives its source damage type some hit damage and
    the hit some chance (Chill is 100 % on every hit, so a Fireball with 1 % cold must pass the minimum effect below).

    `applies` = uptime `1 - (1 - chance)^(whole hits per duration)` >= `OWN_HIT_MIN_UPTIME` and the first hit's effect
    reaches PoB's minimum for the ailment (`AilmentMinimum<A>`: under it the game applies nothing)."""

    wanted = [a for a, (_t, _e, kind, _k) in OWN_HIT_AILMENTS.items()
              if (_own_stat(stats, f"{kind}HitAverage") or 0) > 0 and (_own_stat(stats, f"{a}ChanceOnHit") or 0) + (_own_stat(stats, f"{a}ChanceOnCrit") or 0) > 0]
    if not wanted or not all(callable(getattr(pob, name, None)) for name in ("config_checkpoint", "config_rollback", "set_config", "read_state", "stats")):
        return []
    from junkroan.optimizer.trace import TRACE

    state = pob.read_state().get("config_state") or {}
    ident = dict(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None", pantheon_minor=state.get("pantheon_minor") or "None", enemy_state={"is_boss": boss}, preserve="all")
    out: list[OwnHitAilment] = []
    pob.config_checkpoint()
    try:
        with TRACE.muted():
            for ailment in wanted:
                checkbox, effect_var, kind, k = OWN_HIT_AILMENTS[ailment]
                keys = [f"{kind}HitAverage", f"{kind}CritAverage", "CritChance", "HitTime", "HitSpeed", "Speed", f"Maximum{ailment}",
                        *(f"{ailment}{x}" for x in ("ChanceOnHit", "ChanceOnCrit", "Chance", "EffectMod", "Duration"))]
                keys = [*keys, *(f"MainHand.{x}" for x in keys), "EnemyAilmentThreshold", f"AilmentMinimum{ailment}"]
                reads = []
                for typed in (0, _PROBED_VALUE):
                    pob.set_config(inputs={checkbox: True, effect_var: typed}, **ident)
                    reads.append(pob.stats(keys))
                s0, s1 = reads
                threshold = _own_stat(s0, "EnemyAilmentThreshold")
                hit, crit, c = _own_stat(s0, f"{kind}HitAverage"), _own_stat(s0, f"{kind}CritAverage"), (_own_stat(s0, "CritChance") or 0.0) / 100.0
                on_hit, on_crit = _own_stat(s0, f"{ailment}ChanceOnHit") or 0.0, _own_stat(s0, f"{ailment}ChanceOnCrit") or 0.0
                effect_mod, maximum = _own_stat(s0, f"{ailment}EffectMod"), _own_stat(s1, f"Maximum{ailment}")
                speed = _own_stat(s0, "HitSpeed") or _own_stat(s0, "Speed")
                hit_time = _own_stat(s0, "HitTime") or (1.0 / speed if speed else None)
                if not threshold or hit is None or crit is None or not effect_mod or not maximum or not hit_time:
                    continue
                weight_hit, weight_crit = on_hit * (1.0 - min(c, 1.0)), on_crit * min(c, 1.0)
                if weight_hit + weight_crit <= 0:
                    continue
                d0 = (hit * weight_hit + crit * weight_crit) / (weight_hit + weight_crit)
                taken: float | None = None
                if ailment == "Shock":  # a shock is DamageTaken INC: one typed value shows what the enemy already takes (D)
                    probed = _own_stat(s1, f"{kind}HitAverage")
                    if probed and hit > 0 and probed / hit - 1.0 > 1e-9:
                        taken = _PROBED_VALUE / (probed / hit - 1.0) - 100.0
                duration = _own_stat(s0, f"{ailment}Duration") or AILMENT_DURATIONS[ailment]
                per_duration = max(1, math.floor(duration / hit_time + 1e-9))
                hits = max(1, math.ceil(ramp_seconds / hit_time - 1e-9))
                effects, mean, steady = ailment_ramp(d0=d0, threshold=threshold, k=k, effect_mod=effect_mod, maximum=maximum, other_damage_taken=taken, hits=hits, chained=hit_time <= duration + 1e-9)
                chance = _own_stat(s0, f"{ailment}Chance")
                chance = (weight_hit + weight_crit) if chance is None else chance
                uptime = 1.0 - (1.0 - min(chance / 100.0, 1.0)) ** per_duration
                minimum = _own_stat(s0, f"AilmentMinimum{ailment}") or 0.0
                typed = int(math.floor(min(mean, maximum) + 0.5))
                applies = uptime >= OWN_HIT_MIN_UPTIME and effects[0] >= minimum
                if applies:
                    why = (f"the build's own hits {ailment.lower()} the boss {uptime:.0%} of the time ({chance:.1f}% per hit, {per_duration} hits per {duration:g} s); "
                           f"effect {steady:.2f} steady, {mean:.2f} mean over the {hits} hits inside {ramp_seconds:g} s (threshold {threshold:,.0f}), typed {typed}")
                else:
                    why = f"{ailment.lower()}: the build's own hits keep it {uptime:.0%} of the time (needs {OWN_HIT_MIN_UPTIME:.0%}), first-hit effect {effects[0]:.2f} (minimum {minimum:g})"
                out.append(OwnHitAilment(ailment, threshold, d0, taken, hits, effects, steady, mean, typed, uptime, applies, why))
    finally:
        pob.config_rollback()
    return out



DEBUFF_DURATIONS = {"Maimed": 4.0, "Blinded": 4.0, "Hindered": 4.0, "Intimidated": 4.0, "Unnerved": 4.0}  # seconds, the base durations (poewiki)
_DEBUFF_WORD = {"Maimed": "maim", "Blinded": "blind", "Hindered": "hinder", "Intimidated": "intimidate", "Unnerved": "unnerve"}


def _chance_debuff_uptime(key: str, stats: Mapping[str, Any], text: str) -> tuple[float, str] | None:
    """"X% chance to Maim Enemies on Critical Strike with Attacks" (Dismembering, red in PoB): the
    same uptime rule as ailments, 1 - (1 - p)^(hits/s x duration), p x crit chance when on crit.
    None when the text has no such line for the debuff."""

    word = _DEBUFF_WORD.get(key)
    if not word:
        return None
    best: tuple[float, str] | None = None
    hits = float(stats.get("HitSpeed") or stats.get("Speed") or 0.0)
    crit = float(stats.get("CritChance") or 0.0) / 100.0
    for m in re.finditer(rf"(\d+)% chance to {word} (?:enemies |enemy )?(?:on|with|when you) ([a-z ]+)", text, re.IGNORECASE):
        p = float(m.group(1)) / 100.0
        trigger = m.group(2)
        if "crit" in trigger:
            p *= crit
        elif not re.search(r"hit|attack|strike", trigger):
            continue
        duration = DEBUFF_DURATIONS.get(key, 4.0)
        uptime = 1.0 - (1.0 - min(p, 1.0)) ** max(1.0, hits * duration) if p > 0 else 0.0
        if best is None or uptime > best[0]:
            best = (uptime, m.group(0))
    return best


def _applied_probability(stats: Mapping[str, Any], chance_key: str) -> float:
    """Probability the enemy is under the ailment at a given moment: chance per hit
    compounded over the hits landed during one ailment duration."""

    chance = float(stats.get(chance_key) or 0) / 100.0
    if chance <= 0:
        return 0.0
    ailment = next((a for a in AILMENT_DURATIONS if chance_key.startswith(a)), None)
    duration = float(stats.get(f"{ailment}Duration") or AILMENT_DURATIONS.get(ailment or "", 2.0)) if ailment else 2.0
    speed = float(stats.get("Speed") or 1.0)
    hits = max(1.0, speed * duration)
    return 1.0 - (1.0 - min(chance, 1.0)) ** hits


def _ailment_evidence(key: str, stats: Mapping[str, Any]) -> tuple[bool, str] | None:
    """Does the build keep the enemy under `key`? (proven, reason), or None when `key` is
    not an ailment this module judges.

    A damaging ailment needs two things from PoB's own numbers: damage the ailment deals
    (AILMENT_DAMAGE_PROOF; no fire in the hit, no ignite) *and* a chance that applies it
    almost all the time (AILMENT_PROOF, the uptime rule of `_applied_probability`). The
    non-damaging ailments keep the chance-only rule.
    """

    chance_keys = AILMENT_PROOF.get(key)
    if not chance_keys:
        return None
    speed = float(stats.get("Speed") or 0.0)
    damage_keys = AILMENT_DAMAGE_PROOF.get(key)
    damage_shown: str | None = None
    if damage_keys:
        damage_shown = next((k for k in damage_keys if isinstance(stats.get(k), (int, float)) and stats[k] > 0), None)
        if damage_shown is None:
            seen = next((k for k in damage_keys if isinstance(stats.get(k), (int, float))), damage_keys[0])
            return False, f"{key}: {seen} = {float(stats.get(seen) or 0.0):.4g}: no {AILMENT_DAMAGE_SOURCE.get(key, key.lower())} in the hit"
    best: tuple[float, str] | None = None
    for chance_key in chance_keys:
        if isinstance(stats.get(chance_key), (int, float)):
            applied = _applied_probability(stats, chance_key)
            if best is None or applied > best[0]:
                best = (applied, chance_key)
    if best is None:
        return False, f"{key}: PoB shows no {' / '.join(chance_keys)}"
    applied, chance_key = best
    detail = f"{chance_key} {float(stats.get(chance_key) or 0.0):.4g}% applied {applied:.0%} of the time at {speed:.1f} hits/s"
    if applied < 0.9:
        return False, f"{key}: {detail}"
    if damage_shown:
        return True, f"build applies {key} ({damage_shown} = {float(stats[damage_shown]):.4g}, {detail})"
    return True, f"build applies {key} ({detail})"


def _aggravated_bleed(stats: Mapping[str, Any], text: str) -> tuple[bool, str]:
    """PoB 3.29 does not parse "Bleeding you inflict is Aggravated" (Jagged Technique;
    Data/ModCache has the aggravation lines as empty mod lists). Its 200% more bleed
    damage against a moving enemy (CalcSetup) is the only way an aggravated bleed can
    be represented, so the build's own aggravation text proves "enemy is moving"; a
    chance per hit counts by the same uptime rule as ailments; Crimson Dance ("cannot
    be Aggravated") takes it away. A Puncture Gladiator with Jagged Technique lost
    3x of its non-Crimson-Dance bleed to this and chose Crimson Dance (D40)."""

    if re.search(r"cannot be aggravated", text, re.IGNORECASE):
        return False, "bleeding cannot be Aggravated (Crimson Dance); no other moving source"
    if re.search(r"bleeding you inflict (is|are) aggravated", text, re.IGNORECASE):
        return True, "Aggravated bleeding deals damage as though the enemy is moving (build text); PoB does not parse aggravation"
    best: tuple[float, str] | None = None
    for m in re.finditer(r"(\d+)% chance to aggravate bleeding on targets you (hit|critically strike)", text, re.IGNORECASE):
        chance = float(m.group(1)) / 100.0
        if m.group(2).lower().startswith("crit"):
            chance *= float(stats.get("CritChance") or 0) / 100.0
        duration = float(stats.get("BleedDuration") or AILMENT_DURATIONS["Bleed"])
        hits = max(1.0, float(stats.get("Speed") or 1.0) * duration)
        uptime = 1.0 - (1.0 - min(chance, 1.0)) ** hits
        if best is None or uptime > best[0]:
            best = (uptime, m.group(0))
    if best and best[0] >= 0.9:
        return True, f"{best[1]}: aggravated {best[0]:.0%} of the time over a bleed's duration (as though moving)"
    if best:
        return False, f"{best[1]}: aggravated only {best[0]:.0%} of the time"
    return False, "no aggravation source in build text; enemy movement is a state assumption"


def _generator_proof(pattern: str, text: str, gem_tags: frozenset[str], main_tags: frozenset[str] | None = None,
                     proof_lines: list[str] | None = None) -> tuple[bool, str]:
    """The first line of the build's text that matches `pattern` and is a proof on a boss:
    a line whose trigger needs a skill kind the build has not got is not one (R1.1), and
    neither is a line that needs a kill (R1.3: impale_cyclone's `buffOnslaught` stood on
    "20% chance to gain Onslaught for 4 seconds on Kill"). The optimistic lane is untouched:
    it enables everything PoB shows."""

    rejected: list[str] = []
    accepted: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lower()  # `build_text` is lower-case already; a hand-written text need not be
        if not line or not re.search(pattern, line):
            continue
        needs = missing_enabler(line, gem_tags, main_tags)
        if needs:
            rejected.append(f"{line[:90]} (needs a {needs} skill; none in the build)")
        elif ON_KILL_TRIGGER.search(line):
            rejected.append(f"{line[:90]} (on kill: no kills on a boss)")
        else:
            accepted.append(raw.strip())
    if accepted:
        if proof_lines is not None:
            proof_lines.extend(accepted)
        return True, f"source found in build: {accepted[0][:90]}"
    if rejected:
        return False, "no source that holds on a boss: " + "; ".join(rejected[:2])
    return False, "source not found in build"


def buff_candidate_lines(text: str) -> list[str]:
    """Text lines worth sending to PoB for player-buff sources.

    Pattern matching only keeps the batch small. It is not proof: the parser
    still has to emit the exact top-level player ``Condition`` flag.
    """

    patterns = tuple(re.compile(pattern, re.IGNORECASE) for kind, pattern in GENERATORS.items() if kind != "Leeching")
    return [line for line in text.splitlines() if line.strip() and any(pattern.search(line) for pattern in patterns)]


def corpse_cycle(gems: Sequence[Gem]) -> tuple[str | None, str | None]:
    """(the gem that creates corpses, the gem that consumes them), each None when the build has
    neither. PoB's own skill data answers both (`desecrate_number_of_corpses_to_create` /
    `corpseMonsterVariety` for Desecrate and Unearth, `number_of_corpses_to_consume` for Volatile
    Dead, Cremation, Detonate Dead, Bodyswap): no list of skill names is kept here."""

    from junkroan.pob.skill_facts import corpses_consumed_per_cast, corpses_created_per_cast

    creator = next((g.name for g in gems if g.effect_id and corpses_created_per_cast(g.effect_id)), None)
    consumer = next((g.name for g in gems if g.effect_id and corpses_consumed_per_cast(g.effect_id)), None)
    return creator, consumer


def _corpse_cycle_allows(key: str, corpse: tuple[str | None, str | None]) -> tuple[bool, str]:
    """The boss lane's answer for a corpse condition: the build itself has to make the corpses."""

    creator, consumer = corpse
    if not creator:
        return False, f"{key}: no gem in the build creates corpses; a corpse a kill leaves is not a source on a boss"
    if not CORPSE_CONDITIONS[key]:
        return True, f"{creator.title()} creates corpses every cast"
    if not consumer:
        return False, f"{key}: {creator.title()} creates corpses but nothing in the build consumes them"
    return True, f"{creator.title()} creates corpses and {consumer.title()} consumes them every cast"


def _crit_recently(stats: Mapping[str, Any], main_tags: frozenset[str]) -> tuple[bool, str]:
    """Does the build keep "has crit recently" up? Elemental Overload is the case that
    needs it (the user's reading 2026-09-18: 7% effective crit on a slow channelled
    Burning Arrow against 17% on Kinetic Fusillade), and PoB's keystone takes effect
    through exactly this per-skill condition ("Skills that have dealt a Critical Strike
    in the past 8 seconds ..."), so the proof is the same uptime rule the ailments use:
    1 - (1 - c)^(8 r) >= 90%, c = PoB's effective crit per attempt (`CritChance`, which in
    the effective mode already carries the accuracy roll: CalcOffence multiplies it by
    `AccuracyHitChance`) and r = hits per second. Proxies hit for you (totems, traps,
    mines: PoB's Speed is already theirs); minions do not -- Elemental Overload is per
    skill and a minion's critical strike is the minion's (research 2026-09-18,
    docs/research/...-game-knowledge)."""

    if "minion" in main_tags:
        return False, "the damage is your minions'; their critical strikes are theirs, and Elemental Overload is per skill"
    return crit_recently_uptime(stats)


def crit_recently_uptime(stats: Mapping[str, Any]) -> tuple[bool, str]:
    """(kept up, detail) for the 8 s "dealt a critical strike recently" window; the arithmetic is
    `keystone_floors.crit_recently_uptime`, shared with the objective's Elemental Overload floor."""

    from junkroan.optimizer.keystone_floors import crit_recently_uptime as uptime_of

    uptime, detail = uptime_of(stats)
    return uptime >= CRIT_RECENTLY_MIN_UPTIME, detail


def _conservative_allows(var: str, preds: Mapping[str, Any], stats: Mapping[str, Any], text: str, gem_tags: frozenset[str] = frozenset(), aux_gem_tags: frozenset[str] = frozenset(), main_tags: frozenset[str] | None = None, *, corpse: tuple[str | None, str | None] = (None, None), warcry_sources: Sequence[Mapping[str, Any]] = (), parsed: Mapping[str, Mapping[str, Any]] | None = None, option: Mapping[str, Any] | None = None, gem_names: Sequence[str] = (), source_contexts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None, proof_lines: list[str] | None = None, ramp_seconds: float = DEFAULT_RAMP_BUDGET_S) -> tuple[bool, str]:
    def proven(keys: tuple[str, ...]) -> bool:
        # a chance per hit counts when the enemy ends up affected almost all the time:
        # 1 - (1 - p)^(hits per second x ailment duration) >= 0.9 (a 14% bleed chance at
        # 4 hits/s over 5 s is 95%); a stray 10% shock on a spell cast twice a second is not.
        # Rate/effect keys (leech) only need to exist; ailments go through _ailment_evidence.
        return any(isinstance(stats.get(k), (int, float)) and (stats.get(k) >= 1e-9 if "Chance" not in k else _applied_probability(stats, k) >= 0.9) for k in keys)

    if var in CHARGE_VARS:
        use, why, _override, _rate = charge_rule(var, stats, text, gem_tags, ramp_seconds=ramp_seconds, main_tags=main_tags, warcry_sources=warcry_sources, source_contexts=source_contexts, proof_lines=proof_lines)
        return use, why
    if var in ENABLER_GEM_INPUTS:
        # PoB shows the input only when the gem is in the build (its `ifSkill` predicate), and
        # this input says the skill's effect was used, not that something else went right
        if var == "feedingFrenzyFeedingFrenzyActive" and "feeding frenzy" not in {name.strip().lower() for name in gem_names}:
            return False, "Feeding Frenzy is not in an enabled link"
        return True, f"{ENABLER_GEM_INPUTS[var]}: a fact of playing the skill the build carries, not an assumption about the fight"
    if var in BUFF_VARS:
        return parsed_buff_proof(var, stats, parsed or {}, option, gem_tags, main_tags or frozenset(), gem_names, proof_lines)
    enemy_cond = preds.get("ifEnemyCond")
    if not enemy_cond and var.startswith("conditionEnemy") and (var[len("conditionEnemy"):] in AILMENT_PROOF or var[len("conditionEnemy"):] in OTHER_SKILL_AILMENTS):
        enemy_cond = var[len("conditionEnemy"):]  # e.g. conditionEnemyChilled has no predicate in PoB (always shown)
    if enemy_cond:
        keys = enemy_cond if isinstance(enemy_cond, list) else [enemy_cond]
        unproven: list[str] = []
        for key in keys:
            if str(key) in OTHER_SKILL_AILMENTS:
                element = OTHER_SKILL_AILMENTS[str(key)]
                if element and element in aux_gem_tags:
                    return True, f"a second {element} skill in the build can apply {key}"
                return False, f"{key}: no second {element or 'ailment'} skill in the build (the main skill's own hits are typed by own_hit_ailments, not here)"
            evidence = _ailment_evidence(str(key), stats)
            if evidence is None:
                continue
            ok, why = evidence
            if ok:
                return True, why
            unproven.append(why)
        for key in keys:
            gen = GENERATORS.get(str(key))
            if gen:
                ok, why = _generator_proof(gen, text, gem_tags, main_tags, proof_lines)
                if ok:
                    return True, f"{key}: {why}"
        for key in keys:
            chance = _chance_debuff_uptime(str(key), stats, text)
            if chance is not None:
                uptime, line = chance
                if uptime >= 0.9:
                    return True, f"{line}: {key} {uptime:.0%} of the time over its duration (PoB does not parse the line; chance x hits/s x duration)"
                return False, f"{line}: {key} only {uptime:.0%} of the time"
        return False, "; ".join(unproven) if unproven else f"build does not apply {keys}"
    cond = preds.get("ifCond")
    if cond:
        keys = cond if isinstance(cond, list) else [cond]
        for key in keys:
            key = str(key)
            if key in CORPSE_CONDITIONS:
                return _corpse_cycle_allows(key, corpse)
            if key in KILL_CONDITIONS:
                return False, f"{key} needs kills (boss lane)"
            if key in STATE_ASSUMPTIONS:
                return False, f"{key} is a state assumption"
            proxy_main = bool((main_tags or frozenset()) & PROXY_DELIVERY_TAGS)
            proxy_subject = var.lower().startswith(("conditiontotems", "conditiontraps", "conditionmines"))
            is_proxy_subject = key.startswith(tuple(prefix for prefix, _delivery in PROXY_SUBJECT_PREFIXES))
            direct = _condition_allows(key, stats, gem_tags, main_tags or frozenset(), proxy_subject=proxy_subject) if proxy_main and (key in PROXY_MAIN_CONDITIONS or is_proxy_subject) else None
            if direct is not None:
                return direct
            if key in COMBAT_SUSTAINED:
                tag = SUSTAINED_NEEDS_GEM_TAG.get(key)
                if tag and tag not in gem_tags:
                    return False, f"{key} needs a {tag} gem; none in the build"
                if key in CRIT_RECENTLY_CONDITIONS:
                    ok, why = _crit_recently(stats, main_tags or frozenset())
                    return ok, f"{key}: {why}"
                return True, f"{key} is sustained by using the main skill"
            gen = GENERATORS.get(key)
            if gen:
                ok, why = _generator_proof(gen, text, gem_tags, main_tags, proof_lines)
                if ok:
                    return True, f"{key}: {why}"
        return False, f"no generator known for {keys}"
    if preds.get("ifSkill") or preds.get("ifSkillFlag") or preds.get("ifSkillData"):
        # e.g. ColdSnapBypassCD, golem buffs: having the skill is not proof the
        # assumption holds (bypassing a cooldown needs charges). Optimistic lane only.
        return False, "skill option is an assumption, not a source"
    if var == "conditionEnemyMoving":
        return _aggravated_bleed(stats, text)
    if preds.get("ifFlag") or preds.get("ifMod") or preds.get("ifOption") or preds.get("ifMult") or preds.get("ifStat"):
        return False, "referenced but no generator rule"
    if not preds and var.startswith("condition"):
        key = var[len("condition"):]  # PoB shows some conditions unconditionally (consecrated ground ...)
        gen = GENERATORS.get(key)
        if gen:
            ok, why = _generator_proof(gen, text, gem_tags, main_tags, proof_lines)
            if ok:
                return True, f"{key}: {why}"
        if key in CRIT_RECENTLY_CONDITIONS:
            ok, why = _crit_recently(stats, main_tags or frozenset())
            return ok, f"{key}: {why}"
        if key in COMBAT_SUSTAINED and not (SUSTAINED_NEEDS_GEM_TAG.get(key) and SUSTAINED_NEEDS_GEM_TAG[key] not in gem_tags):
            return True, f"{key} is sustained by using the main skill"
    return False, "no predicate; not assumed"


__all__ = ["charge_rule", "charge_sources", "corpse_cycle", "derive_config", "DerivedConfig", "LaneConfig", "build_facts", "build_text", "generator_source_contexts",
           "config_surfaces", "is_stack_option", "judge_stack_options", "missing_enabler", "conservative_generator_issue", "CORPSE_CONDITIONS", "ENABLER_GEM_INPUTS",
           "warcry_charge_effect_ids", "warcry_charge_sources", "warcry_usage_proof"]
