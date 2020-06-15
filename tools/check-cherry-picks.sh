#!/bin/sh
#
# A tool to check the cherry-pick hashes from the current git commit message
# to verify that they're all on either master or stable/ branches
#

hashes=$(git show --format='%b' --quiet $1 | sed -nr 's/^.cherry picked from commit (.*).$/\1/p')
checked=0
branches+=""
for hash in $hashes; do
    branch=$(git branch -a --contains "$hash" 2>/dev/null| grep -oE '(master|stable/[a-z]+)')
    if [ $? -ne 0 ]; then
        echo "Cherry pick hash $hash not on any master or stable branches"
        exit 1
    fi
    branches+=" $branch"
    checked=$(($checked + 1))
done

if [ $checked -eq 0 ]; then
    if ! grep -q '^defaultbranch=stable/' .gitreview; then
        echo "Checked $checked cherry-pick hashes: OK"
        exit 0
    else
        if ! git show --format='%B' --quiet | grep -qi 'stable.*only'; then
            echo 'Stable branch requires either cherry-pick -x headers or [stable-only] tag!'
            exit 1
        fi
    fi
else
    echo Checked $checked cherry-pick hashes on branches: $(echo $branches | tr ' ' '\n' | sort | uniq)
fi
