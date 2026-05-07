"""Shared domain logic for Sarjy.

Modules under `core` are deep: each presents a small, stable interface and
hides substantial complexity. Adapters (the API and the agent worker) are
deliberately shallow — they translate transport-level events into core calls
and never contain business logic that is not also exposed here.
"""
