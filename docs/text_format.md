# TXT input format and preview/synthesis rules

VoxBraid only accepts **UTF-8 TXT**, including UTF-8 BOM and Windows line endings.
`preview` creates an **offline plan**. M2 `synthesize` writes separate audio
clips and a manifest, but does not yet compose one audiobook.

## Plain text

```text
Once upon a time, a fox found a little bird.
The forest was quiet.

One day, they went on an adventure.
```

- Plain TXT uses role `narrator` for everything.
- **One or more blank lines** separate paragraphs.
- A newline without a blank line is treated as a wrapped line in the *same*
  paragraph. This helps with lines copied from PDF/OCR, but may require cleanup
  for texts that intentionally use one-line paragraphs.

## Tagged text

```text
# A comment (ignored only in tagged TXT)
[narrator]
The witch came home.

[witch]
“Who gave you this?”

[narrator:tag]
shouts the witch.

[rapunzel]
“The prince,”

[narrator:tag]
says Rapunzel.

[narrator:lead]
Then he calls:

[prince]
“Rapunzel, let down your hair!”
```

- `[role]` is a separate line; names are case insensitive and use letters,
  numbers, `_`, `-`, starting with a letter (`[old_witch]`, `[little-bee]`).
- Any role name is valid; M1 doesn't constrain it to an existing voice list.
  M2 selects a voice for each role using a JSON file (`--voices`).
- `[narrator:tag]` marks attribution, such as `she said.`; `[narrator:lead]`
  marks narration introducing an immediately following quote.
- `:tag` and `:lead` are reserved for `narrator` and help plan short pauses.
- A new `[role]` always begins a new paragraph even without a blank line.
- A role heading must have nonempty content before the next role heading/end.
- Lines beginning with `#` are comments in tagged mode only. They are **spoken
  text** in plain mode; do not put comments into a plain TXT file.
- In tagged mode, text before the first role heading causes a helpful error.
- Malformed standalone bracket headings and unsupported modifiers cause an error,
  rather than being silently read aloud.
- To handle literal headings like `[note]` in ordinary prose, edit the upstream
  TXT so they do not resemble VoxBraid role markers.

## Pauses and precedence

M1's suggested defaults are **not a change to the original Rapunzel MP3**:

| Pause class | Default | When used |
|---|---:|---|
| intro | 3.0 s | Before first segment |
| sentence | 1.5 s | Another sentence inside same paragraph |
| paragraph | 3.0 s | New paragraph, same role |
| speaker | 1.0 s | Different role, ordinary transition |
| attribution | 0.4 s | Around `[narrator:tag]` |
| lead | 0.6 s | After `[narrator:lead]` when a character speaks |

Each segment receives **exactly one** `pause_before`. For a segment following
multiple conceptual boundaries, precedence is: first segment → sentence inside
paragraph → attribution → lead → speaker → paragraph. The values do not add up.

Pause settings can be overridden by CLI flags in `voxbraid preview --help`.

## Sentence splitting and quotes

- M1 uses a deterministic English punctuation heuristic (not an AI model).
- It handles `Mr.`, `Mrs.`, `Dr.`, common abbreviations, decimal numbers, initials,
  curly quotes and consecutive punctuation.
- Quotations followed by clear speech attribution (`“Hello!” she said.`)
  stay one segment in plain narration.
- Balanced outer quotes wrapping a **character's entire paragraph** are
  removed from the actual character segment text, including when the paragraph
  spans multiple sentences.
- It cannot always identify sentence boundaries correctly in malformed OCR,
  poetry, initials, unfamiliar abbreviations, or complex nested dialogue.
- It never decides which character is speaking; speakers must be tagged upstream.

## Source locations and machine-readable output

`voxbraid preview` reports the original TXT line numbers (`L6`, `L6-7`), role,
paragraph index, pause type and seconds. `--json` emits the same segment data.
No TTS engine, credentials, internet, model download or audio tool is required.

## M2 voice selection

The role names `[narrator]`, `[witch]`, etc. are mapped independently in a
JSON file, for example:

```json
{
  "narrator": {"provider":"edge", "voice":"en-US-BrianNeural", "options":{"rate":"-10%"}},
  "witch": {"provider":"edge", "voice":"en-US-EmmaNeural", "options":{"rate":"-10%"}}
}
```

If no voice file is supplied, only `narrator` has a default (Brian, -10%).
A missing non-narrator role is an error, not an implicit narrator fallback.
Pause metadata in the manifest is **planned only**; actual silence is M4.
