# pob-slots

The Junkroan monitor pane.

## Silence flag (#821)

File: `C:/Users/user/.claude/mods/pob-slots/bin/.cache/pane.silenced` (next to `redraws.log`).

While it exists, every pull (`python collect.py <mode>`) and every redraw is skipped; the pane keeps its last
picture. Delete the file and pulls and redraws resume within one fast tick (5 s). The flag is checked at the top of
each pull, never cached.

## Error line in `bin/.cache/redraws.log`

A pull or render error adds one line:

    <ISO time> <sessionId> error <kind> <message>

`kind` is `pull` or `render`; the message is one line (whitespace runs become one space), cut to 200 characters.
A healthy pull writes none. The redraw line shape `<ISO time> <sessionId> <tabKey> <chars>` is unchanged.
