# Reading 2026-09-18, part 1: the frozen campaigns' best seeds (new18-frozen, first column)

Folder: `Documents\Path of Building\Builds\Junkroan\benchmark 2026-09-16 1929-new18-frozen`.
The user's words verbatim (Russian), then what the data says, then the class and the rule.
Policy: a remark becomes a rule only when it names a class of builds the corpora or a PoB
stat can express; per-build remarks are recorded. Research questions went to GPT-5.6 through
opencode (`docs/research/briefs/2026-09-18-game-knowledge.md`; the user, 2026-09-18: game
knowledge that the wiki does not settle is researched on Reddit by a GPT model through
opencode / codex, always).

## The user's text

> vd_spellslinger s3.xml
> Не понимаю почему мастери на конверт физы в фаер дает 3% дпса, возможно баг поба. Ставить 9 хитов вд с обычным спелл каскадом нереалистично. По моему там рандом от 6 до 8 и в среднем получается 7 вроде и 9-10 при грейтер/эвекенед спелл каскадах/де. Это надо сделать ресерч по реддиту или другим местам для более точных цифр (поскольку ты не умеешь ходить на реддит, дай эту задачу гптшной модели через опенкод/кодекс и всегда так делай когда надо идти на реддит. По гейм ноледжу в 99% случаев надо идти на реддит помимо вики если вики не дало ответ или он смазан). Триггерим спелслингер через скилл френзи, а макс френзи чарджи не стоят в конфиге. Вернее ситуация хуже. Галочка не стоит. Но когда я ставлю, то получаю -28% дпса. Как будто на уровне кода ты проставил колво френзи и оно отличается от макс френзи по побу? Не знаю в чем дело, но какой то баг не ясно на чьей стороне. На перчах тоже конверт физы в фаер не понимаю почему он здесь, но видимо дает дпс почему то (у вд физ дмг 49 - 92 если что по кальк вкладке). Впервые вижу в твоем побе меджик айтем. Кольцо не плохое и мне такая практика даже нравится, проще будет по такому побу одевать чара. Но просто говорю об этом, возможно это какая то ошибка потому что до этого так не было. Кстати раз уж мы затронули триггер скиллы, тут важно уточнить что на них атак спид является невероятно важным и его надо точно расчитывать в билде. Не так что на мапе к примеру есть рамп в х2 атак спида. Потому что если ты посмотришь в побе, есть такая стата эффектив тригер рейт. И излишний атак спид может жестко заруинить весь дпс. И наоборот к примеру +10% атак спида даст в 2 раза меньше дпс, а +15% атак спида хитнет брейкпоинт и будет в 2 раза больше урона от текущего. Короче это сложно и надеюсь что наша система учитывает брейкпоинты а не то что скейлится линейно как у всех остальных статов
>
> shockwave_cyclone s1.xml
> Первый ред флег - у тебя стилскин включен и он жестко инфилтрейтит ехп и макс хиты. Гард скиллы и прочие подобные штуки которые не постоянные должны быть выключены и не влиять на статы персонажа. Это ситуационная хуйня, пускай в этомслуча и стоящая на квдт, но все равно. Очень странно что макс рез лайтнинг 78 но у тебя рез 76, но это видимо поинтов не хватило судя по поинту с армор + рез. Мана кост в сек 43.84, мана реген 39.3 и нет лича. На челелинг скиллах вроде сайклона это будет особо хуево ощущаться потмоу что это мувмент скилл и у тебя аптайм максимальный у него, мана будет обрывать ченнел. Возможно я ошиьаюсь и я слепой, но я не вижу причину почему стоят макс френзи и эндюрки. Имбалансд гвард не уверен насчет этого кистоуна. Возможно он сильный при лоу инвесте в армор и без пдр инвеста? Тут нужен ресерч, моего ноледжа недостаточно. И скорее всего тут еще влияет то что наша система не знает как работает армор. Он тем слабее, чем сильнее входящий урон. То есть на слабые тычки на мапе даже мало армора очень спасают. Возможно этот кистоун будет резать такой кейс. Но если честно все равно все гонят макс физ хит и как будто твое решение неплохое? Нужен ресерч и аналитика на основе разных хитов чтобы понимать когда этот кистоун действительно использовать.
>
> static_strike s3.xml
> А, вижу откуда ты насуетил макс френджи и эндюрки, кластер на чарджи за баннер плейсмент. Но только не в этом ни в придыдущем билде у тебя нет ни одного баннера. Даже если каким то образом у тебя был бы аптайм чарджей из за баннера, в чем я крайне сомневаюсь, это все равно ошибка. Опять 2 одиночных нода, но видимо ок. 3400 лайфа, пиздец мало, но я хз сколько у автора было. Похоже на то что поб автоматом не считает травма дмг от саппорта/скилла в тотал деген. У тебя 752 физ дмг по персонажу за каждую атаку. Хз как это работает на статик страйке, один раз тебя хитнет или нет, но это все равно пиздец как много урона учитывая что у тебя блять 3400 хп. Статик страйк в целом гимики скилл, он снепшотит свой стейт на момент прожатия на весь дюрейшен, поэтому ему обычно разгоняют дюрейшен для комфорта. И юзают что то типо абмуша чтобы изи крит капиться. Но это так, если вдруг однажды у тебя система предложит такое, чтобы был ноледж что такое можно, но с норм дюрейшеном иначе маппинг говно будет. Тут мака ност в секунду высокий, но мы и не будем спамить статик страйк как я сказал. Видимо твоя система это понимает, круто? Не понимаю зачем на белте кдр с бенча, но видимо ок. Поставил берн, игнайт и чил, что как будто ок с 37% крита и трипл эле дмг (насчет берна не уверен, не помню механику игнайт это берн или нет). Но почему нет шока? Его надо научиться высчитывать правильно, это тоже надо изучить на вики, там есть формула. Как будто можно считать шок правильно учитывая рамп, потоу что шок то тоже рампается сам от себя.
>
> kinetic_fusillade s2.xml
> Торнадо тоже отдельная тема, надо делать ресерч вики и реддита чтобы хотя бы примерно понимать сколько урона это дает на определнном скилле. Но у теяб он не учитывается в поб, так что это ок, это совсем на будущее. Стоит в скиллах флеймволл но не стоит в конфиге галочка что проджи прошли сквозь него. Как будто должна стоять, иначе нахуя он вообще в билде этот флеймвол. А тут шок у тебя стоит. Но не пойму сколько процентный. Поб научился считать шок возможно? Но в любом случае он это делает на ферст хит и не учитывается рамп о котором я говорил (хз кста насколько этот рамп будет отилчаться в разных билдах, возможно настолько незначительно что похуй на этот рамп потому что он будет давать пару процентов после рампа по рейлу). В бандитах стоит хелп Алира. Вот тут я хочу добавить рейл - никаких хелпов бандитам. Все побы всегда килл ол бандиты ради доп поинтов. И пускай система так высчитывает. ЕО кистоун с 17% крита эт опрям хорошо. Важно учитывать что при малом крите ЕО будет почти не прокать. Тут как надо, 17% как будто адекватно с таких хитрейтом (кста у селф и тотемов индепендент проки ЕО будут, ЕО вообще прокает на каждом скилле индепендент, это важно учитыать если в побе этого нет). Фьюзелейд тоже гимик скилл. У него балансятся атак спид и редьюс дюрейшен чтобы при атаке они вылетали мгновенно. Но поб это вроде не считает. И билд автора про дефолт фьюзелейд без приколов с ред. дюрейшеном видимо так что ок
>
> burning_arrow_snipe s1.xml
> Зачем брать мом кистоун на 10% анрезервд мане не понимаю. В таких ситауциях мом будет только руинить отому что тебе будут сбивать ману и у тебя не будет хватать на атаки/касты. Вот здесь ЕО кистоун выглядит хуево. Эфф крит 7% + у тебя очень долгая атака из за ченелинга. Вероятность прока ЕО довольно маленькая. Манафордж френзи, макс френзи не взяты в конфиге почему то.
>
> soulrend_chaos_dot s1.xml
> Мастери на +1 хаос но 10% селф дмг за каждый каст это нельзя брать если ты не тригеришь хаос скиллы чем то не хаосным. Да, на боссе такое еще можно будет переживать но будет неприятно. Но мапиться с этим мастери будет буквально невозможно даже с лайф/ес он килл. Не взятый хейсти демайс выглядит криминально особенно учитывая что взята не проходная стренджа просто так, ничего не капящая. Кстати интересно как у тебя капятся атрибуты. Обычно их капят всегда с гира и в последнюю очередь с дерева. Если у тебя в пайплайне наоборот, то это очень плохо. Последнее слово по аттрибутам должно быть за гиром всегда. С аккураси также, но в лейте. С резами также, но на любой стадии.
>
> lightning_trap s2.xml
> Первый странный прикол и я не знаю это ошибка или нет. У тебя билд лайтнин трап. Но он забилжен через мины. То есть персонаж кидает мину, детонейтит и вылетают лайтнин трапы. Это как бы технически возможно. Но играться будет хуево. Крайне странно что это лучше чем простобилд через трапу. Интересно рассматривался ли он вообще (полагаю автором да, и он явно не билдил вот этот абоминейшен). Ну за креативность 5. Тотал нет рекавери -12 что звучит ужасно. Нельзя играть с дегеном. Ты просто будешь умирать постоянно рано или поздно, даже с таким маленьким. Если билд есный, то это вообще ломает ес и его речардж. Клевер констракшн явно не взят потому что он красный. Но по факту насколько я знаю это тупо 10% мо дмг на трапах (и аналогично для мин но другой нод вроде) и его всегда берут. Учитывая что 2.5% лайф регена с мин, то ситуация с дегеном еще хуже. Будешь умирать пока просто бежишь по мапе где нет мобов к примеру или лутаешься. Не уверен насчет марк мастери. Это надо читать вики. У кого то из них (трапы или мины) не работают он хит/ он килл эффекты потому что это прокси. Но как в текущем случае где и мины и трапы я хз вообще, надо ресерчить. Энивей странно брать вообще это мастери когда есть на минах/трапах довольно легко найти генерацию френди и павер чарджей через саппорты и прочую хуйню. И кстати вот вскрылась проблема - геп ноледжа системы. Она сделала миновый билд где анрезервд мана 4%. Это 4 актив мины. Система не знает механику работы мин и поэтому так происходит. Нужно чтобы система все таки читала базовые механики перед выбором мин к примеру. Но я хз спарсено ли у нас это. Если нет, то надо парсить эти данные с вики и аккуратно складывать чтобы система не тратила много времени(агент) на поиск и чтение таких данных. Просто деливеритайпы в пое не очевидные. Как будто надо чтоыб система знала как работают мины, трапы, бренды и тд перед тем как их билдить. Там есть вещи типо резерва которые поб не скажет. Шрапнел спешлист интересный выбор. Возможно идея с минами + трапами все таки автора тогда? Хз
>
> spectral_shield_throw s1.xml
> Как будто на гладе когда у тебя уже и блоки с сабкласса и 65% атак блока и версатайл комбатант кистоун, странно не докапливать спелл блок до капа любыми способами, ну ок. Я не уверен насчет того что ты ставишь у прайда макс эффект всегда в побах. Это же тоже рамп. Макс эффект при 4с это слишком для наших рейлов нет? Инишл эффект маловато но ок. В последствии можно в кастом модах прописывать чтобы соответсовало нашему рампу и пометку, но необязательно. Но в целом как решение костылей это хорошо и возможно быстрее чем поб. В кастом модах просто прописать мод который допонляет что то до правильных цифр и закоментить пометку что это и почему здесь (важно чтобы имено сам мод работал и давал импакт а коммент нет, это синий и красный цвет в аппке сооветственно).
>
> pyroclast_mine s3.xml
> Ну тут опять не учтен мана резерв механика мин. И пирокласт вроде мультихитают боссов, но тут нужен ресерч для примерных цифр. Вот тут в конфиге не макс френзи отражены правильно, без бага. Есть вероятночть что игнайт не равно берн. И тогда имолейт у тебя нахуй идет в 99% твоих билдов. Это надо заресерчить чтобы знатьнаверняка. Насколько я помню берн в игре только от рфа и еще парочки спец скиллов/кейсов.

## What the data says (checked 2026-09-18)

| remark | checked | result |
|---|---|---|
| Lightning Trap "built through mines" | the author's fixture | the author's own link: Lightning Trap + Swift Assembly + Trap and Mine Damage + **High-Impact Mine** + Added Lightning Damage; ours swapped only the last support for Lightning Penetration. Not ours; the playability question goes to the research (4) |
| the magic ring (vd_spellslinger s3, Ring 1) | both XMLs | it is the **author's** "Virile Ruby Ring of Craft", equipped in our build: `scripts/build_from_skeleton.py` sorts items into UNIQUE / RARE / jewels, and a MAGIC item falls through as a fixed item. A leak of the author's gear (class below) |
| Chaos Mastery "+1 chaos gems / lose 10% life and ES per chaos skill use" on soulrend s1 | the log and `pipeline.py:163` | the self-cost rule exists (pattern matches this line) but its context is computed once from the empty build's text, before the tree; a self-cost mastery taken later is never seen by the floor. Taken 7 times in the log at +17% each |
| frenzy charges off with Frenzy as the Spellslinger trigger; -28% when turned on | reasoning, PoB to confirm | charges add attack speed and the trigger rate crosses a cooldown breakpoint (PoB's effective trigger rate); the lane has no rule that the Frenzy gem generates frenzy charges, so the honest state (charges on) is not what the optimizer tunes the attack speed for. Same gap on burning_arrow (Manaforged Frenzy) |
| max frenzy + endurance on shockwave_cyclone / static_strike | the audit's red lines | the proof took "Gain 3 Endurance / Frenzy Charges when you consume maximum Valour to place a Banner" as a generator; neither build has a banner |
| Steelskin in EHP / max hit | the audit | warning "buff uptime: Steelskin ~50%" exists on all three seeds, but the buff still counts in the floors and on the author's side |
| mana 43.84/s against regen 39.3/s (shockwave_cyclone) | rails | 89.6%: inside the 85% sustain floor; the floor is too low for a channelled skill |
| net recovery -12 (lightning_trap) | rails | inside the -100 floor of D34; the user's verdict: no degen at all, the floor must hold while idle (no leech) |
| Pride at MAX in every lane | lanes | a list choice judged by PoB (D24), MAX wins; Pride's maximum takes 4 s, the rails' ramp budget is 2.5 s |
| bandit Alira | `_tune_identity` | the bandit is a judged choice today |

## Classes and rules (each = code + test + audit check; all of them change numbers, so they ride
## with the one 7.1h reopening and its single rerun)

1. **Guard skills and other cooldown-limited buffs count for nothing** (Steelskin, Immortal Call,
   Molten Shell, ...): off in both lanes and on the author's side; the audit's buff-uptime table
   already names them. From: shockwave_cyclone.
2. **A generator needs its enabler in the build**: "when you place a Banner" without a banner gem,
   and the same for warcry / mine / totem / mark conditions in generator lines. From:
   shockwave_cyclone, static_strike (and the bleed_bow red lines).
3. **The Frenzy skill (self-cast, Manaforged, or as the Spellslinger trigger) generates frenzy
   charges**: `useFrenzyCharges` on in the conservative lane; the optimizer then sees PoB's
   trigger-rate breakpoints under the honest attack speed. From: vd_spellslinger, burning_arrow.
4. **Self-cost lines are judged per candidate, not once**: a mastery effect or node whose text is
   a self-cost line matching the main skill's tags is excluded when the main skill is not
   triggered; the context is re-derived on every reconfigure. From: soulrend.
5. **No degen while idle** (the user: "нельзя играть с дегеном"): net life + ES regeneration without
   leech, recoup or on-hit recovery >= 0, replacing the -100 of D34. From: lightning_trap.
6. **Sustain 100% for channelled main skills** (corpus tag), 85% stays for the rest. From:
   shockwave_cyclone.
7. **Bandits: always kill all** (the user's rail): `bandit = None`, no judged choice. From:
   kinetic_fusillade.
8. **Pride (and any list choice that is a ramp) follows the ramp budget**: initial effect in the
   conservative lane unless the ramp fits 2.5 s; an intermediate value can be written as a custom
   mod with a comment (the mod works, the comment explains). From: spectral_shield_throw.
9. **Gear has the last word on attributes, resistances and (late) accuracy**: a tree node whose
   only contribution is such a floor stat is a candidate for removal with a gear re-roll repairing
   the floor; judged like any move. From: soulrend (a Strength node off the path while Hasty Demise
   is untaken).
10. **Enabler gems turn their condition on**: Flame Wall in the build means projectiles pass
    through it. From: kinetic_fusillade.
11. **Only rares are rolled, only uniques are fixed: a MAGIC (or normal) item of the author's is a
    rare slot** to roll, never carried. From: vd_spellslinger.
12. **Elemental Overload needs an uptime proof**: P(crit within the window) from effective crit
    chance and hit rate, like the ailment uptime rule. From: burning_arrow (7% crit, slow
    channelled attack) against kinetic_fusillade (17%, fine).
13. **Mind over Matter needs unreserved mana to stand on**: a threshold the user names (asked).
    From: burning_arrow (10% unreserved).
14. **Delivery types carry facts PoB does not tell** (mines reserve mana per placed mine, proxies
    and on-hit / on-kill effects, trigger breakpoints): a small machine-readable
    `mechanics/delivery_types.json` fed from the research, read by the config rules and the
    floors (unreserved mana for N mines). From: lightning_trap, pyroclast_mine.
15. Trauma's self-damage enters the degen floor once the research gives the formula. From:
    static_strike.

Research (GPT-5.6 through opencode, report `docs/research/2026-09-18-game-knowledge.md`): VD +
Spell Cascade orb count (the user: 6-8, average 7; our rule says 9), ignite = burning?, the shock
formula and its ramp, mines' reservation and proxies' on-hit / on-kill, Imbalanced Guard by hit
size, Clever Construction, Pyroclast multi-hit, Trauma, Pride's ramp and EO's window, Kinetic
Fusillade and Tornado, trigger-rate breakpoints.

Per-build remarks, recorded, no rule: the phys-to-fire mastery and gloves on VD (+3%, PoB's number:
VD carries 49-92 added physical damage); lightning resistance 76 of a 78 cap; two single travel
nodes on static_strike; the cooldown-recovery bench craft on its belt; spell block left uncapped on
the Gladiator (the TotalEHP floor of D61 will price it); Static Strike and Kinetic Fusillade as
gimmick skills (duration snapshot, attack speed against duration); Tornado for later.
