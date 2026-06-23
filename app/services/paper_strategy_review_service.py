class PaperStrategyReviewService:
    def __init__(self,analytics):self.analytics=analytics
    def review(self,strategy_id,criteria=None,persist=True):return self.analytics.promotion_review(strategy_id,criteria,persist)
