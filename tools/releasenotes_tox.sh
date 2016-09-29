#!/usr/bin/env bash

rm -rf releasenotes/build

sphinx-build -a -E -W \
    -d releasenotes/build/doctrees \
    -b html \
    releasenotes/source releasenotes/build/html
BUILD_RESULT=$?

UNCOMMITTED_NOTES=$(git status --porcelain | \
    awk '$1 == "M" && $2 ~ /releasenotes\/notes/ {print $2}')

if [ "${UNCOMMITTED_NOTES}" ]
then
    cat <<EOF

REMINDER: The following changes to release notes have not been committed:

${UNCOMMITTED_NOTES}

While that may be intentional, keep in mind that release notes are built from
committed changes, not the working directory.

EOF
fi

exit ${BUILD_RESULT}
