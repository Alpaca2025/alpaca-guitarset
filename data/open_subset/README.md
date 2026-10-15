# Open subset (CC-BY-4.0)

Original compositions owned by the dataset authors. Each song ships its
Guitar Pro source (`.gp`), exported MusicXML, rendered 44.1 kHz / 24-bit
audio stems (one WAV per track, as exported from Guitar Pro) and the
GM-token serialized records produced by `pipeline/ser_musicxml_to_gmtoken.py`
(`<name>_<track>_<tempo>.txt`, one per recognized-timbre part).

| song          | corpus section | note                                        |
|---------------|----------------|---------------------------------------------|
| blur_of_life  | 70             | in-corpus; see `metadata.csv` row           |
| starlight     | --             | open bonus; NOT part of the corpus counts   |
| tec           | --             | all-40-technique demo; NOT in the corpus    |
|               |                | (the in-corpus supplement is section 101)   |

## Attribution (required by CC-BY-4.0)

Credit: "AlpacaGuitarSet open subset (anonymous submission, AMIW 2026)".
Update to the author list at camera-ready. Link to the license:
https://creativecommons.org/licenses/by/4.0/ . Indicate if changes were
made (the WAV stems and records are rendered/derived from the scores).

## How to fill this directory (for the dataset authors)

For each song, copy the material into the matching sub-folders BEFORE
pushing the repository, and scrub identifying metadata first:

    blur_of_life/score/    blur_of_life.gp, blur_of_life.xml
    blur_of_life/audio/    the per-track WAV stems exported from Guitar Pro
    blur_of_life/gmtoken/  records from
                           python pipeline/ser_musicxml_to_gmtoken.py blur_of_life.xml
                           (regenerate with the final script; do not reuse
                           earlier-format txts)

Scrubbing (anonymity): Guitar Pro files store File Properties (title /
artist / composer / copyright) -- clear them in Guitar Pro. WAV files may
carry RIFF INFO tags (artist, comments, copyright) -- inspect with
`exiftool file.wav` and strip with `exiftool -all= file.wav` if present.
Check for hidden files (.DS_Store etc.); .gitignore already excludes them.
