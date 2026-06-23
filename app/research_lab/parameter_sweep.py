from __future__ import annotations

import itertools,statistics,uuid


def expand_grid(grid):
    if isinstance(grid,list):return grid
    if not grid:return [{}]
    keys=list(grid);return [dict(zip(keys,values)) for values in itertools.product(*(grid[k] if isinstance(grid[k],list) else [grid[k]] for k in keys))]

def run_parameter_sweep(config,train,test,evaluator):
    rows=[]
    for params in expand_grid(config.get("parameter_grid",{})):
        full_metrics=evaluator(config,None,params);train_metrics=evaluator(config,train,params);test_metrics=evaluator(config,test,params);score=float(test_metrics.get("net_return_pct",0))-abs(float(test_metrics.get("max_drawdown_pct",0)))*.25
        rows.append({"parameter_set_id":"params_"+uuid.uuid4().hex[:12],"parameters":params,"full_metrics":full_metrics,"train_metrics":train_metrics,"test_metrics":test_metrics,"walk_forward_metrics":{},"raw_score":score})
    rows.sort(key=lambda r:r["raw_score"],reverse=True);scores=[r["raw_score"] for r in rows]
    isolated=bool(len(scores)>2 and scores[0]>statistics.mean(scores[1:min(4,len(scores))])*1.5)
    spread=statistics.pstdev(scores) if len(scores)>1 else abs(scores[0] if scores else 0);stability=max(0,100-spread*5-(30 if isolated else 0))
    for rank,row in enumerate(rows,1):row.update({"rank":rank,"stability_score":stability,"overfit_warning":"Best parameter set is isolated; nearby parameters perform poorly" if rank==1 and isolated else None})
    return rows,{"parameter_stability_score":stability,"isolated_best":isolated,"warning":rows[0]["overfit_warning"] if rows else "No parameter results"}
