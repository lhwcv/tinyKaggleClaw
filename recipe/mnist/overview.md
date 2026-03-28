# MNIST Overview

Status: proposed by `researcher` on 2026-03-28 under `task-1a2b3c4d5e`

This file is an assumption-based overview because the original `recipe/mnist/overview.md` was missing.

## Confirmed From Existing Recipe Files

- data root is intended to be `data/mnist`
- the modeling goal is to optimize a CNN for MNIST
- target metric is `test_acc`
- target score is `99.8%`
- model-size constraint is fewer than `1M` parameters

## Working Assumptions

Unless later repo evidence contradicts this, treat the task as standard MNIST classification:

- 10 digit classes: `0-9`
- standard train/test split
- grayscale `28x28` images
- no mandatory Kaggle submission file

## Evaluation Contract

Confirmed:

- report `test_acc`
- report parameter count

Recommended local protocol:

1. use the standard MNIST training set for fitting
2. carve a validation split only from training data for model selection
3. keep the official MNIST test split frozen for final evaluation
4. reject models above `1M` parameters even if accuracy is strong

## Submission Contract

Current assumption:

- this task is a local benchmark task, not a Kaggle CSV submission task

If later evidence introduces a submission file requirement, update this document before baseline iteration starts.

## Main Risks

- leaking the official test set into architecture search
- overfitting to a single validation split on a small benchmark
- using augmentations that distort digit identity
- optimizing only for accuracy without tracking parameter budget

## Immediate EDA Scope

- verify actual dataset intake layout under `data/mnist`
- measure train/test counts and label balance
- inspect sample quality and obvious corruption risk
- check for exact duplicate overlap across train and test

## Next Stage Gate

Do not begin formal baseline training until the empirical EDA artifacts under `eda/` are reviewed and the evaluation contract above is accepted or corrected.
