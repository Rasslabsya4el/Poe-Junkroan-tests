"""#392: day 1 carries no Pantheon power (rulebook c-pantheon); the rail fixes the gods, null gives the choice back."""
import json
from types import SimpleNamespace

from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.rails import DEFAULT_RAILS_PATH, Rails


def test_default_rails_carry_no_god():
    rails = Rails.load()
    assert rails.pantheon_major == "None" and rails.pantheon_minor == "None"


def test_json_null_means_optimizer_chooses(tmp_path):
    raw = json.loads(DEFAULT_RAILS_PATH.read_text(encoding="utf-8"))
    raw.setdefault("character", {}).update(pantheon_major=None, pantheon_minor="Abberath")
    path = tmp_path / "rails.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    rails = Rails.load(path)
    assert rails.pantheon_major is None and rails.pantheon_minor == "Abberath"


def _pipeline(rails, scores):
    class _Pob:
        calls = 0
        major = minor = "None"

        def stats(self, keys):
            type(self).calls += 1
            return {"god": self.major}

    p = BuildPipeline.__new__(BuildPipeline)
    p.rails = rails
    p.log = lambda *_a, **_k: None
    p.pob = _Pob()
    p.judging = SimpleNamespace()
    p.objective = SimpleNamespace(stat_keys=("god",), score=lambda stats: scores.get(stats["god"], 0.0))
    p._spend_extra_points = lambda _sk: 0

    def apply_config(sk, _derived):
        p.pob.major, p.pob.minor = sk.pantheon_major, sk.pantheon_minor

    p.judging.lanes = SimpleNamespace(write=apply_config)
    return p


def test_rails_identity_resets_gods():
    p = _pipeline(Rails(), {})
    sk = SimpleNamespace(bandit="None", pantheon_major="Lunaris", pantheon_minor="Abberath")
    p._rails_identity(sk)
    assert (sk.pantheon_major, sk.pantheon_minor) == ("None", "None")


def test_tune_identity_rail_fixed_never_asks_pob():
    p = _pipeline(Rails(), {"Solaris": 9.0})
    sk = SimpleNamespace(pantheon_major="Solaris", pantheon_minor="Abberath")
    chosen = p._tune_identity(sk, None)
    assert chosen == {"pantheon_major": "None", "pantheon_minor": "None"}
    assert (sk.pantheon_major, sk.pantheon_minor) == ("None", "None")
    assert p.pob.calls == 0


def test_tune_identity_rail_none_picks_best_god():
    p = _pipeline(Rails(pantheon_major=None, pantheon_minor=None), {"Solaris": 9.0})
    sk = SimpleNamespace(pantheon_major="None", pantheon_minor="None")
    chosen = p._tune_identity(sk, None)
    assert chosen["pantheon_major"] == "Solaris" and sk.pantheon_major == "Solaris"
    assert p.pob.calls > 0
