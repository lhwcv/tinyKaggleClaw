First of all, this is my first time to reach the prize on kaggle, much thanks to the organizers and all the participants.

My solution is a SED solution inspired by birdclef2023 2nd place solution, combined with a custom soft AUC loss and semi-supervised learning.

Main concept: soft AUC loss

I always thought that the best loss should be the metric itself, so I tried to find an AUC loss and found:

class AUCLoss(nn.Module):
    def __init__(self, margin=1.0, pos_weight=1.0, neg_weight=1.0):
        super().__init__()
        self.margin = margin
        self.pos_weight = pos_weight
        self.neg_weight = neg_weight

    def forward(self, preds, labels, sample_weights=None):
        pos_preds = preds[labels == 1]
        neg_preds = preds[labels == 0]

        if len(pos_preds) == 0 or len(neg_preds) == 0:
            return torch.tensor(0.0, device=preds.device)

        if sample_weights is not None:
            sample_weights = torch.stack([sample_weights]*labels.shape[1], dim=1)
            pos_weights = sample_weights[labels == 1]  # [N_pos]
            neg_weights = sample_weights[labels == 0]  # [N_neg]
        else:
            pos_weights = torch.ones_like(pos_preds) * self.pos_weight
            neg_weights = torch.ones_like(neg_preds) * self.neg_weight

        diff = pos_preds.unsqueeze(1) - neg_preds.unsqueeze(0)  # [N_pos, N_neg]
        loss_matrix = torch.log(1 + torch.exp(-diff * self.margin))  # [N_pos, N_neg]

        weighted_loss = loss_matrix * pos_weights.unsqueeze(1) * neg_weights.unsqueeze(0)

        return weighted_loss.mean()
This AUC loss seems to be very resistant to overfitting. In all experiments, the cv scores of the models trained with the cross entropy loss were significantly better than those trained with the soft AUC loss, but the lb scores were significantly worse.
There is a problem with this AUC loss: it does not support soft labels like cross entropy loss. For both knowledge distillation and semi-supervised learning, I need a loss that supports soft labels, so I made some changes to the above AUC loss:

class SoftAUCLoss(nn.Module):
    def __init__(self, margin=1.0, pos_weight=1.0, neg_weight=1.0):
        super().__init__()
        self.margin = margin
        self.pos_weight = pos_weight
        self.neg_weight = neg_weight

def forward(self, preds, labels, sample_weights=None):
        pos_preds = preds[labels>0.5]
        neg_preds = preds[labels<0.5]
        pos_labels = labels[labels>0.5]
        neg_labels = labels[labels<0.5]

        if len(pos_preds) == 0 or len(neg_preds) == 0:
            return torch.tensor(0.0, device=preds.device)

        pos_weights = torch.ones_like(pos_preds) * self.pos_weight * (pos_labels-0.5)
        neg_weights = torch.ones_like(neg_preds) * self.neg_weight * (0.5-neg_labels)
        if sample_weights is not None:
            sample_weights = torch.stack([sample_weights]*labels.shape[1], dim=1)
            pos_weights = pos_weights * sample_weights
            neg_weights = neg_weights * sample_weights

        diff = pos_preds.unsqueeze(1) - neg_preds.unsqueeze(0)  # [N_pos, N_neg]
        loss_matrix = torch.log(1 + torch.exp(-diff * self.margin))  # [N_pos, N_neg]

        weighted_loss = loss_matrix * pos_weights.unsqueeze(1) * neg_weights.unsqueeze(0)

        return weighted_loss.mean()
This soft AUC loss + semi-supervised learning improved my single tf_efficientnetv2_b0 model's lb score from 0.850 to 0.901. More importantly, my improvement from 11th to 4th on private lb is probably due to the use of this loss.

Other things that helped
Semi-supervised learning. The labeling model is 10 SED models of efficientnet_b0-b4, efficientnetv2_b0-b3 and efficientnetv2_s trained wiht first 10s audio data.
Smaller hop_length (64) and larger n_mels (256).
Audio mixup augmentation (which is to add two audios as the new audio and take the maximum value of their labels as the new label). This augmentation did not directly improve my model, but in order to increase the diversity of the final solution, I still added this to the training of some models.

Things that didn't help or make it worse
Any kind of pretraining.
Knowledge distillation.
Models other than efficientnet.
Data normalizitions other than 2D batch normalizition.

Final models
16models of efficientnet_lite0-4, efficientnet_b2-3, efficientnetv2_b2-3 and efficientnetv2_s. 17-25 epochs, learning rate 5e-4. 3 types of mel spectrogram parameters. 2 types of data augmentation. First 10s data and random 10s data.

Code
https://github.com/dylanliu2/BirdCLEF2025-4th-place-solution