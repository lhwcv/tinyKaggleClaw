6th place solution

Thank you to the organizers for hosting this excellent competition, and also to all the participants who shared valuable insights throughout the competition period.

I was greatly inspired by the top solutions from past competitions. Thank you to everyone who shared their approaches.
In this post, I will mainly highlight the differences in my approach.

Model / Loss

I used a SED-style model like the one below:

class AttBlockV2(nn.Module):
    def __init__(self, in_features: int, out_features: int, activation="sigmoid"):
        ...
        self.activation = activation
        ...

    def forward(self, x):
        norm_att = torch.softmax(torch.tanh(self.att(x)), dim=-1)
        cla = self.nonlinear_transform(self.cla(x))
        x = (norm_att * cla).sum(2)
        return x, norm_att, cla

   def nonlinear_transform(self, x):
        if self.activation == "linear":
            return x
        elif self.activation == "sigmoid":
            return torch.sigmoid(x)

class BirdModel(nn.Module):
    def __init__(self, cfg, pretrained: bool = True):
        ...
        self.encoder = timm.create_model(
            cfg.backbone,
            pretrained=cfg.pretrained,
            num_classes=0,
            global_pool="",
            in_chans=cfg.in_chans,
            drop_path_rate=0.2,
            drop_rate=0.5,
        )
        ...
        self.att_block = AttBlockV2(in_features, self.num_classes, activation="sigmoid")
        ...

    def forward(self, x, y=None):
        ...
        clipwise_output, norm_att, segmentwise_output = self.att_block(x)
        segmentwise_logit = self.att_block.cla(x).transpose(1, 2)
        if self.training:
            return clipwise_output, segmentwise_logit.max(1)[0], y
        else:
            return clipwise_output, segmentwise_logit.max(1)[0]
During training, I applied nn.BCEWithLogitsLoss to both clipwise_output and segmentwise_logit.max(1)[0].
Although clipwise_output passes through a sigmoid before loss computation (making BCEWithLogitsLoss technically inappropriate), this setup significantly improved my public score.

When using timm/tf_efficientnet_b3.ns_jft_in1k as the backbone and submitting with clipwise_output (without using train_soundscape), I achieved a public score of 0.900 and a private score of 0.908. At this stage, clipwise_output gave better results than segmentwise_logit.

Pseudo Labeling

I added pseudo labels to train_soundscapes and ran several training cycles with them included as training data.

In the first round, I used only the clipwise_output from a single model (timm/tf_efficientnet_b3.ns_jft_in1k) to generate pseudo labels.

From the second round onwards, I used an ensemble of multiple models' segmentwise_logit.max(1)[0] outputs for pseudo labeling.

Since clipwise_output was trained somewhat unnaturally with BCEWithLogitsLoss, its values were too small and didn't help improve the score when reused in pseudo labeling.

Using segmentwise_logit.max(1)[0] for pseudo labeling led to higher public scores.

Models used for generating pseudo labels included:

timm/tf_efficientnet_b3.ns_jft_in1k

timm/tf_efficientnet_b5.ns_jft_in1k

timm/tf_efficientnetv2_b3.in21k

Finally, I trained the following two models on the combined training data and pseudo labels, and used them for the final submission:

timm/tf_efficientnet_b3.ns_jft_in1k

timm/tf_efficientnetv2_b3.in21k

Score

Public Score: 0.928

Private Score: 0.923