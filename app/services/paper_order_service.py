class PaperOrderService:
    def __init__(self,broker): self.broker=broker
    def create(self,payload): return self.broker.create_order(payload)
    def approve(self,order_id): return self.broker.approve_order(order_id)
    def cancel(self,order_id): return self.broker.cancel_order(order_id)
    def list(self): return self.broker.orders()
