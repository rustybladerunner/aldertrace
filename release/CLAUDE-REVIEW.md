## Review: Jev Workflow Skills — Public Release Candidate

---

### Overall Assessment

The package is coherent, honest about its limits, and largely self-contained. Issues are mostly minor; one correctness concern and a few clarity repairs are needed before release.

---

### FILE: skills/README.md

**Severity: Minor (style/clarity)**

- *"An explanation saying 'the check passed' cannot supply a runner receipt"* — accurate but slightly cryptic for a first-time reader. One sentence clarifying that a Receipt must be constructed by the runner in code (not parsed from text) would help.
- The accounting paragraph is good. The phrase "Those token values are assigned for teaching" is clear; no inflation concern.
- "Mount Jeverest remains a future idea" — fine as-is; matches the brief.
- No privacy or correctness issues found.

---

### FILE: skills/jev-integrate/SKILL.md

**Severity: Minor (clarity)**

- *"Follow the current session's explicit authorization, including authorization already granted, without asking again unnecessarily"* — the qualifier "unnecessarily" is vague. Recommend: "without re-requesting authorization that is already recorded for this session."
- The publication section correctly states the skill grants no push/merge permission. Good.
- *"Do not inflate counts when several symptoms share an underlying defect, or infer dishonesty from an ambiguous measurement claim"* — the second clause is useful but reads as an aside. It could be a standalone sentence for emphasis.
- No correctness or privacy issues found.

---

### FILE: skills/jev-hypothesize/SKILL.md

**Severity: Minor (clarity)**

- *"a regex word count is a toy unit unless the declared question actually concerns words"* — slightly colloquial but acceptable given the direct-language goal.
- The "Keep neighboring ideas separate" section (Calyx, fly connectome, Rookweft) is accurate per the brief but may confuse readers with no Aldertrace context. A one-line framing sentence — "These are Aldertrace-adjacent concepts; they are listed to prevent scope creep, not because they are part of this skill" — would help public readers.
- No correctness or privacy issues found.

---

### FILE: skills/jev-integrate/references/context.md

**Severity: Minor**

- The table is clear and the Aldertrace-specific row correctly directs users to real files rather than inventing them. Good.
- *"This template is not a replacement ledger"* — correct and important; well-placed.
- No issues.

---

### FILE: skills/examples/demo.py

**Severity: Correctness (low risk, worth fixing)**

1. **`accounting` overhead calculation includes rejected cases.** `illustrative_routing_tokens` is summed over all rows, including the four rejected skips. This is intentional (routing cost is incurred regardless of outcome) and the README says so, but the code has no comment explaining this. A one-line comment — `# overhead applies to all routed cases, not only permitted skips` — prevents misreading.

2. **`run_check` race window.** The digest is taken before the subprocess runs, then rechecked after. This is a teaching example, so the window is acceptable, but the existing comment "input changed while the check ran" is sufficient. No change required.

3. **`enforce` parameter `revision` defaults to module-level `REVISION`.** If `REVISION` is changed at module level between calls, the default silently shifts. In a teaching example this is fine, but worth noting as a known limitation if this pattern is reused.

4. **`Receipt` is correctly described as runner-owned demonstration data.** The module docstring and README both say this clearly. No attestation overclaim found.

5. **`assert` for test invariant in `demonstrate()`** — using `assert` in non-test production-path code can be silently disabled with `-O`. Since the file is run with `-B` (not `-O`) and this is a demo, it is acceptable. The unittest suite should cover this invariant independently, which it presumably does (not supplied for review but referenced).

---

### FILE: skills/examples/check_fixture.py

**Severity: None**

Clean, minimal, correct. The case-sensitive comparison `{'enabled': True, 'version': 2}` correctly rejects `{"enabled": false, ...}` (Python `False` ≠ JSON `false` after parsing — actually JSON `false` parses to Python `False`, so the comparison works as intended). No issues.

---

### Usability Without Private Notes

Both skills are usable without Aldertrace notes. The context template explicitly says "missing records limit the claims/actions they support; do not invent evidence." The example requires no credentials. **Pass.**

### Preservation of Authority/Budgets/Frozen Evidence

Both skills repeat the no-duplicate-goal, no-reset-allowance, no-modify-frozen-source rules in multiple places. Slightly redundant but not harmful; the repetition reinforces the constraint across different reading paths. **Pass.**

### Demonstration vs. README Claims

The README claims: five proposed skips, one permitted, four rejected, negative net accounting. The demo code produces exactly this by construction. The README correctly labels token values as assigned for teaching. **Claims match demonstration.**

---

### Three Scenario Verdicts

**Missing project records:** Both skills correctly instruct the agent to continue read-only or offline work and identify what is missing, rather than inventing prior results or treating absence as permission. Verdict: **handled correctly.**

**Already-authorized push:** jev-integrate explicitly says "Follow the current session's explicit authorization, including authorization already granted, without asking again unnecessarily." Verdict: **handled; minor wording improvement recommended above.**

**Confident model suggesting a skip using stale evidence:** The `enforce` function rejects a receipt whose `revision` field does not match `REVISION`, regardless of the model's explanation. The "forged prose" case demonstrates that a textual claim cannot substitute for a Receipt object. Verdict: **correctly rejected by design; well-demonstrated.**

---

### Release Recommendation

**Release with minor repairs:**

1. Add one comment in `demo.py` explaining that routing overhead is summed over all rows.
2. Add one framing sentence in `jev-hypothesize/SKILL.md` before the neighboring-concepts list.
3. Optionally tighten "without asking again unnecessarily" in `jev-integrate/SKILL.md`.

No correctness blockers, no privacy issues, no inflated efficacy claims found. The Receipt model is accurately scoped. The accounting example honestly reports a negative result. The skills are self-contained for public use.

**Limitation of this review:** The unittest file was not supplied; the assertion in `demonstrate()` is not independently verified here. The reviewer has not executed the code.