#!/usr/bin/env python3
"""WCAG 2.1 상대휘도 대비 계산 — 값을 손으로 적지 않기 위한 계기."""
import sys

def lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

def lum(hexstr):
    h = hexstr.lstrip('#')
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

def ratio(fg, bg):
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)

PAIRS = [
    ("본문 잉크 / 페이지 바탕",      "#2a2622", "#fbf7f0"),
    ("본문 잉크 / 카드 표면",        "#2a2622", "#ffffff"),
    ("진한 보조 / 카드 표면",        "#4a423b", "#ffffff"),
    ("흐린 글 / 페이지 바탕",        "#6b625a", "#fbf7f0"),
    ("흐린 글 / 카드 표면",          "#6b625a", "#ffffff"),
    ("링크(accent-hover) / 바탕",    "#8f3f14", "#fbf7f0"),
    ("링크(accent-hover) / 카드",    "#8f3f14", "#ffffff"),
    ("배지 글자 / 배지 표면",        "#6f2f0e", "#fbeee4"),
    ("버튼 흰 글자 / 액센트",        "#ffffff", "#a8521b"),
    ("미정 표기 / 미정 표면",        "#4d5b63", "#eef1f3"),
    ("미정 표기 / 카드 표면",        "#4d5b63", "#ffffff"),
    ("구분선 / 페이지 바탕(비-글자)", "#e4d9c6", "#fbf7f0"),
]

fail = 0
for name, fg, bg in PAIRS:
    r = ratio(fg, bg)
    mark = "AA(본문 4.5)" if r >= 4.5 else ("AA(큰글자 3.0)" if r >= 3.0 else "미달")
    if r < 4.5 and "비-글자" not in name:
        fail += 1
        mark += "  ← 글자에 쓰지 마라"
    print(f"{r:6.2f}:1  {name:32s} {fg} on {bg}   {mark}")
print(f"\n글자용 조합 중 4.5 미만 = {fail}건")
