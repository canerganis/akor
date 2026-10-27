# Astra: re-freeze decision, 2026-10-27

Request sent: the evidence pack (run_live.py diff since 17cac21, the three names the pilot uses). Decision as returned by gpt-6-astra (high):

**A. APPROVE**, subject to the checks below. The changed file invalidates the manifest, but the pilot’s used interface and separately pinned runtime remain unchanged. With no pilot runs or expenditure, this is a provenance update without changing the experiment.

**B. Conditions**

1. Compare manifests against `17cac21`. Only `code["bench/live/run_live.py"]` may differ. Preserve the runtime pins and environment requirements.
2. Add an offline regression test pinning `SYSTEM`, the `CLAUDE` resolution rule, and `count` with its o200k encoding. Check import behavior too: the diff adds a `sys.path` insertion and `bench.harness` import, so “import side effects unchanged” is too strong. Confirm intended module resolution and no model launch or ledger creation during import.
3. Recompute the full digest, update `freeze.json`, the active status and all four `--expect` commands. Preserve the historical launch record.
4. Require the pilot tests, `verify.py`, and `pilot.py freeze` to pass afterward. Record the unrelated `test_step1_traces` failure separately. Existing quota and launch gates remain binding.

**C. Append this section after successful verification:**

```markdown
## Re-freeze record, 2026-10-27

At the owner's request, Astra approved replacing digest ea306969b35100cb89ac68a34e7b39c1610569adf987cd8169cc9daa8d62d838 with DIGEST_PLACEHOLDER. The original approval is recorded at commit 17cac21. No pilot run had started and no model tokens had been spent.

Shared measurement harness commits 8afe9af, f445c5b and d0b154d changed bench/live/run_live.py. Its code hash is the only changed manifest field. The pilot's used interface, separately pinned runtime, experimental design, accounting rules and budgets remain unchanged.

Offline interface and import checks, pilot tests, verify.py and freeze verification passed. The unrelated test_step1_traces failure remains separately recorded. The active status and all four launch commands now use DIGEST_PLACEHOLDER. Existing quota admission and stop conditions still apply.
```