# Semantic adequacy rubric — v2 draft 1

These are synthetic statements of understanding, not observations of a person's
competence. Judge only whether the supplied explanation meets the unit's stated
criterion. A correct answer grants permission for that unit alone.

For `skip`, the explanation must identify the causal mechanism or distinction
requested by the criterion, cover each requested component, and avoid a material
contradiction. If a remedy or implementation consequence is requested, it must
also be present and relevant. Short explanations can qualify; word count,
confident phrasing and reuse of terminology do not establish understanding.

For `read`, the explanation contains a substantive misconception, omits a required
mechanism, or proposes behavior inconsistent with the criterion. A mere list of
steps does not satisfy a request to explain why those steps are necessary.

The benchmark uses clear supported/unsupported counterfactual pairs. It does not
sample the prevalence of mistakes in natural agent work. It does not currently
test semantic scope ambiguity or justify production safety claims. Cases that a
reviewer finds genuinely underspecified must be adjudicated before an evaluation
freeze; changing a used case requires a new dataset version.

Every concept has its own prerequisite guide, shared only by its two paired
cases. Guides describe the actual concept and its practical implications. They
are not padded to make routing overhead look cheaper, and they do not combine
unrelated units into a larger reading cost. The acting model receives the unit's
criterion and supplied explanation, not the reference guide or expected label.

Labels and rationales were authored by an agent without querying any target
backend. The author is also the agent that identified shortcomings in v1; this
is disclosed author continuity, not independent review. No human label review or
blinded adjudication has occurred. Preserve `agent_authored_unreviewed` and classify
all resulting evidence as provisional until the protocol's review requirement
is independently met.
