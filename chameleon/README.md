# CHAMELEON — starter repo

This is the scaffolding for your engine. It handles input loading, output
writing, rendering, and Docker packaging — so the only file you need to
edit is **`engine/resize.py`**.

```
input:  a task JSON (source design + target canvas)
              |
              v
        engine/resize.py   <-- YOU IMPLEMENT THIS
              |
              v
output: <task>_output.json  (schema-valid resized design)
        <task>_output.png   (rendered preview)
```

Both the JSON and the PNG are what get evaluated — see `RULES.md`.

## Repo layout

```
engine/
  resize.py        <- implement your approach here
  main.py           <- orchestrator (input -> resize() -> output). Don't need to edit this.
renderer/           <- the real renderer (transformer-convertor + cr-renderer), already vendored
brand_kit/
  assets/           <- image files referenced by asset_id in the sample designs
  fonts/            <- font files matching the schema's font_family values
input/               <- drop task JSON files here for local testing (3 samples included)
output/              <- results land here
chameleon_design_schema_v0.9.json   <- full field-by-field spec for the design format
Dockerfile
RULES.md
```

## Quick start (no Docker needed for iterating on `resize()`)

```bash
pip install -r requirements.txt
python -m engine.main
```

This processes every `*.json` file in `input/` (the 3 sample designs are
already there — one per difficulty level) and writes an `_output.json` and
`_output.png` for each into `output/`.

`engine/resize.py` infers visual roles from element type, geometry, text
styling, and group membership. It keeps declared groups together, preserves
full-bleed backgrounds and image proportions, and reflows foreground content
into horizontal or vertical bands when the target aspect ratio changes
substantially. Text boxes and font sizes are fitted to their new slots without
rewriting copy or changing font families.

Run the engine with `python -m engine.main`. It reads each task from `input/`
and writes a schema-shaped JSON result and rendered PNG into `output/`.

## What the self-check does (and doesn't do)

`main.py` runs a quick structural check after every task — same element
`id`s as the source, required fields present, nothing off-canvas. **This
is not the official scorer.** It exists to catch obvious mistakes before
you waste a submission on them. See `RULES.md` for what's actually
checked and graded.

Output files are written only when the checks pass. Invalid task files are
reported and skipped while the remaining tasks continue; the command exits
non-zero if any task fails.

## The renderer

`main.py` calls `renderer/converter/convert.py`'s `render_design_to_png()`
(a vendored copy of `transformer-convertor`, wrapping `cr-renderer`) to
produce each task's PNG — already wired in, no setup needed. It reads
fonts/assets from `brand_kit/` and writes a real rendered preview. If the
renderer or its dependencies are unavailable, that task is reported as
failed; the engine does not substitute a placeholder image.

## Docker (how you'll actually be run)

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  my-chameleon-engine
```

`--network none` matches how stage-one scoring runs: everything your
engine needs must be installed at **build** time (add it to
`requirements.txt`), not fetched at run time. If you're using a locally
hosted model, bake its weights into the image during the build step.

## See also

- `chameleon_design_schema_v0.9.json` — full input/output field spec
- `RULES.md` — what's checked, what's graded, and what disqualifies a submission
- FAQ — for anything not covered above
