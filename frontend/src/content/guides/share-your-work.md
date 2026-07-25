---
title: "Share models and diagrams with other people"
task: "How do I show a colleague my analysis, or work on it as a team?"
category: "Getting started"
prerequisites: "Something saved — a model, diagram, or analysis."
related_href: "/modelling/models"
related_label: "Open saved models"
order: 45
---

An analysis nobody sees doesn't change a maintenance decision. Reliafy has three
ways to get your work in front of other people, and they suit genuinely different
situations.

## A public link — for people who don't have Reliafy

Open any saved model, diagram, or analysis and use **Share → public link**. You
get a URL that anyone can open, with no account and no sign-in, showing a
read-only view of the result.

This is the right choice for a contractor, a vendor, a regulator, or a manager
who is never going to create an account. It's also the answer to "can you send me
the report" — the link *is* the report, and unlike a PDF it doesn't go stale in
someone's inbox: reopen it later and it reflects the current state of the
analysis.

Treat the URL as the access control. Anyone holding it can view, so share it as
deliberately as you'd share the file itself.

## Sharing with a named person — for a specific colleague

Also under **Share**, you can share an individual artifact with someone by email
address. They see it, view-only, inside their own Reliafy account.

This suits the one-off: a colleague who needs to review your bearing model, but
who shouldn't be pulled into your whole workspace. If they don't have an account
yet, creating one with that email address picks up the share automatically.

## A team workspace — for people you work with continuously

The other two are for showing finished work. A **team** is for doing work
together.

Create one from the workspace switcher at the top right, and everything created
inside it belongs to the team rather than to you — datasets, models, diagrams,
studies. Members see it all, and the switcher moves you between your personal
workspace and any teams you belong to.

This is what you want when reliability is a shared responsibility: the models
outlive whoever built them, and the person covering next month doesn't have to
ask you to re-send anything.

A note on plans: creating a team and editing team content needs Pro, but invited
members can view team content on a free account. So a Pro engineer can bring in
as many reviewers as they like without everyone needing a plan.

## Copying an ID

Every saved artifact shows a copyable **ID** chip under its title. That's what
you use with the [API](/api-docs) or the Python client to fetch a specific model
programmatically — useful when you're pulling results into a notebook, a report,
or another system.

## Which one to use

Roughly:

- **Public link** — someone outside your organisation, or anyone who won't sign
  in.
- **Direct share** — one named colleague, one artifact, view-only.
- **Team** — ongoing shared ownership of a body of work.

Public links and direct shares are both read-only. If you want someone to *edit*,
that's a team.
