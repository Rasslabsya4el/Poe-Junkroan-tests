"""Probe why our pure-Python tree graph thinks a bridge node is a leaf.

Decode a PoB build, BFS from the class start through the allocated nodes (minus
a node to remove) to a target, and print the connecting path with node kinds and
names. Pure Python, no PoB process.

    python scripts/graph_path_probe.py --build <file.pob.txt>
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path
from typing import Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml
from junkroan.pob.session import decode_import_code

DEFAULT_BUILD = r"C:\Coding\poe-junkroan-archive\benchmark\20260921-2020-core14-tpl\spark-s1.pob.txt"
DEFAULT_REMOVE = 8198
DEFAULT_TARGET = 13164


def bfs_path(
    adjacency: Mapping[int, Iterable[int]],
    allocated: Iterable[int],
    starts: Iterable[int],
    target: int,
    *,
    excluded: Iterable[int] = (),
) -> list[int] | None:
    """Shortest path from any start to target walking only through allocated
    nodes, with `excluded` nodes removed. Returns the path (start ... target) or
    None when target is unreachable or excluded. Hand-made adjacency friendly."""

    allowed = {int(n) for n in allocated} - {int(n) for n in excluded}
    target = int(target)
    source_starts = {int(s) for s in starts} & allowed
    if target not in allowed:
        return None
    queue: deque[tuple[int, tuple[int, ...]]] = deque((s, (s,)) for s in sorted(source_starts))
    seen: set[int] = set(source_starts)
    while queue:
        node_id, path = queue.popleft()
        if node_id == target:
            return list(path)
        for nb in sorted(adjacency.get(node_id, ())):
            nb = int(nb)
            if nb in allowed and nb not in seen:
                seen.add(nb)
                queue.append((nb, path + (nb,)))
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", default=DEFAULT_BUILD)
    parser.add_argument("--remove", type=int, default=DEFAULT_REMOVE)
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET)
    args = parser.parse_args(argv)

    xml_text = decode_import_code(Path(args.build).read_text(encoding="utf-8"))
    allocated = parse_allocated_from_xml(xml_text)
    graph = TreeGraph.load()

    roots = graph.roots(allocated)
    path = bfs_path(graph.adjacency, allocated, roots, args.target, excluded=(args.remove,))

    print(f"build={args.build}")
    print(f"remove={args.remove} target={args.target} roots={sorted(roots)}")
    print(f"allocated={len(allocated)} nodes, target_allocated={args.target in set(allocated)}")
    if path is None:
        print("path: NONE")
        return 0
    print(f"path ({len(path)} nodes):")
    for node_id in path:
        node = graph.node(node_id)
        kind = node.kind if node else "?"
        name = node.name if node else "?"
        print(f"  {node_id}\t{kind}\t{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())