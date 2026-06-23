class PaperPositionService:
    def __init__(self,broker): self.broker=broker
    def list(self): return self.broker.positions()
    def get(self,position_id): return self.broker.position(position_id)
    def exit(self,position_id,**kwargs): return self.broker.exit_position(position_id,**kwargs)
