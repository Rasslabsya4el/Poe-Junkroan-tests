# 2026-09-19 D77. A buff is proven by a line PoB parses as its source, never by a word match

Status: Accepted; amended by D77 amd 1

Reading of the campaign's first builds: bleed_perforate's `conditionLeeching` stood on "enemies cannot leech life
from you". `_generator_proof` accepted any line of the build's text that contained the buff's word, so a cap ("+3
to maximum fortification", 6 references), the consumer itself ("43% increased damage while leeching"), a modifier
("20% increased effect of arcane surge on you"), an unproven precondition ("gain adrenaline ... when you reach low
life") and another actor's buff ("minions have unholy might") all switched a buff on -- 24 such proofs over the 58
authors' conservative lanes, and the optimizer hunts exactly these holes.

PoB's own parser separates the roles (`PobSession.parse_mods`): a SOURCE is a FLAG mod named `Condition:<X>`, and
its `Condition` tags are its preconditions ("Gain Arcane Surge on Hit with Spells" -> `Condition:ArcaneSurge`,
tag `HitSpellRecently`); a CONSUMER carries X as a tag on another stat; a cap or an effect modifier is neither; a
line PoB does not parse proves nothing. The rule: a text proof of a buff is a parsed player source (outside
`MinionModifier` / `EnemyModifier`) whose every precondition is itself allowed on the conservative lane,
resolved recursively and fail-closed; the input's condition name is read from PoB's config option;
`conditionLeeching` stands on PoB's computed leech rate only; one batched, memoised `parse_mods` call per build;
the D75 audit check uses the same function.

Lane diff over the 58 references (the lead's run, main f99fd2a -> the branch): inputs move on 9 --
`buffFortification` off on 6, `buffAdrenaline` off on 2, `buffUnholyMight` off on 1; the 6 references with
`conditionLeeching` keep it on PoB's leech rate. 759 tests.

Left for an amendment, with a measurement first: the `condition*` generator proofs still use the word path
(stormbrand's `conditionOnConsecratedGround` on "you have consecrated ground around you while stationary", whose
parsed precondition is a state assumption); the gem table `BUFF_GEM_INPUTS` (Withering Step -> Elusive, Phasing)
is authored and needs the wiki's word on whether the buff survives using a skill; a support gem's bare name
("fortify", "arcane surge") happens to parse as a source even when the gem sits in an unused link.

### D77 amendment 1 (2026-09-19): a buff that ends when the character uses a skill is not held while fighting

The wiki's word arrived (`var/cache/wiki/2026-09-19-buffs-ended-by-skill-use-extract.md`): "Using any skill ends
Withering Step's effects and removes all buffs, except the debuff on enemies"; Phase Run's primary buff (movement
speed, Phasing) is "replaced" the same way. A character that is dealing damage has neither. Measured on the six
references whose lane held `buffElusive` from Withering Step (author's build, our lane, the input on -> off):
CombinedDPS unchanged, `EffectiveMovementSpeedMod` -0.200 on every one (1.440 -> 1.240 ... 1.728 -> 1.428) and
TotalEHP -10.0% (-12.0% on z327_assassin_poison_spark). +0.20 is the WHOLE movement floor (D55): a socketed
Withering Step paid the boots' job for free and padded the EHP floor, and no DPS number could show it.

Rule: a buff whose source skill's own rules end or replace it on skill use proves nothing in the conservative lane,
for damage and for the floors alike; the list of such skills is a `mechanics/` fact with the wiki quote (PoB cannot
compute it), two entries today. The Withered debuff Withering Step leaves on enemies keeps its ramp rule. Elusive
from a source D77 accepts (on Critical Strike, with its preconditions) stays. Spec:
`docs/specs/2026-09-19-buffs-ended-by-skill-use.md`; the audit gets the matching check. Not yet counted: Elusive
itself decays 20% per second and cannot be refreshed before it expires, so even a legitimate source averages
below PoB's 100% -- a later measurement, not part of this amendment.

