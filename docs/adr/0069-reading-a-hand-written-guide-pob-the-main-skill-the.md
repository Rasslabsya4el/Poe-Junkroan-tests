# 2026-09-18 D69. Reading a hand-written guide PoB: the main skill, the ascendancy, the gems, the twins

Status: Accepted

The second reference set (`--set ziz`: the early-game loadout of 31 Zizaran / Maxroll league
starters, 3.25-3.29) is hand-written guide PoBs, and it broke four assumptions the Tuadh day-1
snapshots never tested. Each was a silent wrong number, not an error.

**1. The head of the main link is the active skill `mainActiveSkill` names, not `gems[0]`.**
PoB's `mainActiveSkill` is a 1-based index into a socket group's *active skill list*
(`Modules/CalcSetup.lua`: built gem by gem over each gem's `grantedEffectList` with the supports
skipped, clamped with `m_min(#socketGroupSkillList, group.mainActiveSkill or 1)`;
`Modules/Build.lua` reads `displaySkillList[mainActiveSkill]` as the build's main skill), and a
Vaal gem grants two skills and takes two places in it. An author may socket a support first, and
three references did: z327_necromancer_raise_spectre leads with Minion Damage and
z328_hierophant_shock_nova_archmage with Archmage, so `objective_for` was handed a support name,
picked CombinedDPS over FullDPS and scored those references **0**; z329_occultist_essence_drain
leads with Spellslinger, an active gem that deals no damage, the author pointing at entry 3.
`socket_groups_from_xml` now moves that gem to the front and keeps the supports in the author's
order (`main_active_gem_index`). No Tuadh reference moves: their authors socket the main skill
first.

**2. The author's gems go on the rails before anything is read off them.** Our build is always
socketed at the rails' gems (level 18, quality 0, main skill at `main_skill_quality`); Zizaran's
early loadouts are 20/20 throughout. D23 already says never to compare on unequal gem levels -- it
was enforced on our side only. `scripts/benchmark.py` now rewrites every `<Gem level= quality=>` of
the author's build (`normalize_author_gems`) in the preamble, before `author_raw`, and every later
reload in that preamble carries them; the fixture files keep the author's own values and the
results row records them as `author_gem_levels` (the medians before the rewrite). A level outside a
gem's own range is PoB's to clamp (`Modules/CalcTools.lua` `validateGemLevel`), exactly as it
clamps ours. The author memo now carries `gem_rails` ("18/0/0") next to `tree_version`, so a memo
written before this is not replayed.

Measured on the author's own config, CombinedDPS before -> after, with
`disable_unreliable_buff_gems_xml` applied to both sides as the benchmark does:

| set | n | median | min | max |
|---|---|---|---|---|
| tuadh | 32 | **+0.0%** | -18.8% (elemental_hit) | +16.5% (shockwave_cyclone) |
| ziz | 26 | **-21.9%** | -45.6% (z327_elementalist_lightning_conduit) | +9.0% (z327_hierophant_storm_burst) |

| fixture | author's gems (median) | CombinedDPS | FullDPS |
|---|---|---|---|
| stormbrand | 18/0, 10 gems rewritten | 898,678 -> 860,900 (-4.2%) | 1,797,356 -> 1,721,800 (-4.2%) |
| bleed_bow | 18/0, 10 gems rewritten | 657,803 -> 633,708 (-3.7%) | 0 -> 0 |
| z328_hierophant_shock_nova_archmage | 20/20, 19 gems | 784,607 -> 754,895 (-3.8%) | |
| z329_elementalist_winter_orb | 20/20, 23 gems | 196,708 -> 117,211 (-40.4%) | |

The Tuadh set is a wash at the median, as it must be -- the rails were derived from those builds --
and individual references move both ways because an author's own gems are level 17-19 with a
quality 0-20 main skill. The ziz set loses a fifth of its number, which is the point: our 18/0
build was being compared with a 20/20 author. Lower author rows mean higher "% of author" on that
campaign; that is a corrected comparison, not an easier one.

**3. An ascendancy with no ascendancy class set is read from the allocated nodes.**
z326_chieftain_righteous_fire exports `ascendClassName="None"` (the spec the author left active is
their level 1-20 one) with six Chieftain nodes allocated; `Skeleton.apply` would have called
`set_tree(ascendancy_id="None")` and lost the ascendancy entirely. `skeleton_from_xml` now infers
it from the corpus node -> ascendancy map, filtered by the build's class, and logs the line. PoB's
own `read_state()["ascendancy_readback"]` agrees ("Chieftain"), which is what the test asserts
against.

**4. A re-published guide is one reference, not two.** An author re-publishes a guide unchanged and
the same build then appears under several leagues. Five of the 31 extracted loadouts are older
copies of a build PoB reads identically (equal level, allocated nodes, Life, TotalEHP, CombinedDPS
and FullDPS in the folders' `stats.json`, same allocated node set, same items, same gems; what
differs is the declared tree version, PoB's own empty slots -- "Graft 1/2", "Ring 3" -- and the gem
rename "Lesser Multiple Projectiles" -> "Multiple Projectiles"). `SETS["ziz"]` keeps the newest
league's copy of each and is **26** references; the fixture files all stay in place, and the twins
are listed in `ZIZ_REPUBLISHED` so a test can hold the claim against those stats.json numbers:
champion_explosive_arrow 327 = 328 = 329, elementalist_lightning_conduit 326 = 327,
gladiator_earthquake 326 = 327, juggernaut_boneshatter 328 = 329 (z325 Explosive Arrow, z329
Earthquake and z327 Boneshatter differ and stay). Counting the copies would have weighted four
builds 2-3x in the medians for nothing.

