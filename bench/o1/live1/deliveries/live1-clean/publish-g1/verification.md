# Repair package (repair-handoff-20/v1)

The defects were seeded on purpose in a purpose-built utility package; they are not independently discovered bug reports. The patch is delivered unapplied.

| Ticket | Revision | Module | sha256 | Integration rows |
|---|---|---|---|---|
| A | 1 | amounts.py | 1b3511e7a7368801f42737af9c3f34745d7bd062776f973f552fab7f20fde4d0 | 8 of 8, seeds 0 and 1 |
| B | 1 | intervals.py | 09d185eeff17d0f25a7daf1196683bccfa7ebdae532e75a997447fc157641f05 | 8 of 8, seeds 0 and 1 |
| C | 1 | config_patch.py | 6d51961079f862f805530731c8f112f505f284a23cc566b0b8ce878a466d9e68 | 8 of 8, seeds 0 and 1 |
| D | 1 | jobs.py | 3bf682debce5746730b25c86d899210fe57a676b5f81056059613f084b945261 | 8 of 8, seeds 0 and 1 |

Each function in the package is the exact text of an accepted model candidate; acceptance ran the frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.
