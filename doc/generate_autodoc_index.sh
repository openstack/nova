#!/bin/sh

for x in `./find_modules.sh`;
do
  echo ".. automodule:: ${x}"
  echo "  :members:"
done

