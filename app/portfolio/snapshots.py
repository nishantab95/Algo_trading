def latest_snapshot(broker):
    rows=broker.snapshots(1);return rows[0] if rows else broker.snapshot()
