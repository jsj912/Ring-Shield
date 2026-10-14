# HANDOFF - gitignored data files for the L4 explainability layer

Branch `contract-ccy-valrings` (rings contract schema v2). Generated 2026-10-11 on the
primary checkout; every hash below was computed from the file on disk, not copied from a log.

Verify any file with:

```bash
sha256sum <path>
```

**Two groups.** Group A is in `xai_handoff.zip`. Group B is **not** - those files have not changed,
so the hashes are here for you to verify the copies you already have rather than receive them
again. If a Group B hash does not match your copy, say so before running anything: a silent
mismatch there would get attributed to the schema change, which is exactly the wrong diagnosis.

Total: **Group A 908.40 KiB** across 19 files, **Group B 3.27 GiB** across 22 files.

**Your suite passes on the merge: 116 passed, 0 failed.** See the last section for what that took.

---

## Group A - new or changed. These are in `xai_handoff.zip`.

| path | bytes | size | sha256 |
|---|---:|---:|---|
| `contract/out/rings_full_gine_causal_1.parquet` | 57,618 | 56.27 KiB | `9d1e0b9e692a4680608edfe1e1811691c0f94a3c423943029632886f8fab5328` |
| `contract/out/rings_full_gine_causal_2.parquet` | 57,736 | 56.38 KiB | `24523fef076afa616601141d6ef8dab7f9143bb9e611dd32d5a081f683655fec` |
| `contract/out/rings_full_gine_causal_3.parquet` | 58,041 | 56.68 KiB | `a39737ff9e2763d0a69505e71dcbf47b2849ccbfcffff570286bf587198ae2f8` |
| `contract/out/rings_full_gine_causal_4.parquet` | 58,797 | 57.42 KiB | `b254038a6572a373f5953b45696ad01b53c73c0f956fa15ee7d1f97407d2615d` |
| `contract/out/rings_full_gine_causal_5.parquet` | 53,807 | 52.55 KiB | `e0653d2c09a722aa9c0ce19f756cf09674be108634f07d11fd45bf74c60c44ee` |
| `contract/out/rings_stub_cc.parquet` | 36,343 | 35.49 KiB | `43aa4867061533ca66ca1fcdb8b3259a922d44c1f1a07a79b4d6f0a56a268a9e` |
| `contract/out/rings_stub_cc_step1_legacy.parquet` | 51,824 | 50.61 KiB | `070b14b4208470efd6c34aef7a4badac4185538fd1afe3e496669da79f2d65c9` |
| `contract/out/v1/rings_full_gine_causal_1.parquet` | 47,936 | 46.81 KiB | `9b8c1e65e4ae612cd96f2e101490c6fc69073bf9ebc9692ee5ace97e4625309d` |
| `contract/out/v1/rings_full_gine_causal_2.parquet` | 48,182 | 47.05 KiB | `09b281a8d5ea68515de779dcfe902c1767da10ba98278ae592b116b2a03bc169` |
| `contract/out/v1/rings_full_gine_causal_3.parquet` | 48,323 | 47.19 KiB | `7e2c3de40812d31297e47c09c5d4049cc9d24b28e645a534bcf761d9c76d0b93` |
| `contract/out/v1/rings_full_gine_causal_4.parquet` | 49,061 | 47.91 KiB | `e0db93dccd45383cde0c4f7d1df498d361c1d5c1e0dbad41a1c523c57d27888e` |
| `contract/out/v1/rings_full_gine_causal_5.parquet` | 44,955 | 43.90 KiB | `a41b087be3b766c5befec6d3a4858e8d6ac2dac85ea226406310b1c609c86df9` |
| `contract/out/v1/rings_stub_cc.parquet` | 27,886 | 27.23 KiB | `e427d59a4aad20bc45b86f4b619863b31fe2a02f85494ae8111d169c0c3866f2` |
| `contract/out/v1/rings_stub_cc_step1_legacy.parquet` | 40,770 | 39.81 KiB | `8ee0419458ba037274fa1517d31e4c3c68a447a32b64277306fc71a4ad1564b8` |
| `experiments_valrings/average/seed1/rings_val.parquet` | 49,302 | 48.15 KiB | `fa0b867059410a0db613398407d9111d6f56be7f86efb7da8e22ed01a592467f` |
| `experiments_valrings/average/seed2/rings_val.parquet` | 53,607 | 52.35 KiB | `37a00368f899fd15734e2a0daa8a033bb9144de0115df2fef7f1c20b725c75e6` |
| `experiments_valrings/average/seed3/rings_val.parquet` | 49,838 | 48.67 KiB | `895796d69e0533d9ca79bf3029db91195c7b88c2d23c8cff726ed344b4adfb47` |
| `experiments_valrings/average/seed4/rings_val.parquet` | 49,098 | 47.95 KiB | `db2da374b16900b154b9ba5c08b84d720a9e164e3b1b285025794291e7908567` |
| `experiments_valrings/average/seed5/rings_val.parquet` | 47,075 | 45.97 KiB | `ea8779bbfbe62d7b0df9cba2747a158659378da2b6cd75a377003193401dd7a2` |

Also in the zip, and not a data file:

| path | bytes | sha256 |
|---|---:|---|
| `docs/xai_fixtures.patch` | 2,097 | `92924554da79a618e60bbd72e98617b369561b70424e22cb81632627c39ba913` |
| `docs/HANDOFF_XAI.md` | this file | - |

### What each one is

* `contract/out/rings_full_gine_causal_{1..5}.parquet` - **CHANGED.** Regenerated at schema v2:
  30 columns, `rings_schema_version` 2 in the parquet key-value metadata. The build asserts the
  primary-window precision / recall / F1 / Jaccard / coverage are identical to the R4 `average` run
  **to 1e-9** on all five seeds, so membership did not move - eight columns were added. Primary
  ring-F1 0.5895 +/- 0.0371, unchanged. These replace the files of the same name in your copy.
* `contract/out/rings_stub_cc.parquet` - **CHANGED.** The file `test_stub_loads` reads, now at v2.
  98 rings as before; all 22 v1 columns are identical **row-for-row** against the v1 snapshot, and
  the 8 new columns are **computed**, not left at defaults: `n_currencies` up to 8, 76 of 98 rings
  span more than one currency, 96 accounts across 47 rings come back `undetermined`, and all 96 of
  its role changes are withholdings.
* `contract/out/rings_stub_cc_step1_legacy.parquet` - **CHANGED.** The other stub, regenerated on
  the same terms: 178 rings, 22/22 v1 columns identical, 93 of 178 rings multi-currency, 140
  `undetermined` accounts of 146 role changes (so 6 genuine reclassifications there).
* `contract/out/v1/*.parquet` - **NEW paths.** Byte-verbatim v1 snapshots (22 columns, stamped
  version 1) of the five `full` files and both stubs. Point here to re-derive anything from before
  the merge - including `fidelity_week1_stub_cc_seed1.json` and
  `explanations_week2_stub_cc_seed1.parquet`, which came from the v1 stub.
  `ringshield.rings.rings_schema_version(path)` lets you branch on the version instead of sniffing
  columns.
* `experiments_valrings/average/seed{1..5}/rings_val.parquet` - **NEW.** Validation rings for the
  val-chosen cell, every contract field filled at v2, written by `run_partition.py
  --save-val-rings`. Each run asserts the written member sets are identical to the rings the
  validation metrics came from, so this is the object the grid chose on, not a re-derivation. Val
  F1 0.6138 / 0.5770 / 0.6048 / 0.6048 / 0.5632, matching `configs/detector_choice.yaml`. This is
  what XR-05 needs to bootstrap an interval.

---

## Group B - unchanged. Verify your copies; nothing is being re-sent.

| path | bytes | size | sha256 |
|---|---:|---:|---|
| `contract/out/labels_test.parquet` | 3,741,258 | 3.57 MiB | `49a38d2a3f3b903d4fbc2ac46ca1b5e6148c6c6cc2801aae76414ad4c9df2b36` |
| `contract/out/labels_val.parquet` | 4,149,057 | 3.96 MiB | `117e363d4e0991a8c494f0f86c44502a92ba1c3baccb759e0048e3ad0eee11b1` |
| `contract/out/scored_edges_gine_1.parquet` | 40,386,686 | 38.52 MiB | `1095138a98d2c5ce2031d8f246c73075d028956a8eefbf50c89ac529bcb50485` |
| `contract/out/scored_edges_gine_causal_1.parquet` | 31,804,135 | 30.33 MiB | `19dac050b750e4af39ea104399de3916f9d5254e30f5e44d456352ca69087c68` |
| `contract/out/scored_edges_gine_causal_1_val.parquet` | 33,417,116 | 31.87 MiB | `7a933a180407439bf7a1f0032a261d7a2cae04c0b3a98a4e0c1054baf6e28ffe` |
| `contract/out/scored_edges_gine_causal_2.parquet` | 32,650,860 | 31.14 MiB | `da4ae47ae2cbfb7aed2afca9c24a54d29db72832c144abc94685f04fe2f93431` |
| `contract/out/scored_edges_gine_causal_2_val.parquet` | 34,201,990 | 32.62 MiB | `4ac68cbf726ae7297cd7273dfc5deea03cd23ae38df476ffdf9701687e76c8eb` |
| `contract/out/scored_edges_gine_causal_3.parquet` | 31,267,135 | 29.82 MiB | `c5ab302efd222dd8642dc7f66ac0861216ab3d0ff54da75e365c34ca7a7e8da2` |
| `contract/out/scored_edges_gine_causal_3_val.parquet` | 32,782,884 | 31.26 MiB | `b9d322e4ed8c18d6ec6a6ef0fefe7c4598270a3a01cca8f5b118c7ed708e5511` |
| `contract/out/scored_edges_gine_causal_4.parquet` | 32,373,666 | 30.87 MiB | `d5fd36ed983536740e9bd1399efb1f1e51ca6c3329364a22b1920a0898b31b42` |
| `contract/out/scored_edges_gine_causal_4_val.parquet` | 33,564,905 | 32.01 MiB | `8c9f37293b6c1afe0971f3a765050833bb13f745ac3f07a98d343fb1cb795713` |
| `contract/out/scored_edges_gine_causal_5.parquet` | 32,061,065 | 30.58 MiB | `51562fbb7d28ed508478bd22731499cb8a749972a31f790dbbf6caa97b66e3e8` |
| `contract/out/scored_edges_gine_causal_5_val.parquet` | 33,518,865 | 31.97 MiB | `cc1b95011cedd975cd9160ce0f95756112fd0570168fec6fcdffe3f19b0a1198` |
| `data/processed/amlworld_gfp_features_test.parquet` | 10,713,596 | 10.22 MiB | `1bbd30f72d3419d40fa83fe8afa6931c54c704ed4e82997f033486e7a9f1e2e1` |
| `data/processed/amlworld_ring_ground_truth.parquet` | 94,882 | 92.66 KiB | `cd6d207b1ce464a1e014e7c19cd8ec6658e0401e1b7da1f2b2c07bd9891adf70` |
| `data/processed/amlworld_test.parquet` | 64,193,437 | 61.22 MiB | `771b7c6ea2b49ac6f7ff8b2edd021bcc9fc9c1f6247a214b87dd563067d3d5d4` |
| `data/processed/amlworld_val.parquet` | 62,940,979 | 60.03 MiB | `687f1e922031405c330372506d6c55fe659107ccdbaae15d075e379c7df24d15` |
| `experiments/R1_gine_causal/embeddings_test_seed1.parquet` | 603,130,860 | 575.19 MiB | `f32be717c132b7b320486b7131b45eb70a10bdeb112a65a7f24449460ab19dce` |
| `experiments/R1_gine_causal/embeddings_test_seed2.parquet` | 630,156,975 | 600.96 MiB | `fc539004593cccaf31f9b6c1d76d7940f5f4fe6ddef8c0e67c15d6fb9e0ff294` |
| `experiments/R1_gine_causal/embeddings_test_seed3.parquet` | 577,154,758 | 550.42 MiB | `1ae25a5eb04b28b875f93d2fee9b957b012f64a3aaa012ad6feb8a6b206e92e3` |
| `experiments/R1_gine_causal/embeddings_test_seed4.parquet` | 607,852,499 | 579.69 MiB | `68bc57e55af6060e858cc2080db5361e060179d55a9e22890607eb5788cddf1a` |
| `experiments/R1_gine_causal/embeddings_test_seed5.parquet` | 580,666,035 | 553.77 MiB | `7a8a227b34cc40f8d4798850c2dad2c1bbba91909afa8027e1760002e107acff` |

### What each one is

* `contract/out/scored_edges_gine_causal_{1..5}.parquet` - test scored edges, the
  `inputs.scored_edges` of your config.
* `contract/out/scored_edges_gine_causal_{1..5}_val.parquet` - val scored edges. You did not need
  these before; they are what makes the new val rings usable.
* `contract/out/scored_edges_gine_1.parquet` - the legacy stub's own scored edges. Only needed if
  you rebuild that stub yourself; the rebuilt file is in Group A.
* `contract/out/labels_{test,val}.parquet` - edge labels.
* `data/processed/amlworld_ring_ground_truth.parquet` - truth rings, `inputs.truth`.
* `data/processed/amlworld_{test,val}.parquet` - split parquets. `amlworld_val.parquet` is the val
  counterpart of `inputs.split_parquet`, needed with the val rings.
* `data/processed/amlworld_gfp_features_test.parquet` - GFP features, `research_inputs.gfp`, read by
  `RingRerunner` for non-degraded leave-one-out.
* `experiments/R1_gine_causal/embeddings_test_seed{1..5}.parquet` - `research_inputs.embeddings`,
  also read by `RingRerunner`. 575-601 MiB each, 2.79 GiB for the five: the bulk of Group B and the
  reason it is not in the zip.

**Not listed, deliberately:** `experiments/R4_partition/affinity/` and
`experiments/R4_partition/runs/average/seed{1..5}/config.yaml` are the other two
`research_inputs`, and both are **tracked in git** - you get them from the merge, not from a zip.
`embeddings_val_seed{1..5}.parquet` (595-639 MiB each) are **not** listed either: they are only
needed if you run leave-one-out on the new val rings, which XR-05's bootstrap does not require. Ask
if you want them hashed.

---

## Your suite on the merge: 116 passed, 0 failed

A throwaway merge of `contract-ccy-valrings` into `explainability-l4`, pointed at the Group A files
above, first gave **111 passed, 5 failed**. Both causes were fixed; here is the whole record, because
one of the five is worth knowing about even now that it is green.

**The stub (1 failure) - fixed on our side.** `test_stub_loads` read a v1 file, so the v2 column set
rejected it. Both stubs are now regenerated at v2 (Group A), with the v1 originals snapshotted.

**The fixtures (4 failures) - fixed by `docs/xai_fixtures.patch`, which you apply.**
`explainability/tests/fixtures.py` ends with `pd.DataFrame(self.rings, columns=RINGS_ORDER)`, and
`RINGS_ORDER` grew to 30 entries while the row dicts set 22, so pandas materialised the eight new
columns as all-NaN `float64`. The patch routes the rows through
`contract.schema.ring_record(**overrides)`, which returns a row with every contract column at a
correctly-typed default. One file, two hunks:

```bash
git apply docs/xai_fixtures.patch
```

**The one worth a second look.** `test_broken_fixture_seed_not_in_members_is_rejected` expects
`ContractError: seed_edges not a subset of member_edges`. Before the patch it received the dtype
error instead - so it failed, but the subset check it exists to guard was **not being exercised**.
After the patch it raises for its original reason:

```
rings: 2 violation(s):
  full-fixture-0-fan_out: seed_edges not a subset of member_edges ([1053])
  full-fixture-0-fan_out: a seed_edge is not is_seed in scored_edges
```

Any repair that merely silenced the dtype errors would have turned that test green without the
subset check ever running. If you decide to fix the fixtures differently, check this one explicitly.

**Nothing was committed on `explainability-l4`.** The merge was made in a throwaway worktree and
discarded; the patch is the only thing that touches your files, and it is yours to apply or reject.

### What passed, and why it is the part that matters

* `test_real_files_load[1..5]` and `test_stub_loads` - every rings file on disk loads and validates.
* `test_missing_rings_field_is_named[...]` - parametrised over `RINGS_COLUMNS`, so it grew to cover
  all eight new fields automatically, and all eight pass.
* `test_research_roles_reproduce_the_contract_role_arrays[1..5]` - your raw roles still reproduce
  the contract's role arrays on every seed. This is the end-to-end confirmation that
  `currency="raw"` is byte-identical, so `research_roles`, your `roles_disagreement_*.csv` and
  `currency_policy: raw` all stand.
* `test_rerun_is_not_degraded_and_reproduces_the_shipped_rings[1..5]` - `RingRerunner` still
  reproduces the shipped rings against the v2 files.
* `test_counts_reproduce_the_research_log[1..5]` - matching counts unchanged.

See `docs/MIGRATION.md` for the four action-required boxes: the column set, the `_ccy` roles and
`undetermined`, the `w_flow` within-currency rule, and this patch.
