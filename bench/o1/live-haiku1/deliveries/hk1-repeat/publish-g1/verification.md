# Repair package (repair-handoff-20/v1)

The defects were seeded on purpose in a purpose-built utility package; they are not independently discovered bug reports. The patch is delivered unapplied.

| Ticket | Revision | Module | sha256 | Integration rows |
|---|---|---|---|---|
| A | 1 | amounts.py | de631407231ac4c32cbdee41304d5f0ad5be4284618006bcfe206652a00e951f | 8 of 8, seeds 0 and 1 |
| B | 1 | intervals.py | 196b3f8575dd8f77e222388b48642f3e1c22b216818c0a83fae74febd07ce158 | 8 of 8, seeds 0 and 1 |
| C | 1 | config_patch.py | a45cf83f6232ad5f5ac14a099f7ff46f37aa238f27fdd2d544fe66d7f0905dff | 8 of 8, seeds 0 and 1 |
| D | 1 | jobs.py | 304b45f8e3226eb365f4d386f02c04e1b17dfc2f4a66aa15cd325a9e71f817f7 | 8 of 8, seeds 0 and 1 |

Each function in the package is the exact text of an accepted model candidate; acceptance ran the frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.
