def recommend(score,warnings=None):
    warnings=warnings or []
    if score<35:decision="reject"
    elif score<50:decision="needs_more_data"
    elif score<70:decision="continue_research"
    else:decision="paper_test_candidate"
    return {"decision":decision,"reason":f"Evidence score {score:.1f}. "+("; ".join(warnings[:3]) if warnings else "No critical validation warning."),"warnings":warnings,"live_enabled":False}
