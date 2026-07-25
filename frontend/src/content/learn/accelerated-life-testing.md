---
title: "Accelerated life testing (ALT): extrapolating to use conditions"
description: "ALT tests units at elevated stress to fail them faster, then extrapolates back to normal use with a life-stress model. Here are the Arrhenius, inverse-power and Eyring relationships, the acceleration factor, and a worked temperature example."
cta_text: "Reliafy fits accelerated-life models — pick a distribution and a life-stress relationship, and extrapolate to your use-level stress with the acceleration factor and a use-level reliability calculator."
cta_label: "Fit an accelerated life model"
cta_href: "/reliability-analysis-software"
---

**Accelerated life testing runs units at higher-than-normal stress so they fail
in weeks instead of years, then extrapolates the result back to normal
operating conditions.** You can't wait ten years to learn whether a component
lasts ten years — so you raise the temperature, voltage, or load until failures
arrive on a testable timescale, fit a model that ties life to stress, and read
off the life you'd see at the use level.

The whole method rests on one assumption: that raising the stress **speeds up
the same failure mechanism** without introducing a new one. Bake a capacitor too
hot and you stop learning about its field failures and start learning about a
mode that never happens in service. Chosen well, though, ALT is the only
practical way to characterise long-lived products.

## The life-stress relationship

An ALT model has two parts: a **life distribution** (Weibull, lognormal, …) that
describes the scatter in failure times at any fixed stress, and a **life-stress
relationship** `L(S)` that says how the distribution's characteristic life
shifts as the stress *S* changes. The shape stays the same across stresses; the
scale slides. The common relationships:

- **Arrhenius** — for thermal ageing, driven by absolute temperature *T* (in
  kelvin):

  ```
  L(T) = A · exp(Ea / (k · T))
  ```

  where *Ea* is the activation energy and *k* is Boltzmann's constant. Life
  falls exponentially as temperature rises.

- **Inverse power law** — for voltage, load, or pressure:

  ```
  L(V) = A · V^(−n)
  ```

  Doubling the stress cuts life by a factor of 2ⁿ.

- **Eyring** — a thermodynamically-derived thermal model, a physically grounded
  alternative to Arrhenius, and the base for combined temperature-plus-another-
  stress models.

For two stresses at once (temperature *and* voltage, temperature *and*
humidity), dual relationships such as temperature-nonthermal and the
dual-exponential (Peck) model extend the same idea.

## The acceleration factor

The single most useful number ALT produces is the **acceleration factor** — how
much faster the clock runs at the test stress than at use:

```
AF = L(use) / L(test)
```

If a unit's characteristic life is 200 hours at the test stress and 20,000
hours at the use stress, AF = 100: one hour on the bench buys a hundred hours of
field life. It also tells you how to plan the test — to demonstrate a 10,000-hour
use life at AF = 100, you need units to survive ~100 hours on test.

## A worked temperature example

Suppose you test a component at three temperatures and fit an Arrhenius-Weibull
model, getting these characteristic lives:

```
 60 °C (333 K):  ~12,000 h
 85 °C (358 K):  ~3,200 h
110 °C (383 K):  ~950 h
```

Life is dropping by roughly 3–4× per 25 °C — the signature of thermal
acceleration. The fitted Arrhenius line lets you extrapolate *below* the tested
range to a 40 °C (313 K) use condition, giving a use-level characteristic life
and, from the acceleration factor against your test point, exactly how much lab
time represents a given field life. Because the Weibull shape β is shared across
temperatures, the *whole* reliability curve — not just the mean — transfers to
the use condition, so you can read B10 life, mean life, and reliability at any
mission time at 40 °C.

## Reading the fit critically

Two checks separate a trustworthy ALT model from a plausible-looking one. First,
plot the failures at each stress on the distribution's **probability paper**: a
good fit shows the points at every stress level hugging *parallel straight
lines* — parallel because the shape is shared, straight because the distribution
is right. Fanning or curving lines mean the shape isn't really constant across
stress, and the extrapolation is on thin ice. Second, sanity-check the implied
physics: an Arrhenius activation energy far outside the 0.3–1.5 eV range that
most mechanisms fall in is a warning that you may be fitting more than one
failure mode.

## Frequently asked questions

### What is accelerated life testing?
A method that subjects units to stress levels higher than normal use —
temperature, voltage, load, humidity — so they fail quickly, then fits a
life-stress model to extrapolate the failure behaviour back to normal
conditions. It's how you characterise the reliability of long-lived products
without waiting for their full life.

### What is the acceleration factor?
The ratio of life at the use stress to life at the test stress, `AF =
L(use)/L(test)`. It's the multiplier between bench time and field time: an
AF of 50 means each test hour represents 50 hours of service life.

### Which life-stress model should I use?
Match the model to the dominant stress and mechanism: Arrhenius (or Eyring) for
temperature-driven ageing, inverse power law for voltage/load/pressure, and a
dual model when two stresses act together. The failures on probability paper and
the physical plausibility of the fitted parameters tell you whether the choice
holds.

### How is ALT different from an ordinary life-data fit?
An ordinary fit uses failures at a single operating condition. ALT fits failures
gathered across several elevated stresses and adds a life-stress relationship, so
it can extrapolate to a use level you never actually tested — the thing a
single-condition fit cannot do.
