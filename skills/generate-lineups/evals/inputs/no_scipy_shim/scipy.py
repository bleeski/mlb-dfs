"""Eval shim: importing scipy from this directory fails loudly on purpose.

Eval 7 (missing-scipy) prepends this directory to PYTHONPATH so the build
runs in a sandbox where scipy cannot import, pinning the contract that a
missing solver is a loud, named failure, never a quiet partial build.
"""
raise ImportError("simulated absence: no_scipy_shim (generate-lineups eval 7)")
