# Reading 2026-09-18, part 2: new18-frozen, the rest of the column

Folder: `Documents\Path of Building\Builds\Junkroan\benchmark 2026-09-16 1929-new18-frozen`.
Same format and policy as part 1. The user also asked whether core14-frozen needs reading:
no, those archetypes were read in run E and every build changes with the rules below; they are
read again after the rerun (7.4).

## The user's text

> exsanguinate_mines s3.xml
> Странно видеть в этом билде ауру хейтред на конверт 50% и при этом мастери физовое на игнор пдр. Видно что система не смогла определиться и закомититься во что то одно - колдовый или физовый билд. Не знаю хорошо это или плохо для системы в целом. Проезд через уан виз нейчер крайне странный тупо ради резов. Чардж майнс саппорт и конфиги на эти чарджи это хорошо, так и надо респект
>
> kinetic_bolt_wander s1.xml
> 83% хит шанс это очень мало. Думаю для атак билдов надо поставить рейл минимум 95%. Меньше просто хуево ощущается. Очень интересный необычный билд. Надеюсь наша система однажды тоже сможет такое билдить артхаусное но при этом не слабое. Сиджил оф павер ставить на 50 тоже странно. Он слишком сильно аффектит урон, а 50 стейдж это большой рамп в зависимости от манакоста. В общем его надо просчитывать в зависимости от рампа билда.
>
> elemental_hit s3.xml
> Я не против айрон рефлекс кистоуна. Но мне интересно почему система решила его взять учитывая что он понижает ехп. Потому что он увеличивает макс физ хит? Эле хит необычный скилл тоже. У него рандомится элемент каждый хит. При помощи джевелов можно убирать элементы из вероятности. Но на дей 1 не получится. Суть в том что у тебя файровый билд, но при этом поб не считает (а может и считает хз) что у тебя не каждая тычка будет иметь столько фаер флеты. У эле хита дохуя флеты но он а всегда рандомная. Это опять геп в ноледже системы. Как будто она не читает то что собрано у нас в базе по скиллам? А должна как будто , это важные моменты.
>
> archmage_volatile_dead s3.xml
> Не стоят галочки спавнед корпс рисентли, консьюмд корпс. На вд ты постоянно кастуешь десекрейт и вд. Нирбай корпсес тоже постоянно будут сколько то из за того что часто кастуешь десекрейт со спелл каскадом и вд не все корпсы консюмит (как у тебя было 9). Плюс надо обязательно учитывать и считать рамп корпсов консьюмд рисентли (колво), это корпс пакт и главная фишка некра как сабкласса. Но в текущем случае учитывая что мы кастуем вд и десекрейт руками тут сложнее, человек не сможет идеально быстро прожимать оба скилла (если нет к примеру автоматизации корпсов через арканист бренд). Также надо думать как в таких скиллах учитывать +2 корпсов у андертейкер нода
>
> impale_cyclone s3.xml
> Онслот он килл, на боссах не работает же? Или тут где то получен онслот на боссов?
>
> poison_spark s1.xml
> ТОксик деливери пойзн дюрейшн тоже должен считаться от рампа как будто в конфиге (пойзнс эплайд рисентли). Сакрифайс саппорт не идет в деген или лайф кост. Поэтому система его взяла. Но это должно уычитываться. Думаю с текущим кастрейтом мы просто убьем себя за неольшой прокаст. Визер даже с тотемов надо высчитывать исходя из рампа, они не мгновенно накладывают.
>
> arc_archmage s3.xml
> Вот тут на аркмейдж билдах сиджил оф павер быстро рампается из за мнакоста ебанутого. Но тут он даже не стоит у тебя или у автора хз у кого точно.
>
> impale_ballista s3.xml
> Я крайне сомневаюсь что эроунова работает со шрапнель балистой. Этот поб выглядит не очень легимимным но я не шарю чтобы доказать почему. Надо смотреть что там у автора, возможно это какая то оффмета задумка от него о которой я не знаю.
>
> bleed_perforate s3.xml
> Не очень ясно что здесь с уроном произошло. Возможно мы оба не понимаем как работает этот скилл. Возможно он мультихитает. Нужен ресерч
>
> Мне точно надо читать ...\benchmark 2026-09-17 0844-core14-frozen? Я так понял ты хочешь чтобы я читал как можно большеразных архетипов чтобы находить больше ошибок в логике. А эти я уже читал. Или ты хочешь чтобы я посмотрел на оптимизацию?

## What the data says (checked 2026-09-18)

| remark | checked | result |
|---|---|---|
| Onslaught on impale_cyclone | config sets and the explanation | `buffOnslaught` is on in the **conservative** lane with the reason "source found in build; shown by PoB"; the only source is "20% chance to gain Onslaught for 4 seconds on kill", which the mapping section itself lists as maps-only. The buff proof does not filter on-kill sources |
| Sigil of Power at 50 (kinetic_bolt_wander) | config sets | `sigilOfPowerStages = 50` is ours, in both lanes; the author has no such input. A generic stack ceiling written into an input whose range is the skill's own, with no ramp behind it |
| Sacrifice on poison_spark | links | ours: Spark + **Sacrifice** + Cruelty + Unbound Ailments + Spell Echo; the author: Faster Projectiles + Efficacy instead. Its life cost per use is in no floor (the self-cost class of part 1) |
| Wither on poison_spark | config sets | ours 15 in both lanes, the author typed 6; the author also typed `multiplierPoisonAppliedRecently` 20, which our build does not get (the lane asymmetry: benchmark 78% against 116% under one lane) |
| Arrow Nova on Shrapnel Ballista | links | the **author's** link: Shrapnel Ballista + Arrow Nova + Multiple Totems + Focused Ballista; ours replaced Multiple Totems with Impale (one totem fewer in FullDPS: 84% per totem, 45-102% in the benchmark) |
| Iron Reflexes on elemental_hit | floors | physical max hit is floored, TotalEHP is not (46-53% of the author's on this reference); D61 changes that |

## Classes and rules (continuing part 1's numbering; all inside 7.1h)

16. **Attack builds keep hit chance >= 95%** (the user's rail). From: kinetic_bolt_wander (83%).
17. **Ramp-type numeric inputs come from the ramp budget, never from a ceiling**: Sigil of Power
    stages, Wither stacks (also from totems), poisons applied recently, corpses consumed recently:
    the value the build's own rates reach inside the rails' 2.5 s. From: kinetic_bolt_wander
    (Sigil 50), poison_spark (Wither 15 against the author's 6).
18. **A buff proved by an on-kill source is off on the boss lane**: the on-kill verdict applies to
    buff proofs too. From: impale_cyclone (`buffOnslaught`).
19. **Supports that pay life per use are self-cost** (Sacrifice), judged per candidate like rule 4.
    From: poison_spark.
20. **A skill whose damage part is random per hit is scored as the mean over its parts**
    (Elemental Hit without the jewels that exclude elements), on both sides; a `mechanics/`
    fact naming the skill and its parts. From: elemental_hit.
21. **Corpse-cycle conditions follow a creator plus a consumer in the build**: spawned / consumed
    a corpse recently, corpses consumed recently (a count from the cast rates over 4 s, two
    hand-cast skills share the casting time), nearby corpses, Undertaker's +2. After the
    research. From: archmage_volatile_dead.

Research, second brief (`docs/research/briefs/2026-09-18-game-knowledge-2.md`): Perforate's hit
mechanics in Blood and Sand stance and its bleed; Elemental Hit's random element and what PoB
computes; Corpse Pact and the corpse conditions with hand-cast Desecrate + VD; Sigil of Power
stages and how fast they build by mana cost; Wither stacks from totems over time; Sacrifice
Support's cost; Arrow Nova with Shrapnel Ballista; the accuracy people accept on attack builds.

Per-build remarks, recorded: Hatred with a physical mastery on exsanguinate_mines (PoB's numbers
decide, the system need not commit to a flavour); the path through One With Nature for
resistances (rule 9 of part 1: gear has the last word); charges from the Charged Mines support
and their config are right; kinetic_bolt_wander as an unusual build worth being able to find;
no Sigil of Power on arc_archmage, where it would ramp fast (a candidate for the utility picks
once rule 17 exists).

## Closed the same night: bleed_perforate's gap

The build carries no stance input at all (PoB's default, Blood: every spike at 0.25x). With Sand
Stance written, the same build scores 647,425 against the exported 189,005 and the author's
449,293 under our lane (122%). The `_finish` tuner did try Sand and rejected it: the ramp floor
(`RampBudget >= RampSeconds`) reports 0.134 over budget in Sand (fewer hits, slower rage / charge
ramp), and a feasible 189k beats an infeasible 647k. The fix is rule 17: derive the stack values
reachable inside the budget under each choice instead of a cliff. Not an optimizer gap.
