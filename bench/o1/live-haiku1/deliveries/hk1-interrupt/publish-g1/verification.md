# Repair package (repair-handoff-20/v1)

The defects were seeded on purpose in a purpose-built utility package; they are not independently discovered bug reports. The patch is delivered unapplied.

| Ticket | Revision | Module | sha256 | Integration rows |
|---|---|---|---|---|
| A | 1 | amounts.py | a8cbae9dceb9d8472ab0c9fb7d43e6009b548b256c3801ac2484210c7f5b5275 | 8 of 8, seeds 0 and 1 |
| B | 1 | intervals.py | 3685e9d482a85321309c950c2926af3ad6ea2eac9c13a8f322aefaad535b93b4 | 8 of 8, seeds 0 and 1 |
| C | 1 | config_patch.py | c5f867cf122b83794beaf814261db00d0889263eb14c318f8bbaf7f98e94e449 | 8 of 8, seeds 0 and 1 |
| D | 1 | jobs.py | 127a5f20fdc323982a131c022deab9e66e31a6c4a20717c4eb83d38e58180a02 | 8 of 8, seeds 0 and 1 |

Each function in the package is the exact text of an accepted model candidate; acceptance ran the frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.
