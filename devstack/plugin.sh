NOVA_PLUGINDIR=$(readlink -f $(dirname "${BASH_SOURCE[0]}"))

source $NOVA_PLUGINDIR/lib/mdev_samples

if [[ $1 == "stack" ]]; then
    case $2 in
    install)
        if [[ "$NOVA_COMPILE_MDEV_SAMPLES" == True ]]; then
            async_runfunc compile_mdev_samples
        fi
    ;;
    extra)
        if [[ "$NOVA_COMPILE_MDEV_SAMPLES" == True ]]; then
            async_wait compile_mdev_samples
        fi
    ;;
    esac
elif [[ $1 == "clean" ]]; then
    rm -Rf $NOVA_KERNEL_TEMP
fi
