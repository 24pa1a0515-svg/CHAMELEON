"""
Project CHAMELEON — Vercel API Entrypoint
Exposes the real engine.resize.resize() via HTTP REST API.
"""

from flask import Flask, jsonify, request
from engine.resize import resize

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    """Service status endpoint."""
    return jsonify({
        "status": "online",
        "service": "Project CHAMELEON Automatic Design Reflow API",
        "version": "0.9"
    }), 200


@app.route("/api/resize", methods=["POST"])
@app.route("/resize", methods=["POST"])
@app.route("/", methods=["POST"])
def api_resize():
    """
    POST endpoint to reflow a CHAMELEON design for a target canvas.
    Payload format:
        {
            "source": {"canvas": {"width": 1080, "height": 1080}, "elements": [...]},
            "target_canvas": {"width": 1080, "height": 1350}
        }
    """
    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Invalid request body: expected valid JSON object"}), 400

        # Support flexible payload keys ("source" or "design", "target_canvas" or "target")
        source = data.get("source") or data.get("design")
        target_canvas = data.get("target_canvas") or data.get("target")

        # Fallback if top-level structure itself is a source design with "target_canvas"
        if not source and "elements" in data and "canvas" in data:
            source = {"canvas": data["canvas"], "elements": data["elements"]}

        if not source or not isinstance(source, dict):
            return jsonify({"error": "Missing or invalid 'source' design object"}), 400

        if not target_canvas or not isinstance(target_canvas, dict):
            return jsonify({"error": "Missing or invalid 'target_canvas' object"}), 400

        # Validate source canvas
        src_canvas = source.get("canvas")
        if not src_canvas or not isinstance(src_canvas, dict):
            return jsonify({"error": "Source design missing 'canvas' property"}), 400

        if not isinstance(src_canvas.get("width"), (int, float)) or src_canvas.get("width") <= 0:
            return jsonify({"error": "Source canvas 'width' must be a positive number"}), 400

        if not isinstance(src_canvas.get("height"), (int, float)) or src_canvas.get("height") <= 0:
            return jsonify({"error": "Source canvas 'height' must be a positive number"}), 400

        # Validate elements list
        elements = source.get("elements")
        if not isinstance(elements, list) or len(elements) == 0:
            return jsonify({"error": "Source design 'elements' must be a non-empty array"}), 400

        for idx, el in enumerate(elements):
            if not isinstance(el, dict) or "id" not in el or "type" not in el:
                return jsonify({"error": f"Element at index {idx} missing 'id' or 'type'"}), 400

        # Validate target canvas dimensions
        tgt_w = target_canvas.get("width")
        tgt_h = target_canvas.get("height")
        if not isinstance(tgt_w, (int, float)) or tgt_w <= 0:
            return jsonify({"error": "Target canvas 'width' must be a positive number"}), 400
        if not isinstance(tgt_h, (int, float)) or tgt_h <= 0:
            return jsonify({"error": "Target canvas 'height' must be a positive number"}), 400

        # Execute real design reflow engine
        result = resize(source, {"width": int(tgt_w), "height": int(tgt_h)})

        # Basic verification of returned design
        if not result or "canvas" not in result or "elements" not in result:
            return jsonify({"error": "Engine failed to produce valid output"}), 500

        return jsonify(result), 200

    except Exception:
        # Safe error message without revealing internal stack traces or paths
        return jsonify({"error": "Internal server error occurred while processing design"}), 500


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request"}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=False)
