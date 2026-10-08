# CHAMELEON — Automatic Design Reflow Engine

Project CHAMELEON is an intelligent graphic design reflow engine that receives a source design JSON and a target canvas size, automatically rearranging and reflowing elements to produce a schema-valid layout for the new canvas shape.

Rather than naive stretching or uniform scaling, CHAMELEON preserves visual hierarchy, text legibility, element grouping, brand assets, and image aspect ratios.

The project features a **project-local schema** (`chameleon_design_schema_v0.9.json`) and **generic generated test fixtures** in `input/` covering multiple aspect ratios.

The repository supports **both**:
1. **The CHAMELEON local/Docker evaluation pipeline** (`python3 -m engine.main`).
2. **A working Vercel deployment/API** (`app.py` serverless entrypoint).

---

## Required Structure

```text
CHAMELEON/
├── app.py                           <- Vercel Flask API entrypoint exposing engine.resize.resize()
├── vercel.json                      <- Vercel deployment configuration
├── Dockerfile                       <- Container build spec for evaluation
├── README.md                        <- Project overview and guide
├── RULES.md                         <- Challenge rules and scoring specification
├── requirements.txt                 <- Python dependencies (Pillow, Flask, cr-renderer, jsonschema)
├── chameleon_design_schema_v0.9.json<- Project-local JSON schema spec
│
├── engine/
│   ├── main.py                      <- Local evaluation orchestrator
│   └── resize.py                    <- Core intelligent design reflow algorithm
│
├── brand_kit/
│   ├── assets/                      <- Image assets referenced by asset_id / src
│   └── fonts/                       <- Custom brand font files
│
├── input/                           <- Generic generated test fixtures
└── output/                          <- Output JSON and rendered PNG files
```

---

## Resizing Algorithm (`engine/resize.py`)

The resizing algorithm is implemented in `engine/resize.py` with entrypoint:

```python
def resize(source: dict, target_canvas: dict) -> dict:
```

The engine operates via a deterministic multi-step pipeline:

1. **Property Normalization & Role Classification**:
   - Supports both `snake_case` (`content`, `font_family`, `font_size`, `asset_id`, `fill_color`, `group_id`, `z_index`) and `camelCase` (`text`, `fontFamily`, `fontSize`, `src`, `fill`, `group`, `zIndex`).
   - Analyzes element dimensions, bounding box, z-index, opacity, and text/image/shape properties.
   - Infers visual roles (background layers, decorative accents, logos, hero images, headlines, subheads, CTAs, badges, ribbons, and legal text) without relying on hardcoded element IDs.
2. **Group Identification & Unified Scaling**:
   - Detects designer-intended units sharing a group ID (`group_id` / `group`).
   - Keeps text labels centered and properly proportioned relative to their background container shape.
3. **Aspect Ratio Analysis & Strategy Selection**:
   - Computes target aspect ratio $AR_{tgt} = W_{tgt} / H_{tgt}$.
   - **Portrait / Square ($AR_{tgt} \le 1.3$)**: Vertical single-column stack flow (Logo -> Hero Image -> Headline -> Subhead -> Badges -> CTA -> Legal).
   - **Medium Landscape ($1.3 < AR_{tgt} \le 2.8$)**: Two-column split layout (Left: Hero Image; Right: Logo, Headline, Subhead, Badges, CTA).
   - **Extreme Leaderboard Banner ($AR_{tgt} > 2.8$, e.g. 728x90)**: Horizontal multi-zone ribbon flow (Logo -> Hero -> Headline/Subhead -> CTA -> Badges/Ribbon).
4. **Dynamic Typography Sizing**:
   - Calculates character capacity, explicit `\n` line breaks, and line wrapping for text boxes.
   - Adjusts `font_size` / `fontSize` dynamically to ensure text fits box bounds legibly without line overflow.
5. **Bounded Collision Resolution & Bounds Enforcement**:
   - Uses bounded iterations (max 10 iterations) to detect and resolve unwanted overlaps between independent content elements.
   - Clamps non-decorative content strictly inside canvas boundaries $[0, 0, W_{tgt}, H_{tgt}]$.

---

## Installation & Local Execution

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Local Evaluation Pipeline

```bash
python3 -m engine.main
```

This processes every task in `input/*.json` and generates output artifacts in `output/`:
- `<task>_output.json` (schema-valid resized design)
- `<task>_output.png` (rendered visual preview)

---

## Vercel Deployment & API

The Vercel deployment wraps the exact same `engine.resize.resize()` implementation without any mock or fake data.

### API Endpoints

- `GET /api/health` -> Returns `{"status": "ok"}`
- `POST /api/resize` -> Accepts source design JSON and target canvas JSON, calls `resize()`, returns resized JSON.

### Request Payload Example

```json
{
  "source": {
    "canvas": { "width": 1000, "height": 1000 },
    "elements": [
      {
        "id": "el_bg",
        "type": "image",
        "x": 0,
        "y": 0,
        "width": 1000,
        "height": 1000,
        "z_index": 0,
        "asset_id": "solstice_bg_gradient.png",
        "fit": "cover"
      },
      {
        "id": "el_main_headline",
        "type": "text",
        "x": 100,
        "y": 680,
        "width": 800,
        "height": 120,
        "z_index": 4,
        "content": "Discover Golden Hour Refreshment",
        "font_family": "Solstice Serif",
        "font_size": 52,
        "color": "rgba(255,255,255,1)",
        "text_align": "center"
      }
    ]
  },
  "target_canvas": { "width": 1000, "height": 1500 }
}
```

### Response Example (HTTP 200 OK)

```json
{
  "canvas": { "width": 1000, "height": 1500 },
  "elements": [ ... ]
}
```

---

## Docker Execution

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .

docker run --rm --network none \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  my-chameleon-engine
```

---

## Testing

Run all local pipeline tests and schema validation:

```bash
python3 -m engine.main
```
