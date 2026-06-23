def strategy_summary(item): return {key:item.get(key) for key in ("strategy_id","name","category","status","description")}
