"""Dependency-free core.

Everything in this package imports only the standard library. That is a hard
rule, enforced by tests/core/test_no_third_party.py, and it buys three things:
the dedup / gating / storage logic is unit-testable without installing
anything, a broken third-party release can never take down state handling, and
cold-start install time on the CI runner stays in the single-digit seconds.
"""
