#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
#
#
# before you run this modify your .ssh/config to create a
# review.openstack.org entry:
#
#   Host review.openstack.org
#   User <yourgerritusername>
#   Port 29418
#

# Note: due to gerrit bug somewhere, this double posts messages. :(

# first purge the all reviews that are more than 4w old and blocked by a core -2

set -o errexit

function abandon_review {
    local gitid=$1
    shift
    local msg=$@
    echo "Abandoning $gitid"
    # echo ssh review.openstack.org gerrit review $gitid --abandon --message \"$msg\"
    ssh review.openstack.org gerrit review $gitid --abandon --message \"$msg\"
}

PROJECTS="(project:openstack/nova OR project:openstack/python-novaclient)"

blocked_reviews=$(ssh review.openstack.org "gerrit query --current-patch-set --format json $PROJECTS status:open age:4w label:Code-Review<=-2" | jq .currentPatchSet.revision | grep -v null | sed 's/"//g')

blocked_msg=$(cat <<EOF

This review is > 4 weeks without comment and currently blocked by a
core reviewer with a -2. We are abandoning this for now.

Feel free to reactivate the review by pressing the restore button and
contacting the reviewer with the -2 on this review to ensure you
address their concerns.

EOF
)

# For testing, put in a git rev of something you own and uncomment
# blocked_reviews="b6c4218ae4d75b86c33fa3d37c27bc23b46b6f0f"

for review in $blocked_reviews; do
    # echo ssh review.openstack.org gerrit review $review --abandon --message \"$msg\"
    echo "Blocked review $review"
    abandon_review $review $blocked_msg
done

# then purge all the reviews that are > 4w with no changes and Jenkins has -1ed

failing_reviews=$(ssh review.openstack.org "gerrit query  --current-patch-set --format json $PROJECTS status:open age:4w NOT label:Verified>=1,jenkins" | jq .currentPatchSet.revision | grep -v null | sed 's/"//g')

failing_msg=$(cat <<EOF

This review is > 4 weeks without comment, and failed Jenkins the last
time it was checked. We are abandoning this for now.

Feel free to reactivate the review by pressing the restore button and
leaving a 'recheck' comment to get fresh test results.

EOF
)

for review in $failing_reviews; do
    echo "Failing review $review"
    abandon_review $review $failing_msg
done
