---
date: 2026-11-11
link: /guides/check-a-requirement-and-plan-a-test
image: /guides/img/req-03-sequential.png
---
A fixed-length reliability test decides after a set amount of test time. A sequential test checks after every failure and stops as soon as the answer is clear.

Reliafy's worked example: show an MTBF of 1,000 hours at 90% confidence, where a good design has 2,000. The fixed-length test needs 20,100 hours of total test time. The sequential test decides for a good design after about 10,800 hours on average.

The catch: you don't know in advance when it will stop. Budget for the longest, here 20,100 hours or 15 failures.
