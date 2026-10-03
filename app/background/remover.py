from pathlib import Path
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MODEL_DIR_NAME = "birefnet"
MODEL_REPO = "ZhengPeng7/BiRefNet"


class BackgroundRemovalError(RuntimeError):
    pass


def _model_dir() -> Path:
    # Development/source layout: <project>/models/birefnet
    return Path(__file__).resolve().parents[2] / "models" / MODEL_DIR_NAME


def model_status() -> tuple[bool, str]:
    model_dir = _model_dir()
    required = ["config.json", "model.safetensors", "birefnet.py", "BiRefNet_config.py"]
    missing = [name for name in required if not (model_dir / name).exists()]
    if missing:
        return False, (
            "Local BiRefNet model is not installed. Missing: "
            + ", ".join(missing)
        )
    return True, str(model_dir)


@lru_cache(maxsize=1)
def _load_model():
    ok, info = model_status()
    if not ok:
        raise BackgroundRemovalError(info)

    try:
        import torch
        from transformers import AutoModelForImageSegmentation
    except ImportError as exc:
        raise BackgroundRemovalError(
            "Local AI dependencies are not installed. Run the SakuConvert setup."
        ) from exc

    model_dir = Path(info)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # IMPORTANT: local_files_only prevents any model/network lookup.
    model = AutoModelForImageSegmentation.from_pretrained(
        str(model_dir),
        trust_remote_code=True,
        local_files_only=True,
    )
    model.to(device)
    model.eval()

    return model, device


def remove_background(source: Path, destination: Path) -> Path:
    """
    Run BiRefNet locally.

    No cloud request is made and no model download is allowed during inference.
    The model must already exist in models/birefnet.
    """
    ok, info = model_status()
    if not ok:
        raise BackgroundRemovalError(info)

    try:
        import torch
        from torchvision import transforms
    except ImportError as exc:
        raise BackgroundRemovalError(
            "PyTorch/torchvision is not installed."
        ) from exc

    model, device = _load_model()

    with Image.open(source) as original:
        image = original.convert("RGB")
        original_size = image.size

        # BiRefNet's general checkpoint is designed around 1024-ish input.
        # Keep original pixels for output; only the inference tensor is resized.
        inference = image.resize((1024, 1024), Image.Resampling.LANCZOS)
        tensor = transforms.ToTensor()(inference)
        tensor = transforms.Normalize(
            [0.485, 0.456, 0.406],
            [0.229, 0.224, 0.225],
        )(tensor).unsqueeze(0).to(device)

        with torch.no_grad():
            output = model(tensor)

        # HF wrapper may return a tensor or a tuple/list.
        if isinstance(output, (tuple, list)):
            pred = output[-1]
        elif hasattr(output, "logits"):
            pred = output.logits
        else:
            pred = output

        if pred.ndim == 4:
            pred = pred[:, 0, :, :]

        mask = torch.sigmoid(pred).squeeze().detach().float().cpu().numpy()
        mask = (mask - mask.min()) / max(float(mask.max() - mask.min()), 1e-8)

        mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
        mask_img = mask_img.resize(original_size, Image.Resampling.LANCZOS)

        # Keep the original RGB pixels and replace only alpha.
        rgba = image.convert("RGBA")
        rgba.putalpha(mask_img)

        destination.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(destination, format="PNG", optimize=True)

    return destination
