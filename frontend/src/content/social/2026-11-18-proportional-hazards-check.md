---
date: 2026-11-18
link: /guides/covariates-and-regression
image: /social/ph-check-schoenfeld.png
---
A Cox model gives one hazard ratio per factor, for all time. If a factor's effect changes with age, that one number averages over it and misstates both ends.

The check is the Grambsch–Therneau test on the scaled Schoenfeld residuals. Reliafy runs the same exact test as R's cox.zph (survival 3.0 and later). On the Rossi data, a standard survival teaching set of 432 subjects followed for 52 weeks, both give a global chi-square of 17.69 on 7 degrees of freedom, p = 0.013. For age, p = 0.015: little effect early, a stronger one later.

If the check fails, stratify on that factor or try an accelerated-failure-time model.
