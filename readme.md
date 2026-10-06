# CHAMELEON — Automatic Design Reflow Engine

Project CHAMELEON is an intelligent graphic design reflow engine that receives a source design JSON and a target canvas size, automatically rearranging and reflowing elements to produce a schema-valid layout for the new canvas shape.

Rather than naive stretching or uniform scaling, CHAMELEON preserves visual hierarchy, text legibility, element grouping, brand assets, and image aspect ratios.

The repository supports **both**:
1. **The official CHAMELEON local/Docker evaluation pipeline** (`python3 -m engine.main`).
2. **A working Vercel deployment/API** (`app.py` serverless entrypoint).

---

## Repo Layout

```text
chameleon/
├── app.py                           <- Vercel Flask API entrypoint exposing engine.resize.resize()
├── vercel.json                      <- Vercel deployment configuration
├── Dockerfile                       <- Container build spec for stage-one evaluation
├── README.md                        <- Project overview and guide
├── RULES.md                         <- Challenge rules and scoring specification
├── requirements.txt                 <- Python dependencies (Pillow, Flask, cr-renderer)
├── chameleon_design_schema_v0.9.json<- JSON schema spec
│
├── engine/
│   ├── main.py                      <- Local evaluation orchestrator
│   └── resize.py                    <- Core intelligent design reflow algorithm
│
├── brand_kit/
│   ├── assets/                      <- Image assets referenced by asset_id
│   └── fonts/                       <- Custom brand font files
│
├── input/                           <- Task JSON inputs (Level 1, Level 2, Level 3)
└── output/                          <- Output JSON and rendered PNG files
```

---

## High-Level Algorithm (`engine/resize.py`)

The reflow engine operates via a deterministic multi-step pipeline:

1. **Semantic Parsing & Role Classification**:
   - Analyzes element dimensions, bounding box, z-index, opacity, and text/image/shape properties.
   - Infers visual roles (background layers, decorative accents, logos, hero images, headlines, subheads, CTAs, badges, ribbons, and legal text) without relying on hardcoded element IDs.
2. **Group Identification & Unified Scaling**:
   - Detects designer-intended units sharing a `group_id` (e.g. CTA buttons, badges, ribbons).
   - Keeps text labels centered and properly proportioned relative to their background container shape.
3. **Aspect Ratio Analysis & Strategy Selection**:
   - Computes target aspect ratio $AR_{tgt} = W_{tgt} / H_{tgt}$.
   - **Portrait / Square ($AR_{tgt} \le 1.3$)**: Vertical single-column stack flow (Logo -> Hero Image -> Headline -> Subhead -> Badges -> CTA -> Legal).
   - **Medium Landscape ($1.3 < AR_{tgt} \le 2.8$)**: Two-column split layout (Left: Hero Image; Right: Logo, Headline, Subhead, Badges, CTA).
   - **Extreme Leaderboard Banner ($AR_{tgt} > 2.8$, e.g. 728x90)**: Horizontal multi-zone ribbon flow (Logo -> Hero -> Headline/Subhead -> CTA -> Badges/Ribbon).
4. **Dynamic Typography Sizing**:
   - Calculates character capacity and line wrapping for text boxes.
   - Adjusts `font_size` dynamically to ensure text fits box bounds legibly without line overflow.
5. **Collision Resolution & Canvas Bounds Enforcement**:
   - Clamps non-decorative content strictly inside canvas boundaries $[0, 0, W_{tgt}, H_{tgt}]$.
   - Preserves intentional corner bleed for background/decorative shapes (e.g. `deco_circle_1`).

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
- `<task>_output.png` (rendered visual preview via `cr-renderer`)

---

## Vercel Deployment & API

The Vercel deployment wraps the exact same `engine.resize.resize()` implementation without any mock or fake data.

### API Endpoint

- `POST /api/resize` (also supported on `/resize` and `/`)
- `GET /` (Service health check)

### Request Payload Example

```json
{
  "source": {
    "canvas": { "width": 1080, "height": 1080 },
    "elements": [
      {
        "id": "bg",
        "type": "image",
        "x": 0,
        "y": 0,
        "width": 1080,
        "height": 1080,
        "z_index": 0,
        "asset_id": "solstice_bg_gradient.png",
        "fit": "cover"
      },
      {
        "id": "headline",
        "type": "text",
        "x": 140,
        "y": 420,
        "width": 800,
        "height": 160,
        "z_index": 2,
        "content": "Chase the Light",
        "font_family": "Solstice Serif",
        "font_size": 60,
        "color": "rgba(255,255,255,1)",
        "text_align": "center"
      }
    ]
  },
  "target_canvas": { "width": 1080, "height": 1350 }
}
```

### Response Example (HTTP 200 OK)

```json
{
  "canvas": { "width": 1080, "height": 1350 },
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

Run all local pipeline tests and API validation:

```bash
python3 -m engine.main
```
