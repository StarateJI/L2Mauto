"""
mouse_xy.py — показывает координаты курсора. 
Наводишь мышь на нужное место экрана, жмёшь Enter в консоли, ждёшь 8 сек — печатает координаты.
"""
import time
import ctypes
from ctypes import wintypes

input("Наведи мышь на ЛЕВЫЙ ВЕРХНИЙ краешек ПЕРВОЙ цифры «Текущая минимальная цена» (чуть выше-левее цифры), НЕ ДВИГАЙ. Потом Enter: ")
time.sleep(8)
p = wintypes.POINT()
ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
print("ЛЕВЫЙ ВЕРХ цифр: X =", p.x, " Y =", p.y)

input("Теперь наведи на ПРАВЫЙ НИЖНИЙ краешек ПОСЛЕДНЕЙ цифры (чуть ниже-правее), НЕ ДВИГАЙ. Enter: ")
time.sleep(8)
ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
print("ПРАВЫЙ НИЗ цифр: X =", p.x, " Y =", p.y)

input("Готово! Enter — выход")