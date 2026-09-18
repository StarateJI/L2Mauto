"""
zone_check2.py — широкая полоса: подписи + цифры справа от них. Сдвиг вправо.
"""
import os
import mss

# Полоса сдвинута правее: от X=1250 до X=2050
BIG = {
    "left": 1250,
    "top": 300,
    "width": 800,
    "height": 500,
}

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with mss.mss() as sct:
    z = sct.grab(BIG)

mss.tools.to_png(z.rgb, z.size, output=os.path.join(OUT_DIR, "zone_big.png"))
print("Снято: zone_big.png (полоса 800x500 от точки 1250,300)")
print("Проверь глазами: подписи СЛЕВА, цифры СПРАВА — всё в кадре?")
input("Enter для выхода...")