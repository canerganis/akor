# O1 round 2: Opus 5.5

**SIGN.** I sign Astra's final plan (o1_astra_r2) with her three corrections as conditions. All three are right:

1. H-tier domains frozen with explicit cardinalities and measured runtime before the 2 s limit is called safe. My
   millisecond claim was for A rows, not for exhaustive domains.
2. `-I` implies `-E`, so `PYTHONHASHSEED` is ignored; a hash seed cannot be changed at runtime. A controlled
   launcher (for example `-S -s` without `-E`, with an environment holding only `PYTHONHASHSEED` and what Windows
   needs to start Python) verified at G2 for both seeds. Rejecting tuples and other unsupported types before
   `json.dumps` is needed, since it would turn a tuple into a list.
3. A separate 4,096-byte limit on the decoded source. Escapes can grow a source up to six times, so my 4,200
   serialized bytes was wrong.

One clarification, not a dispute: "admission must cover the enforced billable completion limit" applies only if
the pinned route enforces one. If `claude -p` on this route enforces none, the freeze says so, the reserve stays
measured input plus the declared headroom, and Astra's round 1 rule holds: any actual overrun of the allocation
prevents an overall pass. No output-limit setting is added to the route for this gate, since that would change the
pinned route.
