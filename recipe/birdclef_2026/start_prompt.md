# BirdCLEF 2026 Start Prompt

You are working on BirdCLEF 2026. The goal is not to chase a fancy solution at the start, but to build a strong baseline that is genuinely sensitive to the 2026 data distribution and can be iterated on cleanly. Use 2025 top solutions as the main prior, especially the ones with code or explicit training details, but do not copy them mechanically. Re-evaluate them under the constraints of the 2026 competition.

local data root dir:  ./data/birdclef-2026/
!!note: ./data/birdclef-2026/train_soundscapes_labels.csv has duplicates, deduplication is needed before split generation and training.

## General Working Style

- Analyze first, then change code. Confirm data boundaries, leakage risks in the split, and alignment between training targets and the evaluation metric before deciding on models or augmentations.
- Treat the task as cross-domain multi-label recognition from `train_audio -> soundscape`, not as ordinary classification.
- Start from a stable single-model baseline, then add pseudo labels, distillation, specialist branches, and ensembles step by step.
- For every experiment, explicitly answer 3 questions: does it better match the soundscape distribution, does it reduce label noise, and does it improve rare or missing classes?

## Strong Priors From 2025

- Prefer SED-style models as the main line. Do not branch out too early into pure clip-level classification heads.
- Start with backbones that were repeatedly validated in 2025, especially `tf_efficientnetv2_s`, `tf_efficientnetv2_b3`, and `eca_nfnet_l0`.
- Use `32k` sample rate by default. A good starting range for mel settings is `128~224 mels`, `n_fft=2048/4096`, with chunk designs centered around `5s` or `10s/20s`.
- The main lesson from 2025 is not that more complex models always win. Pseudo labels, self-distillation, sampling strategy, and inference postprocessing mattered more.
- A strong heuristic is that short windows like `5s` are better for precise pseudo labeling and submission-style inference, while longer windows like `10s/20s` often help sustained calls, especially for Amphibia and Insecta.
- Many top 2025 solutions reported weak validation-to-LB correlation, so local validation should be used more for direction and robustness than for overfitting a single fold score.

## Analysis Strategy For 2026

- First separate `seen classes` from `missing classes`. In 2026, some target classes do not exist in `train_audio` and can only be learned from labeled `train_soundscapes`.
- In the baseline stage, let `seen classes` be learned mainly from `train_audio`, and let `missing classes` be covered mainly by labeled soundscape data.
- Be very strict about leakage in soundscape data. Splits must be grouped by full soundscape file, never by random 5-second windows.
- For `train_audio`, at minimum consider grouping by `author` or similar source identity to reduce same-source leakage.
- Build a reliable cross-domain validation setup before upgrading the model. Without a trustworthy split, later scores are mostly noise.

## Coding And Implementation Preferences

- Prefer waveform output from the dataset and compute mel spectrograms dynamically on GPU. This matches several strong 2025 solutions and keeps duration, hop, and mel settings flexible.
- Organize training around `5s` as the base inference unit. Even if training chunks are `10s/15s/20s`, the implementation should degrade cleanly to 5-second slice inference.
- Label handling should support multi-label targets, secondary labels, soft targets, and partial-label masks from the start, because those interfaces will be reused for pseudo labeling and distillation.
- Leave extension points for sampler logic, loss masks, postprocessing, and OOF pseudo labels in the first version. Do not write the baseline as a one-off script.

## Early Priorities

1. Confirm that cleaning, deduplication, split generation, and evaluation scripts are reliable.
2. Build a strong `SED + EfficientNetV2` baseline first, then inspect the gap between `train_audio val` and `soundscape val`.
3. Prioritize class statistics, missing-class coverage, and rare-class sampling before fancy augmentations.
4. Only move to pseudo labels or self-distillation after single-model training is stable.
5. Leave specialist branches, external data, ensembles, and heavier inference tricks for later.

## Recommended First Directions

- Baseline main line:
  `SED + tf_efficientnetv2_s/b3 + 32k + dynamic mel + mixup/specaug + class-balanced sampler`
- Duration strategy:
  compare `5s` and `10s` first, then extend to `15s/20s` if Amphibia or Insecta clearly benefit
- Label strategy:
  supervise both primary and secondary labels; consider partial-label masks for soundscape-derived missing-class samples
- Training strategy:
  start supervised, then self-distill on `train_audio`, then bring in pseudo labels from `train_soundscapes`
- Inference strategy:
  keep a clean 5-second output interface first, then add overlap, smoothing, and file-level rescaling later

## Things To Avoid Early

- Do not rely on external data at the beginning. First understand the cross-domain structure of the official data.
- Do not trust a public LB gain immediately. Check whether it comes from split artifacts, postprocessing luck, or accidental hits on rare classes.
- Do not skip manual data inspection. The 2025 experience repeatedly showed that human speech, dirty labels, silent spans, and bad long-tail trimming can hurt badly.
- Do not write code that only supports a single training round. BirdCLEF usually separates later through multi-round pseudo labeling and distillation.

## Output Style

- Prioritize actionable conclusions, minimal experiment designs, and the code changes that are actually needed.
- For every suggestion, explain why it helps, ideally stating whether it mainly targets cross-domain shift, noisy labels, class imbalance, missing classes, or inference-distribution matching.
- Stay concise. Avoid generic surveys and prefer experience-based judgments with implementation-aware guidance.
