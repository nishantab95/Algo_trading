from app.portfolio.exposure import exposure
from app.portfolio.performance import equity_curve
from app.portfolio.pnl import pnl
from app.portfolio.valuation import portfolio_summary

class PaperPortfolioService:
    def __init__(self,broker):self.broker=broker
    def summary(self):return portfolio_summary(self.broker)
    def equity_curve(self):return equity_curve(self.broker)
    def exposure(self):return exposure(self.broker)
    def pnl(self):return pnl(self.broker)
