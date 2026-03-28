We would like to thank Kaggle, the organizers, our teammates, and all participants. It was a great experience to take part in this competition. Below is a brief overview of our solution.

Data

We used only the 2025 dataset.
First, we used Silero VAD to detect audio files that contain human voices from the train_audio set. Next, using a Streamlit tool developed by @zuoliao11 , we manually listened to those files and removed the segments with human voices.

For underrepresented classes (n < ~30), we manually selected segments that contained bird calls.
For cleaned files, we used the first 60 seconds; for the others, we used the first 30 seconds. To balance the dataset, we duplicated files in classes with fewer than 20 samples.

Model

We used a Sound Event Detection (SED) model.
Backbones:
• 4x tf_efficientnetv2_s
• 3x tf_efficientnetv2_b3
• 4x tf_efficient_b3_ns
• 2x tf_efficient_b0_ns

Training

We trained our models in three stages.


Input features:
• Random 10-second segments
• Mel spectrogram:

  sample_rate: 32000 
  mel_bins: 192 
  fmin: 20 
  fmax: 15000 
  window_size: 2048 
  hop_size: 768
We convert the mel-spectrogram to a logarithmic scale by computing log(melspec+1e-6).
• Augmentations:
　　• Resampling
　　• Gain
　　• FilterAugment
　　• FrequencyMasking, TimeMasking
　　• Sumix on mel domain

• Optimizer: Adam + Cosine Annealing with warmup
• Loss: FocalLoss (gamma=2)
• Epochs: 10
• Target labels: Both primary and secondary labels

1st Stage:
We trained 5-fold models using only train_audio.

2nd Stage - Self-distillation with train_audio only:
While listening to the audio as described in the Data section, we found that many bird calls were present in the training data even though they were not labeled. This was expected, as the recorders were mainly focused on their target species, so other bird calls were often left unlabeled.
From this observation, we believed that the core challenge of the competition was accurately assigning secondary labels. To address this, we used self-distillation to enrich train_audio with more secondary labels. We used predictions from a model trained in the 1st stage as teacher labels and mixed them with the original labels. The teacher model’s predictions may have included true secondary labels that were missing from the original annotations.
We repeated self-distillation 4–5 times. From the 2nd round onward, we used the previously distilled model as the new teacher in an iterative manner. The model’s weights are re-initialized each time. This approach closely resembles the method proposed in this paper.

3rd Stage - Self-distillation with train_audio + train_soundscapes:
We added data from train_soundscapes to the training set and continued self-distillation two more times. We mixed train_audio and train_soundscapes at a 1:1 ratio in each batch (no folds). We further trained several models using different random seeds.

LB Score (Public) 1st ~3rd stage（Ensemble of 5 models）
Model	Stage 1	Stage 2 (Distill x2)	Distill x4	Distill x5	Stage 3 (Distill x1)	Distill x2
tf_efficientnetv2_s	0.839	0.863	0.880	0.884	0.915	0.921
tf_efficientnetv2_b3	0.842	N/A	0.872	-	N/A	0.918
tf_efficient_b3_ns	N/A	N/A	N/A	-	N/A	0.921
tf_efficient_b0_ns	0.836	0.871	0.879	0.883	0.905	0.912
*N/A = not submitted to LB

The following figure shows the results of self-distillation across various models.


Inference

We divided the stage 3 models into two groups, assigning different random seeds to each group when possible.

Model Group A:

4x tf_efficientnetv2_s (seed= 0, 1, 2, 3)
3x tf_efficientnetv2_b3 (seed= 2, 3, 4)
4x tf_efficient_b3_ns (seed= 0, 1, 2, 3)
2x tf_efficient_b0_ns (seed= 0, 1)

Model Group B:

4x tf_efficientnetv2_s (seed= 1, 2, 3, 4)
3x tf_efficientnetv2_b3 (seed=0, 1, 2)
4x tf_efficient_b3_ns (seed= 0, 1, 2, 3) *By mistakes, we ended up using the same seed as Group A.
2x tf_efficient_b0_ns (seed= 2, 3)

Post-Proccesing/TTA

Inference is done with 2.5-second overlap.
Scores are weighted and combined (similar to the 4th place solution from last year).
Alpha = 0.5


Smoothing:
We applied smoothing using neighboring frames with a window of [0.1, 0.8, 0.1].

Power Adjustment for Low-Ranked Classes:
The post-processing method shared in our public notebook improved the LB score, but we eventually decided not to use it due to the risk of overfitting.

Speed-up:
• OpenVINO
• Concurrent.futures.ThreadPoolExecutor

Final Ensemble LB Scores
Setting	Raw Score (Group A only)	2.5-second overlap	Smoothing + overlap
Public LB	0.919	0.928	0.928
Private LB	0.917	0.924	0.924
What didn’t work

CNN-based models.
1D models.
Too many data augmentations.

Training, Inference Notebooks & Model Dataset

Training code
Github
Models
PyTorch
OpenVINO
Inference Notebooks
Convert PyTorch models to OpenVINO
Inference