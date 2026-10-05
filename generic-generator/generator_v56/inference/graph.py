"""Build a dependency graph from inferred edges; topologically order entity
creation (prerequisites first) and deletion (dependents before parents);
detect cycles.

Cycle strategy (documented, per DEVELOPMENT_PROMPT.md requirement #6):
if the raw dependency graph contains a cycle, we break it by removing the
lowest-confidence edge(s) on the cycle (one at a time) until it is acyclic,
and report every broken edge in the generation report as
``cycle_edges_removed``. This is a deterministic, inspectable strategy
rather than a silent one. If a cycle cannot be broken this way (shouldn't
happen since every edge removal strictly reduces edge count), an actionable
error is raised instead of proceeding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from .dependencies import DependencyEdge


@dataclass
class DependencyGraph:
    nodes: List[str]
    edges: List[DependencyEdge]
    creation_order: List[str] = field(default_factory=list)
    deletion_order: List[str] = field(default_factory=list)
    cycle_edges_removed: List[DependencyEdge] = field(default_factory=list)
    had_cycle: bool = False


class CycleError(RuntimeError):
    pass


def _find_cycle(nodes: List[str], adj: Dict[str, List[Tuple[str, DependencyEdge]]]) -> List[DependencyEdge]:
    """Return the edge list of one detected cycle (DFS-based), or [] if none."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    path_edges: List[DependencyEdge] = []

    def dfs(u: str) -> List[DependencyEdge]:
        color[u] = GRAY
        for v, edge in adj.get(u, []):
            if color.get(v, WHITE) == WHITE:
                path_edges.append(edge)
                result = dfs(v)
                if result:
                    return result
                path_edges.pop()
            elif color.get(v) == GRAY:
                # found a cycle back to v; return the edges from v onward
                cyc = []
                found = False
                for pe in path_edges:
                    if pe.source == v:
                        found = True
                    if found:
                        cyc.append(pe)
                cyc.append(edge)
                return cyc
        color[u] = BLACK
        return []

    for n in nodes:
        if color[n] == WHITE:
            result = dfs(n)
            if result:
                return result
    return []


def build_graph(entity_keys: List[str], edges: List[DependencyEdge]) -> DependencyGraph:
    nodes = list(entity_keys)
    working_edges = list(edges)
    removed: List[DependencyEdge] = []
    had_cycle = False

    while True:
        adj: Dict[str, List[Tuple[str, DependencyEdge]]] = {n: [] for n in nodes}
        for e in working_edges:
            if e.source in adj and e.target in adj and e.source != e.target:
                adj[e.source].append((e.target, e))
        cycle = _find_cycle(nodes, adj)
        if not cycle:
            break
        had_cycle = True
        # Remove the lowest-confidence edge on the cycle (deterministic:
        # ties broken by (source, target, field_name) ordering).
        worst = min(cycle, key=lambda e: (e.confidence, e.source, e.target, e.field_name))
        working_edges = [e for e in working_edges if e is not worst]
        removed.append(worst)
        if len(removed) > len(edges) + 1:
            raise CycleError("Unable to break dependency cycle deterministically.")

    # Kahn's algorithm for topological (creation) order: entity with no
    # remaining unresolved dependencies goes first. We want prerequisites
    # (targets) created before dependents (sources), so we compute
    # topological order over the "depends on" edges reversed: process nodes
    # with no outgoing (unsatisfied) dependency first.
    adj: Dict[str, List[str]] = {n: [] for n in nodes}   # source -> targets it depends on
    indegree_removed = {n: 0 for n in nodes}
    for e in working_edges:
        if e.source in adj and e.target in adj:
            adj[e.source].append(e.target)

    remaining = set(nodes)
    creation_order: List[str] = []
    while remaining:
        # Nodes whose dependencies are all already scheduled.
        ready = sorted([n for n in remaining if all(t in creation_order for t in adj[n])])
        if not ready:
            raise CycleError("Residual cycle after edge removal; cannot compute topological order.")
        for n in ready:
            creation_order.append(n)
            remaining.discard(n)

    deletion_order = list(reversed(creation_order))

    return DependencyGraph(
        nodes=nodes, edges=working_edges, creation_order=creation_order,
        deletion_order=deletion_order, cycle_edges_removed=removed, had_cycle=had_cycle,
    )
