"""Icono de Matrículas: una matrícula europea (franja azul y texto inventado)
dentro de las esquinas de un visor, sobre un cuadrado redondeado verde azulado.

Uso: python generar.py <carpeta brand>  (Pillow, que ya trae HA)."""
import math
import sys
from PIL import Image, ImageDraw, ImageFont


def dibujar(lado: int) -> Image.Image:
    S = 4  # sobremuestreo para bordes suaves
    W = lado * S
    u = W / 256  # unidades de un lienzo de 256

    # Fondo: cuadrado redondeado con un degradado vertical suave.
    fondo = Image.new("RGBA", (W, W))
    arriba, abajo = (0, 150, 136), (0, 92, 84)
    df = ImageDraw.Draw(fondo)
    for y in range(W):
        t = y / (W - 1)
        df.line([(0, y), (W, y)], fill=tuple(round(arriba[i] + (abajo[i] - arriba[i]) * t) for i in range(3)) + (255,))
    mascara = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, W - 1, W - 1], radius=56 * u, fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(fondo, (0, 0), mascara)
    d = ImageDraw.Draw(img)
    blanco = (255, 255, 255, 255)

    # Esquinas del visor, con los extremos redondeados.
    grosor, brazo = 11 * u, 30 * u
    x0, y0, x1, y1 = 30 * u, 62 * u, 226 * u, 194 * u
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        for fin in ((cx + sx * brazo, cy), (cx, cy + sy * brazo)):
            d.line([(cx, cy), fin], fill=blanco, width=round(grosor))
            for px, py in ((cx, cy), fin):
                r = grosor / 2
                d.ellipse([px - r, py - r, px + r, py + r], fill=blanco)

    # Matrícula: blanca, con la franja azul a la izquierda.
    px0, py0, px1, py1, rp = 48 * u, 98 * u, 208 * u, 158 * u, 9 * u
    placa = Image.new("L", (W, W), 0)
    ImageDraw.Draw(placa).rounded_rectangle([px0, py0, px1, py1], radius=rp, fill=255)
    img.paste(blanco, (0, 0), placa)
    franja = Image.new("L", (W, W), 0)
    ImageDraw.Draw(franja).rectangle([px0, py0, px0 + 26 * u, py1], fill=255)
    franja = Image.composite(franja, Image.new("L", (W, W), 0), placa)
    img.paste((0, 57, 166, 255), (0, 0), franja)
    # Las estrellas de la franja, en un anillo amarillo.
    cx, cy, ra = px0 + 13 * u, py0 + 19 * u, 8 * u
    for k in range(12):
        a = math.radians(k * 30)
        x, y, re = cx + ra * math.cos(a), cy + ra * math.sin(a), 1.5 * u
        d.ellipse([x - re, y - re, x + re, y + re], fill=(255, 204, 0, 255))

    # Texto inventado, centrado en la parte blanca y un poco engrosado.
    texto = "1234 BCD"
    zona0, zona1 = px0 + 31 * u, px1 - 6 * u
    tam = round(34 * u)
    while True:
        fuente = ImageFont.load_default(size=tam)
        caja = d.textbbox((0, 0), texto, font=fuente, stroke_width=round(1.6 * u))
        if caja[2] - caja[0] <= zona1 - zona0 or tam < 8:
            break
        tam -= 1
    ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
    tx = zona0 + (zona1 - zona0 - ancho) / 2 - caja[0]
    ty = (py0 + py1) / 2 - alto / 2 - caja[1]
    oscuro = (33, 33, 33, 255)
    d.text((tx, ty), texto, font=fuente, fill=oscuro, stroke_width=round(1.6 * u), stroke_fill=oscuro)

    return img.resize((lado, lado), Image.LANCZOS)


destino = sys.argv[1]
dibujar(256).save(f"{destino}/icon.png", optimize=True)
dibujar(512).save(f"{destino}/icon@2x.png", optimize=True)
print("ok")
