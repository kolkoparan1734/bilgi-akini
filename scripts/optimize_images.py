"""
Görselleri sunum/mobil için hazırlar: PNG -> WebP, küçültme, manifest ikonları.

Kaynaklar kaynak_gorseller/ klasöründe durur (orijinal, dokunulmamış PNG'ler);
çıktılar frontend/assets/ altına yazılır. Tekrar tekrar çalıştırılabilir.

Kullanım (Pillow gerekli — backend venv'inde kurulu):
    backend\\venv\\Scripts\\python.exe scripts\\optimize_images.py
"""
import os
import shutil

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "kaynak_gorseller")
OUT = os.path.join(ROOT, "frontend", "assets")

# Harita görselinde üstte/altta baskılı duran örnek arayüz parçalarını (skor
# kutusu, "Bölge Seç!" paneli, alttaki dönem kaydırıcısı, çerçeve) kırparak
# atıyoruz. Oranlar görselin tamamına göre (0-1). Ülke koordinatları
# (backend/app.py -> COUNTRY_LAYOUT) bu kırpılmış görsele göre verilmiştir.
MAP_CROP = (0.015, 0.13, 0.985, 0.86)


def src(name):
    return os.path.join(SRC, name)


def move_originals():
    """İlk çalıştırmada frontend/assets'teki büyük PNG'leri kaynak_gorseller/'e taşır."""
    os.makedirs(os.path.join(SRC, "characters"), exist_ok=True)
    for rel in ["world-map.png", "hero-login.png", "logo-badge.png", "box-art.png"]:
        a, b = os.path.join(OUT, rel), src(rel)
        if os.path.exists(a) and not os.path.exists(b):
            shutil.move(a, b)
    char_dir = os.path.join(OUT, "characters")
    for f in os.listdir(char_dir):
        if f.endswith(".png"):
            a, b = os.path.join(char_dir, f), src(os.path.join("characters", f))
            if not os.path.exists(b):
                shutil.move(a, b)
            elif os.path.exists(a):
                os.remove(a)


def fill_row_gradient(im, box):
    """box içini her satırda sol ve sağ kenar renkleri arasında doğrusal
    geçişle doldurur — düz/degrade zemindeki baskılı bir öğeyi silmek için."""
    x0, y0, x1, y1 = box
    px = im.load()
    for y in range(y0, y1):
        left, right = px[x0 - 1, y], px[x1, y]
        w = x1 - x0
        for x in range(x0, x1):
            t = (x - x0) / w
            px[x, y] = tuple(int(left[c] * (1 - t) + right[c] * t) for c in range(3))
    # sert dikiş kalmasın diye bölgeyi hafifçe yumuşat
    region = im.crop(box).filter(ImageFilter.GaussianBlur(6))
    im.paste(region, box[:2])


def patch_from(im, dst_box, src_offset_y, feather=40):
    """dst_box bölgesini, aynı genişlikte ama src_offset_y kadar yukarıdaki
    bölgeyle örter. Sol ve alt kenar görselin kenarına denk geldiği için
    yalnızca üst ve sağ kenar yumuşatılır."""
    x0, y0, x1, y1 = dst_box
    patch = im.crop((x0, y0 - src_offset_y, x1, y1 - src_offset_y))
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).rectangle(
        (-feather, feather, patch.width - feather, patch.height + feather), fill=255
    )
    mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))
    im.paste(patch, (x0, y0), mask)


def save_webp(im, rel, quality, max_w=None):
    if max_w and im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    path = os.path.join(OUT, rel)
    im.save(path, "WEBP", quality=quality, method=6)
    print(f"{rel:32s} {im.size[0]}x{im.size[1]}  {os.path.getsize(path) // 1024} KB")


def build_map():
    im = Image.open(src("world-map.png")).convert("RGB")
    W, H = im.size
    # Sol alttaki baskılı pusulayı, hemen üstündeki açık okyanus dokusuyla ört.
    patch_from(im, (0, int(H * 0.72), int(W * 0.19), int(H * 0.88)), int(H * 0.12))
    l, t, r, b = MAP_CROP
    im = im.crop((int(W * l), int(H * t), int(W * r), int(H * b)))
    save_webp(im, "world-map.webp", 80, max_w=1920)


def build_hero():
    im = Image.open(src("hero-login.png")).convert("RGB")
    # Sol üstte baskılı duran logoyu sil; oyun kendi (animasyonlu) logosunu koyar.
    fill_row_gradient(im, (180, 112, 1268, 474))
    save_webp(im, "hero-login.webp", 78, max_w=1920)


def build_logo_and_icons():
    logo = Image.open(src("logo-badge.png")).convert("RGBA")
    # Logonun teal zeminini saydam yap (kahverengi üst barda kutu gibi durmasın).
    bg = logo.getpixel((2, 2))[:3]
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b_, a = px[x, y]
            d = abs(r - bg[0]) + abs(g - bg[1]) + abs(b_ - bg[2])
            if d < 40:
                px[x, y] = (r, g, b_, 0)
            elif d < 90:
                px[x, y] = (r, g, b_, int(255 * (d - 40) / 50))
    logo = logo.crop(logo.getbbox())
    logo.save(os.path.join(OUT, "logo-badge.webp"), "WEBP", quality=90, method=6)
    logo.save(os.path.join(OUT, "logo-badge.png"))  # eski tarayıcılar / apple-touch için yedek
    print(f"logo-badge.webp                  {logo.size[0]}x{logo.size[1]}")

    os.makedirs(os.path.join(OUT, "icons"), exist_ok=True)
    teal = (59, 145, 178)
    wood = (63, 39, 24)
    gold = (224, 181, 99)
    for out_size, maskable in [(192, False), (512, False), (512, True)]:
        size = out_size * 4  # büyük çizip küçült: yuvarlak köşeler tırtıklı olmasın
        icon = Image.new("RGBA", (size, size), wood + (255,))
        d = ImageDraw.Draw(icon)
        if not maskable:
            pad = size * 0.04
            d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size * 0.18,
                                fill=teal, outline=gold, width=max(3, size // 40))
            logo_w = size * 0.84
        else:
            # maskable: arka plan tam kare, logo merkezdeki %80 güvenli alanda
            d.rectangle((0, 0, size, size), fill=teal)
            logo_w = size * 0.70
        lw = int(logo_w)
        lh = round(logo.height * lw / logo.width)
        l = logo.resize((lw, lh), Image.LANCZOS)  # noqa: E741
        icon.alpha_composite(l, ((size - lw) // 2, (size - lh) // 2))
        icon = icon.resize((out_size, out_size), Image.LANCZOS)
        name = f"icon-{out_size}{'-maskable' if maskable else ''}.png"
        icon.save(os.path.join(OUT, "icons", name))
        print("icons/" + name)


def build_characters():
    for f in sorted(os.listdir(os.path.join(SRC, "characters"))):
        if not f.endswith(".png"):
            continue
        im = Image.open(src(os.path.join("characters", f))).convert("RGBA")
        im = im.resize((256, 256), Image.LANCZOS)
        save_webp(im, os.path.join("characters", f.replace(".png", ".webp")), 82)


if __name__ == "__main__":
    move_originals()
    build_map()
    build_hero()
    build_logo_and_icons()
    build_characters()
