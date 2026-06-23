def build_context(results:list[dict],limit:int=6)->str:
    return "\n\n".join(f"[{item.get('source_type')}:{item.get('source_id')}] {item.get('title')}\n{item.get('snippet')}" for item in results[:limit])
