"""Child seeds of the optimizer, derived from the build seed by a hash, never by a linear formula (#464).

`seed + 7919 * p + d` made build seeds s and s+1 share draw seeds, and different purposes collide across build
seeds a few apart, so the seeds of a benchmark run were not independent samples. `derive_seed` hashes the tuple
(build seed, purpose, indices) with blake2b and keeps 53 bits: the result reaches PoB's LuaJIT `math.randomseed`
as a double and must stay exact.
"""

from __future__ import annotations

import hashlib

SEED_BITS = 53

# One purpose per derivation site; a callee that derives again from the seed it was given uses its own purpose.
PURPOSE_CONSTRUCT_RIG_GEAR = "construct.rig_gear"
PURPOSE_CONSTRUCT_RIG_FINAL_GEAR = "construct.rig_final_gear"
PURPOSE_CONSTRUCT_GEAR = "construct.gear"
PURPOSE_CONSTRUCT_GEAR_PASSES = "construct.gear_passes"
PURPOSE_HEADROOM_SLOTS = "loop.headroom_slots"
PURPOSE_HEADROOM_ROLLS = "headroom.rolls"
PURPOSE_LOOP_FILL_SLOT = "loop.fill_slot"
PURPOSE_JOINT_KICK_RNG = "joint.kick_rng"
PURPOSE_JOINT_FILL_SLOT = "joint.fill_slot"
PURPOSE_TREE_KICK = "kick.tree"
PURPOSE_JOINT_ROUND = "kick.joint_round"
PURPOSE_LOOT_FILL_SLOT = "loot.fill.slot"
PURPOSE_WISHLIST_FILL_SLOT = "wishlist.fill.slot"
PURPOSE_TEMPLATE_TIES = "wishlist.ties"
PURPOSE_TREE_TIES = "tree.ties"

PURPOSES = (
    PURPOSE_CONSTRUCT_RIG_GEAR,
    PURPOSE_CONSTRUCT_RIG_FINAL_GEAR,
    PURPOSE_CONSTRUCT_GEAR,
    PURPOSE_CONSTRUCT_GEAR_PASSES,
    PURPOSE_HEADROOM_SLOTS,
    PURPOSE_HEADROOM_ROLLS,
    PURPOSE_LOOP_FILL_SLOT,
    PURPOSE_JOINT_KICK_RNG,
    PURPOSE_JOINT_FILL_SLOT,
    PURPOSE_TREE_KICK,
    PURPOSE_JOINT_ROUND,
    PURPOSE_LOOT_FILL_SLOT,
    PURPOSE_WISHLIST_FILL_SLOT,
    PURPOSE_TEMPLATE_TIES,
    PURPOSE_TREE_TIES,
)


def derive_seed(seed: int, purpose: str, *indices: int) -> int:
    """A deterministic child seed in [0, 2**53) for (seed, purpose, indices)."""
    encoded = "|".join([str(int(seed)), purpose, *(str(int(i)) for i in indices)]).encode("utf-8")
    digest = hashlib.blake2b(encoded, digest_size=8).digest()
    return int.from_bytes(digest, "big") >> (64 - SEED_BITS)


def tie_rank(seed: int, purpose: str, label: str) -> int:
    """A seeded priority for one candidate, to break an exact tie between candidates PoB scored the same (#619).

    A stage that takes the best of its candidates by PoB's number keeps the first of two equal ones, or the
    alphabetically last, so every seed met the same pick wherever two candidates measured equal. The rank is a
    hash of the candidate's own label, not a draw from a shared stream: it does not depend on the order the
    candidates were listed in, nor on how many ties came before (#12), and it never overrules a number PoB
    separated. The larger rank wins.
    """
    encoded = "|".join([str(int(seed)), purpose, label]).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(encoded, digest_size=8).digest(), "big") >> (64 - SEED_BITS)
