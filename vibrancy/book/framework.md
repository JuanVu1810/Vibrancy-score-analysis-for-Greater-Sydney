# The framework

This chapter is the map of the method: what the index measures, the steps it goes through in order, and the chapter that covers each step.

## What the index measures

The index ranks the 373 Greater Sydney SA2s by the conditions associated with lively, varied, walkable areas. It is built from
three parts, called pillars, described in [The three pillars](pillars.md):

- **Intensity:** how much is there (businesses, stops, homes and other destinations).
- **Diversity:** how varied it is (the mix of industries and of land uses).
- **Design:** how fine-grained and pedestrian-friendly the streets are (intersections and crossings).

The index is a proxy. It counts the things that make street activity possible. It does not count the people, because nothing in the data
records how many people are actually there. A high score means an area has the ingredients, not that it is busy.

## The steps

The OECD handbook on composite indicators (OECD, 2008) describes building an index as ten steps. The Urban Liveability Index for Melbourne was
informed by the same guide (Higgs et al., 2019). This index goes through the steps in order. The handbook is guidance, not a formula, so the
table also says where this index differs from it.

| Step | What is done | Chapter |
|---|---|---|
| 1. Theoretical framework | The conditions for vibrancy are intensity, diversity and design | [The three pillars](pillars.md) |
| 2. Data selection | Fourteen indicators, each with a stated reason. Every dataset becomes one number per SA2 by explicit spatial rules | [Indicators and formulas](indicators.md), [Spatial assignment rules](spatial-rules.md) |
| 3. Imputation of missing data | One simple rule, and no imputation | [The score](score.md) |
| 4. Multivariate analysis | A correlation matrix of the fourteen indicators, and each pillar's correlation with the index, to see whether indicators overlap. Principal components analysis is not used | [Checks](checks.md) |
| 5. Normalisation | Log transform, then z-scores | [The score](score.md) |
| 6. Weighting and aggregation | Equal weights: a mean within each pillar, then a mean across the three pillars | [The score](score.md) |
| 7. Uncertainty and sensitivity analysis | A handful of alternative runs of the whole calculation | [Checks](checks.md) |
| 8 and 9. Back to the data, and links to other indicators | The top and bottom areas, and comparisons with income and with measured pedestrian counts | [Checks](checks.md) |
| 10. Visualisation of the results | The data story, an interactive page with a map and charts | The data story page |

## Where this index differs from the handbook

- **Steps 8 and 9 are done together.** Both look at the finished scores, so they share one part of the checks.
- **No principal components analysis.** The handbook suggests it for studying the structure of the indicators and for deriving weights. Here the
  weights come from the stated framework (equal across the three pillars), and the structure is examined with a correlation matrix, which is
  easier to read and to explain. Higgs et al. (2019) also considered principal components and factor analysis and chose against them, to keep the
  index explainable to people without a statistics background. With 373 areas and fourteen indicators the sample is large enough for the
  correlation check. Whether any overlap between indicators needs action is reported in [Checks](checks.md).
- **Further analyses sit outside the ten steps.** Place types, hot spots and equity of access use the finished index rather than help build it.
  They are described in [Checks](checks.md).
