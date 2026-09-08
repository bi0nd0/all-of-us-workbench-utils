# Publication review

`build_report` separates raw participant characteristics, weighted balance, participant flow and model results. It writes CSV, HTML and methods evidence into a review directory. Full numerical estimates remain in the private run bundle. Table percentages use explicit denominators; labels distinguish mean/SD from median and quartiles. Baseline significance tests are omitted.

The primary matched analysis models sampled case status. Its odds ratios describe associations under the sampling design; they do not establish incidence, causal effects or treatment recommendations. Conditional Wald intervals are pointwise. Firth profile intervals belong to an unconditional adjusted sensitivity. Non-estimability remains visible even if another prespecified analysis gives a finite estimate.

The [All of Us policy](https://support.researchallofus.org/hc/article_attachments/36691474331668) prohibits disclosure of counts 1–20, directly or indirectly. Automated checks screen count/complement boundaries and conservatively suppress whole variable blocks across groups. Small supporting cells can also suppress model summaries. All outputs retain `requires_manual_disclosure_and_scientific_review` status.

These checks are not a proof of disclosure safety. Review totals, model sample sizes, missingness, overlapping subgroup tables, plots, text and previous public reports together. Small-count reconstruction can occur across otherwise acceptable individual tables. Do not export a real review bundle until that review is complete. Synthetic tables contain generated participants and have no such participant-data restriction.
