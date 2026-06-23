class DraftTools:
    def __init__(self,drafts): self.drafts=drafts
    def create(self,action_type,payload,conversation_id=None,validation=None,risk_check=None): return self.drafts.create(action_type,payload,conversation_id,validation,risk_check)
