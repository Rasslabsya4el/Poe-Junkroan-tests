# Junkroan pane: design system (#683 round 4, 09.10)

The owner's goal (22:4x): every element of the same kind of content is built on ONE component, across all five tabs;
opening anything is understandable and expected. Breaking the round-3 look for that is allowed.

## Sources (practice, not taste)
- Nielsen heuristic 4 "Consistency and standards": the same thing looks and acts the same everywhere, and follows the
  platform the user already knows (here: GitHub, which the owner reads every day).
- Design systems (Primer / Atlassian / Material): a component INVENTORY (one component per content kind, with variants
  and states), TOKENS (colour by meaning, type, spacing) and fixed PLACEMENT of the same fact.
- Primer (GitHub) functional colours, dark, as the starting point (the pane's own values, lifted for contrast, are in
  `hooks/tokens.ts` and the table below): open / success, done, danger / closed,
  attention, accent, muted. Primer components mirrored: StateLabel (state icon + word),
  ProgressBar (thin bar + "3 of 5", as on sub-issues), ActionList (row = leading visual, label, description, trailing
  meta), SegmentedControl.
- dataviz skill: status colours reserved and never reused as identity; status always icon + word, never colour alone
  (green / red fail CVD: validated 09.10, the icon carries it); identity palette validated on #262628.

## Tokens
Colour = meaning, nothing else. A colour never decorates a frame.

| token | hex | meaning (everywhere) | icon |
|---|---|---|---|
| active | #3fb950 | going now: a busy agent, an open ticket, a running merge / run / cell | `running` (a spinning arc); a ticket `issue-opened` |
| done | #b18cff | finished well: closed ticket, landed merge, finished subagent / run / cell | `done` (a ticked ring); a ticket `issue-closed` |
| failed | #ff6961 | failed: tests red, rc != 0, a failed cell / run | `failed` (a crossed ring) |
| waiting | #d29922 | waits for its turn or for someone: queued merge / run, ready-for-human | `waiting` (a clock); a ticket that waits for tickets `hourglass` |
| idle | #7d7d86 | nothing going on, stopped, cancelled, not planned | `circle` (a plain ring); stopped `pause`; not planned `skip` (a ring struck through) |
| accent | #58a6ff | links, the selected row, the primary control | - |

The icon column names icons of the pane's own set (`ICONS` in `hooks/register.tsx`: octicons copied verbatim, a few
line drawings of our own), drawn inside a picture in the token's colour. NO state, toggle, arrow or mark is a text
character on the desktop (the owner, 10.10: «тысячу раз уже обсуждали»); `test/onelook.test.tsx` (`noGlyphs`) holds it
on Tickets and Cost. The terminal has no pictures and keeps its glyphs.

Identity (machines' CPU / RAM / slots only, never a state): PoB #3987e5, agents #d55181, you #c9c9cf (the owner's
reserved slots are "you"). Validated (dataviz, dark #262628): PoB/agents CVD dE 15.9.
Neutrals: page #1a1a19 (the host's), card #262628, row stripe #212123, hover #2f2f33, selected #1d3048, rule #38383c,
text #f0f6fc, muted #a0a8b3, faint #656c76 (a shape, never a text), ink #1c1c1e (a label on a state colour), white #ffffff.
Every text token is >= 4.5:1 on the card, the stripe, the hover and the selected fill (`test/design.test.tsx`).
There is ONE palette: `K` in `hooks/tokens.ts` (plus machine identity `ROLE` and base classes `CLASS` there); no
colour is written anywhere else.
States of a control and a row (#793 F17, F19-F21): ONE selected look = the `sel` fill with the label in `accent` (a tab keeps its 3-px underline, no fill); ONE row look = the flat band (radius 4, `stripe` on every second row, the card between), no tinted pill, no outline; hover = the host's rounded light on the element's face (a row: its pill revealed at .07 white); no Box draws a fill of its own, no square fill anywhere (#994).
#994 (the owner, 14.10: the pressed look is the reference, «весь дешборд должен соблюдать один стиль»): the selected / pressed look and the hover are ONE family on the SAME
shape: a choice of a switch (Cost's period and group) is a capsule of the host light's own shape (19 px, rx 4) drawn in the picture, the chosen one with the `sel` fill, an
accent outline (.55) and its word in the accent, exactly as a picked run's pill; the hover is the host's lighter neutral light over that very face. A pager is TWO ICON
BUTTONS (octicons' chevron-right, turned 180° for «previous»), a 20-px face each with a blank host Button over it; the end of the range is drawn in `faint` and gets no
Button, so it lights nothing. A title (a run, a merge, a ticket, «По тикетам», «По чатам») is ONE line cut with «…». A placeholder («пусто», «ничего») lights nothing.
A blank label is as wide as its face as the real pane lights it (kit `LABEL_EM` 13 px an em space, `LABEL_NB` 3.1 a no-break space, `LABEL_PAD` 7 of the host's padding).
Type: three sizes and two weights, in the pictures and in `hooks/draw.ts`: 12 (body, labels, column heads), 13 (a row's
name, a value), 14 (a card's title); weight 400, and 600 for the row's name, labels and the one total of a card;
muted = meta (model, ctx, host, column heads, footers). Numbers right-aligned in their column.
Time: one format, Russian units: `53 с`, `8 мин`, `1 ч 33 мин` (principle 7); a clock time `до 23:35`.
Spacing: one 4-px scale, `SP` in `hooks/tokens.ts`: 4, 8, 12, 16, 24 (a pane column, 7.8 px, is the 8). Gaps, paddings,
air, indent, a band's edge and every corner radius are steps of it; the grid sizes (`GRID`: table row 20, tab bar 28,
rail 24, indent 24, band edge 16) are multiples of 4. A 1-2 px hairline is a stroke, not spacing. One text row per item,
one blank row between cards, none inside a card except above a section label.

## Components (one per content kind)
1. **Tabs** (SegmentedControl): the tab bar, Cost's period, nothing else. Selected = primary.
2. **Card**: neutral round border, title (bold, sentence case) left, one muted state word right only when the body
   cannot say it (`idle`, `offline`); the body is components 3-8. Every group on every tab is a Card.
3. **Table** (Primer ActionList + DataTable): fixed columns per table, muted column heads in one row, zebra stripe,
   row hover; variants: tree (indent + a `chevron-right` toggle, turned down when open), selectable (a press opens a Detail under the table, the row turns
   `selected`), sectioned (a muted section label row: `в очереди`, `готово`).
   Column order is fixed across tables: icon · # · name · meta · progress · words · time.
4. **Status icon + word**: the token's icon in its colour; a word beside it where the icon alone is not enough.
5. **Progress**: one thin bar (6 px, rounded, active / done / failed fill on a #38383c track) + `a / b` in ink.
   Merge tests, PoB run cells, ORCH's tickets, a ticket's sub-issues, cost and label shares.
6. **Queue** = Table, sectioned: `идёт` rows (the `running` icon, progress, words = phase, time = elapsed), `в очереди` rows (place
   1, 2, ... = who goes next, amber; words = when it starts, time = waited); every section label is drawn even when
   empty (`идёт · пусто`), so the card always reads as a line, `готово` rows (the `done` / `failed` icon, time = took). Children under a running row
   (its builds in progress). Merge and PoB runs are both this.
   **PoB run rows (#773, #995)**: no track row under a running run. The `num` column («билды», 66 px) holds the run's builds as
   the text `done / total` right-aligned (an open total `3 / 5+`; running in the text colour, finished muted unless picked): no
   squares, no bar (the owner, 14.10: «х/у достаточно»). A build row under a running run holds there its REAL stage only:
   `этап N / M` = the step its log last started among the stage catalog's steps (addon.py `build_stage` `stage_index` /
   `stage_count`, #985 c); a build with no such step (a replay, an older log) draws nothing there. The old bar of three
   groups (the loop filled by a time guess) and the replay's 12 time segments marked no stage and are gone. The `meta` column is three pictures in this order: priority (three rising bars, lit by
   level: P0 3, P1 2, P2 1, anything lower 0; lit = ink, unlit = muted at low opacity), machine (`monitor.octicons` /
   `laptop`), slots (one muted square per slot held, 6 x 8 px with a 1.5 corner, gap 2, at most 8); a finished row keeps its date and start as text after
   them. The words ("P1, pc, 2 слота", "1 / 3+ билда") live in the row's `alt`; the terminal keeps its words.
7a. **Agents (#995)**: ONE table of the queue's device: a section label row «Чаты» (the interactive sessions), then «Фоновые сессии»
   (every background session: autopilots, ORCH, keymasters), each busy first; an empty section draws its label and «пусто».
   **Merge (#995)**: no «ветка» column (a row with no ticket title names its branch in the title cell); «Готово» is paged on its
   label row like the runs card's (3 landings a page at most). **PC / Laptop (#995)**: no reservation row, no «резерв» word.
7. **Machine gauge**: stacked bar per resource with its split legend, slot squares, a 10-min area chart (identity
   colours). PC and Laptop.
8. **Detail**: a selected item's title + muted subtitle + actions right, then a two-column Table (key, value) or a
   compare Table (stat, ours, author, %). A square of a run and a row of Builds open the same Detail.
9. **Notice**: one line; muted for empty / loading (`пусто`, `загружаю…`), failed colour for an error.
10. **Ticket link**: `#N` link, its hover card where the tree budget allows; the number is shown once per ticket per card.
11. **Footer**: one muted `обновлено HH:MM` per tab.

## The one pointer element (#972, 13.10)
The owner (13.10 20:5x): «подчеркивания можно убрать вообще, а оставить только светлые фигуры/кнопки как у новее старее … Все должно быть
по одной логике как с визуальным дизайном монитора … чтобы если мы добавили какой то нестандартный элемент или слайдер очередной - ничего
старого не сломалось».

- ONE hover look: the host's light rectangle on the element's own face. No underline anywhere; no host `Link` and no `Markdown` link is drawn
  on the desktop (both show an underline and are laid on the host's 19-px text lines while a card row is 26 px: #972's audit measured their
  zones −8 … +14 px off the number).
- ONE element: `pressEl` (`hooks/register.tsx`): a plain host `Button` in an absolute `Box` at `top: 0` of its row Box, `left` = the cell column of
  its drawn face. The picture draws every word, number, icon and capsule a row holds, in the picture's own font and colour; the Button's label is
  blanks as wide as that face, placed ON it (`blankSpan`: the Box's left is the cell edge at or before the face's first px, a lead of plain no-break
  spaces before the Button carries the rest, the label is em spaces plus no-break spaces to the face's width, each end within ~1.5 px), so the host's
  light shape lights exactly it. Where the picture draws no word (a tab head, a `Ctl` control: «Открыть наш PoB»; since #994 the pager
  is two drawn chevrons and the Cost switches drawn capsules, both under blank Buttons) the Button carries the word itself and the
  host draws it (in the host's text colour, dim when secondary: a Button's child Text is never drawn by the host). A ticket number's press opens its
  URL through the system handler (`openUrl`); every other press runs its own closure.
- ONE row model (`rowsOne`): a card's rows are one picture; over it one absolute column of row Boxes IN THE FLOW, each as high as its row in px
  (a blank Svg gives the height), so a row's Box stands on its picture row exactly in every state. A data row's Box is keyed (`hv-<card><n>`) and
  lights NOTHING of its own (the owner's eye, 13.10 22:15: a Box fill is a square slab over the rounded pill, «квадратный хайлайт»; a picture of the
  pill revealed under the pointer, the baseline's pill form, costs ~290 characters a row and put the heaviest state at 106,000: the pane unmounts).
  The one light in a card is the element's. A table row is a keyed absolute Box at its 19-px line (`tableEl`) with the translucent veil band: a 19-px
  band on a 19-px row, the zebra's 5-px corners the only difference. The picked run's outline in the picture is the selection, not a hover. The pane
  refuses the host's focus ring (`ui.focus` without `next`), so no ring stays on a pressed Button. No size tier picks another placement: there is one drawn form; the tree's size is measured and
  recorded (#944) against the host's limit (100,000 serialized characters unmount the pane; the pane's target is 95,000 with the press stamps counted:
  section «The tabs and the size of a tab»). The diets that keep it there change no look: an em space
  (U+2003, 14.75 px) as the blank of a label, an empty Svg as a row's spacer.
- A new element, card, pager or opening block goes through `pressEl` or it is not a pointer element. `test/hover-972.test.tsx` walks whatever the
  pane draws in every state its openers reach and fails on any Link / Markdown, any element off its drawn text, any second mechanism in a row.

## The tabs and the size of a tab (#972 / #983, 14.10)

The host blanks a pane whose drawn tree (the tree of the SHOWN tab) passes 100,000 characters. So the pane is cut into tabs, and no tab is sized by today's rows:

| tab | holds |
|---|---|
| «Главная» | Agents, Merge, PC, Laptop (nothing of the project's own runs) |
| «POB» | the runs card, the picked run's builds under it, the open build with its stats |
| «Билды» | the readings queue, the open reading's facts and stats |
| «Тикеты» | «Цели», «Вне целей» |
| «Расходы» | one of three groups behind a second switch under the period's: «Роли и модели», «Кто кого запускает», «Дни и тикеты» |
| «Прогресс» | the ten fixed lines of the open tickets, in two cards (#995): «По тикетам» (every line of a ticket's state), then «Остальное» (the folders) |

- **One budget** (`hooks/budget.ts`): the target is 95,000 (the host's limit less 5,000). A tab is first drawn WHOLE and measured: under the target that draw is the pane's, exact.
  Only a tab that does not fit is budgeted: it is drawn with every growing list empty (its fixed part, measured), the room left is shared between the lists, and each list
  draws the page it was given. No list has a page size of its own; a design cap («Готово» 6 runs a page, the picked run 8 builds a page) only narrows what the budget gives.
- **One behaviour a kind of list, on every tab.** A list that does not fit gets the pager (two icon buttons, #994) with its counter (on its label row in a queue, in the card's
  corner elsewhere). A row whose own child rows do not fit keeps as many as fit and ONE calm row that counts the rest: «ещё N …» under a session, a run, a build line
  («ещё N сидов»), a model («остальные (N)»), an offline Laptop («шло: ещё N»).
- **A text never sizes a row.** A row's line of a picture's alt is cut at 160 characters, a free line (an error) at 200; an open reading's hint at 600, its remarks at 8 rows
  of 300 characters and one row that counts the rest.
- **Proven, not assumed.** `test/budget-kinds-983.test.tsx`: for every kind of row the pane's charge is at or over what is drawn (one list filled, from one row to far more
  than fit). `test/worst-case-972.test.tsx`: every tab and every group x period of «Расходы» in the worst case (rows that share nothing, 256-character texts, every opener
  open, the faces at the largest file's size, 49 stat rows) draws at most 95,000. A new list goes through `lane` and gets a family in the first test and rows in the second.

## The one table (#683 round 5 (E), 10.10)
The owner: «должны ВСЕ таблицы быть одного вида/стиля» and «Если что то не умещается и многоточит, значит оно там
быть не должно». On the desktop every table of every tab is `tableSvg` drawn by `tableEl`: one plain picture on the
19-px line grid (muted column labels and a 1-px rule, zebra bands), one keyed hover Box a data row.
- What the row is about stands first (a label, a ticket), the numbers stand at the right edge, right-aligned; the
  same number is on the same column in every table of a tab (Cost: `$`, «ходов»).
- No word is cut. `tableFit` gives each column the width of its widest word; a column with no room leaves the table
  whole, in the order its table names (Tickets: the held / blocked mark, then «готово»; «По моделям»: the note, `%`,
  «ходов»; «По дням» / «По тикетам»: «ходов»; a kind: the mean; a breakdown: `%`; Progress: the bar).
- No code word is drawn (the owner 10.10 12:1x: «хватит сюда нести тупо вериблы из кода», «это UI/UX»): a card's
  name, a column label, a row label and a footer are plain Russian («По моделям», «тикет», «ходов», «контекст на
  ход», «обновлено 23:50» without seconds); a model id is shown as the model's name (`modelName`:
  `claude-haiku-4-5-20251001` = «Haiku 4.5»), a triage label in plain words (`LABEL_WORD`: `ready-for-agent` =
  «готов агенту»). Kept as they are: game / PoB terms, a ticket's title, the role names (ORCH, autopilot, keymaster,
  worker, …), `$` and `%`. `test/onelook.test.tsx` (`noCode`) holds it on Tickets, Cost and Progress.
- The one text that is long by nature (a ticket's title) wraps onto further lines of the picture: the row, its band
  and its hover Box are that many lines high.
- A ticket's `#N` (a Link, with its hover card on Cost) and the tree's toggle are native, inside the row's hover Box
  at their pane column; the picture leaves them out.
- A share of a whole is the table's own 6-px bar (the versus bar without its mark).
- An icon is a cell like a word (`icon: [name, colour]`, 12 px on the row's line). A press whose face is an icon (the
  tree's toggle) = the icon in the picture and over it the native plain Button with a blank label (two no-break
  spaces), so the press is native and nothing is read on it.
The terminal keeps its text tables.

## A ticket's state (Tickets tab, 10.10)
One icon a row, the shapes GitHub draws, in the state's colour; the legend above the cards is the same eight icons
with their words.

| state | icon | colour |
|---|---|---|
| в работе | `issue-opened` (a ring with a dot) | green (active) |
| ждёт тебя | `person` | orange |
| готов агенту | `bot.hubot` (the Agents card's icon) | blue |
| ждёт тикеты | `hourglass` | yellow |
| открыт | `circle` | ink |
| не разобран | `draft` (a dashed ring) | muted |
| закрыт | `issue-closed` (a ticked ring) | purple (done) |
| не делаем | `skip` (a ring struck through) | muted |

At the row's right edge the `hourglass` stands once more only on an open ticket that waits for other tickets while
its state says something else (in work, waits for you). A ticket's hover card (Cost) draws its state and its author
as an icon with its word.

## Расходы (Cost tab, 10.10)

One population, the collector's `cut` of the period (`cost_*.cut`), cut twelve ways. Every cut that claims the whole sums
to the same total (`total.cost_usd`). Above them one head line: the period at the left, at the right the bold
`$ · ≈ N % недельного лимита · tokens`, always in percent (#995: the old `N.N недельного лимита` from 150 % up had no unit). The unit word is `месячного лимита` for the month (`total.limit_days` 30; #1018), `недельного` for a day or a week (7, or absent).

| card | a row is | the bar is |
|---|---|---|
| По ролям | `by_role` as ranked: brain, ORCH, autopilot, keymaster, worker, worker-strong, researcher-find, researcher-how, `другие субагенты`, `другие чаты`, `моды`; muted `сколько` = `143 сессии` / `278 субагентов` / `4 065 вызовов` | share of the total |
| ORCH / autopilot / brain: сам и кого запускает | `сам` (its own turns), then a row per role it started; muted `субагентов`, `за сессию`, `в день` (no `в день` in day mode); sub = `N сессий · всего $X`; a spawner with no turn in the period = the head only. keymaster has no card | share of the card's own total |
| Моды | `мод` (unslop / монитор), muted model name, `вызовов`, `в день`; sub = `$ mods из $ total` | share of the mods' sum |
| По чатам | a chat by its title or `чаты без названия`; the ten dearest, then `остальные (N)`; muted note = its subagents' $; no ORCH / autopilot / keymaster / mod | share of the card's sum |
| По моделям: кто вызывает | two levels (`by_role_model`): a model (normal text), under it one muted row per role on it, ranked by $, indented one level like the Tickets tree; extra column `сколько` = `N сессий / субагентов / вызовов` (blank on the model row); a pair with no tokens and no $ is not drawn | share of the total (the same denominator on both levels) |
| Роль на разных моделях | right after По ролям, no sub; a row per role x model, groups in the order brain, ORCH, autopilot, keymaster, worker, worker-strong, researcher-find, researcher-how, другие субагенты, другие чаты, unslop, монитор; the role named on the first row of its group; columns `роль`, `модель`, `дни` (first - last live day), `запусков`, `в день` (per day from first to last, inclusive), `$ за запуск` (three decimals under $0.10), `токенов за запуск`, `$`; no bar, no `% лимита`. Narrow pane: `в день`, `дни`, `токенов за запуск` leave in that order | none |
| ORCH на разных моделях: результат | right after the ORCH spawner card; a row per model that led ORCH sessions (`led > 0`), by first day: `модель`, `дни`, `сессий`, `субагентов за сессию`, `$ за сессию`, `тикетов закрыто` (dispatcher records, since 26.09), `$ за тикет`; $ = ORCH itself plus its subagents. Narrow pane: `дни`, then `субагентов за сессию` leave | none |
| По виду токенов | ввод / запись в кэш / чтение из кэша / вывод, dearest first | share of the total |
| По дням | every day of the period, newest first, zero days kept (#995: the month's 30 too, no «остальные (N)» row) | share of the dearest day |
| По тикетам | state icon, `#N` (native Link with its hover card), title (wraps whole), then `остальные тикеты (N)` and `без тикета`; no bar | none |

A rate (`за сессию`, `в день`): from 10 an integer, from 0.05 one decimal, above 0 `<0.1`, else `0`; `в день` = per
calendar day of the period (`cut.days`). Agent types (`effort-high`, `general-purpose`) are Claude Code's, not roles: they
are not drawn. A card with no rows draws its table head only.

**Card rule (#774, owner 10.10):** a Cost card is its title and its table, nothing else: no note or foot line under or beside
it; a sub beside the title only when it is a count or a sum (`144 сессии · всего $472`), a definition is not drawn; every
row of every table lies under the same hover Box as on the main tab. The tab ends with ONE muted line:
`1 % недельного лимита ≈ $16.5 по ценам API · обновлено HH:MM`.

Trailing columns, the same in every card: bar (64 px), `% лимита` (cost / $16.5, the weekly limit's API-equivalent a
percent), `$`, `токенов` (k / M / B). In a pane too narrow they leave in this order: the extra count columns (the last
one first), the note, `токенов`, `% лимита`, the bar (the tickets card: `токенов`, then `% лимита`). No turns, no context on the tab.

## One place per fact
| fact | lives in |
|---|---|
| a ticket a session holds | its own group row under the session (icon = the ticket's GitHub state), once |
| what an agent does now | the words column of its row |
| model / ctx | meta columns, aligned across all rows of the card |
| progress | the Progress column, a / b written once |
| a queue place | the first column of a waiting row |
| elapsed / took / waited | the time column (always the last) |
