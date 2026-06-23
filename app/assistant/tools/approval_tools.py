class ApprovalTools:
    def __init__(self,drafts): self.drafts=drafts
    def approve(self,draft_id,actor="user"): return self.drafts.approve(draft_id,actor)
    def reject(self,draft_id,actor="user"): return self.drafts.reject(draft_id,actor)
