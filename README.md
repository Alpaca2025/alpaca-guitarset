# GM-Token and AlpacaGuitarSet (anonymous submission, AMIW 2026)

Data-pipeline code and vocabularies for the GM-token representation and the
AlpacaGuitarSet corpus. The full corpus is distributed under a research-use
agreement; see `data/ACCESS.md` for the copyright-tiered release scheme
(the `data/open_subset/` directory is CC-BY-4.0).

## Design

GM-token has three layers (Sec. 2 of the paper): the definition layer (the
five-tuple <P, A, eps, theta, omega>), the instantiation layer (closed
guitar-family vocabularies: 40 technique IDs, 5 timbres, pitch ranges), and
the serialization layer (per-string (P, A) pairs plus shared eps). The
serialized record is the physical form of the instantiated GM-token: P and A
sit in each "pitch-technique" pair, eps in the "pi-n-d" field, theta is
derived from the record (1 if two or more strings sound), and omega together
with the section tempo is encoded in the output file name. The codec
(serialize / parse_record / derive_theta) therefore lives in the same module
as the MusicXML extractor, since both operate on the same record.

## Layout

    pipeline/   ser_musicxml_to_gmtoken.py: MusicXML -> per-track serialized
                records (deterministic annotation extraction, Sec. 3) plus
                the five-tuple <-> record codec with lossless round-trips
    vocab/      source of truth for the closed vocabularies: technique IDs
                (Table A.2), note-type hierarchy (Table A.1), timbres
    data/       metadata.csv, ACCESS.md, open_subset/ (CC-BY-4.0)

## Quick start

    # score -> per-track serialized records
    python pipeline/ser_musicxml_to_gmtoken.py score.xml
    # -> <name>_<track>_<tempo>.txt  (omega + tempo recoverable from
    #    the file name, as stated in the paper)

    # codec round-trip self-test (prints the Sec. 2 example)
    python pipeline/ser_musicxml_to_gmtoken.py --selftest

## Record format

Each line of a track txt holds: start, end (seconds), one "pitch-technique"
pair per string (string 1 = highest-pitched), and the note type "pi-n-d".
0 marks an inactive string; all-zero pairs mark a rest. The record body is
the string-parallel serialization of Sec. 2; the harmonic indicator theta is
not stored -- derive it with derive_theta() (1 if two or more strings
sound). Absolute durations follow from the tempo-invariant note type and the
section tempo (file name).
