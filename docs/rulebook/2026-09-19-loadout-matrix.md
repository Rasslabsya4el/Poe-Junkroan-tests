# Loadout matrix: which system of the game is allowed from which loadout (the user, 2026-09-19)

Filled by the user in the artifact form (https://claude.ai/artifact/8NUYbPusXf4XoekHdXhDaG); the notes are the user's words,
verbatim. The loadout is the EARLIEST one that allows the system; every later loadout inherits it. Systems come from
`docs/research/2026-09-19-game-systems-inventory.md`. Machine-readable copy: `2026-09-19-loadout-matrix.json`.


## day-1 (T10) (26)

- **Active skill gems** -- это база, будет работать даже если однажды решим чтобы поб делал лодауты под акты
- **Anointments and oil allocation** -- Тут важно спарсить дроплвл масел. Ты должен их соотнести с лвлом в рейле каждого лодаута, чтобы распределить масла по лодаутам. Чтобы к примеру в дей 1 не было голден масел. Призматик ойлы с эндгейма
- **Area/map modifiers (environment, not a loadout)** -- Это в беклог. Тут много можно будет интересного оптимальног опридумать. К примеру - резы согласно т16 эле уикнес + экспоужер чтобы капить резы от такой комбинации. Или капить аккураси в зависимости от лесс аура эффект на мапе (а у нас пресижн аура) или лесс аккураси/мо эвейжн мода у мобов. Но пока что не трогаем это. Это кволити оф лайф будет для билдов и посмотрим, мб для этого тоже будем отдельный лодаут делать хз пока
- **Ascendancy and alternate ascendancy** -- Основные асенденси с дей 1 (на самом деле еще в актах, но там в зависимости от прогрессии, сейчсас не важно). Альтернативные асенденси с т16.
- **Bandit quest choice** -- это база, будет работать даже если однажды решим чтобы поб делал лодауты под акты
- **Character class and class start** -- Это определяется на стадии скелета, стартовая точка дерева не меняется (во всяком случае пока что в игре, возможно что то такое отднажды добавят). Единственное исключение это сционка. У нее по моему основной сабкласс дает возможность брать 2 разные старты одновременно взависимости от сабкласса в сабклассе (надеюсь это мейкс сенс). Это должно работать корректно. И это должно быть с дей 1 у сционки.
- **Character level and quest passive points** -- Квесты всегда на макс и бандиты килл олл. Дей 1 лвл 75-80, т16 лвл 90-95, эндгейм лвл 95-100, миррор 100. Мне кажется очень важно сделать такой джигл лвлов. Чтобы система не делала странные решения типо 2 маленьких нода не проходных. А чтобы она могла закончить дерево на максимально эффишент поинте.
- **Cluster jewels** -- Айлвл баз берем из общего рейла баз (как и везде просто уточняю)Дей 1: лардж/медиум размер, не меньше 12/6 поинтов соответственно, т16: все типы, все колва поинтов. Мегаломениак уник кластер: 2 полезных пассивки эндгейм, 3 полезных миррор. Войсес кластер: 7 пассивок эндгейм, 1 пассивка миррор (5 и 3 надо будет кидать в доп лодауты между эндгейм и миррор если будем их делать)
- **Configurable combat state and enemy state** -- это база, будет работать даже если однажды решим чтобы поб делал лодауты под акты
- **Crafting-bench modifiers** -- С бенчкрафтами такая штука что какие то открываются в актах, а какие то на мапах. И у мап 16 тиров + мапы каждую лигу меняются. Как то спрогнозировать какой бенчкрафт открывается до т10, а какой до т16 сложно. Но может реально? Попробуй это спарсить с поедб и решим что с этим делать. Было бы очень круто если система это учитывала. Что касается бенчкрафтов с уник мап (мультимод, преф/суф кеннот би чендж и тд) - это эндгейм
- **Flask bases, modifiers, and flask enchantments** -- Айлвл согласно общему рейлу айлвлов. Фласк энчанты и кволити с эндгейма
- **Gem level and gem quality** -- Дей 1 18 лвл гемов без кволити. Т16 20 лвл гемов и кволити у 3 мост ипактфул гемов. Эндгейм либо 21 гемы либо 20 лвл и 20 кволити. Миррор 21 20 или 20 23 гемы, 3 мост импактфул гема могут быть 21 23. Соответственно +1 лвл а не 21 у гемов которых макс лвл меньше 20.
- **Item bases and ordinary implicits** -- дей 1 базы до 70 лвла/айлвла. т16 до 83. Эндгейм 86+
  - Superseded for item level by the owner's answer of 2026-10-01 (#26: 72 template / 76 weapon / 70 loot); base drop level 70 stands.
- **Item sockets, links, and socket colours** -- Про сокеты и линки писал выше в составе линков. Цвета тоже аналогично тому что писал по кволити лимитейшенам у лодаутов. Потому что сейчас в игре с 3.29 сокеты по дефолту белые и туда вставляется что угодно. А цвет сокета дает +10% кволити. Вот пускай тогда дей 1 2 сокета с цветом, т16 4, эндгейм 8, миррор сколько угодно
- **Keystones** -- это база, будет работать даже если однажды решим чтобы поб делал лодауты под акты
- **Mastery selections** -- это база, будет работать даже если однажды решим чтобы поб делал лодауты под акты
- **Minion type, minion skill, and spectre choice** -- Это база. Тут варьируется только выбор спектров. Я за спектров не шарю и там надо понимать что когда можно из спекттров получить, что сильно а что нет. Это отдельная огрмоная задача будет по спектрам, там надо будет парсить поедб и считать цифры у спектров. Тип, скилл - это все должно считаться и так, это не должно быть в лодаут рейлах
- **Minion-specific equipment modifiers** -- Это тоже не должно быть в лодаут рейлах. Тут работа скрипта который подбирает гир под билд
- **Ordinary passive nodes and notables** -- это база, будет работать даже если однажды решим чтобы поб делал лодауты под акты
- **Regular jewels** -- Дей 1: 2 джевела с 1 модом. т16: сколько угодно джевелов с 1 модом, эндгейм: сколько угодно джевелов с 3 модами , миррор: сколько угодно джевелов с 4 модами
- **Regular rare explicit modifiers and tiers** -- Это должен считать ты сам в зависимости от рейлов по лвлам/айлвлам
- **Support gems and link composition** -- Тоже база. С дей 1 4 сокентые айтемы имеют 4л, 5+ сокентые айтемы имеют 5л (если 2 5сокетных, то только 1 5л, второй 4л). т16 1 6л. Эндгейм+ 1+ 6л.
- **Tinctures** -- Кволити с эндгейма
- **Transfigured skill-gem variant** -- Дей 1 и по гемлвл/кволити аналогично ваал версиям. Потому что это оба вида гемов которые сложно добываются
- **Unique items and availability source class** -- Дей 1: т5 уники. т16: до т4, эндгейм: до т2, миррор: до т0. Тут надо будет подумать, возможно будем делать дополнительный эндгейм поб к примеру с мейджблад или с хх. Но пока оставляем как я расписал
- **Vaal skill-gem variant** -- Дей 1 18 0 ваал версии гемов. т16 20 0 ваал версии гемов. Эндгейм 20 20 ваал версии гемов. Миррор 21 20 или 20 23 ваал версии гемов

## T16 (7)

- **Abyss jewels** -- Аналогично обычным джевелам, но без дей 1 рейлов. Только с т16
- **Eldritch implicits** -- там 6 тиров у этих имплиситов. т6 самый нижний с т16, т6-т4 с эндгейма, все остальные тиры с миррор лодаута, но на одном айтеме максимум 1 т1 и 1 т2 элдрич имплиситы (они оба могут быть на айтеме экзарх и итер)
- **Essence-forced modifiers** -- Все кроме т0 эссенс модов т16, т0 с эндгейма+.  На вики они называются т8, делириум, хистерия,инсенити, хоррор эссенсы
- **Foulborn / mutated unique modifiers**
- **Pantheon major/minor gods** -- Вообще тут также как с бенчкрафтами интересно было бы чтобы ты спарсил с каких мап/тиров открываются определенные пантеоны. Какие то могут быть ниже т10, какие то ниже т16 но выше т10. Это тоже было бы круто если бы система это учитывала. Но минус что надо перед лигой парсить инфу какие мапы щас какие тиры имеют и где теперь определенные бенчкрафт рецепты/пантеон боссы. Но насколько я знаю ггг вроде каждую лигу при смене мап в атласе балансят чтобы было примерно в одинаковых тирах. Но не уверен, это надо проводить ресерч между несколькими лигами (5 пускай). Интересно посмотреть что скажет ресерч на эту тему
- **Timeless jewels** -- т16: таймлес джевел который мы берем чисто ради кистоуна в каком то месте и просто игнорим эффект изменившихся поинтов в радиусе. Эндгейм: учитываем 3 нотабл пассивки в радиусе и 5 проходных, кистоун. Миррор: учитываем 80% нотабл и проходных пассивок, кистоун. Кистоун невсегда обязателен у билдов если что. У таймлес джевелов есть сиды и они расшифрованы, есть отдельный гит репо расшифратора. Надо будет подумать как сделать так чтобы ты высчитывал насколько вероятен таймлес джевел который система выбрала. Чтобы система дальше на основе вероятности понимала учитываем этот таймлес джевел или нет (к примеру чисто кистоун вероятность 100% не считая что он рипает пассивки в радиусе).
- **Veiled modifiers**

## endgame (7)

- **Awakened and other exceptional supports** -- по гемлвл/кволити аналогично ваал версиям. Потому что это оба вида гемов которые сложно добываются. Респективли макс лвлу гемов, потому что у эвекенд/грейтер и тд не 20 макс лвл обычно
- **Beastcraft modifiers**
- **Delve modifiers**
- **Fractured explicit modifier**
- **Influence modifier pools**
- **Item quality and jewellery catalysts** -- С эндгейма: каталисты до 20. С миррора: кволити на айтемах 27%
- **Tattoos**

## mirror (1)

- **Corruption implicits**

## never (8)

- **Charms** -- По моему лиг специфик и в игре больше нет
- **Crucible weapon/passive tree** -- По моему лиг специфик и в игре больше нет
- **Grafts** -- лиг специфик и в игре больше нет
- **Item enchantments**
- **Necropolis crafting modifiers** -- По моему лиг специфик и в игре больше нет
- **Runegrafts** -- По моему лиг специфик и в игре больше нет
- **Scourge modifiers** -- По моему лиг специфик и в игре больше нет
- **Synthesised implicits** -- По моему их убрали из игры. Но если нет то миррор

## Amendments after the form (the user, 2026-09-19, in chat)

- **A fifth loadout, "uber-endgame", between endgame and mirror** (proposed by the user; not in the form yet). What
  the notes already defer to it: Voices cluster jewels with 5 and 3 passives (7 is endgame, 1 is mirror);
  Mageblood / Headhunter-class uniques ("an additional endgame PoB with Mageblood or HH"); uber-boss-only unique
  drops. To be reviewed row by row once the loadout exists: unique tiers (T2 endgame -> T0 mirror leaves T1 open),
  eldritch implicit tiers (T6-T4 endgame, the rest mirror), gem level / quality steps, jewels with 3 -> 4 mods,
  Megalomaniac (2 useful notables endgame, 3 mirror), timeless jewels (3 notables + 5 small endgame, 80% mirror).
- **Uniques by drop source**: boss-drop-only uniques from endgame; uber-boss-drop-only uniques from uber-endgame.
- **Stability over leagues**: the research "from which map tier is it unlocked, and is that stable over 5 leagues"
  applies to crafting-bench recipes exactly as to the Pantheon.

## The uber-endgame loadout and corrections (the user, 2026-09-19, second pass in chat)

Loadout ladder: day-1 (T10) -> T16 -> endgame -> **uber-endgame** -> mirror.

- **Uniques**, the ladder of drop-rate tiers: day-1 T5; T16 up to T4; **endgame up to T1 inclusive** (the user's
  correction; the form said T2); uber-endgame up to T0, and what it ADDS is the uber-boss-drop-only uniques
  (boss-drop-only uniques start at endgame); mirror T0. **Unique jewels were missing from the inventory** and do not follow
  the ordinary tiers: some are common, some extremely rare -- Intuitive Leap is far more common than Unnatural
  Instinct (the first belongs to endgame, the second only to uber-endgame). The general rules may sort them
  correctly, "but hardly"; unique jewels may need case-by-case entries.
- **Eldritch implicits**: T6 from T16; T6-T4 endgame; uber-endgame down to T3 (T2 -- open); the rest mirror, at most
  one T1 and one T2 per item.
- **Gem level / quality**: uber-endgame 21/20 OR 20/23 -- "it is always a choice"; mirror the same with the three
  most impactful gems allowed 21/23; endgame 21 or 20/20.
- **Regular jewels** (count unlimited from T16): endgame 2 mods, uber-endgame 3 mods, mirror 4 mods or 3 mods + a
  corruption implicit. (This replaces "endgame 3 mods" of the form.)
- **Megalomaniac**: endgame 1 useful notable, uber-endgame 2, mirror 3.
- **Timeless jewels**: uber-endgame gets an intermediate share between endgame (3 notables + 5 small + keystone)
  and mirror (80% of the radius). The user: "these numbers from endgame up are purely from my head; they may be
  too strong and will have to change when we get there -- a potential vulnerability."
- **Tattoos**: T16 tattoos of tier 3 and below; endgame tier 2 and below; uber-endgame any. The tiers are those of
  the wiki's tattoo article, which rests on players' tests and can change -> listed in `docs/DATA_FRESHNESS.md`.
- **Magic items** (for mechanics like The Adorned): 1 prefix + 1 suffix + a corruption implicit is allowed from
  endgame, on every slot, not only jewels.

### To raise the moment the endgame loadout is started (the user: "when I say later, it is important not to forget")

Endgame itemization needs its own discussion before any rails are written: there are many efficient ways to craft
(recombinators for triple-T1 items, and more); the templates of day 1 do not carry over by changing tiers alone.
Together with it: unique jewels case by case, the timeless-jewel numbers, the probability model for a chosen
timeless jewel, spectres as a separate large task.

## Third pass (the user, 2026-09-19, in chat)

- **Uber-endgame level**: 97-100 (day-1 75-80, T16 90-95, endgame 95-100, mirror 100).
- **Runegrafts** -- a correction: the form's "never" was a mistake (the user took them for the Breach league's
  Grafts). Tiers are those of https://www.poewiki.net/wiki/Runegraft, built from players' mass reports, so they are
  refreshed every league (`docs/DATA_FRESHNESS.md`): endgame T6 and T5; uber-endgame T4, T3, T2; mirror T1 and up.
- **Forbidden Flame / Forbidden Flesh**: a boss drop, not an uber one (the user: "if I am not mistaken"), but they
  belong to the uber-endgame loadout.
- **Influence**: an item with TWO influences (Awakener's Orb) is uber-endgame. Items on Heist-only bases (Helical
  Ring, Focused Amulet and the like) are uber-endgame as well.
- **Rare talismans** by the talisman's level requirement (wiki): T16 requirement 1; endgame 1-28; uber-endgame 36+.
- **Timeless-like unique jewels**: 3.29 added four abyss jewels that work like timeless jewels with other nodes /
  notables / keystones, and Reclaimed Malevolence, which replaces the nodes of one random subclass with its own.
  "Many of them are so variable in themselves that each needs its own rail per loadout."
- **Unique jewels (regular, cluster, abyss)**: the user assigns tiers and explanations jewel by jewel in a second
  form, https://claude.ai/artifact/GdgMuo1SmTHmbhMBb23oTr (db collection `jewels`; 189 jewels from PoB's unique
  index: 81 regular, 9 abyss, 9 cluster, 6 timeless, 84 no longer obtainable); the result is saved next to this
  file as `2026-09-19-unique-jewels.md` / `.json` once filled.
- **Standing rule**: whatever turns up later that has not been divided between the loadouts gets divided and this
  book updated -- the book is the single place for it.

## Fourth pass: what "N useful properties" means (the user, 2026-09-19, in chat)

Applies to every rule of the form "N useful mods / notables / properties" in this book (regular jewels 2 / 3 / 4
mods, Megalomaniac 1 / 2 / 3 useful notables, timeless jewels, magic items, and whatever gets such a rule later).

- The build is credited with exactly N useful properties of the item. **Every other USEFUL property of the item is
  ignored** (contributes nothing to the number): the rule prices the rarity of an item with N good lines, the rest
  is "whatever rolled".
- **A NEGATIVE property is never ignored**: it is applied in full.
- The user's example, an item whose two lines each roll from minus to plus: `+10 life / +20 mana` under "1 useful
  property" **passes** (life is credited, the mana is ignored); `+10 life / -20 mana` **does not pass** as a
  "1 useful" item -- the negative line cannot be waved away as "the other line, ignored".
- For the system: a line outside the N credited ones is modelled at zero when it is useful or can roll
  non-negative, and at its real value when it is a drawback; never at a negative roll assumed away, never at a
  positive roll credited for free.

## Wiki check of the rows the user was unsure about (the lead, 2026-09-19, poewiki.net)

| system | the user's row | the wiki says | verdict |
|---|---|---|---|
| Charms | never | "an item obtainable from Affliction encounters"; needs the Wildwood Primalist ascendancy (Affliction league only) | never stands |
| Crucible weapon trees | never | appear on items "used in a Crucible Forge" (Crucible league only) | never stands |
| Grafts | never | "Grafts were items exclusive to Keepers league" | never stands (Runegrafts are a different thing, see the third pass) |
| Scourged items | never | made with the Blood Crucible of Scourge league | never stands |
| Synthesised implicits | "removed, I think; if not, mirror" | NOT removed: "Currently, synthesised items can only be found as unique item drops from Synthesis bosses. The only way to obtain a non-unique synthesised item outside of Standard leagues is to corrupt a unique synthesised item into a non-unique item." | synthesised UNIQUES follow the unique rules (boss drop -> endgame); a non-unique synthesised item is mirror, as the user's fallback said |
| Necropolis crafting | never | no page for its item modifiers found on this pass; Necropolis league content | never stands until shown otherwise |

## The rulebook site (the user's request, 2026-09-19)

The user asked for one tidy, editable rulebook instead of scattered notes: categories, a table of loadouts and an
explanation per entry (broad like "levels", narrow like "Split Personality"), a note per entry that saves itself, and
the same content serving the system as the main file of rails by loadout. Also a SIXTH loadout, an extender between
uber-endgame and mirror ("where, e.g., a +1 property rule on a jewel completely changes the build and its cost /
difficulty of acquiring"); working name Uber-endgame+, id `uber_plus`.

- Canonical file the system reads: `docs/rulebook/loadout-rulebook.json` (built by `scripts/build_rulebook.py` from the
  hand-edited `loadout-rulebook.entries.json` + the jewel form's answers `2026-09-19-unique-jewels.json` + PoB's unique index).
- The page: https://claude.ai/artifact/3CNfysNvnAiQeuo4SbPtdY (`scripts/build_rulebook_page.py`, template
  `docs/rulebook/site/rulebook.template.html`). The user edits any loadout cell (db collection `cells`, doc id
  `<entry>--<loadout>`, fields `text`, `was`) and leaves notes (collection `notes`, doc id = entry id, `_general` for
  the page-level note). When the user says "read it": `read_db` both collections, fold the edits into
  `loadout-rulebook.entries.json`, rebuild, republish to the same URL, delete the folded `cells` docs.
- This matrix file and its passes stay as the dated record of what the user said; the rulebook is the current state.
