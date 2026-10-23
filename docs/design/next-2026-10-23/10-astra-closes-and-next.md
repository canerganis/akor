**ACCEPT.** Candidate closed with zero calls: \(2 × 1,590 / 15,647 = 20.3\% < 25\%\). Accept both changes; no paid attribution or H rewrite.

Next, prioritize **context offloading with large references and a realistically full caller**, using code review as the first new task family. This tests the strongest remaining savings hypothesis while extending correctness evidence.

- Prepare fixtures, independent scoring and exact input sizes offline.
- Compare direct batched execution against selective delegation, same Sonnet, equivalent context and deliverables. Start with two matched pairs, reversed order.
- Rank by verified correct work first, total caller-plus-worker billed tokens second, end-to-end time third. Count failures and retries.
- Expand to log triage only if the pilot justifies it.

Freeze the token cap after sizing. From 46%, admit only runs whose conservative cost fits below 58%; retain 60% as the ceiling. Leave CLI framing and O1 thinking optimization closed for now.


