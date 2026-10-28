"""Convert packed TrueColor X images to bounded RGB8 thumbnails."""

from workspace_overview.core.models import Preview


def decode_rgb(
    data: bytes,
    *,
    width: int,
    height: int,
    bits_per_pixel: int,
    stride: int,
    byteorder: str,
    masks: tuple[int, int, int],
    max_width: int = 320,
    max_height: int = 200,
) -> Preview:
    if min(width, height, max_width, max_height) < 1:
        raise ValueError("Image dimensions must be positive")
    if bits_per_pixel not in (16, 24, 32) or byteorder not in ("little", "big"):
        raise ValueError("Unsupported X image format")
    pixel_bytes = bits_per_pixel // 8
    if stride < width * pixel_bytes or len(data) < stride * height:
        raise ValueError("Truncated X image data")
    channels = []
    used = 0
    for mask in masks:
        if mask <= 0 or mask >= 1 << bits_per_pixel or mask & used:
            raise ValueError("Invalid TrueColor channel masks")
        shift = (mask & -mask).bit_length() - 1
        maximum = mask >> shift
        if maximum & (maximum + 1):
            raise ValueError("Non-contiguous TrueColor mask")
        channels.append((mask, shift, maximum))
        used |= mask
    scale = min(1.0, max_width / width, max_height / height)
    out_width, out_height = max(1, int(width * scale)), max(1, int(height * scale))
    output = bytearray(out_width * out_height * 3)
    for y in range(out_height):
        row = (y * height // out_height) * stride
        for x in range(out_width):
            offset = row + (x * width // out_width) * pixel_bytes
            pixel = int.from_bytes(data[offset : offset + pixel_bytes], byteorder)
            target = (y * out_width + x) * 3
            for channel, (mask, shift, maximum) in enumerate(channels):
                output[target + channel] = ((pixel & mask) >> shift) * 255 // maximum
    return Preview(out_width, out_height, bytes(output))
