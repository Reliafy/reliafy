---
title: "Find the optimal replacement interval"
task: "How often should I replace this component to minimise cost?"
category: "Maintenance strategy"
prerequisites: "A fitted life model, and the cost of a planned replacement versus an unplanned failure."
related_href: "/strategy/replacement"
related_label: "Open optimal replacement"
order: 20
---

This is the calculation that turns a reliability model into a maintenance
decision, and it answers a question every maintenance planner has argued about:
*how often should we change this thing out?*

Replace too often and you're throwing away good life and paying for outages you
didn't need. Replace too rarely and you're paying for failures — which cost more,
because they happen at the worst possible moment and take other things with them.
Somewhere between those is a minimum, and if you know the life distribution and
the two costs, you can find it rather than argue about it.

## What you need

Go to **Strategy → Optimal replacement** and pick a saved model. Then supply two
numbers:

- **Planned replacement cost** — what it costs to change the component out on
  your terms, during a planned window.
- **Unplanned (failure) cost** — what it costs when it fails in service.

The absolute values matter less than the **ratio** between them. A 10:1 ratio
pushes toward frequent preventive replacement; a 1.5:1 ratio means failures
barely cost more than planned changes, so there's little to gain by pre-empting
them.

Be honest about the unplanned figure. It isn't just the part and the labour — it's
the lost production, the collateral damage, the callout at 3am, the expedited
freight, and the safety exposure. Most people undercount it dramatically, and
that single number moves the answer more than anything else on the page.

## The result, and when there isn't one

Reliafy computes the **long-run cost rate** across candidate intervals and finds
the minimum — the interval at which the cost per unit time is lowest — and
compares it against the cost of simply running the component to failure.

Sometimes the honest answer is **don't replace preventively at all**, and the
tool will tell you so. That happens whenever the component isn't wearing out. If
your Weibull β is around 1, the failure rate is constant: a new unit is exactly
as likely to fail as an old one, so swapping a working component for a fresh one
buys you nothing and costs you a replacement. If β is *below* 1, scheduled
replacement is actively harmful — you'd be removing survivors and installing the
riskiest units you have.

This is why the fitted model matters so much here. Preventive replacement only
pays when there's wear-out to pre-empt, and the shape parameter is what tells
you whether there is. A schedule set by habit or by a vendor's default interval
has no way of knowing.

## Where to go next

If the component is inspected rather than replaced on a schedule — you're
looking for a hidden failure rather than pre-empting a visible one — the
**failure-finding interval** calculator under Strategy is the right tool
instead.

If you want to know how many failures to *expect* across a fleet over the next
year, rather than when to replace one item, that's fleet forecasting.

And if you're deciding among several candidate policies, save each analysis —
Reliafy keeps them under Strategy → Saved analyses so you can compare and cite
them later, which matters when someone asks in six months why the interval is
what it is.
