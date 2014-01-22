#!/usr/bin/env bash

print_hint() {
    echo "Try \`${0##*/} --help' for more information." >&2
}

PARSED_OPTIONS=$(getopt -n "${0##*/}" -o hb:p:m:l:o: \
                 --long help,base-dir:,package-name:,output-dir:,module:,library: -- "$@")

if [ $? != 0 ] ; then print_hint ; exit 1 ; fi

eval set -- "$PARSED_OPTIONS"

while true; do
    case "$1" in
        -h|--help)
            echo "${0##*/} [options]"
            echo ""
            echo "options:"
            echo "-h, --help                show brief help"
            echo "-b, --base-dir=DIR        project base directory"
            echo "-p, --package-name=NAME   project package name"
            echo "-o, --output-dir=DIR      file output directory"
            echo "-m, --module=MOD          extra python module to interrogate for options"
            echo "-l, --library=LIB         extra library that registers options for discovery"
            exit 0
            ;;
        -b|--base-dir)
            shift
            BASEDIR=`echo $1 | sed -e 's/\/*$//g'`
            shift
            ;;
        -p|--package-name)
            shift
            PACKAGENAME=`echo $1`
            shift
            ;;
        -o|--output-dir)
            shift
            OUTPUTDIR=`echo $1 | sed -e 's/\/*$//g'`
            shift
            ;;
        -m|--module)
            shift
            MODULES="$MODULES -m $1"
            shift
            ;;
        -l|--library)
            shift
            LIBRARIES="$LIBRARIES -l $1"
            shift
            ;;
        --)
            break
            ;;
    esac
done

BASEDIR=${BASEDIR:-`pwd`}
if ! [ -d $BASEDIR ]
then
    echo "${0##*/}: missing project base directory" >&2 ; print_hint ; exit 1
elif [[ $BASEDIR != /* ]]
then
    BASEDIR=$(cd "$BASEDIR" && pwd)
fi

PACKAGENAME=${PACKAGENAME:-${BASEDIR##*/}}
TARGETDIR=$BASEDIR/$PACKAGENAME
if ! [ -d $TARGETDIR ]
then
    echo "${0##*/}: invalid project package name" >&2 ; print_hint ; exit 1
fi

OUTPUTDIR=${OUTPUTDIR:-$BASEDIR/etc}
# NOTE(bnemec): Some projects put their sample config in etc/,
#               some in etc/$PACKAGENAME/
if [ -d $OUTPUTDIR/$PACKAGENAME ]
then
    OUTPUTDIR=$OUTPUTDIR/$PACKAGENAME
elif ! [ -d $OUTPUTDIR ]
then
    echo "${0##*/}: cannot access \`$OUTPUTDIR': No such file or directory" >&2
    exit 1
fi

BASEDIRESC=`echo $BASEDIR | sed -e 's/\//\\\\\//g'`
find $TARGETDIR -type f -name "*.pyc" -delete
FILES=$(find $TARGETDIR -type f -name "*.py" ! -path "*/tests/*" \
        -exec grep -l "Opt(" {} + | sed -e "s/^$BASEDIRESC\///g" | sort -u)

RC_FILE="`dirname $0`/oslo.config.generator.rc"
if test -r "$RC_FILE"
then
    source "$RC_FILE"
fi

for mod in ${NOVA_CONFIG_GENERATOR_EXTRA_MODULES}; do
    MODULES="$MODULES -m $mod"
done

for lib in ${NOVA_CONFIG_GENERATOR_EXTRA_LIBRARIES}; do
    LIBRARIES="$LIBRARIES -l $lib"
done

export EVENTLET_NO_GREENDNS=yes

OS_VARS=$(set | sed -n '/^OS_/s/=[^=]*$//gp' | xargs)
[ "$OS_VARS" ] && eval "unset \$OS_VARS"
DEFAULT_MODULEPATH=nova.openstack.common.config.generator
MODULEPATH=${MODULEPATH:-$DEFAULT_MODULEPATH}
OUTPUTFILE=$OUTPUTDIR/$PACKAGENAME.conf.sample
python -m $MODULEPATH $MODULES $LIBRARIES $FILES > $OUTPUTFILE

# Hook to allow projects to append custom config file snippets
CONCAT_FILES=$(ls $BASEDIR/tools/config/*.conf.sample 2>/dev/null)
for CONCAT_FILE in $CONCAT_FILES; do
    cat $CONCAT_FILE >> $OUTPUTFILE
done
