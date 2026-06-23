from __future__ import annotations

from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def image_files(folder: Path) -> list[Path]:
    return sorted(
        (path for path in folder.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: path.name.lower(),
    )


def convert_folder_to_pdf(
    folder: Path, *, remove_images: bool = False, title: str | None = None
) -> Path:
    images = image_files(folder)
    if not images:
        raise ValueError("No supported images found in this folder")
    output = unique_path(folder.parent / f"{title or folder.name}.pdf")
    opened: list[Image.Image] = []
    try:
        for path in images:
            with Image.open(path) as image:
                if image.mode in {"RGBA", "LA"} or (
                    image.mode == "P" and "transparency" in image.info
                ):
                    rgba = image.convert("RGBA")
                    ready = Image.new("RGB", image.size, "white")
                    ready.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    ready = image.convert("RGB")
                opened.append(ready)
        opened[0].save(output, "PDF", save_all=True, append_images=opened[1:])
    finally:
        for image in opened:
            image.close()
    if remove_images:
        for path in images:
            path.unlink(missing_ok=True)
    return output


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate a unique PDF filename")
