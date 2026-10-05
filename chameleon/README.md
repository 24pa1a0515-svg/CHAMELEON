# Project CHAMELEON

CHAMELEON reflows a design document to a new canvas size while preserving its
elements and visual intent. It does more than scale the source as a single
image: the engine analyzes geometry, text styling, and declared groups, then
adapts the layout to the target aspect ratio.

The repository supports two interfaces to the same engine:

- The official local/Docker pipeline reads task JSON files, calls
  `engine.resize.resize()`, checks the result, and renders a PNG preview.
- The Vercel API accepts one task over HTTP and returns the resized design as
  JSON. It also calls `engine.resize.resize()`; it is not a separate layout
  implementation.

## Reflow behavior

The deterministic engine infers content roles from element properties rather
than sample IDs. It keeps declared groups together, preserves element IDs and
count, text content and font families, and image proportions. It adapts text
boxes and font sizes as needed, reflows content for portrait and landscape
layouts, and keeps output geometry within the requested canvas. Supplied image
assets are repositioned/resized, never regenerated or replaced.

The official renderer uses the supplied assets and fonts to produce local PNG
previews. The engine does not substitute placeholder images when rendering
fails.

## Install and run locally

Use Python 3.11 or newer, then install the project dependencies:

```bash
python3 -m pip install -r requirements.txt
python3 -m engine.main
```

The command reads every task in `input/*.json` and writes a resized JSON file
and rendered PNG to `output/` for each task. The three supplied tasks cover the
Warm-up, Core, and Advanced challenge levels. Invalid tasks are reported
without preventing other tasks from running; the process exits nonzero if any
task fails.

Each task has this shape:

```json
{
  "source": {
    "canvas": { "width": 1200, "height": 1200 },
    "elements": [
      {
        "id": "headline",
        "type": "text",
        "x": 40,
        "y": 40,
        "width": 1120,
        "height": 140,
        "content": "A headline",
        "font_family": "Example Sans",
        "font_size": 48,
        "color": "rgba(0,0,0,1)"
      }
    ]
  },
  "target_canvas": { "width": 1080, "height": 1920 }
}
```

The local self-check catches structural errors such as changed IDs, missing
fields, off-canvas geometry, or changed image proportions. It is a sanity
check, not the official challenge scorer; see `RULES.md` for evaluation
details. The API validates both its incoming design and resized result against
the bundled schema.

## Docker

Build and run the official offline pipeline from the repository root:

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v "$(pwd)/input:/app/input" \
  -v "$(pwd)/output:/app/output" \
  my-chameleon-engine
```

The image installs dependencies at build time, then processes mounted input
tasks without network access.

## Vercel API

The root `app.py` exports a FastAPI application named `app`, which Vercel's
Python runtime detects automatically. `vercel.json` excludes local renderer
assets, sample inputs/outputs, and documentation from the API bundle while
retaining the design schema and engine. No environment variables or secrets
are required.

`POST /api/resize` accepts the same task format shown above with
`Content-Type: application/json`. It validates the source design and target
canvas against the CHAMELEON schema, calls the real engine, checks the result,
and returns the resized design as JSON. It does not render a PNG.

`GET /health` returns `{"status":"ok"}`. The API limits requests to 4 MB and
designs to 5,000 elements. It returns safe HTTP errors for malformed JSON
(400), unsupported content types (415), oversized requests (413), invalid
designs or canvases (422), and unexpected processing failures (500). It does
not expose source code, stack traces, or internal paths; interactive API docs
are disabled.

To test the API locally with Vercel's development server:

```bash
vercel dev
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  --data-binary @input/chameleon_sample_level1_warmup.json \
  http://localhost:3000/api/resize
```

To deploy, import this repository into Vercel with the repository root as the
project root, or link it with the Vercel CLI and run:

```bash
vercel link
vercel deploy --prod
```
