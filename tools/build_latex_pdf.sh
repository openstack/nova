#!/bin/bash

# Build tox venv and use it
tox -edocs --notest
source .tox/docs/bin/activate

# Build latex source
sphinx-build -b latex doc/source doc/build/latex

pushd doc/build/latex

# Workaround all the sphinx latex bugs

# Convert svg to png (requires ImageMagick)
convert architecture.svg architecture.png

# Update the latex to point to the new image, switch unicode chars to latex
# markup, and add packages for symbols
sed -i -e 's/architecture.svg/architecture.png/g' -e 's/\\code{✔}/\\checkmark/g' -e 's/\\code{✖}/\\ding{54}/g' -e 's/\\usepackage{multirow}/\\usepackage{multirow}\n\\usepackage{amsmath,amssymb,latexsym}\n\\usepackage{pifont}/g' Nova.tex

# To run the actual latex build you need to ensure that you have latex installed
# on ubuntu the texlive-full package will take care of this
make

deactivate
popd

cp doc/build/latex/Nova.pdf .
