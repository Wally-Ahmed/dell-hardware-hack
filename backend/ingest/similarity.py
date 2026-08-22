"""Cosine similarity primitives. Pure numpy, no I/O, no state.

Brute force is the design (docs/api.md §5): at demo scale — hundreds to a few
thousand vectors — a matmul is microseconds, and we are not standing up a
Mongo search node on aarch64 tonight.
"""

from __future__ import annotations

import numpy as np

# Below this, a vector is "zero" and its similarity to anything is defined as
# 0.0 rather than NaN — a dead embedding should never accidentally match.
_EPS = 1e-12

Vector = np.ndarray  # 1-D float array
Matrix = np.ndarray  # 2-D float array, rows are vectors


def cosine(a: Vector | list[float], b: Vector | list[float]) -> float:
    """Cosine similarity of two vectors. Raises on shape mismatch — the pure
    math layer stays strict; tolerant skipping of mixed-dimension stores is
    the pipeline's explicit job."""
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.shape != vb.shape:
        raise ValueError(f"cosine: shape mismatch {va.shape} vs {vb.shape}")
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na < _EPS or nb < _EPS:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def cosine_matrix(
    A: Matrix | list[list[float]], B: Matrix | list[list[float]]
) -> Matrix:
    """Pairwise cosine similarities, shape (len(A), len(B)). Zero rows score 0."""
    ma = np.atleast_2d(np.asarray(A, dtype=np.float64))
    mb = np.atleast_2d(np.asarray(B, dtype=np.float64))
    if ma.shape[1] != mb.shape[1]:
        raise ValueError(f"cosine_matrix: dim mismatch {ma.shape[1]} vs {mb.shape[1]}")
    na = np.linalg.norm(ma, axis=1, keepdims=True)
    nb = np.linalg.norm(mb, axis=1, keepdims=True)
    # Divide by 1 where the norm is ~0, then the zero vector's dot products are
    # already 0 — no NaNs, no accidental matches.
    ma = ma / np.where(na < _EPS, 1.0, na)
    mb = mb / np.where(nb < _EPS, 1.0, nb)
    return ma @ mb.T


def top_k(
    query: Vector | list[float], candidates: Matrix | list[list[float]], k: int = 5
) -> list[tuple[int, float]]:
    """Top-k (index, score) pairs, best first. Stable sort so equal scores
    keep candidate order — determinism is load-bearing for the tests."""
    if len(candidates) == 0:
        return []
    sims = cosine_matrix([np.asarray(query, dtype=np.float64)], candidates)[0]
    order = np.argsort(-sims, kind="stable")[: max(k, 0)]
    return [(int(i), float(sims[i])) for i in order]
