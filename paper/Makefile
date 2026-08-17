PAPER = retry-amplification-ice2cpt
LETTER = cover-letter/cover-letter

.PHONY: all clean view verify
all: $(PAPER).pdf $(LETTER).pdf

$(PAPER).pdf: $(PAPER).tex references.bib
	pdflatex $(PAPER)
	bibtex $(PAPER)
	pdflatex $(PAPER)
	pdflatex $(PAPER)

$(LETTER).pdf: $(LETTER).tex
	cd cover-letter && pdflatex cover-letter

# Recompute every reported figure from results/ and check the manuscript
# against it. Run after building, so the PDF freshness check passes too.
verify: all
	cd .. && python analysis/experiments/verify_paper_claims.py

clean:
	rm -f $(PAPER).aux $(PAPER).bbl $(PAPER).blg $(PAPER).log $(PAPER).out
	rm -f $(LETTER).aux $(LETTER).log

view: $(PAPER).pdf
	open $(PAPER).pdf
