# svg_rasterizer_simple.py
# Minimal SVG -> PNG/JPEG rasterizer for ComfyUI using CairoSVG (no font embedding).

import io
import os
import re
import json
import hashlib
import numpy as np
from PIL import Image
import cairosvg
import torch
import folder_paths


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
        png_bytes = cairosvg.svg2png(bytestring=svg_text.encode("utf-8"))
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



class RasterizeSVG:
    """
    A node to rasterize SVG text into an image, with options for resizing,
    background color, and a border.

    Inputs:
    - svg_text: The SVG content as a string.
    - width: The desired output width in pixels. If set to a value > 0,
             it overrides the 'scale' parameter.
    - scale: A scaling factor for the SVG. This is only used if 'width' is 0.
    - background_color: The background color in hexadecimal format (e.g., #RRGGBB)
                        or 'transparent'. This is visible through transparent
                        areas of the SVG.
    - border_width: The width of the border to add around the image in pixels. Only used if greater than 0.
    - border_color: The color of the border in hexadecimal format (e.g., #RRGGBB)
                    or 'transparent'.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "svg_text": ("STRING", {"multiline": True, "default": "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 256 256'><circle cx='128' cy='128' r='96' fill='#22c55e'/></svg>"}),
                "width": ("INT", {"default": 512, "min": 0, "max": 4096}),
                "scale": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 20.0, "step": 0.1}),
                "background_color": ("STRING", {"default": "transparent"}),
                "border_width": ("INT", {"default": 0, "min": 0, "max": 1024}),
                "border_color": ("STRING", {"default": "transparent"}),
            }
        }

    CATEGORY = "FromSVG/Tools"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "rasterize"

    def rasterize(self, svg_text, width, scale, background_color, border_width, border_color):
        if not svg_text or not svg_text.strip():
            raise ValueError("SVG text is empty")
        
        bg_color = self._parse_hex_color_string(background_color, "Background color")
        br_color = self._parse_hex_color_string(border_color, "Border color")
        resize_kwargs = self._get_resize_kwargs(width, scale)                
        
        png_bytes = cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            background_color=bg_color,
            **resize_kwargs
        )
        pil_image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

        if border_width > 0:
            # Add a border around the image
            pil_image = self._add_border(pil_image, border_width, br_color)
        
        return (_pil_to_tensor(pil_image),)
     
    def _get_resize_kwargs(self, width, scale):
        """Get the resize kwargs for the cairosvg.svg2png function."""
        resize_kwargs = {}
        if width > 0:
            resize_kwargs["output_width"] = width
        elif scale > 0:
            resize_kwargs["scale"] = scale
        else:
            raise ValueError("Invalid width or scale")
        return resize_kwargs

    def _parse_hex_color_string(self, color_string, field_name="Color"):
        """Parse a hex color string to an (R, G, B, A) tuple."""
        color = None
        clean_color = color_string.strip()
        if clean_color and clean_color.lower() not in ('transparent', 'none', ''):
            if not re.match(r'^#[A-Fa-f0-9]{6}$', clean_color):
                raise ValueError(f"{field_name} must be in hexadecimal format (e.g., #RRGGBB) or 'transparent'.")
            color = clean_color
        return color
    
    def _hex_to_rgba(self, hex_color):
        """Converts a hex color string to an (R, G, B, A) tuple."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            r, g, b = tuple(int(c * 2, 16) for c in hex_color)
        else:
            r, g, b = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, 255)
    
    def _add_border(self, pil_image, border_width, br_color):
        original_width, original_height = pil_image.size
        new_width = original_width + 2 * border_width
        new_height = original_height + 2 * border_width

        pil_border_color = (0, 0, 0, 0)
        if br_color:
            pil_border_color = self._hex_to_rgba(br_color)

        bordered_image = Image.new("RGBA", (new_width, new_height), pil_border_color)
        bordered_image.paste(pil_image, (border_width, border_width), pil_image)
        pil_image = bordered_image
        return pil_image



# Required mappings for ComfyUI to discover the node
NODE_CLASS_MAPPINGS = {
    "LoadSVGImage": LoadSVGImage,
    "RasterizeSVG": RasterizeSVG,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadSVGImage": "Load SVG Image",
    "RasterizeSVG": "SVG Rasterizer (Simple)",
}
