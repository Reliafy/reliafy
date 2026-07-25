---
title: "Model system availability (repairable RBD)"
task: "How do I build a repairable reliability block diagram and read its availability?"
category: "Reliability block diagrams"
minutes: 4
prerequisites: "A system you can sketch as blocks, and a failure and repair estimate for each block."
related_href: "/rbds/b"
related_label: "Open the RBD builder"
order: 30
---

Use this when your system is **repaired and put back into service** and you care
about uptime. A repairable diagram gives every block a failure *and* a repair
distribution, and reports the system's **availability** — the long-run fraction
of time it's working — plus which components drive the downtime.

1. Open **RBDs** in the sidebar and click **New diagram**.

   ![The RBD builder with an empty canvas](/guides/img/availability-01-new.png)

2. In the top-left, set **System** to **Repairable · availability**. The diagram
   is now in availability mode — every component will need a repair time.

   ![The System selector set to Repairable · availability](/guides/img/availability-02-system.png)

3. Right-click the canvas and choose **Add component** for each part of your
   system. Give them names by double-clicking the title.

   ![Adding component blocks from the right-click menu](/guides/img/availability-03-add.png)

4. **Double-click a component** to open its models. Set the **life model** (time
   to failure) and the **repair-time distribution** (time to repair) — a
   lognormal mean-time-to-repair is the usual choice.

   ![The component dialog with a life model and a repair-time distribution](/guides/img/availability-04-models.png)

5. Drag from the **input** handle through your components to the **output** to
   wire the diagram. Put redundant units in parallel (both feeding the output).

   ![A controller in series with two redundant pumps, wired input to output](/guides/img/availability-05-wired.png)

6. Switch to the **Calculate** tab and press **Validate**. A repairable diagram
   is valid once every component has both a life model and a repair time.

   ![The validation panel showing the diagram is valid](/guides/img/availability-06-validate.png)

7. Press **Calculate**. You'll get the headline **steady-state availability**
   (uptime %), the mean up and down times, and a **"what drives downtime"** bar
   for each component — the parts to fix first.

   ![The availability results: 99.5% uptime and per-component downtime bars](/guides/img/availability-07-results.png)

**Result:** a saved repairable RBD reporting system availability. To learn the
theory behind the numbers, see the Learn article on
[system availability](/learn/system-availability).
