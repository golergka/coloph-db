# Project instructions

Keep releases on `0.1.*` until the user changes this constraint.
The package owns transaction lifecycle, execution hooks, and connection cleanup.
Applications own authentication, principals, tenant scope, RLS, SQL settings, and domain maintenance.
Do not introduce application table names or application imports into the package.
Preserve every independent project under `examples/` and run its tests in CI.
Run the checks and artifact smoke procedure in CONTRIBUTING.md before release.
Tags identify tested commits on the public main branch. Published versions are immutable.
Never publish private credentials or private repository links in public documents.
