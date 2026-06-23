def reconcile(broker):
    snapshot=broker.mark_to_market()
    return {"status":"reconciled","mode":"PAPER","snapshot":snapshot,"positions":len(broker.positions())}
