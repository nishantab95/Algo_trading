from __future__ import annotations

import csv,json
from pathlib import Path
from app.research_lab.reports import validation_markdown


TABLE_EXPORTS={"experiments":"research_experiments","walk_forward_folds":"walk_forward_folds","parameter_sweep_results":"parameter_sweep_results","robustness_results":"robustness_results","regime_results":"regime_results","symbol_analysis":"symbol_analysis_results","correlation_results":"strategy_correlation_results","research_decisions":"research_decisions"}

class ResearchExportService:
    def __init__(self,database,root):self.database,self.root=database,Path(root)
    def export_all(self):
        target=self.root/"reports"/"research";target.mkdir(parents=True,exist_ok=True);paths={}
        for name,table in TABLE_EXPORTS.items():
            rows=self.database.query(f"SELECT * FROM {table}");fields=sorted({k for row in rows for k in row}) if rows else [];path=target/f"{name}.csv"
            with path.open("w",newline="",encoding="utf-8") as h:
                w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
            paths[name]=str(path)
        return paths
    def export_experiment(self,experiment):
        rows=self.database.query("SELECT summary_json FROM research_validation_summaries WHERE experiment_id=?",(experiment["id"],))
        if not rows:raise ValueError("Experiment has no validation summary")
        summary=json.loads(rows[0]["summary_json"]);target=self.root/"reports"/"research";target.mkdir(parents=True,exist_ok=True);path=target/f"{experiment['id']}_validation_report.md";path.write_text(validation_markdown(experiment,summary),encoding="utf-8");return str(path)
