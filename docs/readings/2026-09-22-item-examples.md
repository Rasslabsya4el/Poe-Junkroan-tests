# Item examples 2026-09-22: author / loot / template

Method: raw PoB import codes were base64/zlib-decoded locally (no PobSession, no PoB run) with a
throwaway script; item text and the active ItemSet's slot map were parsed directly from the XML.
Ratio field used for seed selection: `report.md`'s "ours / author (our lane)" column (5th data
column). Per reference, the seed picked is the one whose ratio is the MEDIAN of the three seeds in
that run (not the best).

Slots shown: Weapon 1, Weapon 2, Helmet, Body Armour, Gloves, Boots, Belt, Amulet, Ring 1, Ring 2.
Implicits are shown only for Weapon/Belt/Amulet/Ring slots (kept short); helmet/body/gloves/boots
show explicit + crafted lines only. "(crafted)" marks the bench-craft line PoB stores last.

## stormbrand (core14)

- loot run `20260921-0026-core14-r3`: s1=146%, s2=143%, s3=152% -> median seed **s1, 146%**
- template run `20260921-2020-core14-tpl`: s1=199%, s2=201%, s3=174% -> median seed **s1, 199%**

Files:
- author: `tests/fixtures/tuadh_329/stormbrand.pob.txt`
- loot: `C:\Coding\poe-junkroan-archive\benchmark\20260921-0026-core14-r3\stormbrand-s1.pob.txt`
- template: `C:\Coding\poe-junkroan-archive\benchmark\20260921-2020-core14-tpl\stormbrand-s1.pob.txt`

| slot | author | loot (s1, 146%) | template (s1, 199%) |
|---|---|---|---|
| Weapon 1 | Rare Karui Sceptre (Loath Roar) — implicit 26% Elemental Dmg; Adds 17-27 Phys; +24% Fire Dmg; Adds 26-50 Fire; Adds 10-170 Lightning to Spells; 27% chance to Freeze; (crafted) +15% Cast Speed | Rare Opal Sceptre — implicit 40% Elemental Dmg; +77% Lightning Dmg; Adds 12-176 Lightning to Spells; +5% Attack Speed; +85 Mana; Gain 70 Life per Enemy Killed; (crafted) +16% Cast Speed | Rare Void Sceptre — implicit 40% Elemental Dmg; +77% Lightning Dmg; +19% Cast Speed; +65% Spell Crit Chance; (crafted) Adds 7-120 Lightning to Spells |
| Weapon 2 | Rare Blood Sceptre (Tempest Crusher) — implicit 24% Elemental Dmg; +52% Spell Dmg; Adds 34-72 Cold to Spells; +35% Stun Duration on Enemies; (crafted) +17% Cast Speed | Rare Opal Sceptre — implicit 40% Elemental Dmg; +119% Spell Dmg; +22% Attack Speed; +18% Crit Multi; +35 Mana; +14% Mana Regen; +1 Lvl Lightning Spell Gems | Rare Void Sceptre — identical roll to Weapon 1 (implicit 40% Elemental Dmg; +77% Lightning Dmg; +19% Cast Speed; +65% Spell Crit Chance; (crafted) Adds 7-120 Lightning to Spells) |
| Helmet | Rare Necromancer Circlet (Hate Visage) — +76 Life; Regen 41.8 Life/s; +50 Mana; +21% Fire Res; +42% Cold Res; (crafted) +71% ES | Rare Necromancer Circlet — +19 ES; +62% ES; +128 Life; Regen 34.7 Life/s; +21% Cold Res; (crafted) +23 Int | Rare Royal Burgonet — +107 Life; +33% Cold Res; (crafted) +18 Str/Dex |
| Body Armour | Rare Savant's Robe (Gale Shroud) — 10% Phys hit taken as Cold; +9% Non-Curse Aura Effect; +29 Int; +15 ES; +119 Life; +34 Mana; +42% Cold Res; (crafted) +13% Fire/Cold Res | Rare Savant's Robe — +38 Int; +73% ES; +128 Life; +27% Cold Res; (crafted) +7% Life, +7% Mana | Rare Astral Plate — implicit +10% all Ele Res; +107 Life; +39% Cold Res; (crafted) +18 Str/Dex |
| Gloves | Rare Vaal Gauntlets (Glyph Claw) — 15% chance Extinguish on Hit; Adds 9-19 Fire to Attacks; +111 Life; +13% Life Regen rate; +40% Fire Res; +39% Lightning Res; (crafted) +49% Armour | Rare Vaal Gauntlets — +62 Armour; +25% Armour; +17% Life Regen rate; +32% Fire Res; +39% Cold Res; (crafted) Regen 15 Life/s, +31 Mana | Rare Titan Gauntlets — +41 Armour; +133 Life; +33% Fire Res |
| Boots | Rare Goliath Greaves (Dread Slippers) — 35% chance avoid Ignite; 32% reduced Attr Req; +53% Armour; +116 Life; Regen 25.7 Life/s; +30% MS; +28% Stun/Block Recovery | Rare Goliath Greaves — +25 Str; +84 Armour; +113 Life; +27% Fire Res; +28% Lightning Res; +25% MS | Rare Titan Greaves — +107 Life; +27% Fire Res; +25% MS |
| Belt | Rare Rustic Sash (Doom Trap) — implicit 14% Global Phys Dmg; +98 Life; +52 Mana; +45% Fire Res; +26% Lightning Res; +25% Stun/Block Recovery; +29% Flask Life Recovery rate | Rare Rustic Sash — implicit 18% Global Phys Dmg; +138 Life; +23 Mana; +22% Fire Res; +22% Lightning Res; +23% Elemental Dmg w/ Attack Skills; (crafted) Regen 90 ES/s near Rare/Unique | Rare Heavy Belt — implicit +30 Str; +107 Life; +33% Cold Res; (crafted) +18 Str/Dex |
| Amulet | Magic Stout Jade Amulet of Craft — implicit +23 Dex; +64 Life; (crafted) +20% Lightning Res | Rare Jade Amulet — implicit +25 Dex; +28 all Attr; +30 Int; Adds 6-13 Cold to Attacks; +19% Cast Speed; (crafted) Adds 7-10 Fire, Adds 1-15 Lightning | Rare Amber Amulet — implicit +25 Str; +27% Crit Multi; +92 Life; +39% Cold Res; +39% Lightning Res |
| Ring 1 | Rare Two-Stone Ring (Kraken Knot) — implicit +13% Fire/Cold Res; +131 Accuracy; +10% Cast Speed; +9 Life; (crafted) +19% Lightning Res | Rare Two-Stone Ring — implicit +14% Fire/Cold Res; +41 Str; +64 Evasion; +34 ES; +101 Life; +19% Lightning Res; (crafted) +12 all Attr | Rare Moonstone Ring — implicit 9% Cast Speed; +11% Cast Speed; +92 Life; +39% Fire Res; +27% Lightning Res |
| Ring 2 | Rare Two-Stone Ring (Empyrean Grip) — implicit +12% Fire/Lightning Res; +12% Cast Speed; +95 Life; +29 Mana; (crafted) +14% Cold/Lightning Res | Rare Two-Stone Ring — implicit +14% Fire/Cold Res; +25 Dex; +28 ES; +104 Life; +28% Rarity of Items found; +34% Lightning Res | Rare Ruby Ring — implicit +25% Fire Res; +11% Cast Speed; +92 Life; +27% Lightning Res |

Differences: template's two weapons are identical Void Sceptre rolls with a Spell Crit Chance
suffix (65%) that neither author nor loot weapon has; author's weapon 1 alone carries a huge flat
"Adds 10 to 170 Lightning Damage to Spells" line that no generated build matches. Loot and
template helmet/body/belt/amulet/rings are mostly generic +Life/+Res filler versus the author's
mix of regen and utility mods (Life Regen, Cast Speed on rings, Stun Duration).

## bleed_bow (core14)

- loot run `20260921-0026-core14-r3`: s1=103%, s2=120%, s3=135% -> median seed **s2, 120%**
- template run `20260921-2020-core14-tpl`: s1=145%, s2=125%, s3=136% -> median seed **s3, 136%**

Files:
- author: `tests/fixtures/tuadh_329/bleed_bow.pob.txt`
- loot: `C:\Coding\poe-junkroan-archive\benchmark\20260921-0026-core14-r3\bleed_bow-s2.pob.txt`
- template: `C:\Coding\poe-junkroan-archive\benchmark\20260921-2020-core14-tpl\bleed_bow-s3.pob.txt`

| slot | author | loot (s2, 120%) | template (s3, 136%) |
|---|---|---|---|
| Weapon 1 | Rare Citadel Bow (Vortex Wind) — Adds 21-46 Phys; +18% Attack Speed; +35% Crit Multi; 2.26% Phys Atk Dmg Leeched as Life; (crafted) +91% Phys Dmg | Rare Citadel Bow — implicit +38 Dex; +144% Phys Dmg; Adds 13-25 Phys; Adds 2-6 Cold; +21% Crit Multi; +27% Stun Duration on Enemies | Rare Citadel Bow — implicit 185% Phys Dmg; Adds 19-38 Phys; +85 Accuracy; (crafted) +17% Phys DoT Multi |
| Weapon 2 (quiver) | Rare Heavy Arrow Quiver (Pandemonium Spike) — implicit +9 Dex; Adds 14-24 Phys to Attacks; Adds 6-10 Phys to Attacks; +107 Life; +27% Lightning Res; +29% Projectile Speed | Rare Heavy Arrow Quiver — implicit Adds 14-26 Phys to Attacks; +10 Dex; +89 Life; +21% Fire Res; +29% Lightning Res; +36% Dmg w/ Bow Skills; (crafted) Adds 6-9 Phys to Attacks | Rare Heavy Arrow Quiver — implicit Adds 14-26 Phys to Attacks; +107 Life; +33% Fire Res; +18% Dmg over Time Multi w/ Attacks |
| Helmet | Rare Conqueror's Helmet (Cataclysm Keep) — +62% Armour; +127 Life; +1 Lvl all Minion Gems; +42% Cold Res | Rare Conqueror's Helmet — +73 Armour; +50% Armour; +174 Life; +7% Lightning Res; (crafted) +10% Fire/Chaos Res | Rare Aventail Helmet — +107 Life; +33% Cold Res; (crafted) +18 Dex/Int |
| Body Armour | Rare Battle Lamellar (Dire Cloak) — 1% less Dmg Taken per 220 Dex; +1% max Lightning Res; +265 Armour; +243 Evasion; +69% Armour/Evasion; +131 Life; +38% Fire Res; (crafted) +25% Cold Res | Rare Battle Lamellar — +79 Evasion; +65% Armour/Evasion; +153 Life; +19% Fire Res; (crafted) +10% Fire/Chaos Res | Rare Astral Plate — implicit +10% all Ele Res; +107 Life; +39% Cold Res; (crafted) +18 Dex/Int |
| Gloves | Rare Serpentscale Gauntlets (Soul Claw) — Adds 1-33 Lightning to Attacks; +46 Armour; +46 Evasion; +77 Life; +35% Cold Res | Rare Serpentscale Gauntlets — Adds 3-6 Phys to Attacks; +74% Armour/Evasion; +110 Life; +28% Cold Res; (crafted) +10% Attack Speed | Rare Vaal Gauntlets — +12% Attack Speed; +107 Life; +33% Lightning Res |
| Boots | Rare Goliath Greaves (Viper Trail) — +96 Life; +16% Fire Res; +33% Lightning Res; +25% MS; (crafted) +16% Cold Res | Rare Goliath Greaves — +18 Life; +10% Fire Res; +24% Cold Res; +34% Lightning Res; +20% MS; (crafted) +20 ES | Rare Goliath Greaves — +107 Life; +27% Fire Res; +25% MS |
| Belt | Rare Rustic Sash (Golem Leash) — implicit 22% Global Phys Dmg; +144 Life; +53 Mana; +45% Lightning Res; +31% Stun Duration on Enemies; (crafted) +23% Cold Res | Rare Rustic Sash — implicit 18% Global Phys Dmg; +10 ES; +141 Life; +7% Fire Res; +34% Cold Res; +20% Lightning Res | Rare Leather Belt — implicit +33 Life; +107 Life; +39% Cold Res; +33% Lightning Res; +23% Chaos Res |
| Amulet | Rare Jade Amulet (Wrath Gorget) — implicit +23 Dex; +6% Cast Speed; +21 ES; +95 Life; +38% Lightning Res | Rare Jade Amulet — implicit +25 Dex; +27 all Attr; 14% Rarity found; +25% Cold Res; +32% Lightning Res; (crafted) +48 Life | Rare Turquoise Amulet — implicit +20 Dex/Int; +18% DoT Multi; +92 Life; +39% Fire Res |
| Ring 1 | Rare Sapphire Ring (Apocalypse Turn) — implicit +24% Cold Res; +11 Int; +65 Evasion; Regen 3.3 Life/s; +41 Mana; +44% Fire Res; (crafted) +46 Life | Rare Sapphire Ring — implicit +25% Cold Res; Adds 5-9 Phys to Attacks; +7 ES; +110 Life; +7% all Ele Res; +27% Lightning Res; 11% Dmg Taken Recouped as Life | Rare Iron Ring — implicit Adds 1-4 Phys to Attacks; +92 Life; +27% Lightning Res; (crafted) +13% Dmg |
| Ring 2 | Rare Amethyst Ring (Vortex Coil) — implicit +22% Chaos Res; +188 Accuracy; +89 Life; Regen 7.2 Life/s; +26% Fire Res; (crafted) Adds 3-7 Phys to Attacks | Rare Amethyst Ring — implicit +20% Chaos Res; +26 Int; Adds 7-12 Phys to Attacks; +310 Accuracy; +113 Life; +27% Fire Res; (crafted) +28 ES | Rare Iron Ring — implicit Adds 1-4 Phys to Attacks; +92 Life; +27% Cold Res; (crafted) +13% Dmg |

Differences: template's bow rolled 3 physical-damage prefix lines (185% inc, flat phys, accuracy)
with all 3 suffix slots empty, versus author's 1 physical line + 2 attribute/utility lines (attack
speed, leech) and loot's 1 physical + 2 attribute lines (dex, cold add). Author and loot both use
named/rolled rare bases with leech or attack-speed suffixes; template rings/amulet default to a
single generic prefix+suffix pair (often only Life + one resist) with several empty suffix slots.

## archmage_volatile_dead (new18)

- loot run `20260920-1618-new18-r3`: s1=214%, s2=200%, s3=222% -> median seed **s1, 214%**
- template run `20260921-0929-new18-tpl`: s1=128%, s2=143%, s3=143% -> median is 143% (s2 and s3
  tie on an identical roll, 1,338,502 CombinedDPS both) -> picked **s2, 143%**

Files:
- author: `tests/fixtures/tuadh_329/archmage_volatile_dead.pob.txt`
- loot: `C:\Coding\poe-junkroan-archive\benchmark\20260920-1618-new18-r3\archmage_volatile_dead-s1.pob.txt`
- template: `C:\Coding\poe-junkroan-archive\benchmark\20260921-0929-new18-tpl\archmage_volatile_dead-s2.pob.txt`

| slot | author | loot (s1, 214%) | template (s2, 143%) |
|---|---|---|---|
| Weapon 1 | Rare Omen Wand (Rune Weaver) — +29% Spell Dmg; +22% Phys DoT Multi; +24% Fire Dmg; +13% Lightning Dmg; +120 Mana; +51% Mana Regen Rate; (crafted) Adds 3-74 Lightning to Spells | Rare Prophecy Wand — implicit 38% Spell Dmg; +100% Spell Dmg; +14% Cast Speed; +36 Mana; +1 Lvl Cold Spell Gems; (crafted) 3% chance Double Dmg | Rare Prophecy Wand — implicit 38% Spell Dmg; +105% Spell Dmg; +116 Mana; (crafted) 5% chance Double Dmg |
| Weapon 2 | Rare Vaal Spirit Shield (Hypnotic Spell) — implicit 5% Spell Dmg; +45% Spell Dmg; +48 Mana; +56% Mana Regen Rate; +31% Lightning Res; (crafted) +37% Block Chance | Rare Vaal Spirit Shield — implicit 8% Spell Dmg; +68% Spell Dmg; +14 ES; +27 Life; Regen 5.4 Life/s; +61 Mana; +42% Mana Regen Rate; (crafted) 3% chance Double Dmg | Rare Ceremonial Kite Shield — implicit +12% all Ele Res; +122 Life; +33% Cold Res; (crafted) 5% chance Double Dmg |
| Helmet | Rare Necromancer Circlet (Havoc Glance) — +71% ES; +83 Life; +34% Fire Res; Reflects 7 Phys to Melee Attackers | Rare Necromancer Circlet — +23 ES; +174 Life; +46 Mana; +31% Cold Res; (crafted) +12 all Attr | Rare Hubris Circlet — +107 Life; +33% Cold Res; (crafted) +12 all Attr |
| Body Armour | Rare Silken Wrap (Damnation Shelter) — Purity of Lightning +19% Aura Effect; Flesh and Stone +16% AoE; 32% reduced Attr Req; +91% ES; +41 Mana; +29% Lightning Res; (crafted) +16% faster ES Recharge start | Rare Silken Wrap — 18% reduced Attr Req; +31 Int; +44 ES; +106 Life; +61 Mana; (crafted) +28 Str | Rare Astral Plate — implicit +10% all Ele Res; +40 Str; +107 Life; +39% Cold Res |
| Gloves | Rare Arcanist Gloves (Woe Grasp) — +18 Dex; +96 Life; +37% Fire Res; +33% Cold Res; (crafted) +35 Mana | Rare Arcanist Gloves — +25 Int; +11 ES; +128 Life; +71 Mana; Gain 14 Life per Enemy Killed; (crafted) +28 Str | Rare Arcanist Gloves — +107 Life; +33% Cold Res; (crafted) +50 Mana |
| Boots | Rare Hydrascale Boots (Armageddon Stride) — +75 Armour; +45 Evasion; +24 Life; +26% Fire Res; +20% Lightning Res; +20% MS | Rare Hydrascale Boots — 17% Armour/Evasion; +125 Life; +20% Lightning Res; +30% MS; +8% Stun/Block Recovery; (crafted) +28 Int | Rare Sorcerer Boots — +107 Life; +27% Cold Res; +25% MS |
| Belt | Rare Heavy Belt (Corpse Shackle) — implicit +30 Str; +95 Armour; +57 Life; Regen 18.3 Life/s; +46 Mana; Regen 5.3 Mana/s; (crafted) +27% Lightning Res | Rare Heavy Belt — implicit +30 Str; +39 Str; 14% reduced Enemy Stun Threshold; +143 Life; +48 Mana; +34% Lightning Res; (crafted) +128 Armour, +13 ES | Rare Heavy Belt — implicit +30 Str; +107 Life; +33% Cold Res; (crafted) +13% Dmg |
| Amulet | Rare Jade Amulet (Honour Pendant) — implicit +29 Dex; +40 Dex; Adds 4-41 Lightning to Attacks; +48% Mana Regen Rate; +34% Effect of Non-Dmg Ailments; (crafted) +40 Mana | Rare Jade Amulet — implicit +25 Dex; +31 Int; +29% Armour; +21 ES; +125 Life; +57% Mana Regen Rate; (crafted) Regen 16 Life/s, Regen 2.4 Mana/s | Rare Citrine Amulet — implicit +20 Str/Dex; +92 Life; +39% Cold Res; (crafted) +33 Mana, Regen 3 Mana/s |
| Ring 1 | Rare Ruby Ring (Death Nail) — implicit +26% Fire Res; +19% Cold Dmg; +112 Life; +11% all Ele Res; 0.39% Phys Atk Dmg Leeched as Life; (crafted) +42 Mana | Rare Ruby Ring — implicit +25% Fire Res; +42 Dex; +30 ES; +108 Life; +57 Mana; +39% Fire Res; +31% Cold Res | Rare Two-Stone Ring (Fire/Lightning) — implicit +14% Fire/Lightning Res; +92 Life; +27% Fire Res; (crafted) +33 Mana, Regen 3 Mana/s |
| Ring 2 | Rare Diamond Ring (Sol Eye) — implicit 20% Global Crit Chance; +34 Str; +5 ES; +65 Life; Regen 33.3 Life/s; +59 Mana; +7% all Ele Res; +35% Cold Res | Rare Diamond Ring — implicit 25% Global Crit Chance; +17% Lightning Dmg; +62 Mana; +38% Cold Res; +25% Lightning Res; (crafted) Adds 7-10 Cold, Adds 1-15 Lightning | Rare Two-Stone Ring (Fire/Lightning) — implicit +14% Fire/Lightning Res; +92 Life; +27% Lightning Res; (crafted) +33 Mana, Regen 3 Mana/s |

Differences: loot's Prophecy Wand carries a 3rd prefix ("+1 to Level of all Cold Spell Skill Gems")
and a Cast Speed suffix; the template's identical Prophecy Wand base has no gem-level or
cast-speed roll at all, just 2 mana/damage prefixes. Across almost every template slot the suffix
rows are "None"/near-empty (helmet, boots, gloves, body, belt each carry 1 prefix + 1 resist
suffix only), while loot and the author fill 2-3 suffixes per item with extra ES/mana/attribute
rolls — this is the largest visible pattern behind template's -70.5-point gap here.

## burning_arrow_snipe (new18)

- loot run `20260920-1618-new18-r3`: s1=166%, s2=140%, s3=146% -> median seed **s3, 146%**
- template run `20260921-0929-new18-tpl`: s1=99%, s2=108%, s3=113% -> median seed **s2, 108%**

Files:
- author: `tests/fixtures/tuadh_329/burning_arrow_snipe.pob.txt`
- loot: `C:\Coding\poe-junkroan-archive\benchmark\20260920-1618-new18-r3\burning_arrow_snipe-s3.pob.txt`
- template: `C:\Coding\poe-junkroan-archive\benchmark\20260921-0929-new18-tpl\burning_arrow_snipe-s2.pob.txt`

| slot | author | loot (s3, 146%) | template (s2, 108%) |
|---|---|---|---|
| Weapon 1 | Rare Imperial Bow (Storm Song) — 20% Ele Dmg w/ Attack Skills; Adds 110-181 Fire; Adds 105-200 Cold; Adds 5-88 Lightning; +15% Crit Multi; Gain 29 Mana per Enemy Killed; +278 Accuracy | Rare Imperial Bow — implicit 22% Ele Dmg w/ Attack Skills; Adds 74-138 Fire; Adds 118-216 Cold; Adds 21-390 Lightning; +433 Accuracy; (crafted) +28 Dex | Rare Highborn Bow — implicit 22% Ele Dmg w/ Attack Skills; Adds 74-138 Fire; Adds 17-304 Lightning; +57% Ele Dmg w/ Attack Skills; (crafted) +17% Fire DoT Multi |
| Weapon 2 (quiver) | Unique Primal Arrow Quiver (The Poised Prism) — implicit 29% Ele Dmg w/ Attack Skills; +21% Fire Res; +17% Cold Res; +25% Lightning Res; Adds 1-2 Cold per 10 Dex; Adds 1-2 Fire per 10 Str; Adds 0-3 Lightning per 10 Int | **none equipped** | **none equipped** |
| Helmet | Magic Athlete's Great Crown of Craft — +129 Life; (crafted) +14% Fire/Lightning Res | Rare Great Crown — +262 Accuracy; +31% Armour/ES; +132 Life; +27% Fire Res; +22% Lightning Res; (crafted) +40 ES | Rare Great Crown — +107 Life; +1 Lvl all Minion Gems; +33% Cold Res |
| Body Armour | Rare General's Brigandine (Rapture Veil) — While Unique Enemy in Presence 8% Block Chance; +1% all max Res; +41 Dex; +75% Armour/Evasion; +152 Life; +40% Cold Res; +16% Stun/Block Recovery; (crafted) +255 Evasion | Rare General's Brigandine — +29 Dex; +105 Armour; +123 Evasion; +158 Life; +17% Fire Res; +37% Cold Res | Rare General's Brigandine — implicit +30 Dex; +107 Life; +39% Cold Res |
| Gloves | Rare Assassin's Mitts (Pain Mitts) — +6% Fire DoT Multi; +34 Dex; +13% Attack Speed; +38 Evasion; +112 Life; +35% Cold Res; (crafted) Adds 3-36 Lightning to Attacks | Rare Assassin's Mitts — +343 Accuracy; +59 Evasion; +24 ES; +115 Life; +38% Cold Res; +38% Lightning Res; (crafted) Adds 3-34 Lightning to Attacks | Rare Assassin's Mitts — implicit +35 Dex; +107 Life; +33% Cold Res |
| Boots | Rare Conjurer Boots (Brood Trail) — +13 ES; +37% ES; +27 Life; +25% MS; +34% Stun/Block Recovery; (crafted) +24% Lightning Res | Rare Conjurer Boots — +34 Int; +105 Life; Regen 29.7 Life/s; +17 Mana; +25% MS; (crafted) +12 all Attr | Rare Conjurer Boots — +107 Life; +27% Fire Res; +25% MS |
| Belt | Unique Prismweave — implicit 21% Global Phys Dmg; Adds 15-32 Fire; Adds 12-25 Cold; Adds 1-63 Lightning; +13% all Ele Res; 30% Ele Dmg w/ Attack Skills during Flask | Unique Prismweave (Current) — implicit 12-24% Global Phys Dmg; Adds 14-16 to 30-32 Fire; Adds 10-12 to 24-28 Cold; Adds 1 to 60-68 Lightning; +6-15% all Ele Res; 30% Ele Dmg w/ Attack Skills during Flask | Unique Prismweave (Current) — same roll as loot |
| Amulet | Rare Jade Amulet (Corruption Gorget) — implicit +29 Dex; +11 Dex; +6% Spell Dmg; +141 Accuracy; +68 Life; +9% Cold Res; (crafted) Adds 3-34 Lightning to Attacks | Rare Jade Amulet — implicit +25 Dex; +11% all Attr; +39 Str; +118 Life; +15% all Ele Res; (crafted) +28 ES | Rare Jade Amulet — implicit +25 Dex; +18% DoT Multi; +92 Life; +39% Fire Res |
| Ring 1 | Rare Two-Stone Ring (Rapture Coil) — implicit +13% Fire/Lightning Res; Adds 3-5 Phys to Attacks; Adds 2-22 Lightning to Attacks; +112 Life; +23% Cold Res | Rare Two-Stone Ring — implicit +14% Fire/Cold Res; +20% Fire Dmg; Adds 11-21 Fire to Attacks; +78 Life; Regen 15.2 Life/s; Gain 13 Mana per Enemy Killed; (crafted) +19% Ele Dmg w/ Attack Skills | Rare Two-Stone Ring (Fire/Lightning) — implicit +14% Fire/Lightning Res; +92 Life; +27% Lightning Res; (crafted) Adds 3-45 Lightning to Attacks |
| Ring 2 | Rare Topaz Ring (Foe Knuckle) — implicit +21% Lightning Res; Adds 1-40 Lightning to Attacks; +82 Life; Regen 43.6 Life/s; +32% Fire Res; +30% Cold Res; (crafted) Adds 10-16 Fire to Attacks | Rare Topaz Ring — implicit +25% Lightning Res; +41 Str; +27 Dex; +14 ES; +103 Life; 7% Dmg Taken Recouped as Life; (crafted) Adds 3-45 Lightning to Attacks | Rare Two-Stone Ring (Fire/Lightning) — same roll as Ring 1 |

Differences: neither generated build filled the quiver slot (Weapon 2 = none), losing the author's
unique "The Poised Prism" 3-line per-attribute elemental damage kit entirely. Author's bow has 3
flat elemental damage lines (Fire+Cold+Lightning); loot's bow has 3 too but no Lightning-Res-style
suffix, while template's bow drops the Cold line altogether (only Fire+Lightning) in favor of a
second "% increased Elemental Damage with Attack Skills" prefix.
