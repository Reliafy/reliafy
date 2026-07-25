---
family: regression
title: "Regression models"
description: "Life as a function of covariates — proportional hazards, accelerated failure time, proportional odds and additive hazards, across seven baseline distributions plus Cox."
---

These answer a different question from a plain distribution: not *how long does
this last?* but **what changes it?** Temperature, load, supplier, operating mode
— a covariate is anything you recorded alongside the failure time that might
matter.

Every model here pairs a **baseline distribution** with an **effect type**, and
it's the effect type that determines how you read the coefficients. Reliafy
reports each coefficient with a 95% interval; an interval spanning zero means
the data can't distinguish that covariate from no effect.

### Proportional hazards (`*_ph`)

Covariates multiply the hazard by a constant factor at every age.

```
h(t | z) = h₀(t) · exp(β·z)
```

`exp(β)` is the **hazard ratio**: 1.5 means 50% more failure rate per unit of
that covariate, at any age. The key assumption is *proportionality* — the ratio
doesn't change over time. If a covariate matters more to old units than new
ones, that assumption is violated and the fit will average the two.

### Accelerated failure time (`*_aft`)

Covariates stretch or compress the time axis, as though the clock runs faster.

```
t(z) = t₀ · exp(−β·z)
```

`exp(β)` is a **time ratio**. This is the natural frame for stress: doubling the
load doesn't just raise the instantaneous risk, it makes everything happen
sooner. It's also the model underneath accelerated life testing and
load-sharing.

### Proportional odds (`*_po`)

Covariates multiply the *odds* of failure rather than the hazard.

```
F(t|z)/R(t|z) = exp(β·z) · F₀(t)/R₀(t)
```

`exp(β)` is an **odds ratio**. Useful when effects appear to converge over time
— proportional odds allows hazard ratios that shrink toward 1 with age, which
proportional hazards cannot.

### Additive hazards (`*_ah`)

Covariates add to the hazard instead of scaling it.

```
h(t | z) = h₀(t) + β·z
```

Coefficients are read on the hazard's own scale (excess failures per unit time),
not as a ratio — which is often the more natural quantity for risk attribution.
**Watch out:** nothing constrains the total hazard to stay positive, so a large
negative coefficient can drive the cumulative hazard below zero and push
reliability above 1. Reliafy warns you when that happens; the fix is to choose a
different effect type rather than to trust the numbers.

### Choosing between them

Start with proportional hazards — it's the convention, and the hazard ratio is
the most widely understood output. Move to AFT when the covariate is a stress
and you think in terms of accelerated clocks, to proportional odds when effects
fade with age, and to additive hazards when you want excess risk rather than a
ratio. If you only care about *whether* a covariate matters and not about
absolute lives, `cox_ph` makes the fewest assumptions of all.


## weibull_ph

A Weibull baseline — the usual choice, since its shape parameter already spans infant mortality, random and wear-out behaviour. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## exponential_ph

A constant-hazard baseline. The simplest option: all age-dependence is assumed away, so the covariates carry the entire story. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## lognormal_ph

A lognormal baseline — right-skewed, with a hazard that rises then falls. Suits fatigue and degradation-driven failure. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## normal_ph

A Normal baseline — symmetric with a steadily rising hazard. Fits tight wear-out, but admits negative times. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## gamma_ph

A Gamma baseline, appropriate when failure follows an accumulation of shocks or stages. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## logistic_ph

A logistic baseline — symmetric like Normal but heavier in the tails. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## gumbel_ph

A smallest-extreme-value baseline — the weakest-link case, and the log-scale relative of the Weibull. Covariates act by multiplying the hazard — see **proportional hazards** above for how to read the coefficients (hazard ratio).

## cox_ph

**Semi-parametric.** Estimates covariate effects *without* assuming any baseline shape — the baseline hazard is left completely unspecified and only the ratios are estimated.

Use it when you care about **how much a covariate matters** rather than about absolute lives: it makes the weakest assumption of anything here. The cost is that it can't give you an absolute reliability curve or an MTTF, because there's no baseline to integrate. Reach for a parametric PH model when you need those.

## weibull_aft

A Weibull baseline — the usual choice, since its shape parameter already spans infant mortality, random and wear-out behaviour. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## exponential_aft

A constant-hazard baseline. The simplest option: all age-dependence is assumed away, so the covariates carry the entire story. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## lognormal_aft

A lognormal baseline — right-skewed, with a hazard that rises then falls. Suits fatigue and degradation-driven failure. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## normal_aft

A Normal baseline — symmetric with a steadily rising hazard. Fits tight wear-out, but admits negative times. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## gamma_aft

A Gamma baseline, appropriate when failure follows an accumulation of shocks or stages. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## logistic_aft

A logistic baseline — symmetric like Normal but heavier in the tails. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## gumbel_aft

A smallest-extreme-value baseline — the weakest-link case, and the log-scale relative of the Weibull. Covariates act by scaling time to failure — see **accelerated failure time** above for how to read the coefficients (time ratio).

## weibull_po

A Weibull baseline — the usual choice, since its shape parameter already spans infant mortality, random and wear-out behaviour. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## exponential_po

A constant-hazard baseline. The simplest option: all age-dependence is assumed away, so the covariates carry the entire story. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## lognormal_po

A lognormal baseline — right-skewed, with a hazard that rises then falls. Suits fatigue and degradation-driven failure. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## normal_po

A Normal baseline — symmetric with a steadily rising hazard. Fits tight wear-out, but admits negative times. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## gamma_po

A Gamma baseline, appropriate when failure follows an accumulation of shocks or stages. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## logistic_po

A logistic baseline — symmetric like Normal but heavier in the tails. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## gumbel_po

A smallest-extreme-value baseline — the weakest-link case, and the log-scale relative of the Weibull. Covariates act by multiplying the odds of failure — see **proportional odds** above for how to read the coefficients (odds ratio).

## weibull_ah

A Weibull baseline — the usual choice, since its shape parameter already spans infant mortality, random and wear-out behaviour. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).

## exponential_ah

A constant-hazard baseline. The simplest option: all age-dependence is assumed away, so the covariates carry the entire story. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).

## lognormal_ah

A lognormal baseline — right-skewed, with a hazard that rises then falls. Suits fatigue and degradation-driven failure. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).

## normal_ah

A Normal baseline — symmetric with a steadily rising hazard. Fits tight wear-out, but admits negative times. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).

## gamma_ah

A Gamma baseline, appropriate when failure follows an accumulation of shocks or stages. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).

## logistic_ah

A logistic baseline — symmetric like Normal but heavier in the tails. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).

## gumbel_ah

A smallest-extreme-value baseline — the weakest-link case, and the log-scale relative of the Weibull. Covariates act by adding to the hazard — see **additive hazards** above for how to read the coefficients (additive effect).
