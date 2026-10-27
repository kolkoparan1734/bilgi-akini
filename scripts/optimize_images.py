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


def fill_row_gradient(im, box, blur=6):
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
    region = im.crop(box).filter(ImageFilter.GaussianBlur(blur))
    im.paste(region, box[:2])


def fill_coons(im, box, feather=24, blur=10):
    """box içini dört kenarındaki renklerden (yatay + dikey geçişin birleşimi,
    "Coons yaması") doldurur; çizgi/leke bırakmadan çevresine kaynaşır.
    Kenarlar yumuşak maskeyle harmanlanır."""
    x0, y0, x1, y1 = box
    src_px = im.load()
    w, h = x1 - x0, y1 - y0
    top = [src_px[x0 + i, y0 - 1] for i in range(w)]
    bottom = [src_px[x0 + i, y1] for i in range(w)]
    left = [src_px[x0 - 1, y0 + j] for j in range(h)]
    right = [src_px[x1, y0 + j] for j in range(h)]
    c00, c10, c01, c11 = src_px[x0 - 1, y0 - 1], src_px[x1, y0 - 1], src_px[x0 - 1, y1], src_px[x1, y1]
    patch = Image.new("RGB", (w, h))
    pp = patch.load()
    for j in range(h):
        v = j / (h - 1)
        for i in range(w):
            u = i / (w - 1)
            px = []
            for c in range(3):
                horiz = left[j][c] * (1 - u) + right[j][c] * u
                vert = top[i][c] * (1 - v) + bottom[i][c] * v
                bil = (c00[c] * (1 - u) * (1 - v) + c10[c] * u * (1 - v)
                       + c01[c] * (1 - u) * v + c11[c] * u * v)
                px.append(max(0, min(255, int(horiz + vert - bil))))
            pp[i, j] = tuple(px)
    patch = patch.filter(ImageFilter.GaussianBlur(blur))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle((feather, feather, w - feather, h - feather), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))
    im.paste(patch, (x0, y0), mask)


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
    # Ortadaki baskılı örnek giriş kartını da sil (ekran geçişlerinde ve geniş
    # ekranda arkadan görünmesin); zemin, çevresindeki renklerle doldurulur.
    W, H = im.size
    fill_coons(im, (int(W * 0.375), int(H * 0.33), int(W * 0.625), int(H * 0.79)), feather=30, blur=22)
    save_webp(im, "hero-login.webp", 78, max_w=1920)


# Giriş / seçim ekranı arka planları. Kaynak: AI ile sola/geniş açıya
# genişletilmiş (outpaint) PNG'ler (kaynak_gorseller/outpaint/). İlk elden
# gelen JPG'ler yedek olarak frontend/assets/ içinde kalır.
# WebP hedefi 400-600 KB, en fazla 1920 px genişlik.
# crop_right: görselin sağındaki boş gökyüzünü at ki okçu sağ kenara yaslansın
# (style.css'teki --bg-ratio değerleri bu kırpılmış oranlara göre).
BACKGROUNDS = {
    "arkaplan-giris": {"src": "outpaint/giris-21x9.png", "crop_right": 1.0},
    "arkaplan-secim": {"src": "outpaint/secim-21x9.png", "crop_right": 0.92},
}


def build_backgrounds():
    for name, cfg in BACKGROUNDS.items():
        im = Image.open(src(cfg["src"])).convert("RGB")
        im = im.crop((0, 0, round(im.width * cfg["crop_right"]), im.height))
        ratio = im.width / im.height
        im = im.resize((1920, round(1920 / ratio)), Image.LANCZOS)
        path = os.path.join(OUT, name + ".webp")
        # 400-600 KB aralığına düşen en yüksek kaliteyi bul
        chosen = None
        for q in range(95, 59, -3):
            im.save(path, "WEBP", quality=q, method=6)
            if os.path.getsize(path) <= 600 * 1024:
                chosen = q
                break
        print(f"{name}.webp".ljust(33) + f"{im.size[0]}x{im.size[1]}  oran {ratio:.4f}  q{chosen}  {os.path.getsize(path) // 1024} KB")
        # Ekran görselden de genişse sol boşluğu dolduran küçük, bulanık kopya
        small = im.resize((480, round(480 / ratio)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(10))
        small.save(os.path.join(OUT, name + "-blur.webp"), "WEBP", quality=70, method=6)


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


def clear_fake_checkerboard(im):
    """Portrelerin etrafına gömülmüş gri-beyaz "sahte saydamlık" desenini
    gerçekten saydam yapar. Kenarlardan başlayan bir taşma (flood fill) ile
    sadece dışarıdan ulaşılabilen açık gri/beyaz pikseller silinir; portrenin
    içindeki parlak zırh vb. koyu kalkan zeminiyle çevrili olduğu için korunur."""
    w, h = im.size
    px = im.load()

    def is_bg(x, y):
        r, g, b, a = px[x, y]
        if a < 20:
            return True
        return max(r, g, b) - min(r, g, b) < 22 and min(r, g, b) > 150

    seen = bytearray(w * h)
    stack = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    while stack:
        x, y = stack.pop()
        i = y * w + x
        if seen[i] or not is_bg(x, y):
            continue
        seen[i] = 1
        px[x, y] = (0, 0, 0, 0)
        if x > 0: stack.append((x - 1, y))
        if x < w - 1: stack.append((x + 1, y))
        if y > 0: stack.append((x, y - 1))
        if y < h - 1: stack.append((x, y + 1))
    return im


def build_characters():
    for f in sorted(os.listdir(os.path.join(SRC, "characters"))):
        if not f.endswith(".png"):
            continue
        im = Image.open(src(os.path.join("characters", f))).convert("RGBA")
        im = clear_fake_checkerboard(im)
        # Kalkan biçimli portreyi kare kırp: genişlik kadar kare, üstten hizalı
        # (yüzler üst kısımda) — dairesel çerçevede yüz büyük ve ortada görünür.
        l, t, r, b = im.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
        side = r - l
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.alpha_composite(im.crop((l, t, r, min(b, t + side))), (0, 0))
        square = square.resize((256, 256), Image.LANCZOS)
        save_webp(square, os.path.join("characters", f.replace(".png", ".webp")), 82)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["arkaplan"]:  # sadece arka planları üret (hızlı)
        build_backgrounds()
        sys.exit(0)
    move_originals()
    build_map()
    build_hero()
    build_logo_and_icons()
    build_characters()
    build_backgrounds()
