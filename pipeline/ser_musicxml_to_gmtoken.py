#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MusicXML -> GM-token serialized records (annotation step + codec).

Converter for the GM-token / AlpacaGuitarSet release (anonymous submission,
AMIW 2026). It converts single-part and multi-part Guitar Pro MusicXML files
into per-track GM-token serialized records by deterministic rules, and hosts
the codec between the canonical five-tuple and its serialized form.

Design (three layers, Sec. 2 of the paper)
------------------------------------------
* Definition layer: the concept GM = <P, A, eps, theta, omega> (pitch,
  technique, tempo-invariant note type, harmonic indicator, timbre identity).
* Instantiation layer: the closed guitar-family vocabularies -- 40 technique
  IDs and 5 timbres (see vocab/), plus the E2-E6 / E1-G3 pitch ranges.
* Serialization layer: the implementation -- per-string (P, A) pairs plus the
  shared eps, a compact structure that preserves fretboard topology
  (15 bytes per six-string event instead of 42; 11 for bass).

The serialized record IS the physical form of the instantiated GM-token, so
no separate "gm-token format" is stored: P and A sit in each "pitch-technique"
pair, eps in the "pi-n-d" field, theta is derived from the record (1 if two
or more strings sound), and omega together with the section tempo is encoded
in the output file name. The codec (serialize / parse_record / derive_theta)
is therefore kept in this module next to the extractor; run with --selftest
to verify lossless round-trips against the Sec. 2 example.

Timbre handling
---------------
Each part is classified from ``<midi-program>`` (primary) or
``<part-abbreviation>`` (fallback) into the five timbres of the local
dataset (omega: 0 jazz, 1 nylon, 2 distortion, 3 overdriven, 4 bass; see
``vocab/timbres.json``). Recognized parts are written to
``<name>_<track>_<tempo>.txt`` so that omega and the section tempo remain
recoverable from file names, as stated in the paper. Parts with any other
timbre (e.g. percussion) are skipped; extend ``TIMBRE_BY_PROGRAM`` /
``TIMBRE_BY_ABBR`` to add timbres.

Output format (guitar: 9 columns, bass: 7 columns)
--------------------------------------------------
    start, end,
    (pitch-technique) x N strings (string 1 = highest-pitched),
    note type "pi-n-d"

The record body (pairs + note type) equals the string-parallel
serialization of Sec. 2; start/end are prepended for frame-level use.
Rows look like::

    0.0 0.5 65-0 0-0 0-0 0-0 0-0 0-0 09-0-0

Conventions
-----------
* ``start``/``end`` are offsets in seconds; the tempo-invariant note type
  plus the section tempo (file name) recover absolute durations
  (proportional audio/score slicing, Sec. 4 of the paper).
* Pitches are sounding MIDI pitches; 0 marks an inactive string, all-zero
  pairs a rest. Technique IDs are the 40 closed guitar-family IDs
  (``vocab/techniques.json``, Table A.2 of the paper), shared by guitar
  and bass.
* Note type eps = <pi, n, d>: pi selects a base value from the 14-level
  hierarchy (``vocab/note_types.json``, Table A.1), (n, d) is the tuplet
  ratio ("n in the time of d", printed as 0-0 when absent).
* The harmonic indicator theta is NOT stored in the record; derive it with
  derive_theta() (1 if two or more strings sound, 0 otherwise).
* Adjacent rests are merged only when the merged duration is exactly
  representable in the 14-level hierarchy; longer rests (e.g. several whole
  rests) are kept as separate events, since eps cannot encode them.
* Artificial harmonics are exported at their sounding pitch (the
  ``sounding-pitch`` marker note overwrites the base-pitch string).

Usage:
    python ser_musicxml_to_gmtoken.py [<file.xml>] [--outdir DIR]
    python ser_musicxml_to_gmtoken.py --selftest
Without arguments the script prompts for the file name (interactive mode).
Output files are written to DIR (default: current working directory).
"""

import argparse
import os
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- constants

STEP_TO_SEMITONE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

# <type> element -> duration in beats (beat = 60 / tempo)
TYPE_TO_BEATS = {'whole': 4.0, 'half': 2.0, 'quarter': 1.0, 'eighth': 0.5,
                 '16th': 0.25, '32nd': 0.125, '64th': 0.0625}
# <type> element -> pi code (add 1 for dotted values, Table A.1)
TYPE_TO_PI = {'whole': 13, 'half': 11, 'quarter': 9, 'eighth': 7,
              '16th': 5, '32nd': 3, '64th': 1}

# merged duration on a 64th-note grid (during / beat * 64) -> pi code;
# the grid is the exact set of durations representable in Table A.1
GRID_TO_PI = {256: 13, 384: 14,   # whole, dotted whole
              128: 11, 192: 12,   # half, dotted half
              64: 9, 96: 10,      # quarter, dotted quarter
              32: 7, 48: 8,       # eighth, dotted eighth
              16: 5, 24: 6,       # 16th, dotted 16th
              8: 3, 12: 4,        # 32nd, dotted 32nd
              4: 1, 6: 2}         # 64th, dotted 64th

TRILL_STEP_TO_ID = {'unison': 6, 'half': 7, 'whole': 8}
ARTICULATION_TO_ID = {'accent': 3, 'staccato': 4, 'scoop': 23, 'plop': 24,
                      'falloff': 25, 'doit': 26}

# reference pitch ranges (paper): guitar E2-E6 = MIDI 40-88, bass E1-G3 = 28-55
PITCH_RANGE = {6: (40, 88, 'guitar E2-E6'), 4: (28, 55, 'bass E1-G3')}

# Local timbre vocabulary: GM midi-program -> (canonical track tag, omega).
# Omega order matches vocab/timbres.json (0 jazz, 1 nylon, 2 distortion,
# 3 overdriven, 4 bass).
TIMBRE_BY_PROGRAM = {
    27: ('jz.guit', 0),    # jazz guitar
    25: ('n.guit', 1),     # nylon guitar
    31: ('dist.guit', 2),  # distortion guitar
    30: ('od.guit', 3),    # overdriven guitar
    33: ('a.bs', 4),       # acoustic bass
    36: ('fl.bs', 4),      # fretless bass (bass family, omega = 4)
}
# part-abbreviation (lowercase, trailing dot stripped) -> omega;
# fallback when midi-program is missing or unrecognized
TIMBRE_BY_ABBR = {
    'jz.guit': 0, 'j.guit': 0, 'jazz.guit': 0,
    'n.guit': 1, 'nylon.guit': 1,
    'dist.guit': 2, 'dist.g': 2,
    'od.guit': 3, 'overd.guit': 3,
    'a.bs': 4, 'ac.bs': 4, 'fl.bs': 4, 'bs': 4, 'bass': 4,
}


def _findtext(el, path):
    x = el.find(path)
    return x.text if x is not None else None


# ------------------------------------------------------------------- codec
# Canonical five-tuple <-> serialized record (Sec. 2, serialization layer).
# The record stores per-string (P, A) pairs plus the shared eps; theta is
# derived and omega is track-level metadata (file name).

def serialize(strings, epsilon):
    """Serialize per-string (P, A) pairs plus shared eps = (pi, n, d).

    strings: list of (pitch, technique), string 1 (highest-pitched) first;
    inactive strings are (0, 0). epsilon: (pi, n, d) note-type triple.
    Returns the record string.
    """
    pairs = ' '.join('{}-{}'.format(p, t) for p, t in strings)
    pi, n, d = epsilon
    return '{} {:02d}-{}-{}'.format(pairs, pi, n, d)


def parse_record(record):
    """Inverse of serialize(); returns (strings, epsilon)."""
    fields = record.split()
    strings = [tuple(int(x) for x in pair.split('-')) for pair in fields[:-1]]
    pi, n, d = (int(x) for x in fields[-1].split('-'))
    return strings, (pi, n, d)


def derive_theta(strings):
    """Harmonic indicator: 1 if two or more strings sound, else 0."""
    return 1 if sum(1 for p, _ in strings if p > 0) >= 2 else 0


def to_canonical(strings, epsilon, omega):
    """Assemble the full five-tuple from a record plus track-level omega."""
    return {'P': [p for p, _ in strings],
            'A': [a for _, a in strings],
            'eps': epsilon, 'theta': derive_theta(strings), 'omega': omega}


def selftest():
    """Lossless round-trip checks, including the Sec. 2 example."""
    demo = [(55, 19)] + [(0, 0)] * 5
    rec = serialize(demo, (7, 3, 2))
    assert rec == '55-19 0-0 0-0 0-0 0-0 0-0 07-3-2', rec
    assert parse_record(rec) == (demo, (7, 3, 2))
    assert derive_theta(demo) == 0
    chord = [(64, 0), (60, 0), (55, 0), (52, 0), (48, 0), (0, 0)]
    assert derive_theta(chord) == 1
    assert parse_record(serialize(chord, (9, 0, 0))) == (chord, (9, 0, 0))
    print('selftest OK:', rec)


# ------------------------------------------------------------ timbre lookup

def read_part_info(root):
    """Read <part-list> into {part_id: {'name', 'abbr', 'program'}}."""
    info = {}
    for sp in root.findall('./part-list/score-part'):
        mi = sp.find('midi-instrument')
        prog = mi.findtext('midi-program') if mi is not None else None
        info[sp.get('id')] = {
            'name': sp.findtext('part-name') or '',
            'abbr': (sp.findtext('part-abbreviation') or '').strip(),
            'program': int(prog) if prog else None,
        }
    return info


def detect_timbre(meta):
    """Classify a part into the local timbre vocabulary.

    Returns (track_tag, omega); (None, None) when unrecognized (the caller
    skips the part, leaving room for vocabulary extension). The track tag is
    the file's own part-abbreviation (canonical tag as fallback) so that
    omega stays recoverable from output file names.
    """
    prog = meta.get('program')
    if prog in TIMBRE_BY_PROGRAM:
        canon, omega = TIMBRE_BY_PROGRAM[prog]
        track = meta['abbr'].rstrip('.').strip() or canon
        return track, omega
    abbr = meta['abbr'].lower().rstrip('.').strip()
    if abbr in TIMBRE_BY_ABBR:
        return meta['abbr'].rstrip('.').strip(), TIMBRE_BY_ABBR[abbr]
    return None, None


def find_tempo(part):
    """Read the tempo from a part's direction/sound elements (None if absent)."""
    for d in part.iter('direction'):
        s = d.find('sound')
        if s is not None and s.get('tempo'):
            return int(float(s.get('tempo')))
    return None


# ------------------------------------------------------------------ parsing

def parse_note(el):
    """Parse one <note> element into an intermediate dict (no technique ID)."""
    n = {'rest': el.find('rest') is not None,
         'chord': el.find('chord') is not None,
         'grace': el.find('grace') is not None,
         'tie': None, 'mute': None, 'slide': None,
         'trill': None, 'tremolo': None,
         'articulations': [], 'tap': False,
         'hammer': None, 'harmonic': None, 'bend_alter': None,
         'string': None, 'dot': el.find('dot') is not None,
         'type': None, 'beats': 1.0, 'actual': 1, 'normal': 1, 'pitch': None}

    tie = el.find('tie')
    if tie is not None:
        n['tie'] = tie.get('type')
    play = el.find('play')
    if play is not None and play.find('mute') is not None:
        n['mute'] = play.find('mute').text
    type_text = _findtext(el, 'type')
    if type_text in TYPE_TO_BEATS:
        n['type'] = type_text
        n['beats'] = TYPE_TO_BEATS[type_text]
    tm = el.find('time-modification')
    if tm is not None:
        n['actual'] = int(tm.findtext('actual-notes'))
        n['normal'] = int(tm.findtext('normal-notes'))
    pitch_el = el.find('pitch')
    if pitch_el is not None:
        step = pitch_el.findtext('step')
        octave = int(pitch_el.findtext('octave'))
        alter = int(pitch_el.findtext('alter') or 0)
        n['pitch'] = 12 * (octave + 1) + STEP_TO_SEMITONE[step] + alter

    notations = el.find('notations')
    if notations is None:
        return n
    slide = notations.find('slide')
    if slide is not None:
        n['slide'] = slide.get('type')
    ornaments = notations.find('ornaments')
    if ornaments is not None:
        trill = ornaments.find('trill-mark')
        if trill is not None:
            n['trill'] = trill.get('trill-step') or 'unison'
        tremolo = ornaments.find('tremolo')
        if tremolo is not None and tremolo.text:
            n['tremolo'] = int(tremolo.text)
    articulations = notations.find('articulations')
    if articulations is not None:
        for art in articulations:
            if art.tag in ARTICULATION_TO_ID:
                n['articulations'].append(art.tag)
    technical = notations.find('technical')
    if technical is not None:
        s = technical.findtext('string')
        if s is not None:
            n['string'] = int(s)
        if technical.find('tap') is not None:
            n['tap'] = True
        # legato-passing notes carry both start and stop hammer-on marks;
        # the last mark wins, matching the corpus convention
        hammers = technical.findall('hammer-on')
        if hammers:
            n['hammer'] = hammers[-1].get('type')
        harmonic = technical.find('harmonic')
        if harmonic is not None:
            if harmonic.find('natural') is not None:
                n['harmonic'] = ('natural', None)
            elif harmonic.find('artificial') is not None:
                # Guitar Pro exports three marker notes: base-pitch,
                # touching-pitch and sounding-pitch
                kind = 'base'
                for tag, name in (('base-pitch', 'base'),
                                  ('touching-pitch', 'touching'),
                                  ('sounding-pitch', 'sounding')):
                    if harmonic.find(tag) is not None:
                        kind = name
                n['harmonic'] = ('artificial', kind)
        # multiple <bend> elements may appear (e.g. bend + release);
        # the last one determines the ID, as in the original extraction
        bends = technical.findall('bend')
        if bends:
            n['bend_alter'] = int(float(bends[-1].findtext('bend-alter') or 0))
    return n


def resolve_technique(n, fade=None):
    """Resolve the technique ID for a note; later detections override earlier
    ones (priority low -> high): fade < tie < grace < mute < slide < trill <
    tremolo picking < articulation < tap < hammer-on < harmonic < bend."""
    tech = fade or 0                     # 17 fade in / 18 fade out (lowest)
    if n['tie'] == 'start':
        tech = 12                        # tied note start
    elif n['tie'] == 'stop':
        tech = 13                        # tied note end
    if n['grace']:
        tech = 14                        # embellishing (grace) note
    if n['mute'] == 'palm':
        tech = 15                        # palm mute
    elif n['mute'] == 'straight':
        tech = 16                        # dead note
    if n['slide'] == 'start':
        tech = 21                        # slide start
    elif n['slide'] == 'stop':
        tech = 22                        # slide end
    if n['trill'] is not None:
        tech = TRILL_STEP_TO_ID[n['trill']]      # 6-8 trill
    if n['tremolo'] is not None:
        tech = 8 + n['tremolo']                  # 9-11 tremolo picking
    for art in n['articulations']:
        tech = ARTICULATION_TO_ID[art]           # 3, 4, 23-26
    if n['tap']:
        tech = 2                         # right-hand tap
    if n['hammer'] == 'start':
        tech = 19                        # hammer-on
    elif n['hammer'] == 'stop':
        tech = 20                        # pull-off
    if n['harmonic'] is not None:
        tech = 1 if n['harmonic'][0] == 'natural' else 5   # harmonics
    if n['bend_alter'] is not None:
        tech = 27 + 2 * n['bend_alter']  # 27 pre-bend & release; 28-39 bends
    return tech


# ------------------------------------------------------------------- events

class Event(object):
    """One serialized record: per-string (P, A) slots plus shared epsilon."""

    __slots__ = ('start', 'during', 'pitches', 'tecs', 'pi', 'actual',
                 'normal', 'is_rest', 'ah_sounding')

    def __init__(self, start, n_strings):
        self.start = start
        self.during = 0.0
        self.pitches = [0] * n_strings
        self.tecs = [0] * n_strings
        self.pi = 9
        self.actual = 1
        self.normal = 1
        self.is_rest = True
        self.ah_sounding = None  # artificial-harmonic sounding pitch


def add_note_to_event(ev, n, tech, n_strings):
    """Write a note into the event's string slots. Artificial-harmonic marker
    notes (touching/sounding) have no <string> element and only contribute
    their sounding pitch."""
    if n['rest']:
        return
    ev.is_rest = False
    if n['string'] is None:
        if n['harmonic'] and n['harmonic'][0] == 'artificial' \
                and n['harmonic'][1] == 'sounding':
            ev.ah_sounding = n['pitch']
        return
    i = n['string'] - 1
    if not 0 <= i < n_strings:
        print('  [warn] string {} out of range for {} strings; note ignored'
              .format(n['string'], n_strings))
        return
    if ev.pitches[i] == 0:               # keep the first note on a string
        ev.pitches[i] = n['pitch'] or 0
        ev.tecs[i] = tech


def finalize_event(ev):
    """Overwrite the base-pitch string of an artificial harmonic with its
    sounding pitch (GM-token records sounding pitch)."""
    if ev.ah_sounding is None:
        return
    for i, t in enumerate(ev.tecs):
        if t == 5:
            ev.pitches[i] = ev.ah_sounding
            return


def pi_from_during(during, beat):
    """Map a duration to its pi code on the 64th-note grid; None when the
    duration is not exactly representable in the 14-level hierarchy."""
    grid = round(during / beat * 64)
    return GRID_TO_PI.get(grid)


# ------------------------------------------------------------- track export

def build_rows(part, n_strings, beat):
    """Convert one <part> to a list of output rows."""
    events, cur, clock, pending_fade = [], None, 0.0, None
    for measure in part.findall('measure'):
        for el in measure:
            if el.tag == 'direction':
                # fade in/out are note-level direction marks: they apply to
                # the first note that follows the mark
                if el.get('placement') == 'below':
                    words = _findtext(el, 'direction-type/words') or ''
                    if 'Fade in' in words:
                        pending_fade = 17
                    elif 'Fade out' in words:
                        pending_fade = 18
                continue
            if el.tag != 'note':
                continue
            n = parse_note(el)
            during = beat * n['beats']
            if n['dot']:
                during *= 1.5
            during *= n['normal'] / n['actual']
            if not n['chord']:
                cur = Event(clock, n_strings)
                cur.during = during
                cur.pi = TYPE_TO_PI.get(n['type'], 9) + (1 if n['dot'] else 0)
                cur.actual, cur.normal = n['actual'], n['normal']
                events.append(cur)
                clock += during
                tech = resolve_technique(n, pending_fade)
                pending_fade = None
            else:
                tech = resolve_technique(n)
            add_note_to_event(cur, n, tech, n_strings)
    for ev in events:
        finalize_event(ev)

    # merge adjacent rests only when the merged duration is exactly
    # representable in the 14-level hierarchy; longer rests (e.g. several
    # whole rests) exceed the hierarchy and are kept as separate events
    merged = []
    for ev in events:
        if (merged and ev.is_rest and merged[-1].is_rest
                and abs(merged[-1].start + merged[-1].during - ev.start) < 1e-6):
            cand = merged[-1].during + ev.during
            pi = pi_from_during(cand, beat)
            if pi is not None:
                merged[-1].during = cand
                merged[-1].pi = pi
                continue
        merged.append(ev)

    lo, hi, rname = PITCH_RANGE.get(n_strings, (0, 127, ''))
    out_of_range = set()
    rows = []
    for ev in merged:
        nt = '{:02d}-{}-{}'.format(ev.pi,
                                   ev.actual if ev.actual != 1 else 0,
                                   ev.normal if ev.normal != 1 else 0)
        row = [str(ev.start), str(ev.start + ev.during)]
        row += ['{}-{}'.format(p, t) for p, t in zip(ev.pitches, ev.tecs)]
        row += [nt]                     # theta is not stored; use derive_theta()
        for p in ev.pitches:
            if p and not lo <= p <= hi:
                out_of_range.add(p)
        rows.append(' '.join(row))
    return rows, out_of_range, rname


def convert_part(part, meta, speed, outdir):
    """Convert one recognized part and write <stem>_<track>_<tempo>.txt."""
    stem, track, omega = meta['stem'], meta['track'], meta['omega']
    n_strings = int(_findtext(part, './measure/attributes/staff-details/'
                              'staff-lines') or 6)
    beat = 60.0 / speed
    rows, out_of_range, rname = build_rows(part, n_strings, beat)
    if out_of_range:
        print('  [warn] {} pitch(es) outside {}: {}'
              .format(len(out_of_range), rname, sorted(out_of_range)))
    out_path = os.path.join(outdir, '{}_{}_{}.txt'.format(stem, track, speed))
    with open(out_path, 'w') as f:
        f.write('\n'.join(rows) + '\n')
    print('  [ok] part {} "{}" -> {} (omega={}, strings={}, tempo={}, events={})'
          .format(part.get('id'), meta['name'] or track, os.path.basename(out_path),
                  omega, n_strings, speed, len(rows)))
    return out_path


# -------------------------------------------------------------------- driver

def convert(path, outdir=None):
    """Convert a score: one txt per recognized-timbre part, others skipped."""
    root = ET.parse(path).getroot()
    parts = root.findall('part')
    if not parts:
        raise ValueError('no <part> element found: {}'.format(path))
    infos = read_part_info(root)
    stem = os.path.splitext(os.path.basename(path))[0]
    if outdir is None:
        outdir = os.getcwd()
    os.makedirs(outdir, exist_ok=True)

    # multi-part scores usually mark the tempo in the first part only;
    # it serves as fallback for parts without their own tempo mark
    global_speed = None
    for p in parts:
        t = find_tempo(p)
        if t:
            global_speed = t
            break

    outputs = []
    for part in parts:
        info = infos.get(part.get('id'), {'name': '', 'abbr': '', 'program': None})
        track, omega = detect_timbre(info)
        if track is None:
            label = info['abbr'] or info['name'] or part.get('id')
            print('  [skip] part {} "{}": unrecognized timbre (reserved for '
                  'vocabulary extension)'.format(part.get('id'), label))
            continue
        meta = {'stem': stem, 'track': track, 'omega': omega,
                'name': info['name']}
        speed = find_tempo(part) or global_speed or 120
        outputs.append(convert_part(part, meta, speed, outdir))

    if not outputs:
        print('  [warn] nothing to convert (all parts skipped or empty)')
    return outputs


def main():
    ap = argparse.ArgumentParser(
        description='Convert Guitar Pro MusicXML to GM-token serialized '
                    'records (one txt per recognized-timbre part).')
    ap.add_argument('xml', nargs='?', default=None,
                    help='input MusicXML file (prompted when omitted)')
    ap.add_argument('--outdir', default=None,
                    help='output directory (default: current working directory)')
    ap.add_argument('--selftest', action='store_true',
                    help='run codec round-trip self-tests and exit')
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    path = args.xml
    if path is None:                     # interactive fallback
        path = input('Input MusicXML file: ').strip()
        if not path.lower().endswith('.xml'):
            path += '.xml'
    convert(path, args.outdir)


if __name__ == '__main__':
    main()
