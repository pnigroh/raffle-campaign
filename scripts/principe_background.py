"""Rebuild the Príncipe vertical background with the "GANÁ 1 DE LAS 30
BICICLETAS" lockup centred, as in the September comp.

The September .ai embeds its background at 72dpi (600x1632). The pattern behind
it -- out-of-focus cookie blobs -- survives being scaled up from that, but the
lockup does not. The August package ships the same artwork at 2500x6801 with
the lockup sitting left; measured against each other the lockup is identical in
scale and vertical position and only moved horizontally, centre 26.82% ->
50.08% of the width.

So: the September plate supplies the background, and the August plate's
high-resolution lockup is matted out and re-seated on top of it at the
September position. The September plate already carries a soft copy of the
lockup at exactly that position and scale, which is what makes this work -- the
matte's partial-alpha edges and ground shadow blend into a blurred version of
the same pixels rather than into bare pattern, so there is no silhouette to
find. Repainting a "clean" plate instead is not possible: the two lockup
positions overlap between x 699 and 1224, so neither plate is clean there.

The matte is a difference matte, not a colour key: |august - september| over
the August lockup is the lockup plus its shadow and nothing else. The threshold
is measured, not guessed -- across areas that are pattern in both plates the
difference never exceeds 18.4 (pure resampling noise) while the lockup runs
past 250, so a floor of 22 leaks no pattern and the ramp above it keeps the
shadow's falloff.

Run from the scratchpad holding `emb-000.png` (extracted from the September
.ai) and `aug/` (unpacked from drive-download-20260828T182230Z-1-001.zip).
"""
import numpy as np
from PIL import Image, ImageFilter

Image.MAX_IMAGE_PIXELS = None

old = Image.open("aug/Formulario-Principe Galletas Promo_Fondo Vertical.png").convert("RGB")
W, H = old.size
new_up = Image.open("emb-000.png").convert("RGB").resize((W, H), Image.LANCZOS)

o = np.asarray(old).astype(np.float32)
n = np.asarray(new_up).astype(np.float32)
d = np.linalg.norm(o - n, axis=2)

# Lockup box on the August plate, measured, with margin for the ground shadow
# the hard bbox clips. Clamped: the lockup starts 117px from the left edge, so
# the margin would otherwise run off the plate.
x0, x1, y0, y1 = 117, 1224, 5246, 6512
bx0, bx1 = max(0, x0 - 130), min(W, x1 + 1 + 130)
by0, by1 = max(0, y0 - 130), min(H, y1 + 1 + 150)

SHIFT = int(round((0.5008 - 0.2682) * W))  # 582 px at 2500 wide

box = np.zeros(d.shape, bool)
box[by0:by1, bx0:bx1] = True
alpha = np.clip((d - 22.0) / 28.0, 0.0, 1.0) * box
a_img = Image.fromarray((alpha * 255).astype(np.uint8)).filter(
    ImageFilter.GaussianBlur(1.2))

out = new_up.copy()
out.paste(old.crop((bx0, by0, bx1, by1)),
          (bx0 + SHIFT, by0),
          a_img.crop((bx0, by0, bx1, by1)))
out.save("bg_vertical_new.png")

# --- cut into the two halves the template expects ------------------------
# The template paints the pattern half behind the form, stretched to whatever
# height the form ends up being, then the bike half at its natural aspect, then
# the navy footer. Both cuts are chosen so the band needs no margins of its own:
#
#   top  (2060) leaves exactly the 3.8%-of-width of pattern the comp shows
#               between the PARTICIPAR button and the bike;
#   foot (2647) drops the strip the comp hides under the navy footer, which the
#               template stacks below the band rather than over it.
scaled = out.resize((1000, 2720), Image.LANCZOS)
scaled.crop((0, 0, 1000, 2060)).save("bg_mobile_body.jpg", quality=88, optimize=True)
scaled.crop((0, 2060, 1000, 2647)).save("bg_mobile_art.jpg", quality=88, optimize=True)

# Sanity: the lockup must land centred in the art band.
art = np.asarray(Image.open("bg_mobile_art.jpg").convert("RGB")).astype(int)
R, G, B = art[..., 0], art[..., 1], art[..., 2]
cols = np.where((~((B > R + 25) & (B > G + 10))).sum(axis=0) > 3)[0]
print(f"shift {SHIFT}  art 1000x{2647 - 2060}  "
      f"lockup x {cols.min()}-{cols.max()} centre {(cols.min() + cols.max()) / 2 / 10:.1f}%")
