# BirdCLEF 2026 Baseline 方案设计

> 目标：在 **不引入外部数据** 的前提下，构建一条足够稳定、足够可解释、能够真实反映 **train_audio → soundscape 跨域能力** 的 baseline。
>
> 这不是最终冠军方案，而是后续一切增强（external data / pseudo labels / self-distillation / specialist branch / ensemble）的出发点。

---

## 1. 设计目标

这一版 baseline 要优先解决的不是“分数极限”，而是下面 4 件事：

1. **明确数据边界**：先不引入外部数据，只使用比赛官方 2026 数据。
2. **验证跨域能力**：训练尽量只依赖 `train_audio`，验证重点看 `labeled train_soundscapes`。
3. **避免数据泄露**：尤其是 `train_soundscapes_labels.csv` 的重复记录，以及同一 soundscape 文件不能跨 train/val。
4. **为后续升级留接口**：baseline 的数据组织、split、训练接口、评估接口，后面必须能平滑升级到 pseudo labels 和 specialist 模型。

---

## 2. 我们为什么这样设计：从 2025 方案抽出来的共识

下面的结论主要参考：

- `code_ref/BirdCLEF_2025_2nd_place-main/README.md`
- `code_ref/BirdCLEF2025-4th-place-solution-main/README.md`
- `code_ref/BirdCLEF-2025-5th-place-solution-main/README.md`
- `code_ref/my_rank10_birdclef_2025/solution_overview_en.md`
- `code_ref/BirdCLEF_2025_2nd_place-main/scripts/cv_split_cls.py`
- `docs/2025_winning_solution/details/1st.md`
- `docs/2025_winning_solution/details/2nd.md`
- `docs/2025_winning_solution/details/4th.md`
- `docs/2025_winning_solution/details/5th.md`
- `docs/2025_winning_solution/details/10th.md`

### 2.1 从 2025 高排位方案得到的强共识

- **SED 是主干，不是配角**
  - 1st / 5th / 7th / 9th / 10th 都明显偏向 SED 风格建模。
  - 4th 也是明确的 SED solution。

- **EfficientNet / EfficientNetV2 是最稳的 backbone 家族**
  - 2nd 用 `eca_nfnet_l0 + tf_efficientnetv2_s`
  - 4th 大量使用 `efficientnet / efficientnetv2`
  - 5th 大量使用 `tf_efficientnetv2_s / b3` 与 `efficientnet_b3 / b0`
  - 10th 也明确提到 `EfficientNetV2-S`、`ConvNeXt Tiny` 表现较强

- **SSL / pseudo labels 是主战场，但 baseline 先不引入**
  - 2nd、4th、5th、10th 都在伪标签、self-distillation、semi-supervised 上获得大量收益。
  - 但我们当前阶段要先把 **“不用外部数据、不用 pseudo labels”** 的 baseline 做稳，才能知道后续每一步到底提升了什么。

- **validation 必须认真设计**
  - 10th 明确提到 BirdCLEF 最大难点之一是“没有同分布验证集”。
  - 2nd 的代码里专门有 `cv_split_cls.py`，使用 `StratifiedGroupKFold`，并且考虑 `all_species_in_train_folds`、rare species duplication 等细节。

### 2.2 从 2026 数据本身得到的强约束

来自 `eda_2026/summary.md` 和去重后的 soundscape labels：

- `taxonomy.csv` 有 `234` 个目标类别，但 `train.csv` 只覆盖 `206`
- 有 `28` 个目标类别 **只在 `train_soundscapes` 里出现，不在 `train_audio` 中出现**
- 这 `28` 个类别全部属于 `Amphibia` 或 `Insecta`
- 训练音频与声景录音区域存在很强的地理域差
- 每个 5 秒声景窗口平均约 `4.22` 个正标签，是高密度多标签任务

因此，2026 baseline 必须显式承认两件事：

1. **train_audio 是主训练域，soundscape 是目标域**
2. **部分目标类没有 train_audio，只能从 labeled train_soundscapes 中学到**

---

## 3. baseline 总体原则

### 原则 A：训练尽量只用 `train_audio`

- 对于 **在 `train_audio` 中存在** 的类别，baseline 训练主要依赖 `train_audio`
- 这样可以最大化检验：模型到底能不能从 focal recording 泛化到 soundscape

### 原则 B：只有 `train_audio` 中缺失的类别，才显式使用 `train_soundscapes`

- 对于 `taxonomy - train_audio_species` 这 28 个类别，baseline 必须使用 `train_soundscapes`
- 否则这些类别根本无监督信号

### 原则 C：验证以跨域为核心，不以 in-domain 为核心

- `train_audio` 验证集只作为 **训练稳定性和 sanity check**
- 真正主指标应放在 **held-out labeled train_soundscapes** 上

### 原则 D：所有 split 以“防泄露”为先

- `train_soundscapes` 必须以 **整条 soundscape 文件** 为单位划分 fold，不能按 5 秒 chunk 随机切
- `train_audio` 至少应按 `author` 分组，减少相似来源泄露
- 已发现 `train_soundscapes_labels.csv` 原始文件有完全重复记录，后续统一使用：
  - `data/birdclef_2026/train_soundscapes_labels_dedup.csv`

---

## 4. baseline 的数据定义

## 4.1 数据源

### A. 主训练源：`train_audio`

- 文件：`data/birdclef_2026/train.csv`
- 用途：
  - 所有在 `train_audio` 中有样本的类别的主监督来源
  - baseline 的主体训练数据

### B. 辅助训练源：`train_soundscapes_labels_dedup.csv`

- 文件：`data/birdclef_2026/train_soundscapes_labels_dedup.csv`
- 用途：
  - 仅用于补足 `train_audio` 缺失的 `28` 个目标类别
  - 同时作为 **跨域验证集** 的核心来源

### C. taxonomy

- 文件：`data/birdclef_2026/taxonomy.csv`
- 用途：
  - 定义完整 234 类输出空间
  - 定义 `missing_species`

---

## 4.2 类别集合定义

### Seen classes

定义：在 `train.csv` 里出现过的类别。

```text
seen_species = set(train_csv.primary_label)
```

当前数量：`206`

### Missing classes

定义：在 `taxonomy.csv` 中存在，但 `train.csv` 中完全没有样本的类别。

```text
missing_species = set(taxonomy.primary_label) - seen_species
```

当前数量：`28`

---

## 4.3 baseline 训练样本组成

### 对于 seen classes

- 训练样本来自 `train_audio`
- baseline 阶段 **不主动使用** soundscape 作为这些类的训练主来源

### 对于 missing classes

- 训练样本来自 `train_soundscapes_labels_dedup.csv`
- 只从那些 **包含至少一个 missing species 的 5 秒 chunk** 中构建训练样本

---

## 4.4 一个非常关键的实现建议：对 soundscape 训练样本使用 `partial-label mask`

这是本 baseline 里最重要的设计点之一。

### 为什么需要 mask

如果我们直接把包含 missing species 的 soundscape chunk 拿来训练完整 234 类：

- 它们里面通常还包含 seen species
- 这等于把 seen species 的训练也拉进 soundscape 域
- 这会让 baseline 不再满足“**seen classes 主要只用 train_audio 训练**”的设计目标

### 建议做法

对于 **soundscape-derived training samples**：

- 只对 `missing_species` 维度计算 loss
- 对其他 206 个 seen 维度：**不参与 loss**（mask 掉）

即：

- `train_audio sample` → full 234-dim supervised loss
- `soundscape sample with missing species` → only missing-species dims contribute to loss

### 这样做的好处

- 满足你的设计目标：seen classes 的训练尽可能只来自 `train_audio`
- missing classes 仍然能从 soundscape 里获得监督
- 不会因为 soundscape chunk 多标签而把 seen 类强行拉入 baseline 训练域
- 为后续升级到 full SSL 时保留清晰对照组

---

## 5. baseline split 设计（重点）

这一部分是 baseline 最关键的部分。

我们不追求“最漂亮的 CV”，而追求：

- 尽量稳
- 尽量不泄露
- 尽量能反映 `train_audio -> soundscape` 的跨域能力
- 5 折可复现

---

## 5.1 `train_audio` 的 5 折切分逻辑

### 切分目标

对 `train_audio`：

- validation 主要用于训练监控和 sanity check
- training 必须尽量覆盖更多 seen classes
- 相似来源样本不能轻易跨 train/val

### 推荐逻辑

#### Step 1：定义 group

参考 2025 第 2 名 `cv_split_cls.py`：

- 优先用 `author` 作为 group
- 如果 `author` 缺失或未知，则退化为 `filename`

目的：

- 避免同一作者/相近来源样本在 train 和 val 同时出现
- 降低近重复泄露风险

#### Step 2：按 `primary_label` 做 `StratifiedGroupKFold(n_splits=5)`

- `y = primary_label`
- `group = normalized author`
- `n_splits = 5`

这一步借鉴 2025 第 2 名的思路，是目前最合理的第一层 split。

#### Step 3：rare species 单独处理

对于 `train_audio` 中样本数非常少的类别：

- 若某类别样本数 `< 5`
- 或 group 分布过于单一，无法稳定分进 5 折

则不强行要求该类出现在每个 validation fold。

### 推荐策略

将 seen classes 分成 3 组：

#### Group A：`count >= 5` 且 group 足够分散
- 正常参与 5 折 stratified group split
- 尽量保证每折 val 都见到

#### Group B：`2 <= count < 5`
- 尽量参与 split
- 若无法稳定分配，则允许它们只出现在部分 val fold
- 但必须确保 **每个 fold 的 train 中有该类**

#### Group C：`count == 1`
- 不作为 validation 样本
- 该类样本始终放在 train
- 只作为训练补充，不用于本地 val 决策

### 为什么这么做

因为如果强行让极稀有类进入 val：

- val 波动会极大
- fold 间可比性变差
- 而且这些类在 train 中反而可能消失，导致训练不稳定

这和 2025 第 2 名代码里 `all_species_in_train_folds` 的设计思想一致：

> **训练 fold 完整覆盖物种，比 validation fold 的形式完美更重要**

---

## 5.2 `train_soundscapes` 的 5 折切分逻辑

### 切分目标

这里的目标完全不同：

- validation 必须真实衡量 cross-domain performance
- 同一 soundscape 文件绝不能跨 train/val
- 尽量让每折包含尽可能多的物种，尤其是 missing species

### 切分单位

**必须按 `filename` 切，而不是按 5 秒 chunk 切。**

即：

- 先把 `train_soundscapes_labels_dedup.csv` 聚合到 `filename` 级别
- 每个 soundscape file 分配到一个 fold
- 再把该文件下所有 5 秒 chunk 一起带入对应 fold

### 原因

如果按 chunk 随机切：

- 同一 1 分钟 soundscape 的相邻片段会同时出现在 train 和 val
- 背景声场、录音设备、时间连续性都泄露
- 本地验证会严重高估真实泛化能力

### 推荐切分算法

由于 soundscape 是多标签数据，而且只有几十条文件，推荐使用：

#### 文件级 greedy multilabel balancing

步骤：

1. 对每个 `filename`，汇总它覆盖到的 label set
2. 计算每个文件的“稀有标签权重”，例如：
   - 对每个标签取 `1 / frequency`
   - 文件权重为这些值的和
3. 按文件权重从高到低排序
4. 贪心地将每个文件分配到当前最“缺少这些标签”的 fold 中
5. 同时约束每折：
   - 文件数尽量接近
   - chunk 数尽量接近
   - missing species 覆盖尽量均衡

### baseline 不要求每折拥有全部 234 类

这是不现实的。

更合理的目标是：

- 每折尽量覆盖常见声景类
- 每折尽量覆盖一部分 missing species
- missing species 的高频类尽量分散到多个 fold

---

## 5.3 最终每个 fold 的数据组成

对第 `k` 折：

### 训练集

#### 1) `train_audio_train_k`
- 来自 `train_audio`
- seen classes 主训练源

#### 2) `train_soundscape_train_k_missing`
- 来自 `train_soundscapes_labels_dedup.csv`
- 仅保留那些 **标签集合与 `missing_species` 有交集** 的 chunk
- 用于补足 missing classes
- 对 seen classes 维度做 loss mask，不计 loss

### 验证集

#### 1) `train_audio_val_k`
- in-domain 验证
- 只作为 sanity check / 训练稳定性监控

#### 2) `train_soundscape_val_k`
- cross-domain 核心验证
- 用于真正评估 soundscape 泛化能力

---

## 5.4 baseline 的模型选择标准

这一点必须明确，否则会不自觉回到“看 audio CV”老路。

### 训练过程中记录 4 个指标

#### A. `audio_val_auc_seen`
- 在 `train_audio_val_k` 上评估 seen classes
- 作用：检查模型是否训练崩了

#### B. `soundscape_val_auc_all`
- 在 `train_soundscape_val_k` 上评估所有 234 类
- 作用：作为主验证指标

#### C. `soundscape_val_auc_seen`
- 只在 seen classes 上看 soundscape 泛化
- 作用：评估 `train_audio -> soundscape` 的跨域能力

#### D. `soundscape_val_auc_missing`
- 只在 missing classes 上看表现
- 作用：评估 baseline 是否成功补起了那 28 类

### baseline 推荐主指标

```text
primary_metric = soundscape_val_auc_all
secondary_metric = soundscape_val_auc_missing
aux_metric = audio_val_auc_seen
```

也就是说：

- 早停和 checkpoint 选择优先看 `soundscape_val_auc_all`
- 若接近，则优先看 `soundscape_val_auc_missing`
- `audio_val_auc_seen` 只作为辅助

这符合你的目标：

> baseline 重点要验证跨域能力，而不是 in-domain 拟合能力。

---

## 6. baseline 模型方案

## 6.1 主模型：`10s SED EfficientNetV2-S`

这是推荐的 baseline 主模型。

### 为什么选它

综合 2025 的 2/4/5/10 名参考：

- `SED` 比纯 CNN 更稳
- `EfficientNetV2-S` 是高频强 backbone
- `10s` 是一个比 `5s` 更适中的上下文长度，尤其对 2026 的 Amphibia/Insecta 更友好
- 相比 `20s`，`10s` 的训练和 CPU 推理成本更可控

### baseline 配置建议

- backbone: `tf_efficientnetv2_s`
- head: SED head
- sample rate: `32000`
- input duration: `10s`
- output: framewise + clipwise
- mel bins: `192` 或 `224`
- image-like spectrogram shape: `384 x 160` 作为首选 baseline
- fmin: `40~50`
- fmax: `16000`

### 为什么不是 5 秒

- 2026 声景里 Amphibia / Insecta 明显更强，长时持续叫声特征更重要
- 1st 方案在 2025 也明确提到长输入对 Amphibia / Insecta 更友好
- 5th / 7th / 9th / 10th 也普遍使用 `10s` 或更长输入

---

## 6.2 备选 baseline：`10s SED EfficientNetV2-B3`

用途：

- 做 backbone 对照组
- 未来做双模型 teacher ensemble 的种子模型

如果资源允许，建议 baseline 第一轮就至少训练两条：

- `v2s`
- `v2b3`

---

## 6.3 loss 选择

### baseline 首选：`Focal BCE`

原因：

- 2nd、5th、9th 都在使用 BCE/Focal BCE 系列
- 多标签声景问题里它更自然
- 先用它建立稳定比较基线，后续再测 `SoftAUC`

### baseline 不建议直接上：`SoftAUC`

原因：

- 4th 方案的 SoftAUC 很值得测
- 但它本质上已经是 baseline 之后的重要 ablation 分支，而不是最基础的第一版

### baseline 也不建议第一版直接上 10th 的改进混合 CE

原因：

- 那套 loss 更像经验强化版本
- 应该等 baseline 稳后再做对照实验

---

## 6.4 数据增强

baseline 阶段只保留轻量增强：

- [ ] time masking
- [ ] frequency masking
- [ ] mild mixup
- [ ] optional additive noise

暂不做：

- [ ] aggressive pseudo mixing
- [ ] Sumix
- [ ] 复杂 curriculum
- [ ] 特殊阈值重采样

原因：baseline 先看清模型本体与 split 是否合理。

---

## 7. baseline 的训练样本构造

## 7.1 `train_audio` 样本

### 推荐采样

对于每条音频：

- 若时长 `< 10s`：repeat / pad 到 `10s`
- 若时长 `>= 10s`：
  - baseline 推荐采用 **first10-biased random crop**：
    - `p = 0.7`：从前 15 秒里采样 10 秒
    - `p = 0.3`：全音频范围内随机采样 10 秒

### 为什么这样做

- 4th 方案中 `first10` 是非常重要的配置思路
- 2nd 方案又说明不能完全忽视更广范围的随机性
- 这个混合采样是一个稳妥的折中版 baseline

---

## 7.2 `train_soundscapes` 样本

对每个 5 秒 labeled chunk：

- 构造一个 10 秒训练输入
- 方法：以该 5 秒段为中心，取一个覆盖它的 10 秒窗口
- 允许小范围 jitter，但必须保证该 5 秒标签窗口落在模型的主要感受区域内

### 标签处理

#### baseline strict version

- 只保留 `missing_species` 维度参与 loss
- seen species 维度做 loss mask

这是最符合你当前想法的 baseline 版本。

---

## 8. baseline 的评估输出

每个 fold 至少导出：

- [ ] `audio_val_oof.csv`
- [ ] `soundscape_val_oof.csv`
- [ ] `metrics_seen_audio.json`
- [ ] `metrics_seen_soundscape.json`
- [ ] `metrics_missing_soundscape.json`
- [ ] `fold_summary.json`

最终汇总：

- [ ] 5-fold `audio_val_auc_seen` 均值 / 方差
- [ ] 5-fold `soundscape_val_auc_all` 均值 / 方差
- [ ] 5-fold `soundscape_val_auc_missing` 均值 / 方差
- [ ] 每类 AUC 明细，尤其 missing species 明细

---

## 9. baseline 成功标准

这版 baseline 不要求马上打很高的 leaderboard，而是要求它成为“可信的起点”。

### baseline 成功的定义

- [ ] 5 折 split 无明显泄露
- [ ] `train_soundscapes_labels_dedup.csv` 被统一使用
- [ ] 每个 fold 的 train 都尽量覆盖 seen species
- [ ] soundscape validation 能稳定计算 `all / seen / missing` 三类指标
- [ ] 模型训练过程稳定
- [ ] CPU 推理成本可接受
- [ ] 结果可作为后续 pseudo-label teacher 的起点

### baseline 失败的定义

- [ ] 只在 `train_audio_val` 上表现好，但 `soundscape_val` 很差
- [ ] missing species 几乎完全起不来
- [ ] fold 间波动极大，说明 split 不可信
- [ ] 训练/推理接口无法平滑升级到下一阶段

---

## 10. baseline 之后的第一批 ablation（不是现在立刻做）

当 baseline 稳定后，建议按如下顺序做增强：

### 优先级 1
- [ ] `EfficientNetV2-S` vs `EfficientNetV2-B3`
- [ ] `Focal BCE` vs `SoftAUC`
- [ ] `10s` vs `15s` vs `20s`
- [ ] `384x160` vs `384x256`

### 优先级 2
- [ ] no-soundscape-missing-only vs partial-label masked soundscape training
- [ ] first10-biased vs full random crop
- [ ] specialist branch for Amphibia/Insecta

### 优先级 3
- [ ] pseudo labels iteration 1
- [ ] self-distillation on train_audio
- [ ] train_audio + soundscapes joint distillation

---

## 11. 最终推荐的 baseline v1

如果现在必须立刻落地一版 baseline，我建议就是下面这个：

### Data
- `train_audio` 作为 seen species 主训练源
- `train_soundscapes_labels_dedup.csv` 只用于 missing species

### Split
- `train_audio`: `StratifiedGroupKFold(n_splits=5, y=primary_label, group=author_or_filename)`
- rare species 不强行进 val，但保证尽量留在 train
- `train_soundscapes`: 以 `filename` 为单位做 5 折 greedy multilabel split

### Model
- `10s SED tf_efficientnetv2_s`
- `384x160` log-mel
- `Focal BCE`

### Training
- `train_audio` 样本：full 234-dim supervised
- `train_soundscapes` 样本：只对 `missing_species` 维度算 loss

### Selection
- checkpoint / model selection 以 `soundscape_val_auc_all` 为主
- `soundscape_val_auc_missing` 为第二指标
- `audio_val_auc_seen` 只做 sanity check

这会是一条非常干净、非常适合后续扩展的 baseline 主线。

---

## 12. 一句话总结

> **这版 baseline 的核心，不是“先把所有数据都喂进去”，而是“有意识地把 train_audio 视作训练域，把 labeled train_soundscapes 视作目标域代理，并且只用 soundscapes 去补 train_audio 中不存在的那 28 个类别”。**

这会让我们后面每一步增强（pseudo labels、specialist、external data、distillation、ensemble）都更可解释。

