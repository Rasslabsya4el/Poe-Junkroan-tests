"""The working build's state, taken and put back through one type (#813, step 4 of #32).

A rejected change goes back by restoring parts of five: PoB's XML, the Skeleton, the gear filler's
memory, the trees' `history`, and the judging context. Every site names the parts it takes
(`Snapshotter.take`) and the same parts come back (`Snapshotter.restore`); a part a site did not take
is not touched. Nothing here scores, derives or judges: a restore is the XML's own lanes plus what was
saved, no PoB call except `load_xml` itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from typing import Any, Callable, Sequence

from junkroan.optimizer.judging import Mark


@dataclass(frozen=True)
class FillerScope:
    """Which part of the filler's memory a snapshot holds (the filler is `LootGear` / `WishlistGear`).

    `slot` None: the whole `current_raw`; a slot name: that slot's raw only (the gear move rolls one slot).
    `plan`: the filler's whole plan and bookkeeping (`plan_snapshot`, the resistance plan included) instead
    of the resistance plan alone."""

    slot: str | None = None
    plan: bool = False


@dataclass(frozen=True)
class SkeletonFields:
    """A Skeleton part that is a few named fields, not the whole copy. `names` are put back with `setattr`
    (a field the skeleton lacks reads as None); `in_place` are dicts put back inside the same object, so
    whoever holds it (the lanes, the judging) sees the restore (`tuned_choices`, D66). `whole` also deep-copies the
    whole Skeleton (`skeleton=True`) and puts every field back, except the `in_place` dicts, which keep their object (#854)."""

    names: tuple[str, ...] = ()
    in_place: tuple[str, ...] = ()
    whole: bool = False


# what `_finish`'s guarded steps and its D66 fallback write on the skeleton instead of into PoB's XML
SKELETON_IDENTITY = SkeletonFields(names=("pantheon_major", "pantheon_minor", "bandit"), in_place=("tuned_choices",))

# the whole Skeleton, `tuned_choices` restored inside its own dict: a revert after a step that re-judges (the counts
# `refresh_minion_counts` writes) or runs a pass of picks and moves (`main_link`, `extra_groups`, `aura_levels`) (#854)
SKELETON_WHOLE = SkeletonFields(in_place=("tuned_choices",), whole=True)

FILLER_ALL = FillerScope(plan=True)
FILLER_RAW = FillerScope()  # `current_raw` and the resistance plan


def filler_slot(slot: str) -> FillerScope:
    return FillerScope(slot=slot)


@dataclass
class Snapshot:
    """What `Snapshotter.take` took; a part that was not taken is None."""

    xml: str | None = None
    skeleton: Any = None  # a deep copy of the whole Skeleton
    skeleton_scope: SkeletonFields | None = None
    skeleton_fields: dict[str, Any] | None = None  # the named fields' values, the in-place dicts copied
    filler_scope: FillerScope | None = None
    filler_raw: Any = None  # the `current_raw` dict, or the one slot's raw (None: the slot was empty)
    filler_plan: dict[str, Any] | None = None  # `plan_snapshot()` or `resistance_plan_snapshot()`
    history: list[tuple[Any, int]] | None = None  # (tree optimizer, len(history))
    judging: Mark | None = None


@dataclass
class Snapshotter:
    """The five holders of the working build's state. `trees` is read when a snapshot takes `history`."""

    pob: Any
    skeleton: Any
    filler: Any
    judging: Any
    trees: Callable[[], Sequence[Any]]

    def take(self, *, xml: bool | str = False, skeleton: bool | SkeletonFields = False, filler: FillerScope | None = None,
             history: bool = False, judging: str | None = None) -> Snapshot:
        """`xml`: True exports PoB's XML now (one PoB call); a str is an XML already exported, kept as it is.
        `skeleton`: True deep-copies the whole Skeleton; a `SkeletonFields` takes those fields only.
        `judging`: a `Judging.mark` scope."""

        snap = Snapshot()
        if xml is True:
            snap.xml = self.pob.export_xml()
        elif xml:
            snap.xml = str(xml)
        if isinstance(skeleton, SkeletonFields):
            snap.skeleton_scope = skeleton
            snap.skeleton_fields = {name: getattr(self.skeleton, name, None) for name in skeleton.names}
            for name in skeleton.in_place:
                snap.skeleton_fields[name] = dict(getattr(self.skeleton, name, None) or {})
            if skeleton.whole:
                snap.skeleton = copy.deepcopy(self.skeleton)
        elif skeleton:
            snap.skeleton = copy.deepcopy(self.skeleton)
        if filler is not None and self.filler is not None:
            filler_obj = self.filler
            snap.filler_scope = filler
            if filler.slot is not None:
                snap.filler_raw = filler_obj.current_raw.get(filler.slot)
            else:
                snap.filler_raw = dict(filler_obj.current_raw)
            snap.filler_plan = filler_obj.plan_snapshot() if filler.plan else filler_obj.resistance_plan_snapshot()
        if history:
            snap.history = [(opt, len(opt.history)) for opt in self.trees()]
        if judging is not None:
            snap.judging = self.judging.mark(judging)
        return snap

    def restore(self, snap: Snapshot, *, keep_rejections: bool | None = None) -> None:
        """Put back the parts `snap` holds, in the order XML, Skeleton, filler, history, judging.

        `keep_rejections` None: the trees' history is trimmed and nothing else; a bool also calls each tree's
        `invalidate_after_recovery(keep_rejections=...)` (the loop's move restore)."""

        if snap.xml is not None:
            self.pob.load_xml(snap.xml)
        if snap.skeleton is not None:
            self._restore_skeleton(snap.skeleton, keep=snap.skeleton_scope.in_place if snap.skeleton_scope is not None else ())
        if snap.skeleton_fields is not None:
            self._restore_skeleton_fields(snap)
        if snap.filler_scope is not None and self.filler is not None:
            self._restore_filler(snap)
        if snap.history is not None:
            for opt, mark in snap.history:
                del opt.history[mark:]
                if keep_rejections is not None:
                    invalidate = getattr(opt, "invalidate_after_recovery", None)
                    if callable(invalidate):
                        invalidate(keep_rejections=keep_rejections)
        if snap.judging is not None:
            self.judging.restore(snap.judging)  # no PoB call: the castability refold reuses the frozen context

    def _restore_skeleton(self, saved: Any, keep: Sequence[str] = ()) -> None:
        """Every field of the copy back; the `keep` fields are left to `_restore_skeleton_fields` (restored inside their own object)."""

        skeleton = self.skeleton
        if hasattr(skeleton, "__dataclass_fields__"):
            for item in fields(skeleton):
                if item.name not in keep:
                    setattr(skeleton, item.name, getattr(saved, item.name))
            return
        for name in tuple(vars(skeleton)):
            if not hasattr(saved, name):
                delattr(skeleton, name)
        for name, value in vars(saved).items():
            if name not in keep:
                setattr(skeleton, name, value)

    def _restore_skeleton_fields(self, snap: Snapshot) -> None:
        skeleton, scope, saved = self.skeleton, snap.skeleton_scope, snap.skeleton_fields
        for name in scope.in_place:
            held = getattr(skeleton, name, None)
            if held is not None:
                held.clear()
                held.update(saved[name])
        for name in scope.names:
            setattr(skeleton, name, saved[name])

    def _restore_filler(self, snap: Snapshot) -> None:
        filler, scope = self.filler, snap.filler_scope
        if scope.slot is None:
            filler.current_raw = dict(snap.filler_raw)
        elif snap.filler_raw is None:
            filler.current_raw.pop(scope.slot, None)
        else:
            filler.current_raw[scope.slot] = snap.filler_raw
        if scope.plan:
            filler.plan_restore(snap.filler_plan)
        else:
            filler.restore_resistance_plan(snap.filler_plan)
