{
    "server": {
        "name": "new-server-test",
        "imageRef": "%(compute_endpoint)s/images/%(image_id)s",
        "flavorRef": "%(compute_endpoint)s/flavors/1",
        "metadata": {
            "My Server Name": "Apache1"
        },
        "return_reservation_id": "True",
        "min_count": "%(min_count)s",
        "max_count": "%(max_count)s"
    }
}
