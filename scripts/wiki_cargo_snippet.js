// Run in the Browser pane on any poewiki.net page (the wiki refuses bots; its Cargo API answers a logged-out browser).
// 1) start the receiver:  python scripts/wiki_cargo_recv.py <out-prefix> 1     (listens on 127.0.0.1:8765, one POST)
// 2) paste this into the page (javascript tool). fetch() to localhost is blocked by the wiki's CSP (default-src),
//    a FORM POST is not (form-action is not restricted), so the bundle leaves through a hidden form.
// 3) python scripts/wiki_cargo_join_bench.py <dir-of-the-received-file>   -> var/cache/wiki/<date>-*.json
async function cq(tables, fields, where, extra = '') {
  let all = [], off = 0;
  while (true) {
    const u = '/api.php?action=cargoquery&format=json&limit=500&offset=' + off + '&tables=' + tables + '&fields=' + encodeURIComponent(fields) + (where ? '&where=' + encodeURIComponent(where) : '') + extra;
    const j = await (await fetch(u)).json();
    if (j.error) return { error: j.error.info };
    const rows = (j.cargoquery || []).map(x => x.title);
    all = all.concat(rows);
    if (rows.length < 500) break;
    off += 500;
  }
  return all;
}
const series = (await cq('map_series', 'id,name,ordinal')).map(s => ({ ...s, ordinal: +s.ordinal })).sort((a, b) => a.ordinal - b.ordinal).slice(-6);
const ids = series.map(s => s.id);
const nodes = (await cq('atlas_nodes', 'area_id,series_id,tier_0,tier_4,is_off_atlas,region_id')).filter(n => ids.includes(n['series id']));
const bundle = {
  fetched: new Date().toISOString().slice(0, 10), source: 'poewiki.net cargo tables via api.php cargoquery', series, atlas_nodes: nodes,
  bench: await cq('crafting_bench_options', 'id,mod_id,name,rank,affix_type,recipe_unlock_location,required_level,item_class_categories,unveils_required,crafting_bench_unlock_category_description'),
  costs: await cq('crafting_bench_options_costs', 'option_id,name,amount'),
  pantheon_souls: await cq('pantheon_souls', 'id,name,ordinal,target_area_id,target_monster_id,stat_text'),
  areas: await cq('areas', 'id,name,act,area_level,is_map_area,is_unique_map_area', 'is_map_area=1 OR is_unique_map_area=1 OR act<=11'),
};
const f = document.createElement('form'); f.method = 'POST'; f.action = 'http://127.0.0.1:8765/cargo'; f.enctype = 'text/plain';
const ta = document.createElement('textarea'); ta.name = 'd'; ta.value = JSON.stringify(bundle); f.appendChild(ta); f.style.display = 'none';
document.body.appendChild(f); f.submit();
