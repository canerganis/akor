# Repair package (repair-handoff-20/v1)

The defects were seeded on purpose in a purpose-built utility package; they are not independently discovered bug reports. The patch is delivered unapplied.

| Ticket | Revision | Module | sha256 | Integration rows |
|---|---|---|---|---|
| A | 1 | amounts.py | f2d673106732c950c0df69f86ed754ad803291ad3f48748816ecf6fb1c167cef | 8 of 8, seeds 0 and 1 |
| B | 1 | intervals.py | 48310d07ca26d281eafc9fe8a00637e14c39100ec7e0c45e0598e36c6324c4b1 | 8 of 8, seeds 0 and 1 |
| C | 1 | config_patch.py | 62ec4d90ae1247ff3728545ad77126e0250d6ed1f78ccbc1b7e231ad26263155 | 8 of 8, seeds 0 and 1 |
| D | 1 | jobs.py | 00c8dcbb3c9a0772f61af754b1b1dc5dc34e48635783d21ecb345ba7291ed70d | 8 of 8, seeds 0 and 1 |

Each function in the package is the exact text of an accepted model candidate; acceptance ran the frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.
