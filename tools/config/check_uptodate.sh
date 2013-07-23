#!/bin/sh
TEMPDIR=`mktemp -d`
CFGFILE=nova.conf.sample
tools/config/generate_sample.sh -b ./ -p nova -o $TEMPDIR
if ! diff $TEMPDIR/$CFGFILE etc/nova/$CFGFILE
then
    echo "E: nova.conf.sample is not up to date, please run tools/config/generate_sample.sh"
    exit 42
fi
