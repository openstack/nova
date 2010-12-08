#!/bin/bash

NOVA_DIR='../nova/' # include trailing slash
DOCS_DIR='source'

modules=''
for x in `find ${NOVA_DIR} -name '*.py'`; do
    if [ `basename ${x} .py` == "__init__" ] ; then
        continue
    fi
    relative=nova.`echo ${x} | sed -e 's$^'${NOVA_DIR}'$$' -e 's/.py$//' -e 's$/$.$g'`
    modules="${modules} ${relative}"
done

for mod in ${modules} ; do
  if [ ! -f "${DOCS_DIR}/${mod}.rst" ];
  then
    echo ${mod}
  fi
done
