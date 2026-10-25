1. **Agree: stop building tonight.** Burst pooling failed the frozen gate; sparse passed without saving tokens. OZ’s apparent accuracy edge did not reproduce. Further tuning tonight would risk chasing these samples. Pooling stays experimental; the gate stands.

2. **The exact README replacement I sign:**

   > **AKOR — experiments in reducing model calls, with measured trade-offs.**
   >
   > In our Sonnet 5.5 tests through `claude -p`, plain JSON pooling used about 40% fewer total tokens when jobs arrived together, largely by avoiding repeated per-call input overhead. Under staggered burst arrivals, accuracy fell from 31/32 to 30/32 and 29/32, and worst-producer latency increased by up to 25%, failing our acceptance gate. Sparse arrivals passed but saved no tokens. Compact OZ formats demonstrated no consistent token, speed, or accuracy advantage over plain JSON in these tests.

   Retract the general promises **“faster and with fewer tokens,” “fewer tokens on every call,”** and **“cuts the bill … by about 40%, and proves it.”** Remove **31× fewer / 24× faster** and **format-alone 41–43% savings** from headline positioning and promotional graphics; retain them only as explicitly scoped historical benchmark results. Token reductions are not automatically monetary savings, especially with cache pricing.

   The measured ~1.9k input overhead belongs to this tested CLI configuration—not a universal model-call constant.

3. **The owner’s morning decision:** authorize retiring the **“compact language makes agents faster and cheaper”** identity and repositioning AKOR as an **experimental orchestration toolkit with published comparative evidence**, or end active development.

   **My vote: authorize the pivot and publish the negative findings first.** The credible story is that plain batching captured the savings, while our custom wire and executor failed to establish added performance value. That is worth publishing; a superior-product claim is not.

