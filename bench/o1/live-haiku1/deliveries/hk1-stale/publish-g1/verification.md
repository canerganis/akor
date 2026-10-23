# Repair package (repair-handoff-20/v1)

The defects were seeded on purpose in a purpose-built utility package; they are not independently discovered bug reports. The patch is delivered unapplied.

| Ticket | Revision | Module | sha256 | Integration rows |
|---|---|---|---|---|
| A | 2 | amounts.py | 7db91ad7b2f7a9098f62b34efd49b97f5afb60e9bf6dc528ee61448c3c0199f0 | 8 of 8, seeds 0 and 1 |
| B | 1 | intervals.py | a4179b07c4e03039a8e7ca29667245e7a3794ca65825065a8d746c32f1c13616 | 8 of 8, seeds 0 and 1 |
| C | 1 | config_patch.py | 2ed0ad82a1503ddef692b776f913a0fb265ccec179434e44e82254f2453dd472 | 8 of 8, seeds 0 and 1 |
| D | 1 | jobs.py | 67910248bd20b7e01b5b6eea6b37e716d0371fc3b49321acd2c41da4693bd5b3 | 8 of 8, seeds 0 and 1 |

Each function in the package is the exact text of an accepted model candidate; acceptance ran the frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.
