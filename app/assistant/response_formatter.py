def offline_response(results:list[dict])->str:
    if not results: return "LM Studio is offline. Local search is available, but no indexed context matched this request."
    titles=", ".join(item.get("title","") for item in results[:5])
    return f"LM Studio is offline. Local retrieval found: {titles}. Open these records for deterministic details."
