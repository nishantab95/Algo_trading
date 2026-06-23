from __future__ import annotations

import csv
from pathlib import Path


class PaperReportService:
    def __init__(self,broker,analytics,root): self.broker,self.analytics,self.root=broker,analytics,Path(root)
    def export_all(self):
        target=self.root/"reports"/"paper";target.mkdir(parents=True,exist_ok=True)
        datasets={"account_summary":[self.broker.account()],"open_positions":self.broker.positions(),"orders":self.broker.orders(),"fills":self.broker.fills(),"trades":self.broker.journal(),"journal":self.broker.journal(),"strategy_reviews":self.broker.database.query("SELECT * FROM paper_strategy_reviews WHERE account_id=?",(self.broker.account_id,)),"daily_equity":self.broker.snapshots(10000)}
        paths={}
        for name,rows in datasets.items():
            path=target/f"{name}.csv";fields=sorted({key for row in rows for key in row}) if rows else []
            with path.open("w",newline="",encoding="utf-8") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
                for row in rows:writer.writerow(row)
            paths[name]=str(path)
        return paths
    def export_journal(self,path=None):
        if path is None:path=self.root/"reports"/"paper"/"journal.csv"
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);rows=self.broker.journal();fields=sorted({k for row in rows for k in row}) if rows else []
        with path.open("w",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
        return str(path)
