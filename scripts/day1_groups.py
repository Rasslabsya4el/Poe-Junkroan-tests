"""#1119 unit 2: group the day-1 lines PoB leaves unparsed by what they do.

The rule is code, not a model: each line (whitespace normalised, so a PoB line break
inside a sentence does not matter) takes the FIRST family in FAMILIES whose pattern
matches its text (case-insensitive, searched anywhere in the line). A line that
matches none takes `other`, which is always last. So every line is in exactly one
group, and the order below is the rule: a more specific family sits before a broader
one (a jewel condition before the event it qualifies, a cannot before a minion, an
event (on kill, on hit) before the ailment it inflicts).

The families were read off ~120 PoB-unparsed unique lines (uniques.json
`unsupported_lines`, seeded sample), not off game memory.
"""

from __future__ import annotations

import re

FAMILIES: tuple[tuple[str, str], ...] = (
    # whole-line item text: requirements, quality, corruption state, glow text
    ("item_text", r"^requires\b|^corrupted$|\bquality\b|^glows\b"),
    # restrictions and immunities (a cannot is a restriction whatever it names)
    ("cannot_immune", r"\bcannot\b|\bcan't\b|\bcan not\b|\bimmune\b|\bdo(?:es)? not\b|\bis not\b|\bcan only\b|\bnot be\b|\bunaffected\b"),
    # minions, summons, totems, raised or animated things
    ("minion", r"\bminions?\b|\bspectres?\b|\bsummon|\bskeletons?\b|\btotems?\b|\barbalists?\b|\bzombies\b|\bphantasms?\b|\braised\b|\banimated\b|\bsummoned\b"),
    # a condition on a jewel's radius or a socketed jewel, before the effect it qualifies
    ("jewel_conditional", r"\bin radius\b|\bjewel socketed\b"),
    # an event that starts the effect by use: triggers, on use, when you use or spend
    ("trigger", r"\btriggers?\b|\btriggered\b|\btriggering\b|\bon (?:use|using)\b|\bwhen you (?:use|spend)\b|\bupfront cost\b|\busable\b"),
    # an event on a kill
    ("on_kill", r"\bkill(?:s|ed|ing)?\b|\bculling\b"),
    # damage or effect reflected back
    ("reflect", r"\breflect"),
    # stealing charges or resources from an enemy
    ("steal", r"\bsteal|\bstolen\b"),
    # a cost the build pays from itself
    ("self_cost", r"\bsacrific|\bremoves? \d+(?:\.\d+)?% of (?:your )?life\b"),
    # damage made from another stat (conversion, or a damage taken as another type)
    ("conversion", r"\bconverted\b|\bconverts?\b|\bconversion\b|\btaken as\b|\bas (?:fire|cold|lightning|chaos|physical|elemental) damage\b"),
    # recovery of life, mana, energy shield, leech, recoup
    ("recovery", r"\brecover|\brecoup|\bleech|\bregen|\bregain|\brecharge\b|\bgain (?:\d+ )?life\b"),
    # charges and stacking resources (power, frenzy, endurance, rage, souls)
    ("charges", r"\bcharges?\b|\brage\b|\bsouls?\b|\beaten\b"),
    # buffs and auras the build gains for itself
    ("buff", r"\baura|\bbuff|\bonslaught\b|\bphasing\b|\bfortif|\bcat'?s stealth\b|\bavian'?s\b|\bblood shrine\b"),
    # defences: resistances, armour, evasion, suppression, block chance, damage taken
    ("defence", r"\bresistances?\b|\bresist|\barmour\b|\bevasion\b|\bsuppress|\bblock chance\b|\bchance to block\b|\bdodge\b|\bpenetrat|\bdamage taken\b|\bprevent\b"),
    # an event on being hit or blocking
    ("on_hit", r"\bhit(?:s|ting)?\b|\bblock(?:s|ed|ing)?\b|\bhit by\b"),
    # a ground effect the build creates or stands in (Shocked, Desecrated, Burning Ground)
    ("ground", r"\bground\b"),
    # an ailment inflicted on an enemy or a state applied to one
    ("ailment", r"\binflict|\bchill|\bfreez|\bshock|\bignit|\bbleed|\bpoison|\bblind|\bintimidat|\btaunt|\bexposure|\bcurse|\bhex|\bmaim|\bwither|\bailment|\bstun|\bslow"),
    # flasks: their effect on the build or the ground they leave
    ("flask", r"\bflasks?\b"),
    # a named skill or skill type (spell, attack, projectile, arrow, melee, vaal, gems)
    ("skill_specific", r"\bspells?\b|\battacks?\b|\bprojectiles?\b|\barrows?\b|\bmelee\b|\bstrikes?\b|\bslams?\b|\bwarcry|\bvaal\b|\bgems?\b|\bskills?\b|\bbow\b|\bweapon\b|\bsocketed\b|\bbarrage\b|\bfrostbolt\b"),
    # a plain number-carrying stat line that no earlier family took
    ("plain_stat", r"\b(?:increased|reduced|more|less|additional)\b|^[+-]?\d"),
)

GROUPS: tuple[str, ...] = tuple(name for name, _ in FAMILIES) + ("other",)

_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in FAMILIES)


def group_of(line: str) -> str:
    """The one group of a PoB line: the first family in GROUPS order that matches its text."""
    text = " ".join(line.split())
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return "other"
