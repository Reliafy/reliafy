"""Reliafy's readings where the handbook contradicts itself: one switch each.

Each switch is a choice Derryn can reverse (set it to False and rebuild the data
file with ``python -m backend.scripts.build_nswc11``). The records they touch
say "Reliafy's reading" with the page, so the record page shows the choice. The
defaults (True) are the independent accuracy review's recommendations, 9 Nov
2026; with False the record follows the page literally.

- SHAFT_PER_HOUR: Chapter 20 (Eq. 20-3/20-4, p. 20-5) gives the shaft in
  failures per million cycles, but every assembly that uses it lists λ_SH per
  million hours (pump p. 10-10, compressor p. 13-11, motor p. 14-7), and
  converting by revolutions gives a shaft life of hours (about 0.1 to 0.25 per
  million cycles × 108,000 revolutions an hour at 1,800 rpm). True: the shaft
  record is per million hours everywhere. False: per million cycles, and the
  pump, motors and compressor multiply it by the shaft's cycles an hour.
- GEAR_NORMALISED_AT_DESIGN: p. 8-8 says the factors adjust the base rate "for
  any difference" from the design, yet C_GS (Eq. 8-3) is 2.0 and C_GP (Eq. 8-6)
  is 25.8 at the design speed and load (× 51.6). True: each is divided by its
  value at the design point (C_GS / 2, C_GP / 25.8), so a gear at its design
  point gives its base rate (and a maker's rate stays the maker's rate). False:
  the printed factors.
- SHAFT_FINISH_INVERTED: Table 20-3's C_f (p. 20-10) are endurance-strength
  (Marin) factors, 1 or below, and as printed a rougher finish lowers the
  rate. True: the rate is divided by C_f (polished stays 1), so a rougher
  finish raises it. False: multiplied, as printed.
- PILLOW_BLOCK_PER_HOUR: p. 23-14's typical pillow block rate, "5.0 failures
  per million revolutions", gives 540,000 per million hours at 1,800 rpm (a
  life of about 2 hours). True: 5.0 per million hours, like the handbook's other
  bearing-class rates. False: per million revolutions, as printed.
"""

SHAFT_PER_HOUR = True
GEAR_NORMALISED_AT_DESIGN = True
SHAFT_FINISH_INVERTED = True
PILLOW_BLOCK_PER_HOUR = True
