# Repository Baseline

Organs is the version-controlled home of the Renaissance runtime substrate.

The repository was initialized from the existing /srv/organs implementation
after Forge was deliberately removed from the live system.

## Baseline rules

- Runtime databases, caches, histories, and machine-local state are not source.
- Service contracts live in the repository.
- Installation scripts implement the documented contracts; they do not define
  them.
- Historical material may explain the repository's origin but does not define
  its current mission.

## Current engineering mission

Keep Organs dependable as Renaissance infrastructure.

The immediate engineering priorities are:

1. eliminate stale references to retired components;
2. keep service boundaries explicit;
3. keep local network exposure consistent with SECURITY.md;
4. preserve isolated, reproducible tests;
5. clarify persistence ownership;
6. maintain bounded execution and human approval paths;
7. integrate Renaissance domain organs only through explicit contracts.

No domain capability should be absorbed into Organs merely because it is
convenient to implement there.
