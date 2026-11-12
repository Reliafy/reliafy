---
title: "Handle censored data (units that haven't failed)"
task: "How do I include units that are still running, or failed between inspections?"
category: "Life data modelling"
prerequisites: "A dataset where not every unit has failed, or where failure times aren't exactly known."
related_href: "/models/new"
related_label: "Fit a model"
order: 5
---

This is the single most common thing people get wrong with life data, and it's
worth getting right before anything else, because it doesn't produce an error —
it produces a plausible-looking model that's simply pessimistic.

Here's the situation. You pull records for 30 pumps. Eighteen have failed, at
known times. Twelve are still running. What do you do with the twelve?

The two instinctive answers are both wrong. **Deleting them** throws away real
evidence — you know those units survived a long time, which is information about
reliability, and dropping it biases you toward the units that failed early.
**Treating their current age as a failure time** is worse: you're recording
failures that didn't happen, which makes your equipment look far less reliable
than it is.

The right answer is to tell the model that those units survived **at least** that
long. That's censoring, and it's handled properly in the likelihood — the
survivors contribute exactly the information they actually carry.

## Right censoring: still running

This is the ordinary case above. Add a column flagging which rows are failures
and which are survivors — conventionally `0` for a failure, `1` for
right-censored:

```
hours,censored
312,0
420,0
506,0
2000,1
2000,1
```

When you upload the data under [Data](/data) → **New dataset**, choose that
column for **c** (*failed or still running*): the dataset keeps it, and every
model built from it reads it the same way. Reliafy reads `0` as failed and `1` as still running; if your file
uses `1` for a failure, tick **my column uses 1 = failed**. A column of words
such as `Failed` and `Running` is read for you, and the line under **c** shows
how (*Failed → 0, Running → 1*), with a switch to flip any one. So a file works
as it is. That's the whole change,
and it will often move your fitted life substantially.

The sample pump model is exactly this case: 25 pumps, 18 failed and 7 still
running. Its Weibull fit puts the characteristic life at **32.7 months**, with
the survivors counted properly.

![A right-censored Weibull fit — the survivors are counted properly](/guides/img/censored-01-model.png)

Right censoring covers more cases than people realise: units still in service,
units removed for an unrelated reason, units that survived to the end of a test,
and units whose records simply stop.

## Interval censoring: failed somewhere between inspections

Often you don't observe failures as they happen — you inspect monthly and find
something already broken. You know it failed *between* the last two inspections,
but not when.

Recording the inspection date as the failure time systematically overstates
life. Instead, give both bounds. On the upload's **x** row (or **Change** on a fit), choose the
columns for the range: **xl** (the last value it was seen working) **to xr**
(the value it was found failed). A row with no **x** is read from its range:

```
xl,xr
30,60
60,90
```

The unit failed somewhere in that window, and the model accounts for the
uncertainty rather than pretending the failure happened at the moment you looked.

Two columns named like `last_ok_hours` and `found_failed_hours` (or `xl` and
`xr`, earliest and latest, lower and upper) are read this way for you.

A sheet can mix the two: an exact value in **x** on some rows, and **x** left
blank with a range on others. Map all three and each row is read on its own. A
row with **x** *and* both range cells filled says two things at once, so it is
left out of the fit, and the step says how many rows and which ones.

### Units that passed their last inspection

Most inspection records also hold units that never failed. Write them any of
these ways, and they count as still running at the earliest time:

- leave the latest time blank;
- repeat the same time in both columns, beside a status column that says the
  unit is still running (`S`, `Running`, or the code `1`).

```
last_ok_hours,found_failed_hours
400,600
600,800
1000,
```

A blank earliest time means the unit was found failed at its first inspection.
On the fit's **Model** step, under the dataset's reading, Reliafy counts what it read, for example "23 failed
between inspections, 2 found failed at the first inspection, 15 still running":
check that line before you fit. With no status column, a row with the same time
twice is read as a failure at exactly that time, and the step says so.

## Left censoring: already failed when first observed

If a unit had already failed by the time you first checked, you know only that
its life was *less than* that time. Flag it with `-1` in the censoring column:
the line under **c** shows it as **Found failed (left-censored)**.

## Truncation: a different thing entirely

Truncation is often confused with censoring, but it's a distinct problem.
Censoring means a unit is in your dataset with an imprecisely known life.
Truncation means units are **missing from your dataset altogether** because of
how it was collected.

The classic case: you only have warranty records, so units that failed after the
warranty expired never appear. Or you started recording in 2020, so anything that
failed before then is absent. Your sample isn't representative, and a model that
doesn't know this will be biased.

On the upload (or **Change** on a fit), choose the column for **tl** (*late entry: observed only from
this value*) and, when records also stop, the column for **tr** (*observed only
up to this value*), and the fit corrects for the observation window. Both are in
the same unit as **x**, and each row has its own: a blank cell is no limit on
that row. A column named like *Entered at (h)* is read as late entry from the
start. A row whose value is above its **tr**, a unit still running at its
**tr**, or a **tr** below its **tl** is shown beside **tr** with the rows, to
correct before the fit.

## Counts

If one row stands for several identical units — "5 pumps, all failed at 1,000
hours" — choose that column as the **Count** rather than duplicating rows.
Combining the censoring column and a count is the compact way to express a big
fleet: one row for the failures at each time, one row for the survivors.

## How to tell it's working

The fit's **Model** step sums it up under the reading (*18 failures, 7 still running* for
the pump sample), so you can see at once whether the codes are the right way
round: a fit where nearly every row is "still running" almost always means they
aren't.

Fit the same data with and without the censoring column chosen and compare. The
censored fit will show a longer characteristic life — often dramatically so — and
that difference is the reliability your equipment actually has and was previously
being denied.

If your fitted life looks lower than operational experience suggests, unmapped
censoring is the first thing to check.

## Where to go next

The mathematics — how each censoring type enters the likelihood, and worked
examples — is in the Learn article on
[censored data and suspensions](/learn/censored-data-suspensions).
