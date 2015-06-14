{
    "rebuild": {
        "imageRef": "%(glance_host)s/images/%(uuid)s",
        "name": "%(name)s",
        "adminPass": "%(pass)s",
        "metadata": {
            "meta_var": "meta_val"
        },
        "preserve_ephemeral": %(preserve_ephemeral)s
    }
}
