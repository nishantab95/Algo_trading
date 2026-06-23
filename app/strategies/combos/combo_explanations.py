def explain_combo(combo,passed,failed,values):
    return {"combo":combo.get("name"),"confirmations_passed":passed,"confirmations_failed":failed,"indicator_values":values,"explanation":f"{combo.get('name')} accepted {len(passed)} component confirmations under {combo.get('logic',{}).get('mode','all')} logic. Failed components: {', '.join(failed) or 'none'}."}
