"""Draws the app icon and writes icon.png / icon.ico into bgremover_gui/web."""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "bgremover_gui" / "web"
S = 1024  # drawn large, then downsampled for smooth edges


def gradient(size, start, end):
    ramp = Image.linear_gradient("L").resize((size, size))
    diagonal = Image.blend(ramp, ramp.rotate(90), 0.5)
    return Image.composite(Image.new("RGB", (size, size), end), Image.new("RGB", (size, size), start), diagonal)


def rounded_mask(size, box, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def main():
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(gradient(S, (106, 92, 255), (20, 184, 230)), mask=rounded_mask(S, (40, 40, S - 40, S - 40), 230))

    # Checkerboard panel: the "removed" background.
    panel = (232, 232, S - 232, S - 232)
    checker = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(checker)
    cell = (panel[2] - panel[0]) // 4
    for row in range(4):
        for col in range(4):
            alpha = 92 if (row + col) % 2 == 0 else 36
            x, y = panel[0] + col * cell, panel[1] + row * cell
            draw.rectangle((x, y, x + cell, y + cell), fill=(255, 255, 255, alpha))
    panel_mask = rounded_mask(S, panel, 96)
    checker.putalpha(ImageChops.multiply(checker.getchannel("A"), panel_mask))
    icon.alpha_composite(checker)

    # Subject silhouette, clipped to the panel.
    subject = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(subject)
    draw.ellipse((412, 318, 612, 518), fill=255)
    draw.rounded_rectangle((322, 560, 702, 980), radius=180, fill=255)
    subject = ImageChops.multiply(subject, panel_mask)
    icon.paste(Image.new("RGBA", (S, S), (255, 255, 255, 255)), mask=subject)

    OUT.mkdir(parents=True, exist_ok=True)
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    icon.save(OUT / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote", OUT / "icon.png", "and", OUT / "icon.ico")


if __name__ == "__main__":
    main()
