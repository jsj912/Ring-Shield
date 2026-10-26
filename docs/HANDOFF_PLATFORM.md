# Platform hand-off: research artefacts

Every research file the platform reads, as configured in `platform/config.yaml`. The files are
gitignored; this table pins them. Regenerate with `python scripts/platform_handoff_manifest.py`,
verify a machine with `--check`.

Generated 2026-10-24 08:57 UTC.

## Decisions behind the config

- **R10 score source: `tenant_visible`** (option b, fixed pooled cutoff), as registered in
  `docs/TENANT_SIZES.md`. Pooled scores are the secondary row: `--tenant-score-source pooled`.
  Primary tenants 1, 20, 11, 118, 12; robustness set 70, 12, 11, 1, 10 (reported as degenerate:
  bank 70 has no visible ring laundering edge). Files from `scripts/tenant_visible_scores.py`.
- **R12 held-out pattern: CYCLE**, model `models/artifacts/l3only_cycle_full_seed1` =
  `experiments/R7_l3only_cycle/runs/full/seed1` through `python -m ringshield export-model`.
  BIPARTITE was the v1.0 default; holding it out removes no training rows.
- **Retraining inputs:** validation GFP, seed-1 validation embeddings and the ring ground truth.
  The frozen holdout is `platform/holdout/production/holdout_manifest.json` (chosen 2026-10-17).


## active pair

| path | bytes | sha256 |
|---|---:|---|
| `contract/out/scored_edges_gine_causal_1.parquet` | 31,804,135 | `19dac050b750e4af39ea104399de3916f9d5254e30f5e44d456352ca69087c68` |
| `contract/out/scored_edges_gine_causal_1.parquet.log.json` | 1,178 | `5aae4d1d611f2a0c9e1a787b8dff7a3b881b3bc52e64131a3228acc712bdfd08` |
| `contract/out/scored_edges_gine_causal_1_val.parquet` | 33,417,116 | `7a933a180407439bf7a1f0032a261d7a2cae04c0b3a98a4e0c1054baf6e28ffe` |

## features

| path | bytes | sha256 |
|---|---:|---|
| `data/processed/amlworld_gfp_features_test.parquet` | 10,713,596 | `1bbd30f72d3419d40fa83fe8afa6931c54c704ed4e82997f033486e7a9f1e2e1` |
| `data/processed/amlworld_gfp_features_val.parquet` | 11,055,335 | `926e392771b3b2ef3099c5527722cab57a51b24ef7a4655b6aef8beaf3c54d10` |
| `experiments/R1_gine_causal/embeddings_test_seed1.parquet` | 603,130,860 | `f32be717c132b7b320486b7131b45eb70a10bdeb112a65a7f24449460ab19dce` |
| `experiments/R1_gine_causal/embeddings_val_seed1.parquet` | 654,713,691 | `03a149c824813fd802beac6f35d669b55f477708981804160cf3a43c812008da` |

## ground truth

| path | bytes | sha256 |
|---|---:|---|
| `data/processed/amlworld_ring_ground_truth.parquet` | 94,882 | `cd6d207b1ce464a1e014e7c19cd8ec6658e0401e1b7da1f2b2c07bd9891adf70` |
| `data/processed/account_bank.parquet` | 6,890,803 | `dd0dfa6049e97a1337442f03836493d44b66b30f928cb7ab2fb7b973393c286a` |

## active model

| path | bytes | sha256 |
|---|---:|---|
| `models/artifacts/full_gine_causal_seed1/affinity/affinity.json` | 6,767 | `86a3a4aeb478bf79fabcabc98a22d27f55edfcc864b6459deb9c9c1130072e33` |
| `models/artifacts/full_gine_causal_seed1/affinity/affinity.txt` | 333,312 | `61b53eddcb0b94da528d4003675acb959ae81730027b5e0221edc8e78090562b` |
| `models/artifacts/full_gine_causal_seed1/model.json` | 1,163 | `234deb94498cb4a2c960640198fc3f80c0a0fcf80dbab97fd16db8e0bf7d8220` |
| `models/artifacts/full_gine_causal_seed1/policy/policy.json` | 15,730 | `104ebeb19e69b647fa5562a41f56362a25b02729c8af85cc32d01118afd9874e` |
| `models/artifacts/full_gine_causal_seed1/policy/policy.txt` | 1,038,697 | `a1768ee8ea11a147536c7d1972eea98d5f821a5b4cd3694e5ac1ebebe57128d7` |
| `models/artifacts/full_gine_causal_seed1/typing/head.json` | 9,911 | `58055aa04f830d7dafd810c7f1f2111ecabf7c712226a3c8551e51e2dcf3e5f1` |
| `models/artifacts/full_gine_causal_seed1/typing/head.txt` | 581,446 | `ac1470376331376dec3a4756109a58cbc538fa1b9687c7033f6be285cd1d7a5f` |
| `models/artifacts/full_gine_causal_seed1/version.json` | 1,107 | `d73145252fb5b568fee7ba34691ca9a4147e971da65c559a0bce3a5816828fab` |

## R12 held-out model

| path | bytes | sha256 |
|---|---:|---|
| `models/artifacts/l3only_cycle_full_seed1/affinity/affinity.json` | 6,775 | `d7b84c3e561b00a75686618c29ff8a35f921e7032d20fd7341d112afb944a0c5` |
| `models/artifacts/l3only_cycle_full_seed1/affinity/affinity.txt` | 476,808 | `fca23f2bc4c0c8ccbf0786c1386e9ff0e703535260c2e8670e2c18e7b649773b` |
| `models/artifacts/l3only_cycle_full_seed1/model.json` | 1,207 | `563c38253f09de24045e814617f965077c28cd356eaf329cb3a7428b1aba77af` |
| `models/artifacts/l3only_cycle_full_seed1/policy/policy.json` | 15,644 | `4ff57fa1223d48f4df8fead3a903f110a9467390b3ccc687b8c456afed379c67` |
| `models/artifacts/l3only_cycle_full_seed1/policy/policy.txt` | 1,303,106 | `896636cd88fe8fd5407c4ec454f5ac187844facbbf3fbe85cb096f6531e7c14a` |

## R10 pooled scores

| path | bytes | sha256 |
|---|---:|---|
| `contract/out/scored_edges_gine_causal_1.parquet` | 31,804,135 | `19dac050b750e4af39ea104399de3916f9d5254e30f5e44d456352ca69087c68` |
| `contract/out/scored_edges_gine_causal_1.parquet.log.json` | 1,178 | `5aae4d1d611f2a0c9e1a787b8dff7a3b881b3bc52e64131a3228acc712bdfd08` |
| `contract/out/scored_edges_gine_causal_2.parquet` | 32,650,860 | `da4ae47ae2cbfb7aed2afca9c24a54d29db72832c144abc94685f04fe2f93431` |
| `contract/out/scored_edges_gine_causal_2.parquet.log.json` | 1,155 | `5b26a8d6a41d1a1de51997681c78de360661f64056f793f70fad7e98364c1ba1` |
| `contract/out/scored_edges_gine_causal_3.parquet` | 31,267,135 | `c5ab302efd222dd8642dc7f66ac0861216ab3d0ff54da75e365c34ca7a7e8da2` |
| `contract/out/scored_edges_gine_causal_3.parquet.log.json` | 1,156 | `9d4dfa6a2b84074c56ae66dbd39458f0c1d712f971daa5fcfcedde407a7936d5` |
| `contract/out/scored_edges_gine_causal_4.parquet` | 32,373,666 | `d5fd36ed983536740e9bd1399efb1f1e51ca6c3329364a22b1920a0898b31b42` |
| `contract/out/scored_edges_gine_causal_4.parquet.log.json` | 1,156 | `e68994a9b5a47577f5479b66b33a5650b7dcf0cc441c7630041b54c8cbff66fe` |
| `contract/out/scored_edges_gine_causal_5.parquet` | 32,061,065 | `51562fbb7d28ed508478bd22731499cb8a749972a31f790dbbf6caa97b66e3e8` |
| `contract/out/scored_edges_gine_causal_5.parquet.log.json` | 1,154 | `9e6b78842150a555f4ecbdad434607b188f950ebd14cb9cf124723f8451aaac9` |

## R10 tenant-visible scores

| path | bytes | sha256 |
|---|---:|---|
| `data/tenant_visible/scored_edges_visible_1_gine_causal_1.parquet` | 568,094 | `b63142e24439430352e773fc100e103356188dd833687e663e531ee81fb62b0f` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_1.parquet.log.json` | 2,639 | `97fb3d62db35b2bbde8969e140135d323a5cdf9311594359baa9ad43db007703` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_2.parquet` | 578,295 | `c911b5fb0301c3846aaacce48c73d2e8bb70d0156268b434348ae14fdcbefe6a` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_2.parquet.log.json` | 2,639 | `1cc29bd7c69331e8eb9d1bef4beb30aff5481f9d0db7cc8626130d40480cd3f5` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_3.parquet` | 554,562 | `9c6f8225cf8479fb16637dc498b5d6365f9d8d0f7fb639f072f6b6dca26381f8` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_3.parquet.log.json` | 2,638 | `36238d89ff2a2ca3b868b65d0a1f4234532636e38f5194a0cfe3c9f1fa113d3a` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_4.parquet` | 563,930 | `f0d1b0201b69cdb7219065de07ab6fb8c8c9fb4bb3a8bbf59423e7177719f614` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_4.parquet.log.json` | 2,624 | `ab0c4c523b12a76bbd0925db8d8cff54be17b53360664dcae3d12bc516c56454` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_5.parquet` | 577,091 | `83cbe19a9f30c83033984c0d228fdbfda6fb00ceb6d0cfd67d9ba11ccfd1cf66` |
| `data/tenant_visible/scored_edges_visible_1_gine_causal_5.parquet.log.json` | 2,637 | `96fcb788176803ae8e75636befe185e2959e9b7e051daa6fb34ed24258f30ddd` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_1.parquet` | 766,441 | `fa498c8e94428fd95517f4cd777331d96052561a6308b439bf3c354d7d734120` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_1.parquet.log.json` | 2,644 | `123902f90db76a97826be44a0ff697b1b898e2d327ddbffc80f26fd25dd951fe` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_2.parquet` | 782,306 | `f1853049d2b3ef32a50dcfd819c841b72c26599317607c7d94c61a301eab4522` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_2.parquet.log.json` | 2,643 | `30f712d7d9f7e7956799635d4a3fba5930b45ff09515e9db9aa96f7382e78767` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_3.parquet` | 749,030 | `ec33ecf6d6544e10383d2f31c70202b031e636d4c721825f0ad352536c78a383` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_3.parquet.log.json` | 2,629 | `feea814cb02cfbac42c2f11b34f0acee7e8dc5a66983083d5d3e75159af7a7d8` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_4.parquet` | 764,286 | `40992b0c327b4616679d65f70ec7c703d236845afc8ef97b13ffa2bb61499fa0` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_4.parquet.log.json` | 2,644 | `407a485a874484807cf3d03bcaa80ce0f37212a8b8e8d35fadd1f787613025f7` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_5.parquet` | 778,555 | `126e0cb2f6a83a1892c60e7e6ad67f3157babec807885cb104642090dc76a718` |
| `data/tenant_visible/scored_edges_visible_10_gine_causal_5.parquet.log.json` | 2,625 | `c27842724d66886b99f356547205cd782e10fbbb21be4852fc94bce7f7f6f7ce` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_1.parquet` | 275,571 | `330e9eaa41770adaeb45364709f1c2a96005acef41b91e6875ba06599e0bef08` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_1.parquet.log.json` | 2,640 | `70a724600cec4d2e5e0a7f0f1b139f8b640de14b59391dc0de5f4759ce006d6a` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_2.parquet` | 282,370 | `a04b8dd2a6075773ce0438687cebdc0d8488901f0da983856b2f220c9dd5da0a` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_2.parquet.log.json` | 2,638 | `234500923395eca381bb8484e16fb5e8dad70d36d791342a6cda267f590f6a12` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_3.parquet` | 270,715 | `f296ea81701f59ba713dd2d5372d96c0a7c2537774ccae0fb279bb3cbd344a06` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_3.parquet.log.json` | 2,638 | `65929e39f51c92fec1428b2e52e73b81aab8efc4d062503fd0adee74945a56ff` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_4.parquet` | 275,959 | `f40b695d9fa3e0bf987bed74eda9ccb2028b54560d8bb6b759e5f1025dd1769c` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_4.parquet.log.json` | 2,639 | `06f06b3f3d7176e08d0a4d37e0f725ac67d8a3be698a863e0a0a04d7ea06e244` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_5.parquet` | 281,240 | `3e80f8ce853eb45eeacf4fd48cd9046777689d1fc335e8bc922dd468d3fdc8db` |
| `data/tenant_visible/scored_edges_visible_11_gine_causal_5.parquet.log.json` | 2,636 | `714e0e3ae914ae719ddfb50369a84693a8df3d3305b544afdf0120f2f6ee5341` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_1.parquet` | 769,708 | `7083e56da765746e04d51aab2fca6e2019e3972f3ac2ccfedd8504adfb7534b8` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_1.parquet.log.json` | 2,644 | `3d23841b24e0025b83ece2ab3e6fe442898867943f7a786b0afe62c3e48544a7` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_2.parquet` | 790,637 | `577c40dee4d816d28c45603e1f6d4b4ae266a2fc461ebfe256b9a7c6fdc1ff06` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_2.parquet.log.json` | 2,641 | `56855f7abadaf302fcaf8ce94ea449ec1c870dd7bb89cc183f965ac6c0a3ac04` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_3.parquet` | 754,241 | `4513c6007f68edafd0a05b18c1dde539ff9ba63793bd9a7e0169c7c323f79119` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_3.parquet.log.json` | 2,643 | `71a4022401d67fce17608e8b1d13c51435ede603c0424542085422d4c17b56d2` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_4.parquet` | 774,404 | `bd22d0d0468bc2ed17b04057419a4c093e0815d8229ae9d93140d14d68839f12` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_4.parquet.log.json` | 2,643 | `c90faed3f670ed1709dacd2f2a3c0245e9ed24bef0cd64178f58d4ba5c4b3f04` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_5.parquet` | 784,692 | `09e52ab8ecb00dee34a3639a77c449fca8b315bea0d8cdc0d6358209514223a8` |
| `data/tenant_visible/scored_edges_visible_12_gine_causal_5.parquet.log.json` | 2,641 | `ab62d024209822edab9a9ba4e9fea1807a7e610b170f41f3d5dbd9f152191d1a` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_1.parquet` | 394,578 | `cebf7ffb3ab40ff48525a90590591e40c7a7a58974eadbe252a126b4784fdc70` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_1.parquet.log.json` | 2,642 | `33e81f7af850ccc162b2983412f84b5c1ba38e2a54c77bd9382dfc086cd932d3` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_2.parquet` | 406,130 | `beb1a695bf224f2115a338eb2a7d8cd92698e8d5b64893633ac25b8ccf39ae42` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_2.parquet.log.json` | 2,640 | `f2ea065a501baf45b596baf5aa856cff05481546476ae494bed2e8b1f92392b6` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_3.parquet` | 387,717 | `c361f1d612d75b9741e7501ab2ad80818e132a2351eac26f8750786768eb5482` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_3.parquet.log.json` | 2,641 | `5644a4f1852baf66cc23d32e48e4131d3dbbe1895bd128e6e925b6c27d76a081` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_4.parquet` | 397,379 | `a15d7614f8d0d1e4fd66b892df11bdf72e1c4527124f19a1ba584961cb7dcb8c` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_4.parquet.log.json` | 2,643 | `f76422f60d05b82dcede75af55608bc1c8f3fba224fc968b74bc795a0ab37187` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_5.parquet` | 404,296 | `2bea6d4401cc0b46b9ed12989ffce0fbcc2cd121658a5a5d8fef8da84f74e226` |
| `data/tenant_visible/scored_edges_visible_20_gine_causal_5.parquet.log.json` | 2,640 | `8c719d20a006f329de9406c3c5eb9a79320cb180b9b6c0397dd5c1f0dd7cafac` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_1.parquet` | 2,298,582 | `9583638ae83e5b85c8141a3f867a22af55b1746a20fce42c403180d09c54a339` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_1.parquet.log.json` | 2,636 | `8d14fee74b054ab924890ed5e303296a1bef946773e9a622c21f3f41a92628ad` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_2.parquet` | 2,146,487 | `35a40c5ebbb2febb47b08a8f5d7e3369137d17263c6e55a4abf9047c0babd16d` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_2.parquet.log.json` | 2,635 | `99fb0e1dc29f812a216b15c3f0a078dd89c9ab59063b589c0419828f1afe90a8` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_3.parquet` | 2,110,848 | `59e8fd71dbea5754316a2cafc8cc0f1424b87bbcdcdf99d1898198cc92bb5852` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_3.parquet.log.json` | 2,635 | `a83bfdfef2460eb67ba8f8befb3821bf2accb7b966ab300876997c8eb280dd6d` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_4.parquet` | 2,107,310 | `60a0078c7a3b07aedc0448caac03832c3c9d252bcbcd8898a67b423f6e5fef8a` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_4.parquet.log.json` | 2,635 | `b95e0888d32df36f5713da836ee7259f6c2420c6790ed3074783a47a6acb6649` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_5.parquet` | 2,094,964 | `66c174a05965b16fe961ad3caad51f72dd6f663913d7f4fbbcc2944d1957e197` |
| `data/tenant_visible/scored_edges_visible_70_gine_causal_5.parquet.log.json` | 2,633 | `d4aa68ba14942fda0467298dce5e3dfc2904a8e4185d7f24829f0f7dc42633ec` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_1.parquet` | 262,228 | `594672a8dae024f59d800adf57742bf3cf35bd0367333fca8cb8fd76c19d9b38` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_1.parquet.log.json` | 2,642 | `fbf23f878e9a49276750c9773d1d857f072af6803c3f12e697ac4126c7a68e20` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_2.parquet` | 270,445 | `fc2a77f8f05a263322bc2d4b9434eb73b83705c50db13218c695d774ecaf17af` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_2.parquet.log.json` | 2,625 | `6a3c297be7ee88503fd6997b34ae47149d65048c3a93fe69211ad8442221975f` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_3.parquet` | 259,816 | `717abff15476d72ccea6423d9c480425116aeedaf4f54dfb0548646319182495` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_3.parquet.log.json` | 2,639 | `a836acb7198e3dbc6b5d104b19bda444f85aeac93a9fb28bfcb5ba966dd9afce` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_4.parquet` | 264,796 | `524f13bb543855b926bda92cf6a0a305c5b3e901fa8a5b6babeed3c2edbc04aa` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_4.parquet.log.json` | 2,639 | `43d1adac82225e0a8c265bedda1816562c8acc902727515eb0a1beab636d7d16` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_5.parquet` | 268,868 | `da48cdf22ae84fe27e268bb83ed256446e0025ac614355a306baca376280d0e5` |
| `data/tenant_visible/scored_edges_visible_118_gine_causal_5.parquet.log.json` | 2,640 | `2039330ce69bf270b119ea717405809a9bb517fa5a396e9e8db51f8936ddea6b` |
