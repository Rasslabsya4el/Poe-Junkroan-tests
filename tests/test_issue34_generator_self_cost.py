"""#34 unit 2: the generator's self-cost refresh prices like the judging's (gem levels, Trauma stacks)."""

from types import SimpleNamespace

from junkroan.optimizer import config_rules, judging
from junkroan.search import generator


class _Pob:
    def read_state(self):
        return {"skills_state": {"main_socket_group_id": 1, "socket_groups": [{
            "socket_group_id": 1,
            "gems": [{"gem_name": "Fireball", "skill_id": "Fireball", "level": 21}, {"gem_name": "Trauma", "skill_id": "SupportTrauma", "level": 20}],
            "active_skill_entries": [],
        }]}}

    def config_inputs(self):
        return {"traumaStacks": 6}


def test_refresh_passes_gem_levels_and_trauma_stacks(monkeypatch):
    seen = {}

    def fake_context(text, tags, triggered, gems, **kw):
        seen.update(kw, gems=list(gems))
        return "ctx"

    monkeypatch.setattr(generator, "self_cost_context", fake_context)
    monkeypatch.setattr(generator, "with_self_cost", lambda objective, ctx: ctx)
    monkeypatch.setattr(config_rules, "build_text", lambda pob: "")
    monkeypatch.setattr(generator, "active_gems", lambda: {})
    pob = _Pob()
    me = SimpleNamespace(pob=pob, objective=SimpleNamespace(floors=("SelfCostPerSecond",), relations=()))
    generator.SkeletonGenerator._refresh_self_cost(me, SimpleNamespace(main_link=["Fireball"]))
    assert dict(seen["gem_levels"])["Fireball"] == 21
    assert seen["gem_levels"] == judging.main_group(pob)[2]
    assert seen["trauma_stacks"] == judging.trauma_stacks(pob) == 6.0
