CREATE TABLE pci_devices_new (
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    deleted INTEGER,
    id INTEGER NOT NULL,
    compute_node_id INTEGER NOT NULL,
    address VARCHAR(12) NOT NULL,
    vendor_id VARCHAR(4) NOT NULL,
    product_id VARCHAR(4) NOT NULL,
    dev_type VARCHAR(8) NOT NULL,
    dev_id VARCHAR(255),
    label VARCHAR(255) NOT NULL,
    status VARCHAR(36) NOT NULL,
    extra_info TEXT,
    instance_uuid VARCHAR(36),
    PRIMARY KEY (id),
    FOREIGN KEY (compute_node_id) REFERENCES compute_nodes(id),
    CONSTRAINT uniq_pci_devices0compute_node_id0address0deleted UNIQUE (compute_node_id, address, deleted)
);

INSERT INTO pci_devices_new
    SELECT created_at,
           updated_at,
           deleted_at,
           deleted,
           id,
           compute_node_id,
           address,
           vendor_id,
           product_id,
           dev_type,
           dev_id,
           label,
           status,
           extra_info,
           instance_uuid
    FROM pci_devices;

DROP TABLE pci_devices;

ALTER TABLE pci_devices_new RENAME TO pci_devices;

CREATE INDEX ix_pci_devices_compute_node_id_deleted
    ON pci_devices (compute_node_id, deleted);

CREATE INDEX ix_pci_devices_instance_uuid_deleted
    ON pci_devices (instance_uuid, deleted);
