# Repair package (repair-handoff-20/v1)

The defects were seeded on purpose in a purpose-built utility package; they are not independently discovered bug reports. The patch is delivered unapplied.

| Ticket | Revision | Module | sha256 | Integration rows |
|---|---|---|---|---|
| A | 2 | amounts.py | c161285387aa87a41481e7a3f7421b76850dfd74363e063c6f9909ef4ba7acdd | 8 of 8, seeds 0 and 1 |
| B | 1 | intervals.py | 72a7c93417b1b8eeedeef933a99f58b783a17dd8c611b6bb92c0e3c7d7b5ba3f | 8 of 8, seeds 0 and 1 |
| C | 1 | config_patch.py | ed7c02970be012fbe0fea396bd2b13698d7fd4c83b04e94243472e4da42513ee | 8 of 8, seeds 0 and 1 |
| D | 1 | jobs.py | 831df5eb9457e932a32d6bf46b7f5eaccbe31a3a2a4ad97a61a37a555cd92d28 | 8 of 8, seeds 0 and 1 |

Each function in the package is the exact text of an accepted model candidate; acceptance ran the frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.
