#!/bin/sh

for x in `./find_autodoc_modules.sh`;
do
  echo ".. automodule:: ${x}"
  echo "  :members:"
done

