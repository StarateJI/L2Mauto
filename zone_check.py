"""
zone_check2.py — большой снимок области окна продажи: найдём «Текущая минимальная цена».
"""
import os
import mss

# Большая область: вся центральная часть экрана (окно продажи живёт тут)
BIG = {
    "left": 900,
    "top": 300,
    "width": 800,
    "height": 500,
}

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with mss.mss() as sct:
    z = sct.grab(BIG)

mss.tools.to_png(z.rgb, z.size, output=os.path.join(OUT_DIR, "zone_big.png"))
print("Снято: zone_big.png (800x500 от точки 900,300)")
input("Enter для выхода...")