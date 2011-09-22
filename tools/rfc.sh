#!/bin/sh -e
# Copyright (c) 2010-2011 Gluster, Inc. <http://www.gluster.com> 
# This initial version of this file was taken from the source tree
# of GlusterFS. It was not directly attributed, but is assumed to be
# Copyright (c) 2010-2011 Gluster, Inc and release GPLv3
# Subsequent modifications are Copyright (c) 2011 OpenStack, LLC.
#
# GlusterFS is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published
# by the Free Software Foundation; either version 3 of the License,
# or (at your option) any later version.
#
# GlusterFS is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see
# <http://www.gnu.org/licenses/>.


branch="master";

set_hooks_commit_msg()
{
    top_dir=`git rev-parse --show-toplevel`
    f="${top_dir}/.git/hooks/commit-msg";
    u="https://review.openstack.org/tools/hooks/commit-msg";

    if [ -x "$f" ]; then
        return;
    fi

    curl -o $f $u || wget -O $f $u;

    chmod +x $f;

    GIT_EDITOR=true git commit --amend
}

add_remote()
{
    username=$1
    project=$2

    echo "No remote set, testing ssh://$username@review.openstack.org:29418"
    if project_list=`ssh -p29418 -o StrictHostKeyChecking=no $username@review.openstack.org gerrit ls-projects 2>/dev/null`
    then
        echo "$username@review.openstack.org:29418 worked."
        if echo $project_list | grep $project >/dev/null
        then
            echo "Creating a git remote called gerrit that maps to:"
            echo "  ssh://$username@review.openstack.org:29418/$project"
            git remote add gerrit ssh://$username@review.openstack.org:29418/$project
        else
            echo "The current project name, $project, is not a known project."
            echo "Please either reclone from github/gerrit or create a"
            echo "remote named gerrit that points to the intended project."
            return 1
        fi

        return 0
    fi
    return 1
}

check_remote()
{
    if ! git remote | grep gerrit >/dev/null 2>&1
    then
        origin_project=`git remote show origin | grep 'Fetch URL' | perl -nle '@fields = split(m|[:/]|); $len = $#fields; print $fields[$len-1], "/", $fields[$len];'`
        if add_remote $USERNAME $origin_project
        then
            return 0
        else
            echo "Your local name doesn't work on Gerrit."
            echo -n "Enter Gerrit username (same as launchpad): "
            read gerrit_user
            if add_remote $gerrit_user $origin_project
            then
                return 0
            else
                echo "Can't infer where gerrit is - please set a remote named"
                echo "gerrit manually and then try again."
                echo
                echo "For more information, please see:"
                echo "\thttp://wiki.openstack.org/GerritWorkflow"
                exit 1
            fi
        fi
    fi
}

rebase_changes()
{
    git fetch;

    GIT_EDITOR=true git rebase -i origin/$branch || exit $?;
}


assert_diverge()
{
    if ! git diff origin/$branch..HEAD | grep -q .
    then
	echo "No changes between the current branch and origin/$branch."
	exit 1
    fi
}


main()
{
    set_hooks_commit_msg;

    check_remote;

    rebase_changes;

    assert_diverge;

    bug=$(git show --format='%s %b' | perl -nle 'if (/\b([Bb]ug|[Ll][Pp])\s*[#:]?\s*(\d+)/) {print "$2"; exit}')

    bp=$(git show --format='%s %b' | perl -nle 'if (/\b([Bb]lue[Pp]rint|[Bb][Pp])\s*[#:]?\s*([0-9a-zA-Z-_]+)/) {print "$2"; exit}')

    if [ "$DRY_RUN" = 1 ]; then
        drier='echo -e Please use the following command to send your commits to review:\n\n'
    else
        drier=
    fi

    local_branch=`git branch | grep -Ei "\* (.*)" | cut -f2 -d' '`
    if [ -z "$bug" ]; then
	if [ -z "$bp" ]; then
            $drier git push gerrit HEAD:refs/for/$branch/$local_branch;
	else
	    $drier git push gerrit HEAD:refs/for/$branch/bp/$bp;
	fi
    else
        $drier git push gerrit HEAD:refs/for/$branch/bug/$bug;
    fi
}

main "$@"
