# SCADA Digital-Twin Security — Presentation

`presentation.pptx` — a 19-slide, editable PowerPoint with **real native slide
transitions and entrance animations**, custom diagrams, live screenshots, a
native chart, an editable table, and speaker notes on every slide.

## Open / present
- Open `presentation.pptx` in PowerPoint (2016+). Press **F5** to present.
- Each content slide has a one-click build: the headline/frame is shown, then
  the content elements fade in, staggered, on a single click.
- `preview.pdf` is a static render of every slide (no animation).

## Design
- Direction: "cinematic control-room editorial" — near-black canvas, one hot
  orange accent (`F0592A`), a steel-blue for data (`54B2C9`); Cambria display
  serif + Arial; generous negative space; a consistent mono top-frame/index.
- Backgrounds in `assets/bg_*.png` were generated with PIL (vignette + glow +
  faint grid). The four live screenshots are real captures of the running platform.

## Animations (verified in the OOXML)
- `<p:transition>` (fade) on all 19 slides; `<p:timing>` entrance builds on 15
  content slides; 97 `<p:animEffect transition="in" filter="fade">` entrances.
- Verified by: XML inspection, the pptx schema validator ("All validations PASSED"),
  and opening/exporting in PowerPoint via COM (opened without error).

## Regenerate
```bash
cd deck
npm install pptxgenjs              # first time only
node make_deck.js presentation_raw.pptx           # layout + content
python ..\path\to\animate.py presentation_raw.pptx presentation.pptx   # inject transitions + animations
```
`make_deck.js` lays out the editable slides; `animate.py` injects the native
transitions and entrance animations into the slide XML.

## Files
- `presentation.pptx` — the deck (editable, animated)
- `preview.pdf` — static preview of all 19 slides
- `assets/` — backgrounds (PIL) + the 4 live screenshots
- `make_deck.js`, `animate.py` — the source that generates the deck
