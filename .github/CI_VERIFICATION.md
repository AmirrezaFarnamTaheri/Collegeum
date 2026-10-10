# Pull-request CI verification

The `ci` workflow runs on pull requests against the **merge ref**, on Python 3.11
and 3.12. Its checks are required in this order:

1. Dependency-free core tests before installation.
2. Install `.[dev,portals]`.
3. Verify the committed single-file distribution with
   `python tools/verify_single_file.py`.
4. Evaluate the golden fixtures and run the offline smoke check.
5. Lint `src`, `tests`, and `tools`, and run strict `mypy src`.
6. Execute the complete pytest suite with coverage.
7. Build and verify source/wheel archives.
8. Enforce the dependency-free core contract under pytest.

If distribution verification fails, regenerate with `python
tools/build_single_file.py` **after** all source, workflow, and included
documentation edits. The `refresh-release` workflow also synchronizes
`uv.lock` and the reproducible distribution on the maintained PR branch.

A generated-artifact commit with `[skip ci]` does **not** establish successful
CI. Follow it with a non-skipped commit or explicitly run the workflow against
the new branch head. Do not merge unless both Python matrix jobs complete
successfully. Never disable a failing check just to make CI green.
