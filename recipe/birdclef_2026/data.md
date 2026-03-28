Dataset Description
Your challenge in this competition is to identify which species (birds, amphibians, mammals, reptiles, insects) are calling in recordings made in the Brazilian Pantanal. This is an important task for scientists who monitor animal populations for conservation purposes. More accurate solutions could enable more comprehensive monitoring.

This competition uses a hidden test set. When your submitted notebook is scored, the actual test data will be made available to your notebook.

Files

train_audio/ The training data consists of short recordings of individual bird, amphibian, reptile, mammal, and insect sounds generously uploaded by users of xeno-canto.org and iNaturalist. These files have been resampled to 32 kHz where applicable to match the test set audio and converted to the ogg format. Filenames consist of [collection][file_id_in_collection].ogg. The training data should have nearly all relevant files; we expect there is no benefit to looking for more on xeno-canto.org or iNaturalist and appreciate your cooperation in limiting the burden on their servers. If you do, please make sure to adhere to the scraping rules of these data portals.

test_soundscapes/ When you submit a notebook, the test_soundscapes directory will be populated with approximately 600 recordings to be used for scoring. They are 1 minute long and in ogg audio format, resampled to 32 kHz. The file names have the general form of BC2026_Test_<file ID>_<site>_<date>_<time in UTC>.ogg (e.g., file BC2026_Test_0001_S05_20250227_010002.ogg has file ID 0001, was recorded at site S05 on Feb 27 2025 at 01:00 UTC). It should take your submission notebook approximately five minutes to load all the test soundscapes. Not all species from the training data actually occur in the test data.

train_soundscapes/ Additional audio data from roughly the same recording locations as the test_soundscapes. Filenames follow the same naming convention as the test_soundscapes; although some recording sites overlap between train and test, precise recording dates and times do NOT overlap with recordings of the hidden test data. This year, some of the train_soundscapes have been labeled by expert annotators, and we provide the ground truth for a subset of train_soundscapes in train_soundscapes_labels.csv with columns filename referencing the soundscape file, start and end referencing the 5-second segment for which column primary_label provides a semicolon-separated list of species codes that have been marked as present in this segment.

Important note: Some species with occurrences in the hidden test data might only have train samples in the labeled portion of train_soundscapes and not in the train_audio (XC and iNat data). However, not all species from train_soundscapes have occurrences in the test_soundscapes.

train.csv A wide range of metadata is provided for the training data. The most directly relevant fields are:

primary_label: A code for the species (eBird code for birds, iNaturalist taxon ID for non-birds). You can review detailed information about the species by appending codes to eBird and iNaturalist taxon URL, such as https://ebird.org/species/brnowl for the Barn Owl or https://www.inaturalist.org/taxa/41970 for the Jaguar. Not all species have their own pages; some links might fail.
secondary_labels: List of species labels that have been marked by recordists to also occur in the recording. Can be incomplete.
latitude & longitude: Coordinates for where the recording was taken. Some bird species may have local call 'dialects,' so you may want to seek geographic diversity in your training data.
author: The user who provided the recording. Unknown if no name was provided.
filename: The name of the associated audio file.
rating: Values in 1..5 (1 - low quality, 5 - high quality; 0.5 reduction in rating when background species are present) provided by users of Xeno-canto; 0 implies no rating is available; iNaturalist does not provide quality ratings.
collection: Either XC or iNat, indicating which collection the recording was taken from. Filenames also reference the collection and the ID within that collection.
sample_submission.csv A valid sample submission.

row_id: A slug of [soundscape_filename]_[end_time] for the prediction; e.g., Segment 00:15-00:20 of 1-minute test soundscape BC2026_Test_0001_S05_20250227_010002.ogg has row ID BC2026_Test_0001_S05_20250227_010002_20.
[species_id]: There are 234 species ID columns. You will need to predict the probability of the presence of each species for each row.
taxonomy.csv - Data on the different species, including iNaturalist taxon ID and class name (Aves, Amphibia, Mammalia, Insecta, Reptilia). Most insect species in this competition have not been identified on species level and instead occur as sonotypes (e.g., 47158son16 as insect sonotype 16); these sonotypes are treated as classes despite the lack of species ID and some of them also occur in the test data. The 234 rows of this file represent the 234 class columns in the submission file. primary_label specifies the submission file column name.

recording_location.txt - Some high-level information on the recording location (Pantanal, Brazil).