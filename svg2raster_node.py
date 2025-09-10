# svg_rasterizer_simple.py
# Minimal SVG -> PNG/JPEG rasterizer for ComfyUI using CairoSVG (no font embedding).

import io
import os
import json
import hashlib
import numpy as np
from PIL import Image
import cairosvg
import torch
import folder_paths

DEFAULT_PREVIEW_WIDTH = 512

def _pil_to_tensor(pil_img: Image.Image):
    """
    Convert PIL image to ComfyUI IMAGE tensor: (B, H, W, C) in [0,1]
    """
    # Keep 4 channels for PNG if present, else 3
    if pil_img.mode not in ("RGBA", "RGB"):
        pil_img = pil_img.convert("RGBA")
    arr = np.array(pil_img).astype(np.float32) / 255.0
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    # batch dimension
    return torch.from_numpy(np.expand_dims(arr, 0))

class LoadSVGImage:
    @classmethod
    def INPUT_TYPES(s):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f)) and f.lower().endswith('.svg')]
        return {
            "required": {
                "svg": (sorted(files), {"image_upload": True}),
            }
        }

    CATEGORY = "FromSVG/Tools"
    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("svg_text", "preview_image")
    FUNCTION = "load_svg"

    def load_svg(self, svg):
        svg_path = folder_paths.get_annotated_filepath(svg)

        with open(svg_path, "r", encoding="utf-8") as f:
            svg_text = f.read()
        
        # Generate preview with a fixed width, preserving aspect ratio
        png_bytes = cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), output_width=DEFAULT_PREVIEW_WIDTH)
        pil_preview = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        
        return (svg_text, _pil_to_tensor(pil_preview))

    @classmethod
    def IS_CHANGED(s, svg):
        svg_path = folder_paths.get_annotated_filepath(svg)
        m = hashlib.sha256()
        with open(svg_path, 'rb') as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(s, svg):
        if not folder_paths.exists_annotated_filepath(svg):
            return "Invalid SVG file: {}".format(svg)
        return True



# Required mappings for ComfyUI to discover the node
NODE_CLASS_MAPPINGS = {
    "LoadSVGImage": LoadSVGImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadSVGImage": "Load SVG Image",
}
