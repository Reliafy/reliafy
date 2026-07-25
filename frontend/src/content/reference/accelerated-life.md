---
family: accelerated-life
title: "Life-stress relationships"
description: "How characteristic life responds to stress in an accelerated test — Arrhenius, Eyring, inverse power law and the two-stress models, with their functional forms."
---

An accelerated life test runs units at **elevated stress** so they fail in weeks
rather than years, then extrapolates back down to the use condition. Two things
are fitted at once:

* a **life distribution** (Weibull, lognormal, normal, exponential or gamma),
  which describes the *scatter* of failures at any one stress; and
* a **life-stress relationship**, chosen below, which describes how that
  distribution's characteristic life moves with stress.

Formally the distribution's scale parameter is replaced by a function of stress,
`φ(S)` — the forms given below. The shape parameter is held **common across all
stress levels**, which is the central ALT assumption: raising stress makes
failures happen sooner, but doesn't change the failure *mechanism*. If the
probability plot shows the stress levels with visibly different slopes, that
assumption is broken and the extrapolation is not trustworthy.

**Choosing a relationship** is a physics question, not a statistical one. Pick
the one that matches the mechanism — thermal ageing is Arrhenius, voltage or
load is inverse power — and only then compare fit. The extrapolation is where
all the risk lives, and a model chosen purely on AIC will happily extrapolate
somewhere absurd.

**Note on stress units:** Arrhenius, Eyring and the temperature terms of the
two-stress models divide by the stress, so temperature must be **absolute
(kelvin)**. Feeding degrees Celsius gives a fit that looks fine and extrapolates
wrongly — and breaks outright if any value is zero or negative.

## arrhenius

**The standard thermal model**, from reaction-rate chemistry — the right first
choice whenever failure is driven by a chemical or diffusion process that
temperature speeds up.

```
φ(S) = b · exp(a / S)
```

`a` is the activation energy over Boltzmann's constant (Ea/k, in kelvin), and is
positive for a mechanism that temperature accelerates; `b` is the extrapolated
life at infinite temperature and mostly just sets the scale.

**Use it for** insulation, lubricants, electronics, adhesives, batteries —
anything that ages chemically. **Watch out:** stress must be in **kelvin**, and
the acceleration factor between two temperatures is `exp(a·(1/S₁ − 1/S₂))`,
which is very sensitive to `a`. Report an interval on it, not a point.

## eyring

**A thermal model from reaction-rate theory** with an extra `1/S` term that
Arrhenius omits — the more physically complete derivation.

```
φ(S) = (1/S) · exp(a/S − b)
```

**Use it as** the principled alternative to Arrhenius when you want the
theoretical form, or as a check: if Arrhenius and Eyring extrapolate to
noticeably different use-level lives, your data doesn't reach far enough down to
distinguish them, and that gap is a fair measure of your extrapolation risk.
**Watch out:** over any practical temperature range the two are nearly
indistinguishable in fit, so don't choose between them on AIC alone.

## inverse_power

**The standard non-thermal model.** Life falls as a power of stress — the
classic relationship for voltage, mechanical load, pressure and vibration.

```
φ(S) = 1 / (a · S^n)
```

`n` is the acceleration exponent: doubling the stress divides life by `2^n`. It
is the number to quote, and the one an engineer will recognise.

**Use it for** dielectric breakdown, bearing load, fatigue under stress
amplitude, pressure cycling. **Watch out:** as a power law it has no natural
limit — extrapolating far below your lowest tested stress predicts enormous
lives with no physical mechanism holding it up. Keep the extrapolation ratio
modest and say what it was.

## linear

**A straight line in stress.** No transformation, no log axis.

```
φ(S) = a + b · S
```

**Use it when** the physics genuinely is linear over the tested range, or as a
sanity check against a curved model. **Watch out:** nothing prevents `φ(S)`
going negative once you extrapolate, which is meaningless as a life. Of
everything here it is the least defensible for extrapolation — treat it as a
diagnostic rather than a prediction.

## dual_exponential

**Two stresses, both acting through reciprocal-exponential terms** — the
temperature–humidity (Peck-style) model.

```
φ(S₁, S₂) = c · exp(a/S₁) · exp(b/S₂)
```

**Use it for** temperature and humidity together, the standard combination for
electronics and coatings. **Watch out:** your test matrix must actually vary
both stresses independently. If humidity was only ever raised at high
temperature, the two coefficients cannot be separated and the intervals on them
will be wide — or worse, narrow and wrong.

## power_exponential

**Temperature plus a non-thermal stress** — exponential in the first, power law
in the second.

```
φ(S₁, S₂) = c · exp(a/S₁) · S₂^n
```

**Use it for** temperature with voltage, load or current — the most common
two-stress combination after temperature–humidity. Read `a` as the thermal
activation term (S₁ in kelvin) and `n` as the acceleration exponent on the
second stress.

**Watch out:** the order matters. The **first** stress column is the thermal
one; swapping them fits a model that is mathematically valid and physically
meaningless.

## dual_power

**Two stresses, both power laws.**

```
φ(S₁, S₂) = c · S₁^m · S₂^n
```

**Use it when** neither stress is thermal — load and speed, pressure and flow,
amplitude and frequency. **Watch out:** the same open-ended extrapolation
warning as the single inverse power law, now compounded across two dimensions.
Extrapolating both stresses at once moves you further from the data than either
margin suggests.
