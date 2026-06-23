def citation(result: dict) -> str:
    return f"[{result.get('source_type')}:{result.get('source_id')}]"
