"""Consistent high-resolution JPEG output for every user-facing figure export."""
from pathlib import Path


def jpeg_path(path):
    path = Path(path)
    return path if path.suffix.lower() in ('.jpg', '.jpeg') else path.with_suffix('.jpg')


def save_jpeg(figure, path, dpi=400):
    path = jpeg_path(path)
    figure.savefig(path, format='jpeg', dpi=dpi, bbox_inches='tight', facecolor='white',
                   pil_kwargs={'quality': 98, 'subsampling': 0})
    return str(path)
