Thanks to host and every participant in this competion! And thanks to my great teammate @yuanzhezhou ! I learn a lot from this interesting contest and I am glad to get my first gold medal.
Our solution are as follows.

1.Dataset

Only train_audio and train_soundscapes of 2025

2.Data preprocessing

We remove 50% human voice in the audio. Because we find that removing all the human voice will hurt model performance.

3.Training

Stage 1 model

Sample
In our experiments, rms sampling is better than random sampling.

Model
We use sed models opened by 2nd place solution of 2023. Thanks for @honglihang 's fabulous models, I just need to modify some configuration and code so that I got a single model with 0.850+ on lb.

Besides, we also use the cnn model in the public notebook as our first-stage model.

Loss
For sed models, we use FocalBCE loss in the training.
For cnn models, we use CE+BCE loss. In the early stage of training, we use ce loss which can improve convergence speed and use bce loss in the late stage of training.

Data Augmentation
For raw signal:

PitchShift and Shift
Sumix proposed by 7th place solution of 2023 with 0.5 probability
For Mel-Spectrogram:

Mixup2
Time masking
FilterAugment with 0.5 probability
FrequencyMasking with 0.5 probability
PinkNoise with 0.5 probability
Mel-Spectrogram parameters
target_duration  = 5
img_size = 384
SR = 32000
n_fft = 2048
n_mels = 256
f_min = 20
f_max = 16000
hop_length = target_duration * SR // (img_size - 1)

melspec_transform = torchaudio.transforms.MelSpectrogram(
            sample_rate=SR,
            hop_length=hop_length,
            n_mels=n_mels,
            f_min=f_min,
            f_max=f_max,
            n_fft=n_fft,
            pad_mode="constant",
            norm="slaney",
            onesided=True,
            mel_scale="htk",
        )
db_transform = torchaudio.transforms.AmplitudeToDB(
            stype="power", top_db=80
        )

# for cnn
SR = 32000
n_fft = 2048
n_mels = 128
f_min = 20
f_max = 14000
hop_length = 1024
EMA
Applying ema in the training makes my model more robust and narrows the gap between different epochs.

Backbone
For sed models, we use efficientnetv2_b3, eca_nfet_l0 and seresnext26t and train in 10s segments. For cnn model, we use efficientnet_b0 and train in 5s segments.

By blending these models, we can get a sed model with 0.888 on lb and a cnn model with 0.840+ on lb.

Stage 2 model

We use our sed, cnn and models from public notebook to generate pseudo labels in every 10-second chunk. For every sample, we only use top 10% classes as soft labels and other classes are set as zeros.And then, we use the same pipeline to train new sed models. In this stage, we select efficientnetv2_b3 and seresnext26t as our final models' backbone.

By using pseudo labels, we got 0.02+ boost on lb.

4. Inference and TTA

We put 10s chunk into model and use 2 seconds as window length to apply TTA. You can check for more details in my inference notebook. All models were transformed to onnx format firstly.

5. Ensemble and Post-processing

We didn't have too much time to adjust ensemble and post-processing strategy, so we just use weighted average to ensemble models.

For post-processing:

smooth prediction with [0.2, 0.6, 0.2] (boost 0.005~0.01 on lb)
fmax - 2000 in the inference (boost 0.002 on lb)
6. Model score

We notice that random seed make a relatively huge difference on results. So we ensemble models with different seeds and same pipeline.

backbone	seed	public	private
efficientnetv2_b3 ①	42	0.903	0.913
efficientnetv2_b3 ②	3407	0.904	0.915
efficientnetv2_b3 ③	2025	0.896	0.915
seresnext26t ④	42	0.899	0.908
By ensemble ①、②、④, we got 0.913 on lb and 0.921 on private, and we select it as our final submission.
By ensemble ①、②、③, we got 0.913 (lower) on lb and 0.922 on private, but we miss this submission.

Actually, in our final chance submission, we tried to emsemble all 4 models and it just took about 1m20s on ten 60-second soudscapes. It seemed that it won't time out but it did.

BUT when we used single thread instead of multi-threads to submit it again after the contest is end, it worked well and got 0.924 on private. It seems that onnx+multi-threads will lead to bug, which makes us miss the chance to obtain top 5 :(

7. Some ideas don't work on lb but do work on private.

Because of the instability on lb, we regrettably miss some ideas that don't work on lb but do work well on private.

Resample pseudo labels by probility.

With window length of 10 seconds and step of 3 seconds, models predict every 60-second soudscape. Then, we get 17 segments on every soudscape and select the top 3 segments with the highest sum of probability.
This idea makes me get a model with 0.891 on lb but 0.916 on private.

Adjust probility by max and mean in post-processing

This idea comes from 3rd place solution of 2024.

def max_mean_post(sub_df, cfg):
    print("Postprocessing submission predictions...")
    sub_df.loc[:, cfg.bird_cols] = logit(sub_df.iloc[:, 1:].values)
    sub_df["group"] = sub_df['row_id'].str.rsplit('_', n=1).str[0]

    dfg_max = sub_df[["group"] + cfg.bird_cols].groupby('group').max().reset_index()
    dfg_mean = sub_df[["group"] + cfg.bird_cols].groupby('group').mean().reset_index()

    delta = dfg_mean[cfg.bird_cols].mean(1) - dfg_max[cfg.bird_cols].mean(1)
    for c in cfg.bird_cols:
        dfg_max[c] += delta

    sub_df = sub_df.merge(dfg_max, how="left", on="group", suffixes=('', '_delta'))
    for c in cfg.bird_cols:
        sub_df[c] = expit((sub_df[c] + sub_df[c + "_delta"]) / 2)

    return sub_df.loc[:, ['row_id']+cfg.bird_cols].reset_index(drop=True)
It decrease 0.007 on lb but boost 0.001~0.003 on private.

8. What did not work

raw signal model
ensemble with rank average
rms sample with energy weight
use common name as auxiliary target
lower rank power postprocessing
add guassian noise into raw signal
Thanks to everyone! There are many ideas that I haven't had time to try yet. Hope that I can validate them in the BirdCLEF 2026!

Inference notebook: https://www.kaggle.com/code/i2nfinit3y/bird2025-9th-place-solution?scriptVersionId=244060530