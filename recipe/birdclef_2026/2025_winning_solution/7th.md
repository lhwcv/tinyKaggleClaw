I'd like to start by thanking the organizers of BirdCLEF 2025 for hosting this fantastic competition. It was a challenging yet rewarding experience.
Congratulations to all the participants for their hard work and brilliant solutions. I'm excited to share the approach that led to our result.

I also want to give a big thanks to my teammate, rihanpiggy. We've tackled many Kaggle competitions together—sometimes as rivals, sometimes as teammates—and I've learned so much from him along the way. I wouldn't have reached Grandmaster without his hard work and support.

TL;DR

Our solution consists of an ensemble of two model types: SED-style CNNs and 2021 2nd-place style CNNs. As in previous years, combining models trained with different pipelines proved effective for improving our leaderboard score. For the SED model, constructing high-quality pseudo-labels was crucial to achieving strong performance. Small tricks such as post-processing and test-time augmentation also proved consistently effective this year.

CNNs 1: RihanPiggy part

Train dataset

Competition data (manually remove human voice from CSA audio files)
Extra audio files downloaded from Xeno-canto
Models

Blending expert models

SED with tf_efficientnetv2_s_in21k (all species)
SED with hgnetv2_b5.ssld_stage2_ft_in1k (146 aves species)
SED with tf_efficientnetv2_s_in21k (70 aves species which have many training samples)
CNN with hgnetv2_b3.ssld_stage2_ft_in1k (70 major aves species which have many training samples)
SED with hgnetv2_b5.ssld_stage2_ft_in1k (other rare 136 species which have relatively few training samples)
methods which works

Iterative training with pseudo labeling
Inspired by the 3rd place of BirdClef2024, during training, we randomly sample audio clips from train soundscapes and corresponded pseudo label with a probability 50%.
As a result, every train batch contains 50% of train soundscapes and 50% of train audios.
This method works well for all species model and 70 major species model, but not for 146 aves species model and other rare 136 species model.
Iteratively run the cycle of training and pseudo labeling keeps improving the LB. We run this cycle for 4 iterations.
For 70 major aves species model, the pseudo label must be normalized with labels = labels - np.min(labels) to make the approach work.

smoothing postprocess(not used because of the ensemble LB drop)
Smoothing with 2 neighbors using the weight [0.1, 0.8, 0.1] improves both public and private LB for every model.

Extract audio clips from train soundscapes with birdnet
For 146 aves species model and 70 major aves species model, adding audio clips extracted from train soundscapes with birdnet works well.
Birdnet covers 145 aves species, we perform inference on train soundscapes with birdnet and extract audio clips with confidence > 0.1.
This method works well for 146 aves species model and 70 major aves species model, but not for all species model and other rare 136 species model.
This method significantly improves Public LB, but only slightly improves Private LB.

Tricks implemented only on other rare 136 species model
Prevent insecta from mixing up with other species. Insecta only mixup with other insecta species. This trick improves Public LB, but strongly damages Private LB.
0.25 * focal loss. Recovers Private LB damaged by trick 1.
Besides iterative training mentioned above, extracting audio clips from train soundscapes with pseudo labels improves Public LB a lot, but slightly damage Private LB.
After all, baseline shows best Private LB.
Linear model merge
Model merge improves the LB of tf_efficientnetv2_s_in21k (all species, 70 major aves species) model. Merging too much models will damage the LB, 3 models are enough.
For hgnetv2 models, however, model merge will destroy the model.

Model diversity matters
Raw signal model, Simple CNN model increase ensemble LB.

train settings and LB

No	Experiment	architecture	train duration	n_mels	n_fft	fmin	fmax	image_size	Public LB	Private LB
1	all species model baseline	SED v2s	10s	256	2048	0	16000	384	0.866	0.873
2	all species model pseudo iter1	SED v2s	10s	256	2048	0	16000	384	0.894	0.893
3	all species model pseudo iter2	SED v2s	10s	256	2048	0	16000	384	0.898	0.900
4	all species model pseudo merge iter2 iter1 baseline	SED v2s	10s	256	2048	0	16000	384	0.891	0.908
5	all species model pseudo merge iter3 iter2 iter1	SED v2s	10s	256	2048	0	16000	384	0.886	0.903
6	all species model pseudo merge iter4 iter3 iter2	SED v2s	10s	256	2048	0	16000	384	0.894	0.908
No	Experiment	architecture	train duration	n_mels	n_fft	fmin	fmax	image_size	Public LB	Private LB
1	70 major aves species model baseline	SED v2s	10s	256	2048	0	16000	384	0.692	0.695
2	70 major aves species model pseudo iter1	SED v2s	10s	256	2048	0	16000	384	0.696	0.707
3	70 major aves species model pseudo iter2	SED v2s	10s	256	2048	0	16000	384	0.698	0.708
4	70 major aves species model pseudo merge iter2 iter1 baseline	SED v2s	10s	256	2048	0	16000	384	0.699	0.710
5	70 major aves species model pseudo merge iter3 iter2 iter1	SED v2s	10s	256	2048	0	16000	384	0.699	0.710
6	70 major aves species model pseudo merge iter4 iter3 iter2	SED v2s	10s	256	2048	0	16000	384	0.700	0.705
No	Experiment	architecture	train duration	n_mels	n_fft	fmin	fmax	image_size	Public LB	Private LB
1	70 major aves species model baseline	CNN hgnetv2_b3	15s	192	2048	50	14000	288	0.666	0.667
2	70 major aves species model pseudo iter1	CNN hgnetv2_b3	15s	192	2048	50	14000	288	0.687	0.687
3	70 major aves species model pseudo iter2	CNN hgnetv2_b3	15s	192	2048	50	14000	288	0.689	0.685
4	70 major aves species model pseudo iter3	CNN hgnetv2_b3	15s	192	2048	50	14000	288	0.694	0.692
5	70 major aves species model pseudo iter4	CNN hgnetv2_b3	15s	192	2048	50	14000	288	0.688	0.689
No	Experiment	architecture	train duration	n_mels	n_fft	fmin	fmax	image_size	Public LB	Private LB
1	146 aves species model	SED hgnetv2_b3	10s	256	2048	50	14000	288	0.787	0.797
2	other rare 136 species model	SED hgnetv2_b3	10s	256	2048	50	14000	288	0.684	0.662
3	RihanPiggy models ensemble	-	-	-	-	-	-	-	0.916	0.906
Inference

Openvino with async inference queue
Quantize SED models with nncf
What did not work

SED model with train duration 60s to directly catch all the global context in soundscapes.
auxiliary loss of species family classification.
amphibia, mammalia, insecta expert models. Adjusting fmin and fmax to a narrower range for amphibia makes the model even worse.
extract audio clips from train soundscapes with birdvocal.
Separate mixup to different species groups, e.g. aves, insecta, mammalia, amphibia.
Implementing pseudo labeling approach from BirdClef2024 2nd place.
Calculate peaks of each audio and sample audios from peaks. (Somethng like RMS sampling)
Knowledge distillation with logits from birdnet and birdvocal. (Which works for me in BirdClef2024)
CNNs 2: yokuyama part

Training Dataset

Competition data (manually processed to remove human voices from CSA audio files)
Time-series handlabeled competition data (for some rare classes)
Models

I used two CNN models based on the 2021–2nd place solution style. Both models were trained on the same dataset using identical mel-spectrogram settings and backbone. The only difference lies in the length of the audio chunks used during training and inference: one model used 5-second chunks, while the other used 8-second chunks.

The baseline configuration was as follows:

n_mels: 256
n_fft: 2048
fmin: 50
fmax: 14000
image_width: 288
backbone: hgnetv2_b3.ssld_stage1_in22k_in1k
pooling: gem with learnable p
head: linear
loss: bce
optimizer: adamw
max_lr: 1e-3
weight_decay: 1e-3
lr_scheduler linear
epochs: 40
batch_size: 64
augmentation: AddBackgroundNoise, Gain, NoiseInjection, GaussianNoiseSNR, PinkNoiseSNR, SpecAugment, SpecMixup
inference time: ~3min. (single model)
TTA

A simple test-time augmentation was effective: we normalized the audio to a fixed peak volume (0.1) and averaged the model predictions from both the original and normalized mel-spectrograms. This improved robustness to volume variations.

for audio in test_loader:
    audio_norm = 0.1 * audio / audio.abs().amax(dim=1, keepdim=True) # BxL, peak_volume = 0.1
    spec = melspec_transform(audio)
    spec_norm = melspec_transform(audio_norm)
    preds_8s = 0.5 * (model_8s(spec) + model_8s(spec_norm))
Postprocessing

Smoothing with kernel [0.1, 0.3, 1.2, 2.4, 1.2, 0.3, 0.1]
Results

Experiment	private LB	public LB
5s CNN	0.858	0.855
8s CNN	0.851	0.854
5s + 8s + TTA	0.860	0.861
What did not work

Pseudo labeling: Despite significant effort, it did not lead to noticeable performance gains, unlike in SED models.
Auxiliary losses based on taxonomic class and family.
Auxiliary losses based on scale-invariant SNR, SAR, other audio properties…
Alternative front-ends other than mel-spectrograms (e.g., CQT, PECN) were not effective.
Additional Experiments (Not Fully Verified)

Some DINO-pretrained ViT models showed better performance than CNNs.
vit_small_patch14_reg4_dinov2 achieved a promising private LB score in the high 0.88s even in early experiments, outperforming our hgnet. However, due to inference time constraints, it was not included in the final submission.
More thorough human-in-the-loop cleansing and manual label correction had limited impact on the public LB but led to a clear gain of around +0.02 on the private LB.
Ensembles

For the final ensemble, we applied min-max scaling to each model's logits, following the method used by the 11th-place team in the 2024 competition. The scaled logits were then combined using a weighted mean.

We also adopted a soundscape-level postprocessing technique inspired by the 3rd-place team from 2024, which boosted the leaderboard score by ~0.01. The method enhances each soundscape chunk using its maximum logits. A simplified version is shown below:

def postprocess(df, bird_cols, p=0.5):
    # Apply per-soundscape adjustment
    preds = df[bird_cols].values
    for i in range(0,len(preds),12):
        preds_soundscape = preds[i:i+12]
        max_preds_soundscape = preds_soundscape.max(0, keepdims=True)
        max_preds_soundscape = max_preds_soundscape + (preds_soundscape.mean() - max_preds_soundscape.mean())
        preds_soundscape = preds_soundscape + 0.5 * max_preds_soundscape
        preds[i:i+12] = preds_soundscape
    df[bird_cols] = preds

    # Min-max normalization and power scaling
    for bird_col in bird_cols:
        df[bird_col] = df[bird_col].values - df[bird_col].min()
        df[bird_col] = df[bird_col].values / df[bird_col].max()
    df[bird_cols] = df[bird_cols].values ** p
    return df
The final ensemble achieved a public score of 0.924 and a private score of 0.922.