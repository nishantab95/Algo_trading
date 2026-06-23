class PaperJournalService:
    def __init__(self,broker):self.broker=broker
    def list(self,filters=None):return self.broker.journal(filters)
    def update(self,trade_id,changes):return self.broker.update_journal(trade_id,changes)
