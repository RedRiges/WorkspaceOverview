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
    offsets = [(x * width // out_width) * pixel_bytes for x in range(out_width)]
    # Common X11 RGB888 formats need no integer unpacking or channel scaling.
    if all(maximum == 255 and shift % 8 == 0 for _, shift, maximum in channels):
        byte_offsets = [
            shift // 8 if byteorder == "little" else pixel_bytes - 1 - shift // 8
            for _, shift, _ in channels
        ]
        for y in range(out_height):
            row = (y * height // out_height) * stride
            target = y * out_width * 3
            for channel, byte_offset in enumerate(byte_offsets):
                output[target + channel : target + out_width * 3 : 3] = bytes(
                    data[row + offset + byte_offset] for offset in offsets
                )
        return Preview(out_width, out_height, bytes(output))
    for y in range(out_height):
        row = (y * height // out_height) * stride
        for x, source_offset in enumerate(offsets):
            offset = row + source_offset
            pixel = int.from_bytes(data[offset : offset + pixel_bytes], byteorder)
            target = (y * out_width + x) * 3
            for channel, (mask, shift, maximum) in enumerate(channels):
                output[target + channel] = ((pixel & mask) >> shift) * 255 // maximum
    return Preview(out_width, out_height, bytes(output))
