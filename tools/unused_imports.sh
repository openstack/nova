#!/bin/sh

#snakefood sfood-checker detects even more unused imports
! pyflakes nova/ | grep "imported but unused"
