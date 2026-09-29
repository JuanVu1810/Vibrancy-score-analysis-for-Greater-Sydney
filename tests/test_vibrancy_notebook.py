"""Fast checks on the structure and wording of vibrancy_index.ipynb. The notebook is read as JSON, never run."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "vibrancy_index.ipynb"
NUMBERED_HEADING = re.compile(r"^## (\d+)\. (.+)$")
DISPLAYED_FIGURE = re.compile(r'^Image\(filename=str\(FIGURE_IMAGES / "([\w.]+)"\)\)$')
INTERNAL_WORDS = re.compile(r"\bphase\b|stop point|the brief|\bcodex\b|the owner|\bdecision \d", re.IGNORECASE)
PLOTTING_CODE = re.compile(r"matplotlib|\bplt\.|\.plot\(|\.hist\(|\.savefig\(")
FIGURE_ORDER = [
    "vibrancy_map.png", "vibrancy_intensity_map.png", "vibrancy_diversity_map.png", "vibrancy_design_map.png",
    "vibrancy_place_types.png", "vibrancy_hotspots.png", "vibrancy_moran.png", "vibrancy_distance.png", "vibrancy_equity.png",
    "vibrancy_rank_ranges.png", "vibrancy_foot_traffic_weekday.png", "vibrancy_foot_traffic_weekend.png",
]


def load_cells():
    """Return the cells of the notebook."""
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def cell_lines(cell):
    """Return the lines of one cell's source."""
    return "".join(cell["source"]).split("\n")


def numbered_headings():
    """Return (number, title) for every numbered section heading, in notebook order."""
    found = []
    for cell in load_cells():
        if cell["cell_type"] == "markdown":
            match = NUMBERED_HEADING.match(cell_lines(cell)[0])
            if match:
                found.append((int(match.group(1)), match.group(2)))
    return found


def test_every_section_number_appears_once_with_no_gaps():
    """The headings run 1, 2, 3 and so on to the last section, each number used once."""
    numbers = [number for number, _ in numbered_headings()]
    expected = list(range(1, len(numbers) + 1))
    assert numbers == expected, f"Section numbers are {numbers}"


def test_no_heading_uses_the_word_phase():
    """A reader of the book does not know the build phases, so no heading may name one."""
    headings = [line for cell in load_cells() if cell["cell_type"] == "markdown"
                for line in cell_lines(cell) if line.startswith("#")]
    phase_headings = [line for line in headings if re.search(r"\bphase\b", line, re.IGNORECASE)]
    assert phase_headings == [], f"Headings that name a phase: {phase_headings}"


def test_no_internal_words_in_the_notebook_text():
    """Markdown, comments and messages use plain words, not the words of the build instructions."""
    offenders = []
    for index, cell in enumerate(load_cells()):
        for line in cell_lines(cell):
            if INTERNAL_WORDS.search(line):
                offenders.append((index, line.strip()[:80]))
    assert offenders == [], f"Internal words found: {offenders}"


def test_the_last_section_is_the_figures_section():
    """The notebook ends with the story figures, with the section number that follows the others."""
    headings = numbered_headings()
    last_number, last_title = headings[-1]
    assert last_number == len(headings)
    assert last_title == "Figures from the story page"


def figure_section_cells():
    """Return the cells from the figures heading to the end of the notebook."""
    cells = load_cells()
    heading_positions = [index for index, cell in enumerate(cells) if cell["cell_type"] == "markdown"
                         and cell_lines(cell)[0].startswith("## 36. ")]
    assert len(heading_positions) == 1, "There should be one figures heading"
    return cells[heading_positions[0]:]


def test_figures_section_shows_twelve_figures_in_order_each_after_a_lead_in():
    """Each figure is one display cell directly after a one-line markdown lead-in."""
    section = figure_section_cells()
    shown = []
    lead_ins_ok = []
    for position, cell in enumerate(section):
        match = DISPLAYED_FIGURE.match("".join(cell["source"])) if cell["cell_type"] == "code" else None
        if match:
            shown.append(match.group(1))
            before = section[position - 1]
            lead_ins_ok.append(before["cell_type"] == "markdown" and len(cell_lines(before)) == 1)
    assert shown == FIGURE_ORDER
    assert all(lead_ins_ok), "Every figure needs a one-line markdown lead-in directly above it"


def test_the_notebook_draws_figures_only_through_the_builder():
    """The plotting code lives once, in the story builder; the notebook only calls it and shows the images."""
    plotting_lines = [(index, line.strip()[:60]) for index, cell in enumerate(load_cells())
                      if cell["cell_type"] == "code" for line in cell_lines(cell) if PLOTTING_CODE.search(line)]
    assert plotting_lines == [], f"Plotting code in the notebook: {plotting_lines}"


def test_the_notebook_is_saved_without_outputs():
    """Outputs belong in the executed copy under output/, not in the saved notebook."""
    cells_with_outputs = [index for index, cell in enumerate(load_cells())
                          if cell["cell_type"] == "code" and cell["outputs"]]
    assert cells_with_outputs == [], f"Cells saved with outputs: {cells_with_outputs}"
