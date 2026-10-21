# SCADA Digital-Twin Security — IEEE paper (LaTeX / Overleaf)

IEEE conference-format paper (`IEEEtran`, two-column) with TikZ diagrams, a
pgfplots results chart, a results table, and four real screenshots of the
running platform.

**Authors:** S. Saurabh Krishnan, Hemant Bhupesh, Sanjai S, Nitesh V. M.
(Amrita Vishwa Vidyapeetham, Coimbatore, India)

## Files
```
main.tex              the paper (compiles with pdfLaTeX)
figures/
  plant_overview.jpg     Fig. 3 — live operator HMI (P&ID)
  network_topology.jpg   Fig. 5 — Purdue-zoned network + live traffic
  twin_divergence.jpg    Fig. 4 — twin predicted vs observed under attack
  security_center.jpg    Fig. 6 — IDS alerts, incident, auto-response
```
The **architecture diagram (Fig. 1)**, the **per-tick data-flow flowchart
(Fig. 2)** and the **results bar chart (Fig. 7)** are drawn with TikZ/pgfplots,
so no extra image files are required for them.

## Compile on Overleaf (recommended)
1. Go to Overleaf → **New Project → Upload Project** and upload
   `SCADA_paper_overleaf.zip` (or upload `main.tex` and the `figures/` folder).
2. Set the compiler to **pdfLaTeX** (Menu → Compiler → pdfLaTeX) — this is the default.
3. Click **Recompile**. No extra packages are needed; everything used
   (`IEEEtran`, `tikz`, `pgfplots`, `booktabs`, `hyperref`) ships with Overleaf.

## Compile locally
```bash
pdflatex main.tex
pdflatex main.tex    # run twice so cross-references resolve
```
Requires a TeX distribution (TeX Live or MiKTeX) with `IEEEtran`, `tikz` and `pgfplots`.
