---
title: "Build and share a library of data and models"
task: "How do I keep datasets and models together, share them with another team, or publish them?"
category: "Getting started"
prerequisites: "A saved dataset or model to add. Anyone can browse public libraries and the built-in handbooks."
related_href: "/libraries"
related_label: "Open Libraries"
order: 46
---

A library is a named collection of datasets and models. Keep one for a site, a
test programme or a family of equipment, share it with other workspaces, or
publish it for anyone to use. Open **Libraries** in the menu to see
[all libraries](/libraries): yours, those shared with you, and the public ones,
which include the built-in handbooks.

## Make a library

On [All libraries](/libraries), choose **New library…**. Give it a name and one
line on what it holds. You can also say where its contents come from (the
source), how to cite it, and any notes. **Edit…** on the library's page changes
these later.

## Upload a spreadsheet straight into a library

On your library's page, choose **Add…** › **Upload data…**. It opens the same
**New dataset** screen as [Data](/data): pick the file (and the sheet), check how
the columns are read (x, c, n and the rest), and, if one column names each
group, choose it under **Split into datasets by** to make one dataset per value.
The library is already chosen under **Also add to library**, so saving makes
every dataset and adds each one to the library in the same step: all of them,
or, if anything stops it, none. You land back on the library with the new
entries listed.

**New dataset** on the Data page has the same **Also add to library** choice
(one of your libraries, or a new one).

## Add data and models

Open a dataset or a model and choose **Add to library…** from its ⋯ menu. It
works for any dataset and any kind of model: non-repairable, repairable and
accelerated life; fitted to data, entered from parameters, taken from a handbook
or built as a prior. Pick one of your libraries, or make a new one in the same
step.

The library keeps a copy as it is now. Later edits to the dataset or model in
your workspace don't change the copy, so a library stays what you checked. When
you do want the newer version, choose **Update from the original** on the entry:
its version number goes up by one. Nothing is ever added to a library for you.

On a library's page each entry opens in place to show more:

- a **dataset** shows how its columns are read (for example *x = Age (hours) ·
  c = Status*), how many rows it has, and a preview of its first rows;
- a **model** shows its headline (for example a B10 life with its 90% lower
  bound), its parameters, and where it came from: **Fitted on ↑** the dataset,
  when that dataset is in the same library, or words such as *From parameters*
  or *From MIL-HDBK-217F*.

Filter the entries by kind, by tag or by words. **Libraries › Data** and
**Libraries › Models** list every dataset or model in every library you can
see, each with its library.

## Share it with other workspaces

On your library's page, choose **Sharing…** and pick one of three choices:

- **Private**: your workspace only. This is where every library starts.
- **Shared with workspaces**: add each workspace's ID. They can view the
  library and copy from it; only you can change it. Each person finds their own
  workspace ID, with a **Copy** button, on their All libraries page.
- **Public**: anyone can view it, even without an account, and anyone signed in
  can copy from it.

## Publish it

Only public-domain, open or CC BY data may be published, each cited. To make a
library public you choose its licence (Public domain, CC0, CC BY 4.0, or *Our
own data, published under CC BY 4.0*), give its source and citation, and tick
**I have the right to publish this**. If anything is missing, the panel says
what. Once it's public, **Preview as public** shows the page as a visitor sees
it.

## Use an entry

**Use this data** or **Use this model** copies the entry into your workspace,
and the page links to the copy. A model fitted on a dataset in the same library
offers **Also copy the dataset it was fitted on**. A copy remembers where it
came from: its page says *From the library … (version n)*, with a link back.
Signed-out visitors see **Sign in to use** instead.

On the Free plan each library counts as one saved item, however many entries it
holds, and a copy counts as the dataset or model it makes.

## The built-in handbooks

The published handbooks (industry-average failure rates and probabilities on
demand, handbook base rates for electronic parts, and covariate models for
mechanical parts) are under Public, marked **Built-in**. Open one to filter its
records, and use a record as a model or as a prior in a fit. The
[Fit your first model](/guides/fit-your-first-model) guide describes them in
detail.
