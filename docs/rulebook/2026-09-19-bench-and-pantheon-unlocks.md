# Crafting-bench recipes and Pantheon upgrades: where they unlock, and how stable that is (3.25-3.29)

Source: poewiki.net Cargo tables read on 2026-09-19 through `api.php?action=cargoquery` (`crafting_bench_options`,
`crafting_bench_options_costs`, `atlas_nodes`, `areas`, `pantheon_souls`), cached raw in
`var/cache/wiki/2026-09-19-bench-pantheon-cargo.json` and joined in `var/cache/wiki/2026-09-19-crafting-bench-unlocks.json`.
Tier = the area's base tier on the atlas (`atlas_nodes.tier_0`, no Voidstones). Series: Settlers 3.25, Mercenaries 3.26,
Keepers 3.27, Mirage 3.28, Curse of the Allflame 3.29 (the wiki's id `Deepwater`; checked on the Geode page: "tier 6,
northwest quadrant" = `tier_0` 6, region NorthWest).

The GPT report `docs/research/2026-09-19-bench-and-pantheon-unlocks.md` is NOT used: its recipe list comes from a 3.27
third-party guide (Pier = 6 sockets, Lighthouse = 6 links, veiled crafts "by unveiling"), while since 3.26 veiled crafts are
recipe objects in maps (wiki, version history: "41 new Recipe Objects which unlock Veiled Modifier Crafting Recipes") and
its tiers for 3.27-3.29 disagree with the wiki (Cemetery: GPT 4/4/4/6/6, wiki 4/4/4/10/8; Arachnid Tomb: GPT 8/3/3/10/10,
wiki 8/3/14/4/14).

## 1. Where the 829 bench options unlock in 3.29

| where | options |
|---|---:|
| start | 79 |
| campaign | 187 |
| labyrinth | 18 |
| map T1-10 | 422 |
| map T11-16 | 123 |

(`map T1-10` includes 14 options of unique maps whose node has no tier in the 3.28-3.29 series: the five meta-crafts and
Maelström of Chaos; see section 4.)

## 2. Is the unlock tier stable? No.

| map | 3.25 | 3.26 | 3.27 | 3.28 | 3.29 | options | what it unlocks |
|---|---:|---:|---:|---:|---:|---:|---|
| Arachnid Nest | - | - | 8 | - | 2 | 3 | BrandAttachmentRange |
| Fungal Hollow | 3 | - | - | 2 | 2 | 2 | WarcryBuffEffect |
| Marshes | 3 | - | 12 | 16 | 2 | 3 | FlaskEffectAndFlaskChargesGained, FlaskEffectDuration |
| Phantasmagoria | - | 9 | 15 | - | 2 | 5 | LocalCriticalStrikeChance, CriticalStrikeMultiplier, CriticalStrikeChanceSpells2h, CriticalStrikeChanceSpells +1 |
| Ramparts | 8 | 1 | 11 | - | 2 | 6 | ColdDamageOverTimeMultiplierTwoHand, ColdDamageOverTimeMultiplier |
| Reef | - | - | - | 11 | 2 | 6 | LifeRegenerationRate, ReducedPhysicalDamageTaken, ChanceToSuppressSpells, ChanceToSuppressSpellsHigh +2 |
| Cage | 3 | - | - | 12 | 3 | 19 | LocalIncreasedPhysicalDamageAndBleedChanceCrafted, LocalIncreasedPhysicalDamageAndPoisonChanceCrafted, ShockNearbyEnemiesOnFocus, StatusAilmentsYouInflictDurationWhileFocused +4 |
| Frozen Cabins | - | 5 | 10 | 10 | 3 | 3 | IncreasedLife, IncreasedManaTwoHandWeapon, IncreasedManaWeapon |
| Ghetto | - | 5 | 5 | 14 | 3 | 3 | SummonTotemCastSpeed |
| Mesa | 4 | 10 | 4 | 7 | 3 | 4 | ElementalPenetrationWithAttacks, WeaponElementalDamage |
| Strand | 3 | 3 | 3 | 6 | 3 | 2 | CurseEffect |
| Summit | 5 | - | 3 | 4 | 3 | 15 | CriticalStrikeMultiplierIfRareOrUniqueEnemyNearby2h, CriticalStrikeMultiplierIfRareOrUniqueEnemyNearby1h, AttackSpeedPercentIfRareOrUniqueEnemyNearby2h, AttackSpeedPercentIfRareOrUniqueEnemyNearby1h +1 |
| Alleyways | 15 | 1 | 8 | 16 | 4 | 1 | WolfOnKill |
| Bazaar | - | 5 | 8 | - | 4 | 2 | GlobalEnergyShield, MaximumEnergyShield |
| Courthouse | 12 | - | - | 4 | 4 | 8 | CastSpeedAndGainArcaneSurgeOnKillChance2h, CastSpeedAndGainArcaneSurgeOnKillChance1h, LocalAttackSpeedAndLocalDisplayTriggerLevel1BloodRageOnKillChance |
| Flooded Mine | 2 | 14 | 2 | 12 | 4 | 2 | LifeLeechFromAttacksPermyriadSuffix, LocalLifeLeechPermyriadNewSuffix |
| Gardens | 1 | - | - | 13 | 4 | 11 | AddedFireAndColdDamage, AddedFireAndLightningDamage, AddedColdAndLightningDamage, IncreasedFireAndLightningDamage |
| Port | 11 | - | 8 | 2 | 4 | 7 | DamageDuringFlaskEffect, LocalFlaskLifeRegenerationPerMinuteDuringFlaskEffect, LocalFlaskAvoidStunChanceDuringFlaskEffect, LocalFlaskItemFoundRarityDuringFlaskEffect +2 |
| Colonnade | 5 | 8 | - | - | 5 | 10 | ChanceToDealDoubleDamageWhileFocused2h, ChanceToDealDoubleDamageWhileFocused1h, DoubleDamageChance2h, DoubleDamageChance1h |
| Dunes | 2 | 2 | 2 | 5 | 5 | 4 | LocalAccuracyRatingStrengthDexterity, LocalAccuracyRating, AccuracyRating |
| Laboratory | - | 3 | - | - | 5 | 2 | AllDamage |
| Overgrown Shrine | 3 | 3 | 3 | 7 | 5 | 14 | MineLayingSpeed, TrapThrowSpeed, TrapDamageOnWeapon2h, TrapDamageOnWeapon1h +5 |
| Primordial Blocks | - | 7 | 7 | 12 | 5 | 14 | StrengthAndDexterity, DexterityAndIntelligence, StrengthAndIntelligence, PercentageAllAttributes +3 |
| Relic Chambers | 4 | - | - | 5 | 5 | 4 | LocalIncreasedBlockPercentage, SpellBlockPercentage, StaffAttackBlock, StaffSpellBlock |
| Shrine | - | - | - | 1 | 5 | 9 | PhysicalDamageReductionRatingDuringSoulGainPrevention, DamageWithNonVaalSkillsDuringSoulGainPrevention, AvoidElementalDamageChanceDuringSoulGainPrevention, GainOnslaughtDuringSoulGainPrevention |
| Siege | 1 | 4 | - | 11 | 5 | 4 | MinionLife, MinionMovementSpeed, MinionDamageOnWeapon2h, MinionDamageOnWeapon1h |
| Cold River | 8 | 14 | - | 6 | 6 | 1 | DegenerationDamage |
| Coral Ruins | 9 | 9 | - | 7 | 6 | 63 | LocalIncreasedArmourAndEvasionAndLife, LocalIncreasedArmourAndEnergyShieldAndLife, LocalIncreasedEvasionAndEnergyShieldAndLife, LocalIncreasedArmourAndLife +17 |
| Geode | 12 | 2 | - | - | 6 | 28 | ArmourAndEvasionRating, ArmourAndEnergyShield, EvasionRatingAndEnergyShield, DodgeChanceDuringFocus +12 |
| Pier | 11 | 13 | - | - | 6 | 2 | BannerAuraEffect |
| Shipyard | - | 8 | 1 | 15 | 6 | 9 | FireAndChaosDamageResistance, LightningAndChaosDamageResistance, ColdAndChaosDamageResistance |
| Sunken City | - | 12 | - | - | 6 | 9 | IncreasedManaAndRegen, ManaAndDamageTakenGoesToManaPercent, ManaRegeneration, IncreasedManaRegenerationTwoHandWeapon +1 |
| Excavation | - | - | 3 | 10 | 7 | 6 | ChaosDamageOverTimeMultiplierTwoHand, ChaosDamageOverTimeMultiplier |
| Haunted Mansion | 9 | - | - | 11 | 7 | 6 | PhysicalDamageOverTimeMultiplierTwoHand, PhysicalDamageOverTimeMultiplier |
| Silo | 8 | 11 | 4 | 16 | 7 | 7 | BaseLifeAndManaRegen, BaseManaAndLifeRegen, PercentageLifeAndMana |
| Sulphur Vents | 10 | - | 15 | 3 | 7 | 1 | IncreasedLife |
| Terrace | 15 | 1 | - | 4 | 7 | 2 | ItemRarityFromRareAndUniqueEnemies |
| Tropical Island | 2 | 8 | 2 | 5 | 7 | 6 | FireDamageOverTimeMultiplierTwoHand, FireDamageOverTimeMultiplier |
| Basilica | 9 | 6 | - | - | 8 | 5 | RestoreManaAndEnergyShieldOnFocus, GlobalEnergyShield, MaximumEnergyShield |
| Caldera | 13 | - | - | - | 8 | 12 | ColdDamageAndBaseChanceToFreeze2h, ColdDamageAndBaseChanceToFreeze1h, ColdDamageTwoHandPrefix, ColdDamagePrefix +4 |
| Cemetery | 4 | 4 | 4 | 10 | 8 | 4 | LightningAddedAsChaos2h, LightningAddedAsChaos1h |
| Desert Spring | 13 | 9 | 13 | - | 8 | 12 | LightningDamageAndChanceToShock2h, LightningDamageAndChanceToShock1h, LightningDamageTwoHandPrefix, LightningDamagePrefix +4 |
| Lava Lake | 2 | 6 | 9 | 9 | 8 | 5 | LocalCriticalStrikeChance, CriticalStrikeMultiplier, CriticalStrikeChanceSpells2h, CriticalStrikeChanceSpells +1 |
| Pit | 15 | - | 8 | 13 | 8 | 1 | Five Sockets |
| City Square | 8 | 7 | 7 | 7 | 9 | 6 | LocalIncreasedBlockPercentage, SpellBlockPercentage, BlockPercent, SpellBlockPercent +2 |
| Jungle Valley | 8 | 11 | 4 | 5 | 9 | 6 | DamageWhileLeeching, LifeLeechFromAttacksPermyriadSuffix, LocalLifeLeechPermyriadNewSuffix, LocalManaLeechPermyriadNewSuffix +1 |
| Lookout | 12 | - | 6 | 2 | 9 | 4 | FireAddedAsChaos2h, FireAddedAsChaos1h |
| Palace | 9 | 15 | 3 | 16 | 9 | 4 | ColdAddedAsChaos2h, ColdAddedAsChaos1h |
| Plateau | 5 | 4 | 15 | - | 9 | 1 | LightRadiusScalesWithEnergyShield |
| Vault | 4 | 8 | - | - | 9 | 4 | PhysicalAddedAsChaos2h, PhysicalAddedAsChaos1h |
| Atoll | 5 | 5 | 5 | 3 | 10 | 3 | PhysicalDamageConvertedToFire, PhysicalDamageConvertedToCold, PhysicalDamageConvertedToLightning |
| Core | - | 3 | 2 | 2 | 10 | 12 | AvoidFreeze, AvoidStun, AvoidElementalAilments, ReducedElementalAilmentEffect +7 |
| Crater | 11 | - | 10 | 15 | 10 | 11 | ChaosDamageAndChaosSkillDuration2h, ChaosDamageAndChaosSkillDuration1h, ChaosPenetrationWithAttacks, ChaosDamageTwoHandPrefix +1 |
| Lair | 2 | - | - | 10 | 10 | 6 | LifeRegenerationRate, ReducedPhysicalDamageTaken, ChanceToSuppressSpells, ChanceToSuppressSpellsHigh +2 |
| Promenade | 6 | 6 | 6 | 1 | 10 | 9 | MovementVelocityAndMovementVelocityIfNotHitRecently, MovementVelocityAndOnslaughtOnKill, MovementVelocityAndCannotBeChilled |
| Arid Lake | - | 10 | 9 | 13 | 11 | 1 | Six Sockets |
| Factory | - | - | 4 | 14 | 11 | 12 | FireDamageAndChanceToIgnite2h, FireDamageAndChanceToIgnite1h, FireDamageTwoHandPrefix, FireDamagePrefix +4 |
| Foundry | 11 | 4 | - | 14 | 11 | 9 | LocalIncreasedPhysicalDamageAndImpaleCrafted, LocalIncreasedPhysicalDamageAndBlindChanceCrafted, IncreasedChaosAndPhysicalDamage, LocalIncreasedPhysicalDamage |
| Orchard | 16 | 11 | 14 | 4 | 11 | 16 | MinionDamageAndMinionMaximumLife2h, MinionDamageAndMinionMaximumLife1h, MinionAttackAndCastSpeedOnWeapon2h, MinionAttackAndCastSpeedOnWeapon1h +4 |
| Stagnation | - | - | - | - | 11 | 3 | ChaosResistanceToDamageOverTime, ReducedDamageOverTimeTaken |
| Volcano | - | - | 2 | 1 | 11 | 3 | GlobalCooldownRecovery, FocusCooldownRecovery |
| Dark Forest | 2 | 4 | 9 | 2 | 12 | 3 | MinimumEnduranceCharges, DamagePerEnduranceCharge2h, DamagePerEnduranceCharge1h |
| Iceberg | - | 10 | 5 | 7 | 12 | 6 | CriticalChanceAndGainFrenzyChargeOnCriticalStrikePercent, MinimumFrenzyCharges, DamagePerFrenzyCharge2h, DamagePerFrenzyCharge1h |
| Malformation | 10 | 13 | - | - | 12 | 14 | SpellDamageAndManaRegenerationRate2h, SpellDamageAndManaRegenerationRate1h, SpellDamageAndNonChaosDamageToAddAsChaosDamage2h, SpellDamageAndNonChaosDamageToAddAsChaosDamage1h +2 |
| Plaza | - | - | - | 9 | 12 | 1 | Five Linked Sockets |
| Temple | 14 | 14 | 14 | - | 12 | 3 | MinimumPowerCharges, DamagePerPowerCharge2h, DamagePerPowerCharge1h |
| Beach | 14 | 13 | 16 | 10 | 13 | 2 | SocketedGemQuality |
| Bramble Valley | 7 | 9 | 5 | 8 | 13 | 4 | AreaDamageAndAreaOfEffect, SkillAreaOfEffectPercentAndAreaOfEffectGemLevel1- |
| Ivory Temple | - | 5 | 16 | 12 | 13 | 4 | ProjectileDamageAndProjectileSpeed, ProjectilePierceAndProjectileGemLevel |
| Mausoleum | 4 | 2 | 9 | 13 | 13 | 4 | MeleeDamageAndMeleeRange, MeleeRangeAndMeleeGemLevel |
| Residence | 14 | - | 2 | 9 | 13 | 12 | AttackAndCastSpeed, AttackAndCastSpeedWhileFocused, LocalAttackSpeedDexterityIntelligence, LocalIncreasedAttackSpeed +3 |
| Arachnid Tomb | 8 | 3 | 14 | 4 | 14 | 1 | AlwaysHits |
| Belfry | 6 | 11 | 11 | 3 | 14 | 13 | CriticalChanceAndElementalDamagePercentIfHaveCritRecently, CriticalChanceAndAddedChaosDamageIfHaveCritRecently, CriticalMultiplierOnShatter, LocalCriticalStrikeChanceStrengthIntelligence +3 |
| Tower | - | 16 | 7 | 9 | 14 | 9 | ManaAndManaCostEfficiency, ReduceGlobalFlatManaCostChannelling, ReduceGlobalFlatManaCostNonChannelling |
| Grotto | 11 | 10 | 8 | 2 | 16 | 1 | Six Linked Sockets |
| Primordial Pool | - | - | 10 | 8 | 16 | 2 | LocalIncreaseSocketedSupportGemLevel |
| Caer Blaidd, Wolfpack's Den | 15 | 15 | 15 | - | - | 1 | ItemGenerationCannotRollAttackAffixes |
| Maelström of Chaos | 5 | 5 | 5 | - | - | 9 | StrengthAndAvoidIgnite, DexterityAndAvoidFreeze, IntelligenceAndAvoidShock |
| Oba's Cursed Trove | 10 | 10 | 10 | - | - | 1 | ItemGenerationCannotChangeSuffixes |
| The Coward's Trial | 7 | 7 | 7 | - | - | 1 | ItemGenerationCannotChangePrefixes |
| The Putrid Cloister | 12 | 12 | 12 | - | - | 1 | ItemGenerationCanHaveMultipleCraftedMods |
| Whakawairua Tuahu | 3 | 3 | 3 | - | - | 1 | ItemGenerationCannotRollCasterAffixes |

`-` = the map was not on that league's atlas. Of 82 recipe maps, **49 were on both sides of the T10 line** within the five
leagues and only 10 stayed at T10 or below in all five. The recipe itself also moves: the wiki's patch-note line is "Crafting
Recipes that were previously unlocked in Maps that have been removed are now found within other Maps currently on the Atlas."
So the unlock tier is league data, refreshed every league (`docs/DATA_FRESHNESS.md`), never a constant.

## 3. What sits above T10 in 3.29 (not available to a day-1 loadout under a "maps up to T10" rule)

| map | tier | crafts (family: ranks) |
|---|---:|---|
| Factory | 11 | FireDamageAndChanceToIgnite1h: 1,2,3; FireDamageAndChanceToIgnite2h: 1,2,3; FireDamagePrefix: 3; FireDamageTwoHandPrefix: 3; LocalFireDamage: 3; LocalFireDamageTwoHand: 3; SpellAddedFireDamage: 3; SpellAddedFireDamageTwoHand: 3 |
| Foundry | 11 | IncreasedChaosAndPhysicalDamage: 1,2; LocalIncreasedPhysicalDamage: 4; LocalIncreasedPhysicalDamageAndBlindChanceCrafted: 1,2,3; LocalIncreasedPhysicalDamageAndImpaleCrafted: 1,2,3 |
| Orchard | 11 | MaximumZombieAndSkeleton: 0; MinionAttackAndCastSpeedOnWeapon1h: 1,2,3; MinionAttackAndCastSpeedOnWeapon2h: 1,2,3; MinionDamageAndMinionMaximumLife1h: 1,2,3; MinionDamageAndMinionMaximumLife2h: 1,2,3; MinionDamageOnWeapon1h: 3; MinionDamageOnWeapon2h: 3; MinionsRecoverMaximumLifeWhenYouFocus: 0 |
| Stagnation | 11 | ChaosResistanceToDamageOverTime: 1,2; ReducedDamageOverTimeTaken: 0 |
| Volcano | 11 | FocusCooldownRecovery: 0; GlobalCooldownRecovery: 1,2 |
| Dark Forest | 12 | DamagePerEnduranceCharge1h: 0; DamagePerEnduranceCharge2h: 0; MinimumEnduranceCharges: 0 |
| Iceberg | 12 | CriticalChanceAndGainFrenzyChargeOnCriticalStrikePercent: 1,2,3; DamagePerFrenzyCharge1h: 0; DamagePerFrenzyCharge2h: 0; MinimumFrenzyCharges: 0 |
| Malformation | 12 | SpellDamageAndManaRegenerationRate1h: 1,2,3; SpellDamageAndManaRegenerationRate2h: 1,2,3; SpellDamageAndNonChaosDamageToAddAsChaosDamage1h: 1,2,3; SpellDamageAndNonChaosDamageToAddAsChaosDamage2h: 1,2,3; SpellDamageOnTwoHandWeapon: 4; SpellDamageOnWeapon: 4 |
| Temple | 12 | DamagePerPowerCharge1h: 0; DamagePerPowerCharge2h: 0; MinimumPowerCharges: 0 |
| Beach | 13 | SocketedGemQuality: 1,2 |
| Bramble Valley | 13 | AreaDamageAndAreaOfEffect: 1,2,3; SkillAreaOfEffectPercentAndAreaOfEffectGemLevel1-: 0 |
| Ivory Temple | 13 | ProjectileDamageAndProjectileSpeed: 1,2,3; ProjectilePierceAndProjectileGemLevel: 0 |
| Mausoleum | 13 | MeleeDamageAndMeleeRange: 1,2,3; MeleeRangeAndMeleeGemLevel: 0 |
| Residence | 13 | AttackAndCastSpeed: 1,2,3; AttackAndCastSpeedWhileFocused: 1,2,3; IncreasedCastSpeed: 3; IncreasedCastSpeedTwoHand: 3; LocalAttackSpeedDexterityIntelligence: 1,2; LocalIncreasedAttackSpeed: 3; LocalIncreasedAttackSpeedRanged: 3 |
| Arachnid Tomb | 14 | AlwaysHits: 0 |
| Belfry | 14 | CriticalChanceAndAddedChaosDamageIfHaveCritRecently: 1,2,3; CriticalChanceAndElementalDamagePercentIfHaveCritRecently: 1,2,3; CriticalMultiplierOnShatter: 1,2; CriticalStrikeMultiplier: 3; LocalCriticalStrikeChance: 3; LocalCriticalStrikeChanceStrengthIntelligence: 1,2; LuckyCriticalsDuringFocus: 0 |
| Tower | 14 | ManaAndManaCostEfficiency: 1,2,3; ReduceGlobalFlatManaCostChannelling: 1,2,3; ReduceGlobalFlatManaCostNonChannelling: 1,2,3 |
| Primordial Pool | 16 | LocalIncreaseSocketedSupportGemLevel: 1,2 |

## 4. Crafts that cost Exalted or Divine Orbs

| craft | cost | where | tier 3.29 |
|---|---|---|---:|
| EinharMasterLocalIncreasedPhysicalDamage4___ | 4x Exalted Orb | Foundry | 11 |
| EinharMasterSpellDamageOnTwoHandWeapon4_ | 4x Exalted Orb | Malformation | 12 |
| EinharMasterSpellDamageOnWeapon4 | 4x Exalted Orb | Malformation | 12 |
| EinharMasterLocalIncreasedAttackSpeed3 | 4x Exalted Orb | Residence | 13 |
| EinharMasterLocalIncreasedAttackSpeedRanged3 | 4x Exalted Orb | Residence | 13 |
| EinharMasterIncreasedCastSpeedTwoHand3_ | 4x Exalted Orb | Residence | 13 |
| EinharMasterIncreasedCastSpeed3 | 4x Exalted Orb | Residence | 13 |
| JunMaster2SpellDamageAndNonChaosDamageToAddAsChaosDamage2h3 | 4x Exalted Orb | Malformation | 12 |
| JunMaster2SpellDamageAndNonChaosDamageToAddAsChaosDamage1h3 | 4x Exalted Orb | Malformation | 12 |
| JunMaster2ElementalPenetrationWithAttacks3 | 4x Exalted Orb | Mesa | 3 |
| JunMaster2MinimumEnduranceCharges1 | 4x Exalted Orb | Dark Forest | 12 |
| JunMaster2MinimumFrenzyCharges1_ | 4x Exalted Orb | Iceberg | 12 |
| JunMaster2MinimumPowerCharges1 | 4x Exalted Orb | Temple | 12 |
| JunMaster2FlaskEffectAndFlaskChargesGained2 | 4x Exalted Orb | Marshes | 2 |
| JunMaster2GlobalCooldownRecovery2 | 4x Exalted Orb | Volcano | 11 |
| JunMaster2CurseEffect2 | 4x Exalted Orb | Strand | 3 |
| JunMaster2AllDamage3 | 4x Exalted Orb | Laboratory | 5 |
| JunMaster2LocalIncreaseSocketedSupportGemLevel2 | 4x Exalted Orb | Primordial Pool | 16 |
| JunMaster2DamageWhileLeeching3 | 4x Exalted Orb | Jungle Valley | 9 |
| JunMaster2SocketedGemQuality3 | 4x Exalted Orb | Beach | 13 |
| JunMaster2AlwaysHits1 | 4x Exalted Orb | Arachnid Tomb | 14 |
| JunMaster2AvoidFreeze3 | 4x Exalted Orb | Core | 10 |
| JunMaster2LocalAttackSpeedDexterityIntelligence2 | 4x Exalted Orb | Residence | 13 |
| JunMaster2LocalCriticalStrikeChanceStrengthIntelligence2___ | 4x Exalted Orb | Belfry | 14 |
| JunMaster2LocalAttackSpeedAndLocalDisplayTriggerLevel1BloodRageOnKillChance2 | 4x Exalted Orb | Courthouse | 4 |
| JunMaster2AreaDamageAndAreaOfEffect3 | 4x Exalted Orb | Bramble Valley | 13 |
| JunMaster2ProjectileDamageAndProjectileSpeed3 | 4x Exalted Orb | Ivory Temple | 13 |
| JunMaster2MeleeDamageAndMeleeRange3_ | 4x Exalted Orb | Mausoleum | 13 |
| StrMasterItemGenerationCannotChangePrefixes | 2x Divine Orb | The Coward's Trial | - |
| DexMasterItemGenerationCannotChangeSuffixes | 2x Divine Orb | Oba's Cursed Trove | - |
| StrIntMasterItemGenerationCanHaveMultipleCraftedMods | 2x Divine Orb | The Putrid Cloister | - |
| IntMasterItemGenerationCannotRollAttackAffixes | 1x Divine Orb | Caer Blaidd, Wolfpack's Den | - |
| StrDexMasterItemGenerationCannotRollCasterAffixes | 1x Divine Orb | Whakawairua Tuahu | - |

## 5. Flat life on the bench (the craft every life build wants)

| craft | rank | where | tier 3.29 | tiers 3.25-3.29 | cost |
|---|---:|---|---:|---|---|
| HelenaMasterIncreasedLife1 | 1 | starts unlocked | - | -/-/-/-/- | 1x Orb of Alteration |
| EinharMasterIncreasedLife2 | 2 | The Beacon | - | -/-/-/-/- | 6x Orb of Transmutation |
| EinharMasterIncreasedLife3 | 3 | The Feeding Trough | - | -/-/-/-/- | 2x Orb of Alchemy |
| EinharMasterIncreasedLife4 | 4 | Frozen Cabins | 3 | -/5/10/10/3 | 4x Orb of Alchemy |
| EinharMasterIncreasedLife5_ | 5 | Sulphur Vents | 7 | 10/-/15/3/7 | 4x Chaos Orb |

## 6. Pantheon: base powers come from act bosses; each upgrade is a map boss captured with a Divine Vessel

| soul | upgrade | target map (3.29) | 3.25 | 3.26 | 3.27 | 3.28 | 3.29 | what it gives |
|---|---:|---|---:|---:|---:|---:|---:|---|
| Abberath | 1 | Summit | 5 | - | 3 | 4 | 3 | Unaffected by Burning Ground 10% increased Movement Speed while on Burning Ground |
| Arakaali | 1 | Overgrown Shrine | 3 | 3 | 3 | 7 | 5 | 20% increased Recovery rate of Life and Energy Shield if you've stopped taking Damage Over Time Recently |
| Arakaali | 2 | Sunken City | - | 12 | - | - | 6 | Debuffs on you expire 20% faster |
| Arakaali | 3 | Arid Lake | - | 10 | 9 | 13 | 11 | +40% Chaos Resistance against Damage Over Time |
| Garukhan | 1 | Dunes | 2 | 2 | 2 | 5 | 5 | Cannot be Blinded You cannot be Maimed |
| Gruthkul | 1 | Cemetery | 4 | 4 | 4 | 10 | 8 | Enemies that have Hit you with an Attack Recently have 8% reduced Attack Speed |
| Lunaris | 1 | Frozen Cabins | - | 5 | 10 | 10 | 3 | 10% chance to avoid Projectiles |
| Lunaris | 2 | Waterways | - | 7 | 2 | 2 | 10 | 6% reduced Elemental Damage taken if you have been Hit Recently |
| Lunaris | 3 | Beach | 14 | 13 | 16 | 10 | 13 | Avoid Projectiles that have Chained |
| Ralakesh | 1 | Fields | 5 | - | - | 8 | 14 | Corrupted Blood cannot be inflicted on you if you have at least 5 Corrupted Blood Debuffs on you |
| Ryslatha | 1 | Infested Valley | 12 | - | 7 | - | 15 | Enemies you've Hit Recently have 50% reduced Life Regeneration rate |
| Shakari | 1 | Desert Spring | 13 | 9 | 13 | - | 8 | 5% reduced Chaos Damage taken 25% reduced Chaos Damage over Time taken while on Caustic Ground |
| Solaris | 1 | Mesa | 4 | 10 | 4 | 7 | 3 | 8% reduced Elemental Damage taken if you haven't been Hit Recently |
| Solaris | 2 | Lava Lake | 2 | 6 | 9 | 9 | 8 | Take no Extra Damage from Critical Strikes if you have taken a Critical Strike Recently |
| Solaris | 3 | Volcano | - | - | 2 | 1 | 11 | 50% chance to avoid Ailments from Critical Strikes |
| TheBrineKing | 1 | Reef | - | - | - | 11 | 2 | 30% increased Stun and Block Recovery |
| TheBrineKing | 2 | Coral Ruins | 9 | 9 | - | 7 | 6 | 100% chance to Avoid being Frozen |
| TheBrineKing | 3 | Mineral Pools | - | 7 | 10 | 4 | 12 | 50% reduced Effect of Chill on you |
| Tukohama | 1 | Siege | 1 | 4 | - | 11 | 5 | Regenerate 2% of Life per second while stationary |
| Yugul | 1 | Terrace | 15 | 1 | - | 4 | 7 | 30% reduced Effect of Curses on you |

The target map of an upgrade is current-league data as well (the wiki's 3.5.0 note: the map bosses "are mostly shuffled with new
map series that released in each new league").
