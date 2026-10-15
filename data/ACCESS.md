# Access and licensing

The release is copyright-tiered:

1. **Open subset** (`open_subset/`, CC-BY-4.0): original compositions owned
   by the dataset authors, released with full production material
   (Guitar Pro source, MusicXML score, rendered 44.1 kHz / 24-bit audio
   stems and the GM-token serialized records). See `open_subset/README.md`
   for the attribution line.
2. **Metadata** (`metadata.csv`): complete track-level metadata for all 111
   sections (213 guitar + 96 bass tracks), including section tempo,
   duration, timbre (omega), tuning notes and the release tier per track.
3. **Full corpus**: the remaining sections re-render commercial repertoire
   and are distributed under a research-use agreement. During anonymous
   review, request access through the OpenReview submission page; author
   contact details replace the anonymous link at camera-ready.

Arrangements: a few sections were originally performed on extended-range
or alternatively tuned instruments (5-string bass in sections 49, 61, 77,
84, 97; 7-string guitar in section 87; half-step-down tuning in several
sections). For corpus consistency all tracks are arranged and annotated for
standard six-string guitar (E2-E6) and four-string bass (E1-G3); following
Sec. 2 of the paper the annotations record sounding pitch, so melodies are
unchanged and only fingering differs.

Timbre codes follow `vocab/timbres.json`: omega 0 jazz, 1 nylon,
2 distortion, 3 overdriven, 4 bass. `release` marks the CC-BY-4.0 open
tracks (`open`) versus the research-use tracks (`research`).
