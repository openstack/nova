{
    "server": {
        "name": "new-server-test",
        "imageRef": "%(host)s/openstack/images/%(image_id)s",
        "flavorRef": "%(host)s/openstack/flavors/1",
        "metadata": {
            "My Server Name": "Apache1"
        },
        "min_count": "%(min_count)s",
        "max_count": "%(max_count)s"
    }
}
