"""Transform node standard library.

Pure, vectorized functions over sample arrays. Deliberately tiny (keel-v2 §5):
a transform is added here only when a real model needs it.

Input conventions per fn:
    sum           inputs: [node, ...]
    weighted_sum  inputs: {node: weight, ...}
    product       inputs: [node, ...]
    ratio         inputs: [numerator, denominator]
    linear        inputs: [node]           params: {a: <mult>, b: <add>}
"""

from __future__ import annotations

import numpy as np


class TransformError(ValueError):
    pass


def t_sum(arrays: list[np.ndarray], params: dict) -> np.ndarray:
    return np.sum(arrays, axis=0)


def t_weighted_sum(arrays: list[np.ndarray], params: dict) -> np.ndarray:
    weights = params["_weights"]
    return np.sum([w * a for w, a in zip(weights, arrays)], axis=0)


def t_product(arrays: list[np.ndarray], params: dict) -> np.ndarray:
    return np.prod(arrays, axis=0)


def t_ratio(arrays: list[np.ndarray], params: dict) -> np.ndarray:
    if len(arrays) != 2:
        raise TransformError("ratio expects exactly [numerator, denominator]")
    return arrays[0] / arrays[1]


def t_linear(arrays: list[np.ndarray], params: dict) -> np.ndarray:
    if len(arrays) != 1:
        raise TransformError("linear expects exactly one input")
    a = float(params.get("a", 1.0))
    b = float(params.get("b", 0.0))
    return a * arrays[0] + b


TRANSFORMS = {
    "sum": t_sum,
    "weighted_sum": t_weighted_sum,
    "product": t_product,
    "ratio": t_ratio,
    "linear": t_linear,
}
