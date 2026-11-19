---
title: "AI agents will read your failure data next: what to check"
date: 2026-11-16
author: The Reliafy Team
image: /blog/ai-agents-failure-data-card.png
summary: Agents are starting to pull maintenance history straight into reliability analyses. The checks that matter are old ones, from the censoring flag to MTBF on parts that wear out. What changes is how fast a mistake spreads, and how sure of itself it sounds.
linkedin: |
  AI agents can now read a work-order export and fit a Weibull in the same conversation. That's useful. It also means the old mistakes can run in every analysis, written up in fluent prose.

  Twenty gearboxes: 8 failed, 12 still running. Counted properly, the mean life is 7,100 hours. Read the status column the wrong way round: 6,267. Drop the running units: 5,515. Average the failure times and call it MTBF: 5,500. No step throws an error.

  Four checks to ask of any agent (or analyst) before you act on its answer, and two things it should never do silently.

  #ReliabilityEngineering #AI
---

AI agents can now connect to the systems that hold maintenance records, read a
work-order export, and run a Weibull fit in the same conversation. That is
useful. Cleaning up a CMMS export is the part of reliability work most
engineers like least, and an agent does it quickly.

The risk isn't that agents are worse at this than people. It's that they can
make the same mistakes people make in spreadsheets, faster, more often, and
written up in confident prose. A wrong number in a spreadsheet sits in one
file. A wrong habit in an agent runs in every analysis it touches, each with a
tidy summary on top.

None of the checks below are new. What's new is that they have to happen
before the answer is written, not after someone has acted on it.

## The example

Twenty conveyor drive gearboxes from a work-order history. Eight failed, at
2,100, 3,400, 4,300, 5,200, 5,900, 6,800, 7,600 and 8,700 hours. Twelve are
still running, at between 1,500 and 8,000 hours. Fit a Weibull by maximum
likelihood, counting all twenty, and the mean life is **7,100 hours** (95%
bounds 5,707 to 8,835), with a B10 of 3,978 hours. That is the reference. Every
figure here comes from [SurPyval](https://github.com/derrynknife/SurPyval),
which is open source, so you can check them.

## 1. The status column runs the wrong way

Most exports mark each row with a 0 or a 1. SurPyval and Reliafy read 0 as
failed and 1 as still running; plenty of spreadsheets use the opposite. Read
the column the wrong way round and the twelve running gearboxes become
failures, and the eight failures become survivors. The fit still converges. The
mean life comes out at **6,267 hours** and the B10 at 3,058 hours, 23% short.
Nothing errors.

**Check:** before any fit, ask for the count of failed and running units, and
compare it with what the site knows. "Twelve failed, eight running" for a
fleet that is mostly still in service means the column is upside down.

## 2. Units replaced while still running disappear

Gearboxes swapped at an overhaul while still working, and the ones still in
service today, are suspensions: they lasted at least that long. A "failure
history" often leaves them out by definition. Fit the eight failures alone and
the mean life is **5,515 hours**, 22% short, with a B10 of 2,913 hours. Average
the eight failure times and call it MTBF, and it's 5,500 hours. The
[Learn page on suspensions](/learn/censored-data-suspensions) shows why the
bias always runs this way.

**Check:** ask for every unit's time in service, failed or not, and ask how
many units the data left out.

## 3. Different populations pooled into one

Take two illustrative batches of 20 gearboxes, generated from known lives. One
supplier's batch has an early-failure problem (Weibull shape 0.93, B10 267
hours). The other is healthy and wears out (shape 3.62, B10 4,829 hours). Pool
all 40 and fit one Weibull: shape **1.25**, B10 977 hours.

The pooled shape says "failures are roughly random", which is true of neither
batch. The B10 is 3.7 times too long for the bad batch and nearly 5 times too
short for the good one. Worse, it points away from the fix: the answer is the
supplier, not the replacement interval. Later this month we look at a public
dataset with this pattern.

**Check:** before pooling, split by anything that could differ (supplier,
batch, site, duty, failure mode) and
[compare the groups](/guides/compare-groups).

## 4. MTBF quoted for parts that wear out

Say gearbox life follows a Weibull with a shape of 3 and a scale of 10,000
hours. The mean life is 8,930 hours. Quote that as an MTBF and anyone reading
it will assume a constant failure rate: about **20%** failing in the first
2,000 hours. The Weibull says **0.8%**, a 25th as many. For wear-out, an MTBF
says how long parts last on average, but nothing about when they fail. See
[MTBF vs MTTF](/learn/mtbf-vs-mttf).

**Check:** ask for the shape before the MTBF. A shape well above 1 means the
failure rate rises with age, and a single rate misleads.

## What an agent should never do silently

Some things an agent should refuse to do without saying so.

**Invent failure data.** When a block in a model has no data, the honest
options are to ask, or to use a stated guess marked as a guess. A "typical
MTBF" recalled from memory and dropped into a model as if it were measured is a
made-up input.

**Wire redundancy in series.** Two pumps, each 90% likely to last the year,
either of which can do the job: the pair is 99% likely to keep the duty
running. Drawn in series, the diagram says 81%, and the redundancy you paid
for has vanished from the model.

The same goes for leaving out the confidence bounds and the time unit. Eight
failures support a mean life of 7,100 hours, but only to within 5,707 to 8,835.
An answer without its bounds and its unit (operating hours or calendar hours?)
is only half an answer.

## What we do, and what it doesn't fix

Reliafy's tools for AI agents come with a short set of instructions every agent
receives when it connects: 0 means failed and 1 still running, with a switch
for spreadsheets that use the opposite; always state the time unit; never
invent failure data, but ask, or mark a guess as a placeholder; quote bounds
with the point values. None of this is unique to us, and it shouldn't be. Any
tool that lets an agent fit failure data ought to say the same.

It isn't a guarantee, either. An agent can still misread a column, just as a
person can. Instructions make the right habit the default; they don't replace
the engineer reading the counts.

## What to do on Monday

- Ask for the count of failed and running units before any fit.
- Ask what was left out, and why.
- Split before you pool.
- Ask for the shape before the MTBF.
- Ask what was assumed: the unit, the clock, any guessed inputs.

These are the checks good engineers already make. The difference with an agent
is that you can ask it to show them every time, and you should.
