// #837 b11 (the diet): a picture's markup read back as what it DRAWS, so a cut of its characters is proved lossless. `shapesOf(svg)` = one line a leaf (rect, circle, path, text), its place after
// every translate / scale above it, its paint after the cascade (presentation attributes < the picture's `<style>` rules < the inline style, inherited down the groups, a `<use>` resolved to its
// def), numbers to 0.01, a path as ABSOLUTE commands. So `class='sg'` for a run of attributes, `x='1.50'` for `x='1.5'`, a relative path for an absolute one read alike. `maskDigest(svg)` = the
// coverage of a mask (one path with a hole): its fill rule is applied to a grid of points, so the same hole wound the other way under the other rule reads alike.
type Mx = { sx: number; sy: number; tx: number; ty: number }
type Node = { tag: string; a: Record<string, string>; kids: Node[]; text: string }
const ID: Mx = { sx: 1, sy: 1, tx: 0, ty: 0 }
const R = (v: number) => String(+v.toFixed(2))
const apply = (m: Mx, x: number, y: number): [number, number] => [x * m.sx + m.tx, y * m.sy + m.ty]
const compose = (p: Mx, c: Mx): Mx => ({ sx: p.sx * c.sx, sy: p.sy * c.sy, tx: p.sx * c.tx + p.tx, ty: p.sy * c.ty + p.ty })
const unesc = (s: string) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')

function parseXml(src: string): Node {
  const root: Node = { tag: '#root', a: {}, kids: [], text: '' }
  const stack: Node[] = [root]
  const re = /<(\/?)([a-zA-Z][\w:-]*)((?:[^>'"]|'[^']*'|"[^"]*")*?)(\/?)>|([^<]+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) {
    const top = stack[stack.length - 1]!
    if (m[5] !== undefined) { top.text += m[5]; continue }
    if (m[1]) { stack.pop(); continue }
    const a: Record<string, string> = {}
    for (const x of m[3]!.matchAll(/([\w:-]+)\s*=\s*(?:'([^']*)'|"([^"]*)")/g)) a[x[1]!] = x[2] ?? x[3] ?? ''
    const n: Node = { tag: m[2]!, a, kids: [], text: '' }
    top.kids.push(n)
    if (!m[4]) stack.push(n)
  }
  return root
}

const INHERIT = new Set(['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'font', 'font-weight', 'font-size', 'font-family', 'font-variant-numeric', 'text-anchor'])
const PRES = [...INHERIT, 'opacity', 'clip-path', 'animation', 'transform-box', 'transform-origin']

const toks = (d: string) => d.match(/[a-zA-Z]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g) ?? []
const ARGS: Record<string, number> = { m: 2, l: 2, h: 1, v: 1, c: 6, s: 4, q: 4, t: 2, a: 7, z: 0 }
/** a path's data as absolute commands `[cmd, ...args]` (circles stay arcs), in the picture's own units */
export function absPath(d: string): (string | number)[][] {
  const t = toks(d), out: (string | number)[][] = []
  let i = 0, cmd = '', cx = 0, cy = 0, sx0 = 0, sy0 = 0
  const num = () => { const v = Number(t[i++]); if (!Number.isFinite(v)) throw new Error('path: number expected in ' + d); return v }
  while (i < t.length) {
    if (/^[a-zA-Z]$/.test(t[i]!)) { cmd = t[i++]!; if (cmd === 'z' || cmd === 'Z') { out.push(['Z']); cx = sx0; cy = sy0; continue } }
    else if (cmd === 'm') cmd = 'l'; else if (cmd === 'M') cmd = 'L'
    const lo = cmd.toLowerCase(), rel = cmd === lo
    if (!(lo in ARGS)) throw new Error('path: command ' + cmd)
    const ox = rel ? cx : 0, oy = rel ? cy : 0
    if (lo === 'm') { cx = ox + num(); cy = oy + num(); sx0 = cx; sy0 = cy; out.push(['M', cx, cy]) }
    else if (lo === 'l') { cx = ox + num(); cy = oy + num(); out.push(['L', cx, cy]) }
    else if (lo === 'h') { cx = ox + num(); out.push(['L', cx, cy]) }
    else if (lo === 'v') { cy = oy + num(); out.push(['L', cx, cy]) }
    else if (lo === 'c') { const a = [ox + num(), oy + num(), ox + num(), oy + num(), ox + num(), oy + num()]; out.push(['C', ...a]); cx = a[4]!; cy = a[5]! }
    else if (lo === 's' || lo === 'q') { const a = [ox + num(), oy + num(), ox + num(), oy + num()]; out.push([lo.toUpperCase(), ...a]); cx = a[2]!; cy = a[3]! }
    else if (lo === 't') { cx = ox + num(); cy = oy + num(); out.push(['T', cx, cy]) }
    else if (lo === 'a') {
      const rx = num(), ry = num(), rot = num(), f1 = num(), f2 = num()
      if (![0, 1].includes(f1) || ![0, 1].includes(f2)) throw new Error('path: arc flags in ' + d)
      cx = ox + num(); cy = oy + num(); out.push(['A', rx, ry, rot, f1, f2, cx, cy])
    }
  }
  return out
}
const normPath = (d: string, m: Mx) => absPath(d).map(c => {
  const k = c[0] as string
  if (k === 'Z') return 'Z'
  if (k === 'A') { const p = c as number[]; const [x, y] = apply(m, p[6]!, p[7]!); return `A${R(p[1]! * Math.abs(m.sx))} ${R(p[2]! * Math.abs(m.sy))} ${R(p[3]!)} ${p[4]} ${p[5]} ${R(x)} ${R(y)}`.replace(/^A(.*)$/, 'A$1') }
  const a = c.slice(1) as number[], o: string[] = []
  for (let j = 0; j < a.length; j += 2) { const [x, y] = apply(m, a[j]!, a[j + 1]!); o.push(R(x), R(y)) }
  return k + o.join(' ')
}).join('')

function matrixOf(tr: string | undefined): Mx {
  let m = ID
  for (const x of (tr ?? '').matchAll(/(translate|scale)\(([^)]*)\)/g)) {
    const v = x[2]!.split(/[\s,]+/).filter(Boolean).map(Number)
    m = compose(m, x[1] === 'translate' ? { sx: 1, sy: 1, tx: v[0]!, ty: v[1] ?? 0 } : { sx: v[0]!, sy: v[1] ?? v[0]!, tx: 0, ty: 0 })
  }
  return m
}

/** every leaf a picture draws, one line each, in drawing order */
export function shapesOf(svg: string): string[] {
  const root = parseXml(svg).kids[0]!
  const rules: { sel: string; decl: Record<string, string> }[] = []
  const defs = new Map<string, Node>()
  const collect = (n: Node) => {
    if (n.a.id) defs.set(n.a.id, n)
    if (n.tag === 'style') {
      const css = n.text.replace(/@[a-z-]+[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '')
      for (const r of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const decl: Record<string, string> = {}
        for (const p of r[2]!.split(';')) { const i = p.indexOf(':'); if (i > 0) decl[p.slice(0, i).trim()] = p.slice(i + 1).trim() }
        for (const sel of r[1]!.split(',')) rules.push({ sel: sel.trim(), decl })
      }
    }
    n.kids.forEach(collect)
  }
  collect(root)
  const out: string[] = []
  const styleOf = (n: Node, inh: Record<string, string>) => {
    const s = { ...inh }
    for (const k of PRES) if (n.a[k] !== undefined) s[k] = n.a[k]!
    const own: Record<string, string> = {}
    for (const r of rules) {
      const cls = r.sel.startsWith('.') ? r.sel.slice(1) : null
      if (cls ? (n.a.class ?? '').split(/\s+/).includes(cls) : r.sel === n.tag) Object.assign(s, r.decl)
    }
    if (n.a.style) for (const p of n.a.style.split(';')) { const i = p.indexOf(':'); if (i > 0) s[p.slice(0, i).trim()] = p.slice(i + 1).trim() }
    for (const k of Object.keys(s)) if (!INHERIT.has(k)) own[k] = s[k]!
    return { s, own }
  }
  const ref = (v: string | undefined) => /^url\(#([^)]*)\)$/.exec(v ?? '')?.[1]
  const norm = (s: Record<string, string>, m: Mx, ctx: string[]) => {
    const keys = Object.keys(s).sort().filter(k => !(INHERIT.has(k) === false && false))
    const items = keys.map(k => {
      let v = s[k]!
      const id = ref(v)
      if (id && defs.has(id)) { const sub: string[] = []; shapesInto(defs.get(id)!, ID, {}, [], sub, true); v = `{${sub.join('|')}}` }
      if (k === 'stroke-width') v = R(Number(v) * Math.abs(m.sx))
      return `${k}:${v}`
    })
    return items.join(';') + (ctx.length ? ` @${ctx.join('>')}` : '')
  }
  const shapesInto = (n: Node, m: Mx, inh: Record<string, string>, ctx: string[], into: string[], inDefs = false): void => {
    if (!inDefs && (n.tag === 'defs' || n.tag === 'style' || n.tag === 'pattern' || n.tag === 'clipPath')) return
    const { s, own } = styleOf(n, inh)
    const mm = compose(m, matrixOf(n.a.transform))
    const c2 = [...ctx]
    for (const k of Object.keys(own)) if (k !== 'clip-path') c2.push(`${k}=${own[k]}`)
    if (own['clip-path']) { const id = ref(own['clip-path']); if (id && defs.has(id)) { const sub: string[] = []; shapesInto(defs.get(id)!, mm, {}, [], sub, true); c2.push(`clip{${sub.join('|')}}`) } }
    // paint that is not inherited (animation, opacity, ...) rides with the leaf; the inherited paint is `s`
    const paint = Object.fromEntries(Object.entries(s).filter(([k]) => INHERIT.has(k)))
    const num = (k: string) => Number(n.a[k] ?? 0)
    if (n.tag === 'rect') {
      const [x, y] = apply(mm, num('x'), num('y'))
      into.push(`rect ${R(x)} ${R(y)} ${R(num('width') * mm.sx)} ${R(num('height') * mm.sy)} r${R(num('rx') * mm.sx)} ${norm(paint, mm, c2)}`)
    } else if (n.tag === 'circle') {
      const [x, y] = apply(mm, num('cx'), num('cy'))
      into.push(`circle ${R(x)} ${R(y)} ${R(num('r') * mm.sx)} ${norm(paint, mm, c2)}`)
    } else if (n.tag === 'path') {
      into.push(`path ${normPath(n.a.d ?? '', mm)} ${norm(paint, mm, c2)}`)
    } else if (n.tag === 'text') {
      const put = (nn: Node, text: string) => { const [x, y] = apply(mm, Number(nn.a.x ?? n.a.x ?? 0), Number(nn.a.y ?? n.a.y ?? 0)); if (text.trim()) into.push(`text ${R(x)} ${R(y)} "${unesc(text)}" ${norm(paint, mm, c2)}`) }
      put(n, n.text)
      for (const k of n.kids) if (k.tag === 'tspan') { const t2 = styleOf(k, s); const sv = { ...paint, ...Object.fromEntries(Object.entries(t2.s).filter(([q]) => INHERIT.has(q))) }; const [x, y] = apply(mm, Number(k.a.x ?? n.a.x ?? 0), Number(k.a.y ?? n.a.y ?? 0)); if (k.text.trim()) into.push(`text ${R(x)} ${R(y)} "${unesc(k.text)}" ${norm(sv, mm, c2)}`) }
      return
    } else if (n.tag === 'use') {
      const id = /^#(.*)$/.exec(n.a.href ?? n.a['xlink:href'] ?? '')?.[1]
      const target = id ? defs.get(id) : undefined
      if (!target) throw new Error('use: no def ' + n.a.href)
      shapesInto(target, compose(mm, { sx: 1, sy: 1, tx: num('x'), ty: num('y') }), s, c2, into, true)
      return
    }
    for (const k of n.kids) shapesInto(k, mm, s, c2, into, inDefs)
  }
  shapesInto(root, ID, {}, [], out)
  return out
}

/** the coverage of a mask (one path `M0 0H W V H H0Z` + a hole), by its fill rule: 1 = painted, on a grid of points off the shape's own lines */
export function maskDigest(svg: string): string {
  const root = parseXml(svg).kids[0]!
  const W = Number(root.a.width), H = Number(root.a.height)
  const p = root.kids.find(k => k.tag === 'path')!
  const rule = p.a['fill-rule'] === 'evenodd' ? 'evenodd' : 'nonzero'
  const polys: [number, number][][] = []
  let cur: [number, number][] = []
  let px = 0, py = 0
  for (const c of absPath(p.a.d!)) {
    const k = c[0] as string
    if (k === 'M') { if (cur.length) polys.push(cur); px = c[1] as number; py = c[2] as number; cur = [[px, py]] }
    else if (k === 'L') { px = c[1] as number; py = c[2] as number; cur.push([px, py]) }
    else if (k === 'Z') { polys.push(cur); cur = [] }
    else if (k === 'A') {
      const [rx0, ry0, , fa, fs, x2, y2] = (c as number[]).slice(1)
      const r = rx0!, x1 = px, y1 = py
      if (Math.abs(r - ry0!) > 1e-9) throw new Error('mask: elliptic arc')
      // centre of the circle through both ends: the two candidates are at +/- h along the chord's normal; the flags pick one
      const dx = (x2! - x1) / 2, dy = (y2! - y1) / 2, d2 = dx * dx + dy * dy
      const h = Math.sqrt(Math.max(0, r * r - d2) / d2)
      const sgn = fa === fs ? -1 : 1
      const ccx = (x1 + x2!) / 2 + sgn * h * dy, ccy = (y1 + y2!) / 2 - sgn * h * dx
      let a1 = Math.atan2(y1 - ccy, x1 - ccx), a2 = Math.atan2(y2! - ccy, x2! - ccx)
      if (fs === 0 && a2 > a1) a2 -= 2 * Math.PI
      if (fs === 1 && a2 < a1) a2 += 2 * Math.PI
      for (let q = 1; q <= 96; q++) { const a = a1 + (a2 - a1) * q / 96; cur.push([ccx + r * Math.cos(a), ccy + r * Math.sin(a)]) }
      px = x2!; py = y2!
    } else throw new Error('mask: command ' + k)
  }
  if (cur.length) polys.push(cur)
  const winding = (x: number, y: number) => {
    let w = 0
    for (const pl of polys) for (let i = 0; i < pl.length; i++) {
      const [ax, ay] = pl[i]!, [bx, by] = pl[(i + 1) % pl.length]!
      if ((ay <= y) !== (by <= y)) { const t = (y - ay) / (by - ay); if (ax + t * (bx - ax) > x) w += by > ay ? 1 : -1 }
    }
    return w
  }
  let bits = ''
  for (let iy = 0; iy < Math.ceil(H); iy++) for (let ix = 0; ix < Math.ceil(W); ix++) {
    const w = winding(ix + 0.5137, iy + 0.4219)
    bits += (rule === 'evenodd' ? (w & 1) !== 0 : w !== 0) ? '1' : '0'
  }
  return `${Math.ceil(W)}x${Math.ceil(H)}:${fnv(bits)}`
}

export const fnv = (s: string) => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 } return h.toString(16).padStart(8, '0') }
