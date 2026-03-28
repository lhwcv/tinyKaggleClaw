Overview
The goal of this competition is to develop machine learning frameworks capable of identifying understudied species within continuous audio data from Brazil's Pantanal wetlands. Successful solutions will help advance biodiversity monitoring in the last wild places on Earth.

Start
6 days ago
Close
3 months to go
Merger & Entry
Description
link
keyboard_arrow_up
How do you protect an ecosystem you can’t fully see? One way is to listen.

This competition involves building models that automatically identify wildlife species from their vocalizations in audio recordings collected across the Pantanal wetlands. This work will support more reliable biodiversity monitoring in one of the world’s most diverse and threatened ecosystems.

Understanding how ecological communities respond to environmental change and restoration efforts is a central challenge in conservation science. The Pantanal — a wetland spanning 150,000+ km² across Brazil and neighboring countries — is home to over 650 bird species plus countless other animals, yet much of it remains unmonitored. Seasonal flooding, wildfires, agricultural expansion, and climate change make regular fieldwork challenging.

Photo of a jaguar with its mouth open.
Goal of the Competition

Conventional biodiversity monitoring across vast, remote regions is expensive and logistically demanding. To help address these challenges, a growing network of 1,000 acoustic recorders is being deployed across the Pantanal, running continuously to capture wildlife sounds across different habitats and seasons. Continuous audio recording allows researchers to capture multi-species soundscapes over extended periods, providing a community-level perspective on biodiversity dynamics. But the sheer volume of audio is too large to review manually, and labeled species data is limited.

This competition focuses on the development of machine learning models that identify wildlife species from passive acoustic monitoring (PAM). Proposed approaches should work across different habitats, withstand the constraints of messy, field-collected data, and support evidence-based conservation decisions. Successful solutions will help advance biodiversity monitoring in the last wild places on Earth, including research initiatives in the Pantanal wetlands of Brazil.

Listening carefully, and at scale, may be one of the most effective tools available to protect this landscape.

Timeline
link
keyboard_arrow_up
March 11, 2026 - Start Date.

May 27, 2026 - Entry Deadline. You must accept the competition rules before this date to compete.

May 27, 2026 - Team Merger Deadline. This is the last day participants may join or merge teams.

June 3, 2026 - Final Submission Deadline.

All deadlines are at 11:59 PM UTC on the corresponding day unless otherwise noted. The competition organizers reserve the right to update the contest timeline if they deem it necessary.

Evaluation
link
keyboard_arrow_up
The evaluation metric for this contest is a version of macro-averaged ROC-AUC that skips classes that have no true positive labels.

Submission Format

For each row_id, you should predict the probability that a given species was present. There is one column per species. Each row covers a five-second window of audio.

Prizes
link
keyboard_arrow_up
1st Place - $15,000
2nd Place - $10,000
3rd Place - $8,000
4th Place - $7,000
5th Place - $5,000
Best working note award (optional):

Participants of this competition are encouraged to submit working notes to the CLEF 2026 conference. A best BirdCLEF+ working note competition will be held as part of the conference. The top two best working note award winners will receive $2,500 each. See the Evaluation page for judging criteria.

Working Note Award (optional)
link
keyboard_arrow_up
Working Note Submission Timeline
We encourage participants to submit a working note write-up of their approach to the CLEF conference. Organizers will award $5,000 in prize money ($2,500 each) for the two best working note submissions.

Submission dates are:

June 3, 2026 - Competition deadline
June 17, 2026 - Working note submission deadline
June 24, 2026 - Notification of acceptance
July 6, 2026 - Camera-ready submission deadline
Additional information on the submission process will be posted ahead of time on the discussion forum.

Working Note Award Criteria
Criteria for the BirdCLEF+ Best Working Note Award:

Originality. The value of a paper is a function of the degree to which it presents new or novel technical material. Does the paper present results previously unknown? Does it push forward the frontiers of knowledge? Does it present new methods for solving old problems or new viewpoints on old problems? Or, on the other hand, is it a rehash of information already known?

Quality. A paper's value is a function of the innate character or degree of excellence of the work described. Was the work performed or the study made with a high degree of thoroughness? Was high engineering skill demonstrated? Is an experiment described which has a high degree of elegance? Or, on the other hand, is the work described pretty much of a run-of-the-mill nature?

Contribution. The value of a paper is a function of the degree to which it represents an overall contribution to the advancement of the art. This is different from originality. A paper may be highly original but may be concerned with a very minor, or even insignificant, matter or problem. On the other hand, a paper may make a great contribution by collecting and analyzing known data and facts and pointing out their significance. Or, a fine exposition of a known but obscure or complex phenomenon or theory or system or operating technique may be a very real contribution to the art. Obviously, a paper may well score highly on both originality and contribution. Perhaps the important question is, will the engineer who reads the paper be able to practice his profession more effectively because of having read it?

Presentation. The value of the paper is a function of the ease with which the reader can determine what the author is trying to present. Regardless of the other criteria, a paper is not good unless the material is presented clearly and effectively. Is the paper well written? Is the meaning of the author clear? Are the tables, charts, and figures clear? Is their meaning readily apparent? Is the information presented in the paper complete? At the same time, is the paper concise?

Evaluation of the submitted BirdCLEF+ working notes:

Each working note will be reviewed by two reviewers and scores averaged. Maximum score: 15.

a) Evaluation of work and contribution

5 points: Excellent work and a major contribution

4 points: Good, solid work of some importance

3 points: Solid work but a marginal contribution

2 points: Marginal work and minor contribution

1 point: Work doesn't meet scientific standards

b) Originality and novelty

5 points Trailblazing

4 points: A pioneering piece of work

3 points: One step ahead of the pack

2 points: Yet another paper about…

1 point: It's been said many times before

c) Readability and organization

5 points: Excellent

4 points: Well written

3 points: Readable

2 points: Needs considerable work

1 point: Work doesn't meet scientific standards

Code Requirements
link
keyboard_arrow_up
This is a Code Competition

Submissions to this competition must be made through Notebooks. For the "Submit" button to be active after a commit, the following conditions must be met:

CPU Notebook <= 90 minutes run-time
GPU Notebook submissions are disabled. You can technically submit but will only have 1 minute of runtime.
Internet access disabled
Freely & publicly available external data is allowed, including pre-trained models
Submission file must be named submission.csv
Please see the Code Competition FAQ for more information on how to submit. And review the code debugging doc if you encounter submission errors.

Acknowledgements
link
keyboard_arrow_up
The development of the competition dataset was supported by the Bezos Earth Fund AI for Climate and Nature Grand Challenge.

Compiling this extensive dataset was a major undertaking, and we are very thankful to the many domain experts who helped to collect and manually annotate the data for this competition. Specifically, we would like to thank (institutions and individual contributors in alphabetic order):

Chemnitz University of Technology: Stefan Kahl, Mario Lasseck, and Maximilian Eibl

Google Deepmind: Tom Denton

iNaturalist: Grant van Horn

Instituto Homem Pantaneiro: Wener Hugo Arruda Moreno

Instituto Nacional de Pesquisa do Pantanal (INPP): Carolline Zatta Fieker, Karl-L. Schuchmann, Kirk Thiago Pedroso Azevedo, Lucas Korzune Sampaio Teles, Marinez Isaac Marques and Matheus Gonçalves dos Reis

K. Lisa Yang Center for Conservation Bioacoustics: Stefan Kahl, Larissa Sugai and Holger Klinck

LifeCLEF: Alexis Joly and Henning Müller

Sauá Consultoria Ambiental: Carolina Martins Garcia

Universidade Federal de Mato Grosso do Sul (UFMS): Alyson Vieira de Melo, Daiene Louveira Hokama Sousa, José Luiz Massao Moreira Sugai, João Emílio de Almeida Júnior, Liliana Piatti, Mariana Motti Barbosa, Matheus de Oliveira Neves, Priscila do Nascimento Lopes and Ryan Christopher Kridler

Xeno-canto: Willem-Pier Vellinga, Bob Planqué

Photo Credits

Banner picture of a Hyacinth Macaw by Thomas Fuhrmann. Inset picture of a Jaguar by Leonardo Ramos.

Citation
link
keyboard_arrow_up
Stefan Kahl, Tom Denton, Larissa Sugai, Liliana Piatti, Ryan Holbrook, Holger Klinck, and Ashley Oldacre. BirdCLEF+ 2026. https://kaggle.com/competitions/birdclef-2026, 2026. Kaggle.