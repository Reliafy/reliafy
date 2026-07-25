---
title: "Add a common-cause group"
task: "How do I couple redundant components that share a failure cause?"
category: "Reliability block diagrams"
minutes: 3
prerequisites: "A non-repairable RBD with two or more redundant components that share a cause."
related_href: "/rbds/b"
related_label: "Open the RBD builder"
order: 31
---

Redundancy only helps if the redundant units fail **independently**. When they
share a cause — same batch, power supply, environment, or maintenance crew — a
common-cause group tells Reliafy to include the shared-cause failures that plain
parallel math ignores. This is a **reliability** (non-repairable) feature.

1. In a non-repairable diagram, **shift-click** two or more redundant components
   to select them. A **Common-cause group** button appears at the top of the
   canvas.

   ![Two redundant pump blocks selected, with the Common-cause group button showing](/guides/img/ccf-01-select.png)

2. Click **Common-cause group**. Set the **β-factor** — the fraction of each
   component's failures that are shared-cause (typically 1–20%). The read-out
   explains what your value means.

   ![The common-cause modal with a beta-factor slider set to 0.10](/guides/img/ccf-02-beta.png)

3. Create the group. The members now show a **"CC β=…"** chip and a shared halo,
   and the group is listed bottom-left where you can edit β or ungroup.

   ![Grouped components with CC chips and the groups panel](/guides/img/ccf-03-grouped.png)

4. Go to **Calculate → Validate**, then **Calculate**. The results lead with the
   impact: **"Common cause cuts system reliability at the design point from X% to
   Y%."**

   ![The results showing the common-cause reliability impact callout](/guides/img/ccf-04-impact.png)

**Tip:** the β-factor model assumes the grouped units are *identical*. If their
life models differ, Reliafy warns you on Validate — give them the same model for
a meaningful result.

**Result:** an RBD whose reliability honestly reflects the shared cause. The
theory is in the Learn article on
[common-cause failure](/learn/common-cause-failure).
