---
name: transcribe
description: Reading a genealogical record from its image — the act found on a sheet of views, one region per act, a diplomatic and a normalised transcription, the table of persons and the uncertain readings. Use it whenever a record's image must be read (reader role), or a printed page must be OCRed.
---

# Transcribing a record

Call the engine as the `engine` skill says (`--agent reader` for the reader
role). Write the transcription in the record's own language; your notes and
the report prose stay in the research's language.

## 1. The image

An image stays in your context: `TOKENS_EST=` is its cost, read it if worth it,
alone in a message. Never fetch or read a whole view.

1. **Find the act first**: the decennial table or the register's index; then
   a sheet of the top bands of ten views:
   `archive run ad50.sheet --args '{"detail": <d>, "from": 80, "to": 89}'`
   (`iiif.sheet`: `"url"`).
2. **Place the act on the view small** (700 tokens; the next ones if no band
   shows it), never half pages cut to search:
   `ad50.view`, `"view": 84, "size": 900` (IIIF: `iiif.region`, `"width": 900`).
3. **One region per act**: the same call with `"region": "x,y,w,h"` as seen
   on the small view, the act alone cut from the whole view at full size
   (2,500 tokens, 2,576 px at most). IIIF: `"region": "pct:x,y,w,h"`
   (`"rotation": 90`). On disk: `image crop <file> --region x,y,w,h`.
4. Note each doubt as you meet it (§ 2).
5. Views read without the act: a search, logged with `filters: {register,
   views}`, for the negative it proves.
6. A printed page: `transcribe ocr <image> --ocr-lang fra` (`deu`, `frak2021`),
   a draft to check against the image. `REASON=no-tesseract` or `no-pillow`:
   read the image yourself.

## 2. The file

`transcribe template <source id>` writes the skeleton
`evidence/transcriptions/<source>.md` in the family folder. An act read before
its source is proposed: `transcribe new --image <file>` makes the source's id
(`SOURCE=`), the skeleton and the `source=` entry to copy into the proposal;
never make an id yourself. Fill it:

- **Header**: source, image, language, script (cursive, print, gothic…),
  image state (`good`, else what is wrong: seek the register's other copy).
- **Diplomatic transcription**: line by line, as written, with the original
  spelling, abbreviations and punctuation; numbered `1.`, `2.`, … exactly as the
  lines of the record.
- **Normalised transcription**: modern spelling, abbreviations expanded, dates
  written in full and checked with `dates "<text>"` (Latin, Republican and
  Julian dates included).
- **Persons**: one row per person named — role (child, father, mother,
  witness, priest…), as written, normalised form, age, residence or
  occupation, relation, signature (signed, mark, "does not know how to sign").
  A relation the act implies but does not write is marked `(deduced)`.
- **Uncertain readings**: one line per doubt, with its line number and the
  readings you hesitate between: `- line 4: 'Marchant'[?] or 'Marchand'`.
- **Not understood**: what you read but do not understand: `- line 5: 'dlle'`.

### Notation

| Write | For |
|---|---|
| `[…]` | a gap: torn, faded or unreadable |
| `word[?]` | a doubtful reading |
| `{struck: …}` | struck-out text |
| `{margin: …}` | a note in the margin |
| `{blank}` | a space the writer left empty: a clue, not a gap |
| `{above: …}` | added between the lines |
| `{over: a > b}` | `a` written over as `b` |
| `{hand: …}` | another, later hand |
| `{restored: …}` | supposed, not read |

Never guess: an unreadable letter is `[…]`, a doubtful word is `word[?]`;
nothing restored or not understood goes into the normalised text. Read
the image, never an index: a table that disagrees with the act is a doubt,
never the reading.

## 3. Check

`transcribe check <source id> --name "<surname of the person concerned>"`:

- `STATUS=FAIL` lists what is missing or a date `dates` cannot read: fix it
  and check again.
- `doubt=` lines list the `[?]`, the last five marks and what is not understood.
- `UNCERTAIN_READING=` is the text to put in the fact's `uncertain_reading`
  when the doubt touches that person.

Return only the lines your brief asks, 15 at most, a `doubt=` of the check
for each doubt.
