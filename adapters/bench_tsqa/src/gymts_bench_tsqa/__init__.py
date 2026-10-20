"""Evaluation-only benchmark resources; no automatic import, download or execution."""


def register_bench_tsqa_plugins(registries, schemas):
    from .registration import register_bench_tsqa_plugins as register
    return register(registries, schemas)


__all__ = ["register_bench_tsqa_plugins"]
