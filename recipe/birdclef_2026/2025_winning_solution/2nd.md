We would like to thank the Armed Forces of Ukraine, the Security Service of Ukraine, the Defence Intelligence of Ukraine, and the State Emergency Service of Ukraine for providing safety and security to participate in this great competition, complete this work, and help science, technology, and business not to stop but to move forward.

As the competition was coming to an end, russia once again launched a massive missile and drone attack on peaceful Ukrainian cities. This terrorist act targeted civilian homes and critical infrastructure, resulting in widespread destruction and civilian casualties. Moreover, the use of the “double tap” tactic—striking the same location twice to kill rescuers aiding those trapped in damaged and destroyed buildings—further highlights the inhumanity of the assault. This action once again affirms russia’s status as a terrorist state.

Opening Words

If we decompose the entire BirdCLEF competitions journey, we can say that up to and including 2023 were the times of “Additional Data is All You Need” but since 2024, the paradigm has changed into “Journey Down the Rabbit Hole of Pseudo Labels”. So let’s jump into it and explore the Wonderland of Semi-Supervised Learning.

Short Data Story

We downloaded additional Xeno-Canto data, taking into account the bug mentioned in the 2023 competition, which resulted in approximately:

Source	Number of samples
Xeno Canto	7,376
Previous Competitions	90
These samples were not present in the current year's dataset but had appropriate primary_label labels.
Interestingly, using parsed data from XC and iNat did not improve my models but gave a minor performance boost to @vialactea.
That’s all (folks) regarding the main training data.

5 seconds of fame

We trained our models on 5s and randomly selected segments. Based on experience from last year, we initially tried three approaches to picking 5s segments: random 5s from the whole audio, random 5s from the first 7s, and random 5s from the first or last 7s. The reasoning for the last two approaches is that often the recorder starts the audio when the animal is vocalizing and stops it when the animal stops vocalizing. That would help the model avoid false positives. The 7s was just to add some diversity.

In initial tests, the last approach provided better results. However, some species had just a few audios—as few as 2 in some cases—and we were concerned about overfitting. Therefore, we decided to inspect the audios for those species to manually identify sections of vocalization. The following charts illustrate three of the cases we found:

Vocalization with alien speech. By alien speech, we mean speech explaining the recording and with no traces of vocalization or even the same background noise as in the section in which there is vocalization. In the chart, the alien speech occurs both before and after the vocalization.

Speech overlapping with animal vocalization. In this case, the voice can be understood as background noise. In the chart, this occurs between seconds 57 and 142. The final 8 seconds is alien speech.

Vocalization with periods of silence, i.e., when the animal is not vocalizing.

Avoiding false positives must be a good thing, right? Well, no! Skipping random 5s periods in which there is no vocalization actually reduced LB. Why? Were we in over our heads trying to identify vocalization? Was there something in the audio that we were unable to detect but the models could? Maybe those false positives helped generalization by preventing the model from overfitting to the few audios available. We ended up either using the whole audio or avoiding just the sections of alien speech identified either manually or automatically. It seems that fame has more to do with false positives than with our intuition. Perhaps AI is getting too good at imitating biological intelligence, and like people, these models have developed a taste for fake stuff.
Validation Is All You Need but Do Not Have

That is, unfortunately, a true story for all BirdCLEF competitions. We explored a bunch of validation strategies. At the core of each strategy lies stratification by primary_label and grouping by author. After that, we had to figure out how to treat undersampled species. So, what we tried:

Adding at least one sample of each class to each validation fold, even if it introduced a tiiiny data leakage. We also introduced scoring for undersampled species within each fold.
Using the first approach but removing the added sample from the respective training fold.
Adding all undersampled species to the training folds and removing them from the respective validation folds. This allows the model to see more examples of undersampled species and reduces noise in the validation scores of small classes, at the cost of losing validation feedback for those species.
We mostly settled on the first and third strategies.
And of course, the most interesting question: do validation scores correlate with our Public score? After some major improvements, we saw significant positive changes in both metrics, but when tweaking things within ~1% AUC, the correlation was nearly absent.

As you can see in the plot, when we broke the 0.9 Public milestone, the correlation decided to take a rest.

Modelling, let’s be honest, is one of the most useless parts here

We followed the good traditions of previous Bird and Audio competitions and used a Spec → 2D CNN approach. But particularly for this year, backbones really did make the difference! We tried the ConvNeXt family, which showed pretty good results in 2023, but it failed this time—while also introducing very big latency. The ResNeXt family didn’t perform well either. Next encoders have become our favorites:

tf_efficientnetv2_s
eca_nfnet_l0
In some setups, EfficientNet showed better results, while in others, nfnet_l0 carried the day. Additionally, both were a really good match for ensembles.

Regarding classification heads, things were pretty standard: I used a SED head, while @vialactea used a multi-layer perceptron.

Train it to the limit

Common parts for both backbones:

50 epochs
Batch size: 64. We tried larger sizes in the final days of the competition but, unfortunately, didn’t have submissions available to test them.
Scheduler: half of a cosine cycle
Focal + BCE loss
Label smoothing 0.005
Optimizer choice differed between backbones:

eca_nfnet_l0: RAdam with 1e-4 learning rate
tf_efficientnetv2_s: AdamW with 1e-4 learning rate, 1e-8 epsilon, and (0.9, 0.999) betas
I think the most important part here was the balancing strategy. We explored a few and used different ones in the final ensemble:

Balanced
Squared
sample_weights = (
    all_primary_labels.value_counts() / 
    all_primary_labels.value_counts().sum()
)  ** (-0.5)
Upsampling: Repeating samples from the most undersampled classes until each reaches a predefined count (e.g., all classes with fewer than 100 samples are upsampled to have 100).
We ended up using both the Balanced strategy and a combination of Balanced + Upsampling.

And now we come to the first ingredient of our secret sauce—pretraining!

Let me tell you a story about …. Pretraining

From the very first experiments, @vialactea had very good results with fine-tuning from our last year’s pretrained backbones. The general concept is pretty simple:

Download a massive Xeno-Canto dataset, excluding recordings with this year’s species to avoid data leakage
Filter out undersampled species to avoid overcomplicating the classification problem during pretraining—this results in approximately 7,400–7,800 species
Train, train, train!
Picking the right checkpoint is a separate kind of art. We tried using the last, the best, and the average of the 3 best. The last two approaches worked best.
Use only the pretrained backbone and discard the classification head.
Initially, I tried pretraining only on past competition data—and failed. That initialization made things worse. Then I adopted @vialactea approach and confirmed it was a killer feature: scores jumped from 0.83–0.84 to 0.86–0.87.

After the success of last year’s pretrained models, we decided to train new ones on a fresh massive Xeno-Canto snapshot. Unfortunately, it didn’t go as well: they performed comparably or slightly worse than the 2024 pretrains. Still, one eca_nfnet_l0 checkpoint showed promise and was selected for the final ensemble.

After pretraining, we fine-tuned on our main datasets without using sophisticated techniques like differential learning rates for backbone and head.

Augmentations

Here I completely refer to the 2023 write-up, as we used exactly the same setup. We tried turning off RandomFiltering and/or SpecAug, which led to slightly better CV scores but worse LB. So the decision was made: don’t make life easier for the model—robots should work!

Release the Kraken — Pseudo Time!

We used the following algorithm:

Predict all train_soundscapes using our best ensemble in “submission” format (5-second windows).
Select only confident segments—we kept only those with a maximum probability greater than 0.5.
Use soft labels— do not apply thresholding. This can be considered a form of ensemble distillation into a single model, while also adapting to the noise and target distribution of the soundscapes.
Important: Trim low probabilities to zero—we set all probabilities below 0.1 to zero. This is a key step for removing noisy, unconfident labels.
The pseudo-code looks something like this:

…
# primary_label_prob contains max prob across 5 second chunk
soundscape_df = soundscape_df[soundscape_df["primary_label_prob"] > 0.5]
soundscape_df[scored_species <0.1] = 0
…
The next step was sampling correctly. To avoid ruining (further) the already skewed data distribution and to better control the amount of sampled pseudo labels, we used the following strategy:

Sample according to the original sampling strategy.
Check whether the class from the sample exists in soundscape_df. If it does, with some probability (0.4 in our case), select it instead of the current sample and replace the hard label with the pseudo soft label vector.
The first pseudo iteration improved our scores from 0.86–0.87 to 0.89–0.895. But as mentioned—only the first…

The next obvious step? STACK MORE PSEUDO ITERATIONS! So, we predicted using models trained on the first pseudo-iteration samples, this time using the soundscapes that didn’t pass the max-probability threshold. This boosted scores to the 0.90–0.91 range.

Unfortunately, a third iteration didn’t lead to noticeable gains, so we changed the strategy a bit. The main issue was that we couldn’t re-predict soundscapes from the previous iteration due to data leakage. But what if we split the soundscapes into folds? Now we could predict them with the “pseudo-trained” models in OOF (out-of-fold) mode. Sadly, repeating this approach twice didn’t boost scores beyond the second iteration. However, it gave us pseudo-labels generated in a slightly different way—which we then combined with previous pseudo-labels to form a crazy pseudo mix. A tf_efficientnetv2_s-based model trained on this mix became our top solo model, scoring 0.917 Public and 0.91 Private.

Pseudo iteration	Number of selected files
1	4430
2	1483
3	1437
Add a bit of postprocessing

Contrary to our 2023 solution, this year we decided to severely overfit. Not really, of course—but we did select checkpoints based on the best validation ROC AUC. We tried using the last and the average of the 3 best checkpoints, but those usually performed worse on the leaderboard. Fortunately, with fewer files to predict, we didn’t worry too much and simply submitted all 5 fold models per experiment.

We used a simple post-processing step: for each audio file, we multiplied all chunk-level predictions by the top probability for each bird class in that file. This boosts consistently strong predictions and suppresses weaker ones, without affecting the within-file ranking (since all chunks are scaled equally). However, it changes the global ranking across files — e.g., a 0.2 chunk in a strong file (mean = 0.9) becomes 0.18, while in a weak file (mean = 0.4) it becomes 0.08. This consistently improved results, typically by 0.01 for weaker models and around 0.005 for stronger ones. Code for the post-processing function:

def postprocessing(input_df, top=1):
    only_probs = input_df.iloc[:, 1:].values
    N, F = only_probs.shape
    only_probs = only_probs.reshape((N//12, 12, F))
    mean_ = np.mean(np.sort(only_probs, axis=1)[:, -top:], axis=1, keepdims=True)
    only_probs *= mean_
    input_df.iloc[:, 1:] = only_probs.reshape((N, F))
    return input_df
We predicted each 5-second chunk independently during inference. We also tried the overlapping window approach used by the previous TOP 4 team (let’s follow their naming and call it TTA). It performed well on the Public LB, boosting the best experiment’s score from 0.917 to 0.922 on Public and from 0.91 to 0.918 on Private. Unfortunately, it did not perform well with postprocessing on Public

And finally …

Our final submission contained 3 models:

tf_efficientnetv2_s trained on my pipeline with 2 pseudo iterations from the 2024 pretrained checkpoint. Trained on validation split #3 and with a Balanced sampling strategy.
eca_nfnet_l0 trained on my pipeline with 3 pseudo iterations from the 2025 pretrained checkpoint. Trained on validation split #1 and with a Balanced + Upsampling sampling strategy.
tf_efficientnetv2_s trained using @vialactea pipeline with 1 pseudo iteration from the 2024 pretrained checkpoint. Trained on validation split #3 and with a Balanced sampling strategy.
All of this was backed by post-processing on top and without TTA prediction.

A Bit of Failed Stuff

Training on soft labels of the main training data. This seems like a super logical idea, but with deep learning, as usual—you never know what will work.
Using pretrained weights from the latest Xeno Canto snippet
Using additional iNaturalist or XC data
Additional augmentations, like Time Flip
Write-up Speedrun

The strongest ones will cope with our long read, but for others—a short ablation table.

Improvement	Public Score
Baseline	0.83-0.84
+ Pretrain	0.86-0.87
+ Pseudo iteration 1	0.89-0.895
+ Pseudo iteration 2-3	0.9-0.91
+ TTA	0.922
Postprocessing	+0.005-0.01
Closing words

I hope you haven’t fallen asleep while reading. First, I want to congratulate @vialactea on achieving Grandmaster ranking! It was an honour to participate in this competition with you!

I want to thank the entire Kaggle community and congratulate all participants and winners. Special thanks to the Cornell Lab of Ornithology, LifeCLEF, Google Research, Xeno-canto, @stefankahl, @tomdenton, @holgerklinck, and @avocadomastermind. All of you were super active in discussions, shared datasets and interesting materials, answered all questions, and, of course, prepared such a cool competition!

Resources

Inference Kernel : https://www.kaggle.com/code/vladimirsydor/bird-clef-2025-ensemble-v2-final-final?scriptVersionId=244942051
Short Inference Kernel: https://www.kaggle.com/code/vladimirsydor/bird-clef-2025-minimul-inference?scriptVersionId=245080754
GitHub : https://github.com/VSydorskyy/BirdCLEF_2025_2nd_place
Paper : https://ceur-ws.org/Vol-4038/paper_256.pdf